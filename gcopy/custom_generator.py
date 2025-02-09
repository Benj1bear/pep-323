# -*- coding: utf-8 -*-
"""

In order to make this module as backwards compatible as possible 
some of the functions used will be written out manually and a 
preprocessor or otherwise condition statemnt will go over what 
changes will be made if any

Backwards compatibility notes of relevance at the moment:

reference for versions not available on the 
cpython github repo or as an alternative for 
where documentation is lacking: https://hg.python.org/cpython/file/2.2

"""

from types import FunctionType, GeneratorType
from inspect import getsource, currentframe, findsource, getframeinfo
from copy import deepcopy, copy
from sys import version_info
from gcopy.util import (
    collect_multiline_string,
    collect_string,
    empty_generator,
    is_cli,
    lineno_adjust,
    unpack_genexpr,
    get_indent,
    dedent,
    getframe,
    yield_adjust,
    get_col_offset
)

################
### tracking ###
################


def track_iter(obj):
    """
    Tracks an iterator in the local scope initiated by a for loop

    This function has a specific use case where the initialization
    of an iterator via a for loop implictely does not allow for
    reliable extraction from the garbage collector and thus manually
    assigning the iterator for tracking is used

    Note: variables are signified as '.%s' % number_of_indents
    i.e.
        for i in range(3) is 4 indents and thus is assigned '.4'

    This way makes it more effective to retrieve the iterator
    rather than appending iterators. This means only numbers
    that are divisble by 4 should not be used in general usage
    by users.

    Using in generator expressions uses the col_offset instead
    """
    obj = iter(obj)
    frame = currentframe().f_back
    if frame.f_code.co_name == "<genexpr>":
        key = get_col_offset(frame)
    else:
        if is_cli():
            code_context = get_history_item(-frame.f_lineno)
        else:
            code_context = getframeinfo(frame).code_context[0]
        key = get_indent(code_context)
        ## won't work for compound statements that are in block statements ##
        ## therefore, we check for a block statement and add 4 if so ##
        temp = code_context[key:]
        if (
            temp.startswith("if ")
            or temp.startswith("for ")
            or temp.startswith("while ")
            or is_definition(temp)
        ) and lineno_adjust(frame.f_code, frame) == 0:
            key += 4
    frame.f_locals[".%s" % key] = obj
    return obj


############################
### cleaning source code ###
############################


def skip_source_definition(source):
    """Skips the function definition and decorators in the source code"""
    ID, source_iter = "", enumerate(source)
    for index, char in source_iter:
        ## decorators are ignored ##
        while char == "@":
            while char != "\n":
                index, char = next(source_iter)
            index, char = next(source_iter)
        if char.isalnum():
            ID += char
            if len(ID) == 3:
                if ID == "def" and next(source_iter)[1] == " ":
                    while char != "(":
                        index, char = next(source_iter)
                    break
                return source
        else:
            ID = ""
    depth = 1
    for index, char in source_iter:
        if char == ":" and depth == 0:
            return source[index + 1 :]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
    raise SyntaxError("Unexpected format encountered")


def collect_definition(
    line, lines, lineno, source, source_iter, reference_indent, prev
):
    """
    Collects a block of code from source, specifically a
    definition block in the case of this modules use case
    """
    indent = reference_indent + 1
    while reference_indent < indent:
        ## we're not specific about formatting the definitions ##
        ## we just need to make sure to include them ##
        for index, char in source_iter:
            ## collect strings ##
            if char == "'" or char == '"':
                if prev[0] + 2 == prev[1] + 1 == index and prev[2] == char:
                    string_collector = collect_multiline_string
                else:
                    string_collector = collect_string
                temp_index, temp_line = string_collector(source_iter, char)
                prev = (index, temp_index, char)
                line += temp_line
            ## newline ##
            elif char == "\n":
                break
            else:
                line += char
        ## add the line and get the indentation to check if continuing ##
        lineno += 1
        lines += [line]
        line, indent = "", get_indent(source[index + 1 :])
    ## make sure to return the index and char for the indentation ##
    return index, char, lineno, lines


def skip(iter_val, n):
    """Skips the next n iterations in a for loop"""
    for _ in range(n):
        next(iter_val)


## Note: line.startswith("except") will need to put a try statement in front (if it's not there e.g. is less than the minimum indent) ##
## match case default was introduced in python 3.10
if version_info < (3, 10):

    def is_alternative_statement(line):
        return line.startswith("elif") or line.startswith("else")

else:

    def is_alternative_statement(line):
        return (
            line.startswith("elif")
            or line.startswith("else")
            or line.startswith("case")
            or line.startswith("default")
        )


is_alternative_statement.__doc__ = "Checks if a line is an alternative statement"


def is_definition(line):
    """Checks if a line is a definition"""
    return (
        line.startswith("def ")
        or line.startswith("async def ")
        or line.startswith("class ")
        or line.startswith("async class ")
    )


########################
### code adjustments ###
########################
def skip_alternative_statements(line_iter, current_min):
    """Skips all alternative statements for the control flow adjustment"""
    for index, line in line_iter:
        temp_indent = get_indent(line)
        temp_line = line[temp_indent:]
        if temp_indent <= current_min and not is_alternative_statement(temp_line):
            break
    return index, line, temp_indent


