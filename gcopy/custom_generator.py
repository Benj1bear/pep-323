##################################
### picklable/copyable objects ###
##################################
from types import FunctionType, GeneratorType, CodeType
from inspect import currentframe, signature
from copy import deepcopy, copy
from textwrap import dedent
from gcopy.source_processing import *
from gcopy.track import offset_adjust

try:
    from typing import NoReturn
except:
    NoReturn = {
        "NoReturn"
    }  ## for 3.5 since 3.6.2; there might be alternatives that are better than this for 3.5 ##


## minium version supported ##
## if positions in get_instructions does not happen ##
## for lower versions this will have to be 3.11 ##
# if version_info < (3, 5):
if version_info < (3, 11):
    raise ImportError("Python version 3.5 or above is required")


class Pickler:
    """
    class for allowing general copying and pickling of
    some otherwise uncopyable or unpicklable objects
    """

    _not_allowed = tuple()

    def _copier(self, FUNC: FunctionType) -> object:
        """copying will create a new generator object but the copier will determine its depth"""
        obj = type(self)()
        obj.__setstate__(obj.__getstate__(FUNC))
        return obj

    ## for copying ##
    def __copy__(self) -> object:
        return self._copier(copy)

    def __deepcopy__(self, memo: dict) -> object:
        return self._copier(deepcopy)

    ## for pickling ##
    def __getstate__(self, FUNC: FunctionType = lambda x: x) -> dict:
        """Serializing pickle (what object you want serialized)"""
        dct = dict()
        for attr in self._attrs:
            if hasattr(self, attr) and not attr in self._not_allowed:
                dct[attr] = FUNC(getattr(self, attr))
        return dct

    def __setstate__(self, state: dict) -> None:
        """Deserializing pickle (returns an instance of the object with state)"""
        for key, value in state.items():
            setattr(self, key, value)

    def __eq__(self, obj: Any) -> bool:
        return attr_cmp(self, obj, self._attrs)


class code(Pickler):
    """For pickling and copying code objects"""

    _attrs = code_attrs()

    def __init__(self, code_obj: CodeType = None) -> None:
        if code_obj:
            for attr in self._attrs:
                if hasattr(code_obj, attr):
                    setattr(self, attr, getattr(code_obj, attr))

    def __bool__(self) -> bool:
        """Used on i.e. if code_obj:"""
        return hasattrs(self, self._attrs)


class frame(Pickler):
    """
    acts as the initial FrameType

    Note: on pickling ensure f_locals
    and f_back can be pickled
    """

    _attrs = (
        "f_back",
        "f_code",
        "f_lasti",
        "f_lineno",
        "f_locals",
        "f_trace",
        "f_trace_lines",
        "f_trace_opcodes",
    )
    _not_allowed = ("f_globals",)
    f_locals = {}
    f_lineno = 1
    f_globals = globals()
    f_builtins = __builtins__

    def __init__(self, frame: FrameType = None) -> None:
        if frame:
            ## make sure all other frames are the custom type as well ##
            if hasattr(frame, "f_back") and not isinstance(frame.f_back, type(self)):
                self.f_back = type(self)(frame.f_back)
            ## make sure the code can be pickled
            if hasattr(frame, "f_code") and not isinstance(frame.f_code, code):
                self.f_code = code(frame.f_code)
            for attr in self._attrs[2:]:
                if hasattr(frame, attr):
                    setattr(self, attr, getattr(frame, attr))

    def clear(self) -> None:
        """clears f_locals e.g. 'most references held by the frame'"""
        self.f_locals = {}

    ## we have to implement this if I'm going to go 'if frame:' (i.e. in frame.__init__) ##
    def __bool__(self) -> bool:
        """Used on i.e. if frame:"""
        return hasattrs(self, ("f_code", "f_lasti", "f_lineno", "f_locals"))


class EOF(StopIteration):
    """Custom exception to exit out of the generator on return statements"""

    pass