def offset_adjust(f_locals):
    """
    Adjusts the track_iter created variables
    used in generator expressions from offset
    based to indentation based

    We have to do this because generator expressions
    can only have offset based trackers whereas
    when we format the source lines it requires
    indentation based

    Note: only needed on the current variables
    in the frame that use offset based trackers
    """
    ## the first offset will probably get in the way ##
    lineno = 0  ## every line will increase the indentation by 4 ##
    for key, value in f_locals.items():
        if isinstance(key, str) and key[0] == "." and key[1:].isdigit():
            del f_locals[key]
            lineno += 1
            f_locals[4 * lineno] = value
    return f_locals


def control_flow_adjust(lines, indexes, reference_indent=4):
    """
    removes unreachable control flow blocks that
    will get in the way of the generators state

    Note: it assumes that the line is cleaned,
    in particular, that it starts with an
    indentation of 4 (4 because we're in a function)

    It will also add 'try:' when there's an
    'except' line on the next minimum indent
    """
    new_lines, current_min = [], get_indent(lines[0])
    line_iter = enumerate(lines)
    for index, line in line_iter:
        temp_indent = get_indent(line)
        temp_line = line[temp_indent:]
        if temp_indent < current_min:
            ## skip over all alternative statements until it's not an alternative statement ##
            ## and the indent is back to the current min ##
            if is_alternative_statement(temp_line):
                end_index, line, temp_indent = skip_alternative_statements(
                    line_iter, temp_indent
                )
                del indexes[index:end_index]
                index = end_index
            current_min = temp_indent
            if temp_line.startswith("except"):
                new_lines = (
                    [" " * 4 + "try:"]
                    + indent_lines(new_lines)
                    + [line[current_min - 4 :]]
                )
                indexes = [indexes[0]] + indexes
        ## add the line (adjust if indentation is not reference_indent) ##
        if current_min != reference_indent:
            ## adjust using the current_min until it's the same as reference_indent ##
            new_lines += [line[current_min - 4 :]]
        else:
            return (
                new_lines + indent_lines(lines[index:], 4 - reference_indent),
                indexes,
            )
    return new_lines, indexes


def indent_lines(lines, indent=4):
    """indents a list of strings acting as lines"""
    if indent > 0:
        return [" " * indent + line for line in lines]
    if indent < 0:
        indent = -indent
        return [line[indent:] for line in lines]
    return lines


def extract_iter(line, number_of_indents):
    """
    Extracts the iterator from a for loop

    e.g. we extract the second ... in:
    for ... in ...:
    """
    depth, ID, line_iter = 0, "", enumerate(line)
    for index, char in line_iter:
        ## the 'in' key word must be avoided in all forms of loop comprehension ##
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char.isalnum() and depth == 0:
            ID += char
            if ID == "in":
                if next(line_iter)[1] == " ":
                    break
                ID = ""
        else:
            ID = ""
    index += (
        2  ## adjust by 2 to skip the 'n' and ' ' in 'in ' that would've been deduced ##
    )
    iterator = line[index:-1]  ## -1 to remove the end colon ##
    ## remove the leading and trailing whitespace and then it should be a variable name ##
    if iterator.strip().isalnum():
        return line
    return line[:index] + "locals()['.%s']:" % number_of_indents


def iter_adjust(outer_loop):
    """adjust an outer loop with its tracked iterator if it uses one"""
    flag, line = False, outer_loop[0]
    number_of_indents = get_indent(line)
    if line[number_of_indents:].startswith("for "):
        outer_loop[0] = extract_iter(line, number_of_indents)
        flag = True
    return flag, outer_loop


def loop_adjust(lines, indexes, outer_loop, *pos):
    """
    Formats the current code block
    being executed such that all the
    continue -> break;
    break -> empty the current iter; break;

    This allows us to use the control
    flow statements by implementing a
    simple for loop and if statement
    to finish the current loop
    """
    new_lines, flag, line_iter = [], False, enumerate(lines)
    for index, line in line_iter:
        indent = get_indent(line)
        temp_line = line[indent:]
        ## skip over for/while and definition blocks ##
        while (
            temp_line.startswith("for ")
            or temp_line.startswith("while ")
            or is_definition(temp_line)
        ):
            for index, line in line_iter:
                temp_indent = get_indent(line)
                if temp_indent <= indent:
                    break
                new_lines += [line]
            ## continue back ##
            indent = temp_indent
            temp_line = line[indent:]
        if temp_line.startswith("continue"):
            flag = True
            new_lines += ["break"]
        elif temp_line.startswith("break"):
            flag = True
            new_lines += ["locals()['.continue']=False", "break"]
            indexes = indexes[index:] + indexes[index] + indexes[:index]
        else:
            new_lines += [line]
    ## adjust it in case it's an iterator ##
    flag, outer_loop = iter_adjust(outer_loop)
    if flag:
        return ["    locals()['.continue']=True", "    for _ in ():"] + indent_lines(
            new_lines, 8 - get_indent(new_lines[0])
        ) + ["    if locals()['.continue']:"] + indent_lines(
            outer_loop, 8 - get_indent(outer_loop[0])
        ), [
            indexes[0],
            indexes[0],
        ] + indexes + [
            pos[0]
        ] + list(
            range(*pos)
        )
    return indent_lines(lines, 4 - get_indent(lines[0])) + indent_lines(
        outer_loop, 4 - get_indent(outer_loop[0])
    ), indexes + list(range(*pos))


def has_node(line, node):
    """Checks if a node has starting IDs that match"""
    ID, nodes, checks = "", [], node.split()
    for char in line:
        ## no strings allowed ##
        if char == "'" or char == '"':
            return False
        if char.isalnum():
            ID += char
        elif char == " ":
            if ID:
                nodes += [ID]
                for node, check in zip(nodes, checks):
                    if node != check:
                        return False
                if len(nodes) == len(checks):
                    return True
    return False


def send_adjust(line):
    """Checks for variables assigned to yields for making adjustments"""
    parts, flag = line.split("="), 0
    for index, node in enumerate(parts):
        node = node[get_indent(node) :]
        if has_node(node, "yield from "):
            flag = 1
            break
        if has_node(node, "yield "):
            flag = 2
            break
    if flag:
        reciever = "="
        if flag == 2:
            reciever += "locals()['.send']"
        ## indicator       yield statement            assignments
        return flag, ["=".join(parts[index:]), "=".join(parts[:index]) + reciever]
    return None, None


def get_loops(lineno, jump_positions):
    """
    returns a list of tuples (start_lineno,end_lineno) for the loop
    positions in the source code that encapsulate the current lineno
    """
    ## get the outer loops that contian the current lineno ##
    loops = []
    ## jump_positions are in the form (start_lineno,end_lineno) ##
    for (
        pos
    ) in (
        jump_positions
    ):  ## importantly we go from start to finish to capture nesting loops ##
        ## make sure the lineno is contained within the position for a ##
        ## loop adjustment and because the jump positions are ordered we ##
        ## can also break when the start lineno is beyond the current lineno ##
        if lineno < pos[0]:
            break
        if lineno < pos[1]:
            loops += [pos]
    return loops


######################
### expr_getsource ###
######################
def code_attrs():
    """
    all the attrs used by a CodeType object in
    order of types.CodeType function signature
    ideally and correct to the current version
    """
    attrs = ("co_argcount",)
    if (3, 8) <= version_info:
        attrs += ("co_posonlyargcount",)
    attrs += (
        "co_kwonlyargcount",
        "co_nlocals",
        "co_stacksize",
        "co_flags",
        "co_code",
        "co_consts",
        "co_names",
        "co_varnames",
        "co_filename",
        "co_name",
    )
    if (3, 3) <= version_info:
        attrs += ("co_qualname",)
    attrs += ("co_firstlineno",)
    if (3, 10) <= version_info:
        attrs += ("co_linetable",)
    else:
        attrs += ("co_lnotab",)
    if (3, 11) <= version_info:
        attrs += ("co_exceptiontable",)
    attrs += ("co_freevars", "co_cellvars")
    return attrs


def attr_cmp(obj1, obj2, attrs):
    """Compares two objects by a collection of their attrs"""
    for attr in attrs:
        if getattr(obj1, attr) != getattr(obj2, attr):
            return False
    return True


def getcode(obj):
    """Gets the code object from an object via commonly used attrs"""
    for attr in ["__code__", "gi_code", "ag_code", "cr_code"]:
        if hasattr(obj, attr):
            return getattr(obj, attr)
    raise AttributeError("code object not found")


def expr_getsource(FUNC):
    """
    Uses co_positions or otherwise goes through the source code
    extracting expressions until a match is found on a code object
    basis to get the source

    Note:
    the extractor should return a string and if using a
    lambda extractor it will take in a string input but
    if using a generator expression extractor it will
    take a list instead
    """
    code_obj = getcode(FUNC)
    if code_obj.co_name == "<lambda>":
        ## here source is a : str
        source = getsource(code_obj)
        extractor = extract_lambda
    else:
        lineno = getframe(FUNC).f_lineno - 1
        ## here source is a : list[str]
        source = findsource(code_obj)[0][lineno:]
        extractor = extract_genexpr
    ## get the rest of the source ##
    if (3, 11) <= version_info:
        # start_line, end_line, start_col, end_col
        positions = code_obj.co_positions()
        is_source_list = isinstance(source, list)
        pos = next(positions, (None, None, None))[1:]
        current_min, current_max = pos[2:]
        if is_source_list:
            current_max_lineno = pos[1]
        for pos in positions:
            if pos[-2] and pos[-2] < current_min:
                current_min = pos[-2]
            if pos[-1] and pos[-1] > current_max:
                current_min = pos[-1]
            if is_source_list and pos[1] and pos[1] > current_max_lineno:
                current_max_lineno = pos[1]
        if is_source_list:
            source = "\n".join(source[: current_max_lineno + 1])
        return source[current_min:current_max]
    ## otherwise match with generator expressions in the original source to get the source code ##
    attrs = (
        "co_freevars",
        "co_cellvars",
        "co_firstlineno",
        "co_nlocals",
        "co_stacksize",
        "co_flags",
        "co_code",
        "co_consts",
        "co_names",
        "co_varnames",
        "co_name",
    )
    if (3, 3) <= version_info:
        attrs += ("co_qualname",)
    if isinstance(source, list):
        source = "\n".join(source)
    for col_offset, end_col_offset in extractor(source):
        try:  ## we need to make it a try-except in case of potential syntax errors towards the end of the line/s ##
            ## eval should be safe here assuming we have correctly extracted the expression - we can't use compile because it gives a different result ##
            temp_code = getcode(eval(source[col_offset:end_col_offset]))
            if attr_cmp(temp_code, code_obj, attrs):
                return source
        except:
            pass
    raise Exception("No matches to the original source code found")