#################
### Generator ###
#################
class Generator(Pickler):
    """
    Converts a generator function into a generator
    function that is copyable (e.g. shallow and deepcopy)
    and potentially pickle-able

    This should be very portable or at least closely so across
    python implementations ideally.

    The dependencies for this to work only requires that you
    can retrieve your functions source code as a string via
    inspect.getsource.

    How it works:

    Basically we emulate the generator process by converting
    it into an on the fly evaluation iterable thus enabling
    it to be easily copied (Note: deepcopying assumes the
    local variables in the frame can also be copied so if
    you happen to be using a function generator within
    another function generator then make sure that all
    function generators (past one iteration) are of the
    Generator type)

    Note: this class emulates what the GeneratorType
    could be and therefore is treated as a GeneratorType
    in terms of its class/type. This means it's type
    and subclass checked as a Generator or GeneratorType

    The api setup is done via _internals which is a dictionary.
    Essentially, for the various kinds of generator you could
    have you want to assign a prefix and a type. The prefix
    is there to denote i.e. gi_ for Generator, ag_ for
    AsyncGenerator and cr_ for Coroutine such that it's
    very easy to integrate across different implementations
    without losing the familiar api.
    """

    ## Note: by default GeneratorType does not have the  ##
    ## __bool__ (or __nonzero__ in python 2.x) attribute ##
    ## so we don't necessarily have to implement one ##

    _attrs = ("_internals",)  ## for Pickler ##

    def _record_jumps(self, number_of_indents: int) -> None:
        """Records the jump positions for the loops (for and while) to help with code adjustments"""
        ## has to be a list since we're assigning ##
        self._internals["jump_positions"] += [[self._internals["lineno"], None]]
        self._internals["jump_stack"] += [
            (number_of_indents, len(self._internals["jump_positions"]) - 1)
        ]

    def _custom_adjustment(self, line: str) -> list[str]:
        """
        It does the following to the source lines:

        1. replace all lines that start with yields with returns to start with
        2. make sure the generator is closed on regular returns
        3. save the iterator from the for loops replacing with a nonlocal variation
        4. tend to all yield from ... with the same for loop variation
        5. adjust all value yields either via unwrapping or unpacking
        """
        number_of_indents = get_indent(line)
        temp_line = line[number_of_indents:]
        indent = " " * number_of_indents
        ## yield ##
        result = yield_adjust(temp_line, indent)
        if result is not None:
            return result
        ## loops ##
        if is_loop(temp_line):
            self._record_jumps(number_of_indents)
            return [line]
        ## return ##
        if temp_line == "return" or temp_line.startswith("return "):
            ## close the generator then return ##
            ## have to use a try-finally in case the user returns a value from locals() ##
            return [
                indent + "try:",
                indent + "    return EOF('" + line[7:] + "')",
                indent + "finally:",
                indent + "    currentframe().f_back.f_locals['self']._close()",
            ]
        return [line]

    def _update_jump_positions(
        self, lines: list[str], reference_indent: int = -1
    ) -> None:
        """
        Updates the end jump positions in self._internals["jump_positions"].
        It may also append the current lines with adjustments if it's a while
        loop that used a value yield in its condition
        """
        if self._internals["jump_stack"]:
            end_lineno = self._internals["lineno"]
            while (
                self._internals["jump_stack"]
                and reference_indent <= self._internals["jump_stack"][-1][0]
            ):  # -1: top of stack, 0: indent
                index = self._internals["jump_stack"].pop()[1]
                self._internals["jump_positions"][index][1] = end_lineno
                ## add the adjustments
                if (
                    self._internals["jump_stack_adjuster"]
                    ## check if they're the same lineno ##
                    and self._internals["jump_positions"][index][0]
                    == self._internals["jump_stack_adjuster"][-1][0]
                ):
                    adjustments = self._internals["jump_stack_adjuster"].pop().pop()
                    ## add the adjustments ##
                    lines += adjustments
                    ## make sure with the adjustments that have loops ##
                    ## that the loops are recorded and the lineno is adjusted ##
                    count = 0
                    for self._internals["lineno"], line in enumerate(
                        ## temporarily add an additional adjustment to make ##
                        ## sure the loop positions are recorded properly ##
                        adjustments + [""],
                        start=self._internals["lineno"] + 1,
                    ):
                        number_of_indents = get_indent(line)
                        if is_loop(line[number_of_indents:]):
                            count += 1
                            self._record_jumps(number_of_indents)
                        ## we can use -1 since all the loops should be complete ##
                        elif (
                            count
                            and number_of_indents
                            <= self._internals["jump_stack"][-1][0]
                        ):
                            index = self._internals["jump_stack"].pop()[1]
                            self._internals["jump_positions"][index][1] = (
                                self._internals["lineno"] + 1
                            )
                        self._internals["linetable"] += [self._internals["lineno"]]
                    ## since we temporarily increased the number of adjustments ##
                    self._internals["lineno"] -= 1
                    self._internals["linetable"].pop()
        return lines

    def _append_line(
        self,
        index: int,
        char: str,
        source: str,
        source_iter: Iterable,
        running: bool,
        line: str,
        lines: list[str],
        indentation: int,
    ) -> tuple[int, str, int, list[str], str, bool, int]:
        ## skip comments ##
        if char == "#":
            for index, char in source_iter:
                if char == "\n":
                    break
        ## make sure to include it ##
        if char == ":":
            indentation = get_indent(line) + 4  # in case of ';'
            line += char
        if line and not line.isspace():  ## empty lines are possible ##
            reference_indent = get_indent(line)
            lines = self._update_jump_positions(lines, reference_indent)
            ## skip the definitions ##
            if is_definition(line[reference_indent:]):
                index, char, self._internals["lineno"], lines = collect_definition(
                    index - len(line) + 1,
                    lines,
                    self._internals["lineno"],
                    source,
                    source_iter,
                    reference_indent,
                )
            else:
                lines += self._custom_adjustment(line)
                ## update the lineno after so that the loops positions are 0 based indexing ##
                self._internals["lineno"] += 1
                ## make a linetable if using a running generator ##
                ## for the linetable e.g. for lineno_adjust e.g. compound statements ##
                # if running and char == "\n":
                #     self._internals["linetable"] += [self._internals["lineno"]]
        ## start a new line ##
        if char in ":;":
            ## assumes the current line is i.e. ; ... ; ... or if ... : ... ; ... ##
            ## if it's not this then we should get an empty line and this assumption ##
            ## will not take effect in modifying lines ##
            indented, line = True, " " * indentation
        else:
            indented, line = False, ""
        return index, char, lines, line, indented, indentation

    def _block_adjust(
        self,
        current_lines: list[str],
        new_lines: list[str],
        final_line: str,
    ) -> list[str]:
        """
        Checks if lines that were adjusted because of value yields
        are in a block statement and therefore needs adjusting

        Also, the new_lines do need to be indented accordingly
        e.g. to the final_line or specfic adjustment
        """
        ## make sure any loops are recorded (necessary for 'yield from ...' adjustment) ##
        ## and the lineno is updated ##

        for self._internals["lineno"], line in enumerate(
            new_lines, start=self._internals["lineno"] + 1
        ):
            number_of_indents = get_indent(line)
            if is_loop(line[number_of_indents:]):
                self._record_jumps(self._internals["lineno"], number_of_indents)
        ## check for adjustments in the final line ##
        number_of_indents = get_indent(final_line)
        temp_line = final_line[number_of_indents:]
        check = lambda expr: temp_line.startswith(expr) and temp_line[len(expr)] in " :"
        if is_loop(temp_line):
            ## the end of the loop needs to be appended with the new_lines ##
            ## locals()[".args"] += next(...)
            ## while locals()[".args"].pop():
            ##     ...
            ##     locals()[".args"] += next(...)
            self._internals["jump_stack_adjuster"] += [
                [self._internals["lineno"]]
                + indent_lines(new_lines, number_of_indents + 4)
            ]
        ## needs to indent itself and all other lines until the end of the block ##
        ## Note: only elif since if statements should be fine ##
        elif check("elif"):
            ## +4 to encapsulate in an else statement +2 to make it an 'if' statement ##
            final_line = (
                " " * (number_of_indents + 4) + final_line[number_of_indents + 2 :]
            )
            return (
                current_lines
                + [" " * number_of_indents + "else:"]
                + indent_lines(new_lines, number_of_indents + 4)
                + [final_line]
            )
        elif check("except"):
            ## except_adjust automatically does the indentation ##
            return except_adjust(current_lines, new_lines, final_line)
        self._internals["lineno"] += 1
        return current_lines + indent_lines(new_lines, number_of_indents) + [final_line]

    def _string_collector_adjust(
        self,
        index: int,
        char: str,
        prev: tuple[int, int, str],
        source_iter: Iterable,
        line: str,
        source: str,
        lines: list[str],
    ) -> tuple[str, int, list[str]]:
        """Adjust the string collector in case of any value yields in the f-strings"""
        string_collected, prev, adjustments = string_collector_proxy(
            index, char, prev, source_iter, line, source
        )
        if adjustments:
            ## since we have adjustments we need to adjust the chars before it ##
            (adjustments_start, line_start), (adjustments_end, line_end) = (
                unpack(line)[:-1],
                unpack(source_iter=source_iter)[:-1],
            )
            final_adjustments, final_line = (
                adjustments_start + adjustments + adjustments_end,
                line_start + string_collected + line_end,
            )
            return "", prev, self._block_adjust(lines, final_adjustments, final_line)
        return line + string_collected, prev, lines

    def _clean_source_lines(self, running: bool = False) -> list[str]:
        """
        source: str

        returns source_lines: list[str],return_linenos: list[int]

        1. fixes any indentation issues (when ';' is used) and skips empty lines
        2. split on "\n", ";", and ":"
        3. join up the line continuations i.e. "\ ... " will be skipped

        additionally, custom_adjustment will be called on each line formation as well

        Note:
        jump_positions: are the fixed list of (lineno,end_lineno) for the loops (for and while)
        jump_stack: jump_positions currently being recorded (gets popped into jump_positions once
                     the reference indent has been met or lower for the next line that does so)
                     it records a tuple of (reference_indent,jump_position_index)
        """
        ## for loop adjustments ##
        (
            self._internals["jump_positions"],
            self._internals["jump_stack"],
            self._internals["jump_stack_adjuster"],
            self._internals["lineno"],
        ) = (
            [],
            [],
            [],
            0,
        )
        ## setup source as an iterator and making sure the first indentation's correct ##
        source = skip_source_definition(self._internals["source"])
        ## we need to make sure the source is saved for skipping for line continuations ##
        source = source[get_indent(source) :]
        source_iter = enumerate(source)
        ID, depth, line, lines, indented, space, indentation, prev = (
            "",
            0,
            " " * 4,
            [],
            False,
            0,
            4,
            (0, 0, ""),
        )
        ## enumerate since I want the loop to use an iterator but the
        ## index is needed to retain it for when it's used on get_indent
        for index, char in source_iter:
            ## collect strings ##
            if char == "'" or char == '"':
                line, prev, lines = self._string_collector_adjust(
                    index, char, prev, source_iter, line, source, lines
                )
            ## makes the line singly spaced while retaining the indentation ##
            elif char == " ":
                line, space, indented = singly_space(index, char, line, space, indented)
            ## join everything after the line continuation until the next \n or ; ##
            elif char == "\\":
                skip_line_continuation(source_iter, source, index)
                ## in case of a line continuation without a space before (whitespace after is removed) ##
                if space + 1 != index:
                    line += " "
                    space = index
            ## create new line ##
            elif char in "#\n;:":
                ## 'space' is important (otherwise we get more indents than necessary) ##
                space, char, lines, line, indented, indentation = self._append_line(
                    index,
                    char,
                    source,
                    source_iter,
                    running,
                    line,
                    lines,
                    indentation,
                )
                depth, ID = 0, ""
            else:
                line += char
                ## detect value yields [yield] and {yield} is not possible only (yield) ##
                depth = update_depth(depth, char)
                if char == "=":  ## '... = yield ...' and '... = yield from ...'
                    depth += 1
                if depth and char.isalnum():
                    ## in case of ... ... (otherwise you keep appending the ID) ##
                    if space + 1 == index:
                        ID = ""
                    ID += char
                    if ID == "yield":
                        ## isn't temp == self._internals["lineno"]? ##
                        temp, line, lines = (
                            len(lines),
                            "",
                            self._block_adjust(lines, *unpack(line, source_iter)[:-1]),
                        )
                        ## for the linetable e.g. for lineno_adjust e.g. compound statements ##
                        # if running:
                        #     self._internals["linetable"] += [
                        #         self._internals["lineno"]
                        #     ] * (len(lines) - temp)
                        depth, ID = 0, ""
                else:
                    ID = ""
        ## in case you get a for loop at the end and you haven't got the end jump_position ##
        ## then you just pop them all off as being the same end_lineno ##
        ## note: we don't need a reference indent since the line is over e.g. ##
        ## the jump_stack will be popped if it exists ##
        lines = self._update_jump_positions(lines)
        ## jump_stack is no longer needed ##
        del self._internals["jump_stack"], self._internals["jump_stack_adjuster"]
        return lines

    def _create_state(self) -> None:
        """
        creates a section of modified source code to be used in a
        function to act as a generators state

        The approach is as follows:

        Use the entire source code, reducing from the last lineno.
        Adjust the current source code reduction further out of
        control flow statements, loops, etc. then set the adjusted
        source code as the generators state

        Adjusts source code about control flow statements
        so that it can be used in a single directional flow
        as the generators states

        to handle nesting of loops it will simply join
        all the loops together and run them where the
        outermost nesting will be the final section that
        also contains the rest of the source lines as well
        """
        ## jump_positions are in linenos but get_loops automatically sets the indexing to 0 based ##
        loops = get_loops(self._internals["lineno"], self._internals["jump_positions"])
        self._internals["loops"] = len(loops)  ## needs checking ##
        index = self._internals["lineno"] - 1  ## for 0 based indexing ##
        if loops:
            start_pos, end_pos = loops.pop()
            ## adjustment ##
            blocks, indexes = control_flow_adjust(
                self._internals["source_lines"][index:end_pos],
                list(range(index, end_pos)),
                get_indent(self._internals["source_lines"][start_pos]),
            )
            blocks, indexes = loop_adjust(
                blocks,
                indexes,
                self._internals["source_lines"][start_pos:end_pos],
                *(start_pos, end_pos)
            )
            self._internals["state"], self._internals["linetable"] = outer_loop_adjust(
                blocks, indexes, self._internals["source_lines"], loops, end_pos
            )
            return
        self._internals["state"], self._internals["linetable"] = control_flow_adjust(
            self._internals["source_lines"][index:],
            list(range(index, len(self._internals["source_lines"]))),
        )

    def _locals(self) -> dict:
        """
        proxy to replace locals within 'next_state' within
        __next__ while still retaining the same functionality
        """
        return self._internals["frame"].f_locals

    def _frame_init(
        self, exception: str = "", close: bool = False
    ) -> tuple[list[str], FunctionType]:
        """
        initializes the frame with the current
        states variables and the _locals proxy
        but also adjusts the current state
        """
        # set the next state and setup the function; it will raise a StopIteration for us
        next(self._internals["state_generator"])
        ## adjust the current state ##
        if close:
            self._internals["state"] = exit_adjust(self._internals["state"])
        temp = get_indent(self._internals["state"][0])
        if exception:
            if self._internals["state"][0][temp:].startswith("try:"):
                self._internals["state"] = [
                    self._internals["state"][0],
                    " " * (temp + 4) + "raise " + exception,
                ] + self._internals["state"][1:]
                index_0 = self._internals["linetable"][0]
                self._internals["linetable"] = [index_0, index_0] + self._internals[
                    "linetable"
                ][1:]
            else:
                self._internals["state"] = [
                    " " * temp + "raise " + exception
                ] + self._internals["state"]
                ## -1 so that on +1 (on _update) it will be correct ##
                self._internals["linetable"] = [
                    self._internals["linetable"][0] - 1
                ] + self._internals["linetable"]
        ## adjust the initializers ##
        init = [
            self._internals["version"] + "def next_state():",
            " " * 4 + "locals=currentframe().f_back.f_locals['self']._locals",
        ]
        for key in self._internals["frame"].f_locals:
            if isinstance(key, str) and key.isalnum() and key != "locals":
                init += [" " * 4 + "%s=locals()[%s]" % (key, repr(key))]
        ## needs to be added if not already there so it can be appended to ##
        if ".args" not in self._internals["frame"].f_locals:
            init += [" " * 4 + 'locals()[".args"] = []']
        if ".send" not in self._internals["frame"].f_locals:
            init += [" " * 4 + "locals()['.send'] = None"]
        init += ["    currentframe().f_back.f_locals['.frame']=currentframe()"]
        ## try not to use variables here (otherwise it can mess with the state) ##
        exec("\n".join(init + self._internals["state"]), globals(), locals())
        self._internals["running"] = True
        return init, locals()["next_state"]

    def _init_states(self) -> GeneratorType:
        """Initializes the state generation as a generator"""
        ## api setup ##
        prefix = self._internals["prefix"]
        for key in ("code", "frame", "suspended", "yieldfrom", "running"):
            setattr(self, prefix + key, self._internals[key])
        del prefix
        ## since self._internals["state"] starts as 'None' ##
        yield self._create_state()
        ## if no state then it must be EOF ##
        while self._internals["state"]:
            yield self._create_state()

    def _api_setup(self) -> None:
        """sets up the api; subclasses should override this method for alternate api setup"""
        self._internals = {
            "prefix": "gi_",
            "type": GeneratorType,
            "version": "",  ## specific to 'async ' Generators for _frame_init ##
        }

    def __init__(
        self,
        FUNC: FunctionType | GeneratorType | str = None,
    ) -> None:
        """
        Takes in a function/generator or its source code as the first arguement

        If FUNC=None it will simply initialize as without any attributes, this
        is for the __setstate__ method in Pickler._copier use case

        Note:
         - gi_running: is the generator currently being executed
         - gi_suspended: is the generator currently paused e.g. state is saved

        Also, all attributes are set internally first and then exposed to the api.
        The interals are accessible via the _internals dictionary
        """
        ## for the api setup ##
        self._api_setup()
        ## __setstate__ from Pickler._copier ##
        if FUNC:
            ## needed to identify certain attributes ##
            prefix = self._internals["prefix"]
            ## running generator ##
            if hasattr(FUNC, prefix + "code"):
                self._internals["linetable"] = []
                self._internals["frame"] = frame(getframe(FUNC))
                self._internals["code"] = code(getcode(FUNC))
                ## co_name is readonly e.g. can't be changed by user ##
                if FUNC.gi_code.co_name == "<genexpr>":
                    self._internals["source"] = expr_getsource(FUNC)
                    self._internals["source_lines"] = unpack_genexpr(
                        self._internals["source"]
                    )
                    ## change the offsets into indents ##
                    self._internals["frame"].f_locals = offset_adjust(
                        self._internals["frame"].f_locals
                    )
                    self._internals["lineno"] = len(self._internals["source_lines"])
                else:
                    self._internals["source"] = dedent(getsource(getcode(FUNC)))
                    self._internals["source_lines"] = self._clean_source_lines(True)
                    ## Might implement at another time but this is just for compound statements ##
                    ## and therefore not strictly necessary from the standpoint of the style guide ##
                    self._internals["lineno"] = (
                        self._internals["frame"].f_lineno
                        - self._internals["code"].co_firstlineno
                        + 1
                    )
                    # self._internals["lineno"] = self._internals["linetable"][
                    #     self._internals["frame"].f_lineno - self._internals["code"].co_firstlineno
                    # ]  + lineno_adjust(self._internals["frame"])
                ## 'gi_yieldfrom' was introduced in python version 3.5 and yield from ... in 3.3 ##
                if hasattr(FUNC, prefix + "yieldfrom"):
                    self._internals["yieldfrom"] = getattr(FUNC, prefix + "yieldfrom")
                else:
                    self._internals["yieldfrom"] = None
                self._internals["suspended"] = True
            ## uninitialized generator ##
            else:
                ## generator function ##
                if isinstance(FUNC, FunctionType):
                    self._internals["code"] = code(FUNC.__code__)
                    self._internals["signature"] = signature(FUNC)
                    if FUNC.__code__.co_name == "<lambda>":
                        self._internals["source"] = expr_getsource(FUNC)
                        ## proably need something that locates its source better for other cases ##
                    else:
                        self._internals["source"] = dedent(getsource(FUNC))
                        self._internals["source_lines"] = self._clean_source_lines()
                ## source code string ##
                elif isinstance(FUNC, str):
                    self._internals["source"] = FUNC
                    self._internals["source_lines"] = self._clean_source_lines()
                    self._internals["code"] = code(
                        compile(FUNC, currentframe().f_code.co_filename, "exec")
                    )
                ## code object - use a decompilation library and send in as a string ##
                else:
                    raise TypeError(
                        "type '%s' is an invalid initializer for a Generator"
                        % type(FUNC)
                    )
                ## create the states ##
                self._internals["frame"] = frame()
                self._internals["suspended"] = False
                self._internals["yieldfrom"] = None
                ## modified every time __next__ is called; always start at line 1 ##
                self._internals["lineno"] = 1
            self._internals["running"] = False
            self._internals["state"] = None
            self._internals["state_generator"] = self._init_states()

    def __call__(self, *args, **kwargs) -> GeneratorType:
        """initializes the generators locals with arguements and keyword arguements"""
        _signature = self._internals.get("signature", None)
        if _signature:
            ## if binding to the signature fails it will raise an error ##
            binding = _signature.bind(*args, **kwargs)
            ## makes sure default arguments are applied ##
            binding.apply_defaults()
            self._internals["frame"].f_locals.update(binding.arguments)
            return self
        raise TypeError("Generator expression is not callable")

    def __iter__(self) -> GeneratorType:
        """Converts the generator function into an iterable"""
        while True:
            try:
                yield next(self)
            except StopIteration:
                break

    def __next__(self, exception: str = "", close: bool = False) -> Any:
        """updates the current state and returns the result"""
        ## update with the new state and get the frame ##
        init, next_state = self._frame_init(exception, close)
        try:
            result = next_state()
            if isinstance(result, EOF):
                self._close()
                raise result
            return result
        except Exception as e:
            self._close()
            locals()[".frame"] = None
            raise e
        finally:
            self._update(locals()[".frame"], len(init))

    def _update(self, _frame: FrameType, init_length: int) -> None:
        """Update the line position and frame"""
        self._internals["running"] = False

        ### update the frame ###

        f_back = self._internals["frame"]
        if _frame:

            #### update f_locals ####

            _frame = self._internals["frame"] = frame(_frame)
            ## remove 'locals' variable from memory since it interferes with pickling ##
            del _frame.f_locals["locals"]
            ## '.send' reference is not needed ##
            if ".send" in _frame.f_locals:
                del _frame.f_locals[".send"]
            if ".yieldfrom" in _frame.f_locals:
                self._internals["yieldfrom"] = _frame.f_locals[".yieldfrom"]
            if f_back:
                ## make sure the new frames locals are on the right hand side to take presedence ##
                _frame.f_locals = f_back.f_locals | _frame.f_locals
            _frame.f_back = f_back

            #### update lineno ####

            ## update the frames lineno in accordance with its state ##
            _frame.f_lineno = _frame.f_lineno - init_length
            ## update the lineno in accordance with the linetable ##
            if len(self._internals["linetable"]) > _frame.f_lineno:
                ## +1 to get the next lineno after returning ##
                self._internals["lineno"] = (
                    self._internals["linetable"][_frame.f_lineno] + 1
                )
            else:
                ## EOF ##
                self._internals["state"] = None
                self._internals["lineno"] = len(self._internals["source_lines"])

        else:
            ## exception was raised e.g. _frame == frame() ##
            self._internals["state"] = None

    def send(self, arg: Any) -> Any:
        """
        Send takes exactly one arguement 'arg' that
        is sent to the functions yield variable
        """
        if arg is not None and self._internals["lineno"] == 1:
            raise TypeError("can't send non-None value to a just-started generator")
        self._internals["frame"].f_locals[".send"] = arg
        return next(self)

    def _close(self) -> None:
        self._internals.update(
            {
                "state_generator": empty_generator(),
                "frame": None,
                "running": False,
                "suspended": False,
                "yieldfrom": None,
            }
        )

    def close(self) -> None:
        """
        Throws a GeneratorExit and closes the generator clearing its
        frame, state_generator, and yieldfrom

        return = return
        yield  = return 1
        """
        try:
            if self.__next__("GeneratorExit()", True):
                raise RuntimeError("generator ignored GeneratorExit")
        except GeneratorExit:
            ## This error is internally ignored by generators during closing ##
            pass
        finally:
            self._close()

    def throw(self, exception: Exception) -> NoReturn:
        """
        Raises an exception from the last line in the
        current state e.g. only from what has been
        """
        if issubclass(exception, BaseException):
            if isinstance(exception, type):
                exception = exception.__name__
            else:
                exception = repr(exception)
            return self.__next__(exception)
        raise TypeError(
            "exceptions must be classes or instances deriving from BaseException, not %s"
            % type(exception)
        )

    def __setstate__(self, state: dict) -> None:
        Pickler.__setstate__(self, state)
        self._internals["state_generator"] = self._init_states()

    def __instancecheck__(self, instance: object) -> bool:
        return isinstance(instance, self._internals["type"] | type(self))

    def __subclasscheck__(self, subclass: type) -> bool:
        return issubclass(subclass, self._internals["type"] | type(self))