###############
### genexpr ###
###############
def extract_genexpr(source):
    """Extracts each generator expression from a list of the source code lines"""
    ID, is_genexpr, depth, prev = "", False, 0, (0, "")
    source_iter = enumerate(source)
    for index, char in source_iter:
        ## skip all strings if not in genexpr
        if char == "'" or char == '"':
            if prev[0] - 1 == index and char == prev[1]:
                index, temp_line = collect_multiline_string(source_iter, char)
            else:
                index, temp_line = collect_string(source_iter, char)
            prev = (index, char)
            continue
        ## detect brackets
        elif char == "(":
            temp_col_offset = index
            depth += 1
        elif char == ")":
            depth -= 1
            if is_genexpr and depth + 1 == genexpr_depth:
                yield col_offset, index + 1
                number_of_expressions += 1
                ID, is_genexpr = "", False
            continue
        ## record source code ##
        if depth and not is_genexpr:
            ## record ID ##
            if char.isalnum():
                ID += char
                ## detect a for loop
                if ID == "for":
                    genexpr_depth, is_genexpr, col_offset = depth, True, temp_col_offset
            else:
                ID = ""


##############
### lambda ###
##############
def extract_lambda(source_code):
    """Extracts each lambda expression from the source code string"""
    ID, is_lambda, lambda_depth, prev = "", False, 0, (0, "")
    source_code = enumerate(source_code)
    for index, char in source_code:
        ## skip all strings if not in lambda
        if char == "'" or char == '"':
            if prev[0] - 1 == index and char == prev[1]:
                string_collector = collect_multiline_string
            else:
                string_collector = collect_string
            index, temp_line = string_collector(source_code, char)
            prev = (index, char)
            continue
        ## detect brackets (lambda can be in all 3 types of brackets) ##
        elif char in "({[":
            depth += 1
        elif char in "]})":
            depth -= 1
        ## record source code ##
        if is_lambda:
            if char == "\n;" or (
                char == ")" and depth + 1 == lambda_depth
            ):  # lambda_depth needed in case of brackets; depth+1 since depth would've got reduced by 1
                yield col_offset, index + 1
                ID, is_lambda = "", False
        else:
            ## record ID ##
            if char.isalnum():
                ID += char
                ## detect a lambda
                if ID == "lambda" and depth <= 1:
                    lambda_depth, is_lambda, col_offset = depth, True, index - 6
            else:
                ID = ""
    ## in case of a current match ending ##
    if is_lambda:
        yield col_offset, None


########################
### pickling/copying ###
########################

class Pickler(object):
    """
    class for allowing general copying and pickling of
    some otherwise uncopyable or unpicklable objects
    """

    _not_allowed = tuple()

    def _copier(self, FUNC):
        """copying will create a new generator object but the copier will determine its depth"""
        obj = type(self)()
        obj.__setstate__(obj.__getstate__(obj, FUNC))
        return obj

    ## for copying ##
    def __copy__(self):
        return self._copier(copy)

    def __deepcopy__(self, memo):
        return self._copier(deepcopy)

    ## for pickling ##
    def __getstate__(self, FUNC=lambda x: x):
        """Serializing pickle (what object you want serialized)"""
        dct = dict()
        for attr in self._attrs:
            if hasattr(self, attr) and not attr in self._not_allowed:
                dct[attr] = FUNC(getattr(self, attr))
        return dct

    def __setstate__(self, state):
        """Deserializing pickle (returns an instance of the object with state)"""
        for key, value in state.items():
            setattr(self, key, value)


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

    def __init__(self, frame=None):
        if frame:
            if hasattr(
                frame, "f_back"
            ):  ## make sure all other frames are the custom type as well ##
                self.f_back = type(self)(frame.f_back)
            if hasattr(frame, "f_code"):  ## make sure it can be pickled
                self.f_code = code(frame.f_code)
            for attr in self._attrs[2:]:
                setattr(self, attr, getattr(frame, attr))

    def clear(self):
        """clears f_locals e.g. 'most references held by the frame'"""
        self.f_locals = {}

    ## we have to implement this if I'm going to go 'if frame:' (i.e. in frame.__init__) ##
    def __bool__(self):
        """Used on i.e. if frame:"""
        for attr in ("f_code", "f_lasti", "f_lineno", "f_locals"):
            if not hasattr(self, attr):
                return False
        return True

    if version_info < (3, 0):
        __nonzero__ = __bool__


class code(Pickler):
    """For pickling and copying code objects"""

    _attrs = code_attrs()

    def __init__(self, code_obj=None):
        if code_obj:
            for attr in self._attrs:
                setattr(self, attr, getattr(code_obj, attr))

    def __bool__(self):
        """Used on i.e. if code_obj:"""
        for attr in self._attrs:
            if not hasattr(self, attr):
                return False
        return True

    if version_info < (3, 0):
        __nonzero__ = __bool__


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
    """

    _internals = {"prefix": "gi_", "type": GeneratorType}
    _attrs = ("_internals",)

    def _custom_adjustment(self, line, lineno):
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
        if temp_line.startswith("yield from "):
            return [
                indent
                + "currentframe().f_back.f_locals['.yieldfrom']="
                + temp_line[11:],
                indent
                + "for currentframe().f_back.f_locals['.i'] in currentframe().f_back.f_locals['.yieldfrom']:",
                indent + "    return currentframe().f_back.f_locals['.i']",
            ]
        if temp_line.startswith("yield "):
            return [indent + "return" + temp_line[5:]]  ## 5 to retain the whitespace ##
        if temp_line.startswith("for ") or temp_line.startswith("while "):
            self._internals["jump_positions"] += [
                [lineno, None]
            ]  ## has to be a list since we're assigning ##
            self._internals["jump_stack"] += [
                (number_of_indents, len(self._internals["jump_positions"]) - 1)
            ]  ## doesn't have to be a list since it'll get popped e.g. it's not really meant to be modified as is ##
            return [line]
        if temp_line.startswith("return "):
            ## close the generator then return ##
            return [
                indent + "currentframe().f_back.f_locals['self'].close()",
                "raise StopIteration(" + line[7:] + ")",
            ]
        ## handles the .send method ##
        flag, adjustment = send_adjust(temp_line)
        if flag:
            if flag == 2:
                ## 5: to get past the 'yield'
                return [indent + "return" + adjustment[0][5:], indent + adjustment[1]]
            else:
                ## 11: to get past the 'yield from'
                return [
                    indent
                    + "currentframe().f_back.f_locals['.yieldfrom']="
                    + adjustment[0][11:],
                    indent
                    + "for currentframe().f_back.f_locals['.i'] in currentframe().f_back.f_locals['.yieldfrom']:",
                    indent + "    return currentframe().f_back.f_locals['.i']",
                    indent
                    + "    %scurrentframe().f_back.f_locals['.yieldfrom'].send(currentframe().f_back.f_locals['.send'])"
                    % adjustment[1],
                ]
        return [line]

    def _clean_source_lines(self, running=False):
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
        self._internals["jump_positions"], self._internals["jump_stack"], lineno = (
            [],
            [],
            0,
        )
        ## setup source as an iterator and making sure the first indentation's correct ##
        source = skip_source_definition(self._internals["source"])
        source = source[
            get_indent(source) :
        ]  ## we need to make sure the source is saved for skipping for line continuations ##
        source_iter = enumerate(source)
        line, lines, indented, space, indentation, prev = (
            " " * 4,
            [],
            False,
            0,
            4,
            (0, 0, ""),
        )
        ID, depth, depth_index, value_yields = "", 0, 0, []
        ## enumerate since I want the loop to use an iterator but the
        ## index is needed to retain it for when it's used on get_indent
        for index, char in source_iter:
            ## collect strings ##
            if char == "'" or char == '"':
                if prev[0] + 2 == prev[1] + 1 == index and prev[2] == char:
                    string_collector = collect_multiline_string
                else:
                    string_collector = collect_string
                temp_index, temp_line = string_collector(
                    source_iter, char, (source[index - 1] == "f")
                )  ## f-strings ##
                prev = (index, temp_index, char)
                line += temp_line
            ## makes the line singly spaced while retaining the indentation ##
            elif char == " ":
                if indented:
                    if space + 1 != index:
                        line += char
                else:
                    line += char
                    if space + 1 != index:
                        indented = True
                space = index
            ## join everything after the line continuation until the next \n or ; ##
            elif char == "\\":
                whitespace = get_indent(source[index + 1 :])
                ## skip the whitespace before newline ##
                skip(source_iter, whitespace)  ## +1 since 'index:' is inclusive ##
                ## skip the whitespace after newline ##
                skip(source_iter, get_indent(source[index + 1 + whitespace :]))
            ## create new line ##
            elif char in "#\n;:":
                ## skip comments ##
                if char == "#":
                    for index, char in source_iter:
                        if char == "\n":
                            break
                ## make sure to include it ##
                if char == ":":
                    indentation = get_indent(line) + 4  # in case of ';'
                    line += char
                if not line.isspace():  ## empty lines are possible ##
                    reference_indent = get_indent(line)
                    if self._internals["jump_stack"]:
                        end_lineno = len(lines) + 1
                        while (
                            self._internals["jump_stack"]
                            and reference_indent <= self._internals["jump_stack"][-1][0]
                        ):  # -1: top of stack, 0: start lineno
                            self._internals["jump_positions"][
                                self._internals["jump_stack"].pop()[1]
                            ][
                                1
                            ] = end_lineno  ## +1 assuming exclusion slicing on the stop index ##
                    ## skip the definitions ##
                    if is_definition(line[reference_indent:]):
                        index, char, lineno, lines = collect_definition(
                            line,
                            lines,
                            lineno,
                            source,
                            source_iter,
                            reference_indent,
                            prev,
                        )
                    else:
                        lineno += 1
                        if value_yields:
                            line = yield_adjust(line, value_yields)
                        lines += self._custom_adjustment(line, lineno)
                        ## make a linetable if using a running generator ##
                        if running and char == "\n":
                            self._internals["linetable"] += [lineno]
                ## start a new line ##
                if char in ":;":
                    # just in case
                    indented, line = True, " " * indentation
                else:
                    indented, line = False, ""
                space = index  ## this is important (otherwise we get more indents than necessary) ##
                value_yields = []
            else:
                line += char
                ## detect value yields ##
                if char == "(":  ## [yield] and {yield} is not possible only (yield) ##
                    depth_index = index
                    depth += 1
                elif char == ")":
                    depth -= 1
                if depth and char.isalnum():
                    ID += char
                    if ID == "yield":
                        value_yields += [depth_index]
                else:
                    ID = ""
        ## in case you get a for loop at the end and you haven't got the end jump_position ##
        ## then you just pop them all off as being the same end_lineno ##
        end_lineno = len(lines) + 1
        while self._internals["jump_stack"]:
            self._internals["jump_positions"][self._internals["jump_stack"].pop()[1]][
                1
            ] = end_lineno
        ## are not used by this generator (was only for formatting source code and
        ## recording the jump positions needed in the for loop adjustments) ##
        del self._internals["jump_stack"]
        return lines

    def _create_state(self, loops):
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
        temp_lineno = self._internals["lineno"] - 1  ## for 0 based indexing ##
        if loops:
            start_pos, end_pos = loops.pop()
            ## for 0 based indexing since they're linenos ##
            start_pos -= 1
            end_pos -= 1
            ## adjustment ##
            blocks, indexes = control_flow_adjust(
                self._internals["source_lines"][temp_lineno:end_pos],
                list(range(temp_lineno, end_pos)),
                get_indent(self._internals["source_lines"][start_pos]),
            )
            blocks, indexes = loop_adjust(
                blocks,
                indexes,
                self._internals["source_lines"][start_pos:end_pos],
                *(start_pos, end_pos)
            )
            self._internals["linetable"] = indexes
            ## add all the outer loops ##
            for start_pos, end_pos in loops[::-1]:
                start_pos -= 1
                end_pos -= 1
                flag, block = iter_adjust(
                    self._internals["source_lines"][start_pos:end_pos]
                )
                blocks += indent_lines(block, 4 - get_indent(block[0]))
                if flag:
                    self._internals["linetable"] += [start_pos]
                self._internals["linetable"] += list(range(start_pos, end_pos))
            self._internals["state"] = "\n".join(
                blocks + self._internals["source_lines"][end_pos:]
            )
            return
        block, self._internals["linetable"] = control_flow_adjust(
            self._internals["source_lines"][temp_lineno:],
            list(range(temp_lineno, len(self._internals["source_lines"]))),
        )
        self._internals["state"] = "\n".join(block)

    def _locals(self):
        """
        proxy to replace locals within 'next_state' within
        __next__ while still retaining the same functionality
        """
        return self._internals["frame"].f_locals

    def _frame_init(self):
        """
        initializes the frame with the current
        states variables and the _locals proxy
        """
        assign = []
        for key in self._internals["frame"].f_locals:
            if isinstance(key, str) and key.isalnum() and key != "locals":
                assign += [" " * 4 + "%s=locals()[%s]" % (key, key)]
        if assign:
            assign = "\n" + "\n".join(assign)
        else:
            assign = ""
        ## try not to use variables here (otherwise it can mess with the state) ##
        return (
            """def next_state():
    locals=currentframe().f_back.f_locals['self']._locals%s
    currentframe().f_back.f_locals['.frame']=currentframe()
"""
            % assign
        )

    def init_states(self):
        """Initializes the state generation as a generator"""
        ## api setup ##
        prefix = self._internals["prefix"]
        for key in ("code", "frame", "suspended", "yieldfrom", "running"):
            setattr(self, prefix + key, self._internals[key])
        del prefix
        ## since self._internals["state"] starts as 'None' ##
        yield self._create_state(
            get_loops(self._internals["lineno"], self._internals["jump_positions"])
        )
        loops = get_loops(self._internals["lineno"], self._internals["jump_positions"])
        while (
            self._internals["state"]
            and len(self._internals["linetable"]) > self._internals["frame"].f_lineno
        ) or loops:
            yield self._create_state(loops)
            loops = get_loops(
                self._internals["lineno"], self._internals["jump_positions"]
            )

    def __init__(self, FUNC=None, overwrite=False):
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
        ## __setstate__ from Pickler._copier ##
        if FUNC:
            prefix = self._internals[
                "prefix"
            ]  ## needed to identify certain attributes ##
            ## running generator ##
            if hasattr(FUNC, prefix + "code"):
                self._internals["linetable"] = []
                self._internals["frame"] = frame(getframe(FUNC))
                if (
                    FUNC.gi_code.co_name == "<genexpr>"
                ):  ## co_name is readonly e.g. can't be changed by user ##
                    self._internals["source"] = expr_getsource(FUNC)
                    self._internals["source_lines"] = unpack_genexpr(
                        self._internals["source"]
                    )
                    ## change the offsets into indents ##
                    self._internals["frame"].f_locals = offset_adjust(
                        self._internals["frame"].f_locals
                    )
                else:
                    self._internals["source"] = dedent(getsource(getcode(FUNC)))
                    self._internals["source_lines"] = self._clean_source_lines(True)
                    self._internals["lineno"] = self._internals["linetable"][
                        getframe(FUNC).f_lineno - 1
                    ] + lineno_adjust(FUNC)
                self._internals["code"] = code(getcode(FUNC))
                ## 'gi_yieldfrom' was introduced in python version 3.5 and yield from ... in 3.3 ##
                if hasattr(FUNC, prefix + "yieldfrom"):
                    self._internals["yieldfrom"] = getattr(FUNC, prefix + "yieldfrom")
                else:
                    self._internals["yieldfrom"] = None
                self._internals["suspended"] = True
            ## uninitialized generator ##
            else:
                ## source code string ##
                if isinstance(FUNC, str):
                    self._internals["source"] = FUNC
                    self._internals["code"] = code(compile(FUNC, "", "eval"))
                ## generator function ##
                elif isinstance(FUNC, FunctionType):
                    if FUNC.__code__.co_name == "<lambda>":
                        self._internals["source"] = expr_getsource(FUNC)
                    else:
                        self._internals["source"] = dedent(getsource(FUNC))
                    self._internals["code"] = code(FUNC.__code__)
                else:
                    raise TypeError(
                        "type '%s' is an invalid initializer for a Generator"
                        % type(FUNC)
                    )
                ## make sure the source code is standardized and usable by this generator ##
                self._internals["source_lines"] = self._clean_source_lines()
                ## create the states ##
                self._internals["frame"] = frame()
                self._internals["suspended"] = False
                self._internals["yieldfrom"] = None
                self._internals["lineno"] = (
                    1  ## modified every time __next__ is called; always start at line 1 ##
                )
            self._internals["running"] = False
            self._internals["state"] = None
            self._internals["state_generator"] = self.init_states()
            if overwrite:
                currentframe().f_back.f_locals[getcode(FUNC).co_name] = self

    def __len__(self):
        """
        Gets the number of states for generators with
        yield statements indented exactly 4 spaces.

        In general, you shouldn't be able to get the length
        of a generator function, but if it's very predictably
        defined then you can.
        """

        def number_of_yields():
            """Gets the number of yields that are indented exactly 4 spaces"""
            for line in self._internals["state"]:
                indents = get_indent(line)
                temp = line[indents:]
                if temp.startswith("yield") and not temp.startswith("yield from"):
                    if indents > 4:
                        raise TypeError(
                            "__len__ is only available where all yield statements are indented exactly 4 spaces"
                        )
                    yield 1

        return sum(number_of_yields())

    def __iter__(self):
        """Converts the generator function into an iterable"""
        while True:
            try:
                yield next(self)
            except StopIteration:
                break

    def __next__(self):
        """updates the current state and returns the result"""
        # set the next state and setup the function
        next(
            self._internals["state_generator"]
        )  ## it will raise a StopIteration for us
        ## update with the new state and get the frame ##
        exec(self._frame_init() + self._internals["state"], globals(), locals())
        self._internals["running"] = True
        ## if an error does occur it will be formatted correctly in cpython (just incorrect frame and line number) ##
        try:
            return locals()["next_state"]()
        finally:
            ## update the line position and frame ##
            self._internals["running"] = False
            ## update the frame ##
            f_back = self._internals["frame"]
            self._internals["frame"] = locals()[".frame"]
            if self._internals["frame"]:
                self._internals["frame"] = frame(self._internals["frame"])
                ## remove locals from memory since it interferes with pickling ##
                del self._internals["frame"].f_locals["locals"]
                self._internals["frame"].f_back = f_back
                ## update f_locals ##
                if f_back:
                    f_back.f_locals.update(self._internals["frame"].f_locals)
                    self._internals["frame"].f_locals = f_back.f_locals
                self._internals["frame"].f_locals[".send"] = None
                self._internals["frame"].f_lineno = self._internals[
                    "frame"
                ].f_lineno - self.init.count("\n")
                if (
                    len(self._internals["linetable"])
                    > self._internals["frame"].f_lineno
                ):
                    self._internals["lineno"] = (
                        self._internals["linetable"][self._internals["frame"].f_lineno]
                        + 1
                    )  ## +1 to get the next lineno after returning ##
                else:
                    ## EOF ##
                    self._internals["lineno"] = len(self._internals["source_lines"]) + 1

    def send(self, arg):
        """
        Send takes exactly one arguement 'arg' that
        is sent to the functions yield variable
        """
        if self._internals["lineno"] == 1:
            raise TypeError("can't send non-None value to a just-started generator")
        if self._internals["yieldfrom"]:
            self._internals["yieldfrom"].send(arg)
        else:
            self._internals["frame"].f_locals()[".send"] = arg
        return next(self)

    def close(self):
        """Closes the generator clearing its frame, state_generator, and yieldfrom"""
        self._internals.update(
            {
                "state_generator": empty_generator(),
                "frame": None,
                "running": False,
                "suspended": False,
                "yieldfrom": None,
            }
        )

    def throw(self, exception):
        """
        Raises an exception from the last line in the
        current state e.g. only from what has been
        """
        raise exception

    def __setstate__(self, state):
        Pickler.__setstate__(self, state)
        self._internals["state_generator"] = self.init_states()

    def __instancecheck__(self, instance):
        return isinstance(instance, self._internals["type"] | type(self))

    def __subclasscheck__(self, subclass):
        return issubclass(subclass, self._internals["type"] | type(self))


AnyGeneratorType = GeneratorType | Generator

from types import AsyncGeneratorType

AnyGeneratorType |= AsyncGeneratorType

class AsyncGenerator(Generator):
    _internals = {"prefix": "ag_", "type": AsyncGeneratorType}


from typing import Callable, Any, NoReturn, Iterable
from types import CodeType, FrameType, CoroutineType

class Coroutine(Generator):
    _internals = {"prefix": "cr_", "type": CoroutineType}

AnyGeneratorType |= CoroutineType
## utility functions ##
empty_generator.__annotations__ = {"return": GeneratorType}
lineno_adjust.__annotations__ = {
    "FUNC": AnyGeneratorType,
    "frame": FrameType | None,
    "return": int,
}
unpack_genexpr.__annotations__ = {"source": str, "return": list[str]}
## tracking ##
track_iter.__annotations__ = {"obj": object, "return": Iterable}
## cleaning source code ##
skip_source_definition.__annotations__ = {"source": str, "return": str}
collect_string.__annotations__ = {
    "iter_val": enumerate,
    "reference": str,
    "f_string": bool,
    "return": tuple[int, str],
}
collect_multiline_string.__annotations__ = {
    "iter_val": enumerate,
    "reference": str,
    "f_string": bool,
    "return": tuple[int, str],
}
collect_definition.__annotations__ = {
    "line": str,
    "lines": list[str],
    "lineno": int,
    "source": str,
    "source_iter": enumerate,
    "reference_indent": int,
    "prev": tuple[int, str],
    "return": tuple[int, str, int, list[str]],
}
dedent.__annotations__ = {"text": str, "return": str}
get_indent.__annotations__ = {"line": str, "return": int}
skip.__annotations__ = {"iter_val": Iterable, "n": int, "return": None}
is_alternative_statement.__annotations__ = {"line": str, "return": bool}
## code adjustments ##
skip_alternative_statements.__annotations__ = {
    "line_iter": enumerate,
    "return": tuple[int, str, int],
}
offset_adjust.__annotations__ = {"f_locals": dict, "return": dict}
control_flow_adjust.__annotations__ = {
    "lines": list[str],
    "indexes": list[int],
    "return": tuple[bool, list[str], list[int]],
}
indent_lines.__annotations__ = {
    "lines": list[str],
    "indent": int,
    "return": list[str],
}
extract_iter.__annotations__ = {
    "line": str,
    "number_of_indents": int | None,
    "return": str,
}
iter_adjust.__annotations__ = {
    "outer_loop": list[str],
    "return": tuple[bool, list[str]],
}
loop_adjust.__annotations__ = {
    "lines": list[str],
    "indexes": list[int],
    "outer_loop": list[str],
    "pos": tuple[int, int],
    "return": tuple[list[str], list[int]],
}
has_node.__annotations__ = {"line": str, "node": str, "return": bool}
send_adjust.__annotations__ = {
    "line": str,
    "return": tuple[None | int, None | list[str, str]],
}
yield_adjust.__annotations__ = {
    "line": str,
    "offsets": tuple[int, int],
    "return": str,
}
get_loops.__annotations__ = {
    "lineno": int,
    "jump_positions": list[tuple[int, int]],
    "return": list[tuple[int, int]],
}
## expr_getsource ##
code_attrs.__annotations__ = {"return": tuple[str, ...]}
attr_cmp.__annotations__ = {
    "obj1": object,
    "obj2": object,
    "attr": tuple[str, ...],
    "return": bool,
}
getcode.__annotations__ = {"obj": AnyGeneratorType, "return": CodeType}
getframe.__annotations__ = {"obj": AnyGeneratorType, "return": FrameType}
expr_getsource.__annotations__ = {"FUNC": AnyGeneratorType, "return": str}
## genexpr ##
extract_genexpr.__annotations__ = {
    "source_lines": list[str],
    "return": GeneratorType,
}
## lambda ##
extract_lambda.__annotations__ = {"source_code": str, "return": GeneratorType}
### copying/pickling ###
Pickler.__copy__.__annotations__ = {"return": Pickler}
Pickler.__deepcopy__.__annotations__ = {"memo": dict, "return": Pickler}
Pickler.__getstate__.__annotations__ = {"return": dict}
Pickler.__setstate__.__annotations__ = {"state": dict, "return": None}
frame.__init__.__annotations__ = {"frame": FrameType | None, "return": None}
frame.clear.__annotations__ = {"return": None}
frame.__bool__.__annotations__ = {"return": bool}
code.__init__.__annotations__ = {"code": CodeType | None, "return": None}
code.__bool__.__annotations__ = {"return": bool}
### Generator ###
Generator._custom_adjustment.__annotations__ = {
    "line": str,
    "lineno": int,
    "return": list[str],
}
Generator._clean_source_lines.__annotations__ = {"return": list[str]}
Generator._create_state.__annotations__ = {"return": None}
Generator.init_states.__annotations__ = {"return": Iterable}
Generator._frame_init.__annotations__ = {"return": str}
Generator.__init__.__annotations__ = {
    "FUNC": AnyGeneratorType | str | None,
    "return": None,
}
Generator.__len__.__annotations__ = {"return": int}
Generator.__iter__.__annotations__ = {"return": Iterable}
Generator.__next__.__annotations__ = {"return": Any}
Generator.send.__annotations__ = {"arg": Any, "return": Any}
Generator.close.__annotations__ = {"return": None}
Generator.throw.__annotations__ = {"exception": Exception, "return": NoReturn}
Generator._copier.__annotations__ = {"FUNC": Callable, "return": Generator}
Generator.__copy__.__annotations__ = {"return": Generator}
Generator.__deepcopy__.__annotations__ = {"memo": dict, "return": Generator}
Generator.__getstate__.__annotations__ = {"return": dict}
Generator.__setstate__.__annotations__ = {"state": dict, "return": None}
