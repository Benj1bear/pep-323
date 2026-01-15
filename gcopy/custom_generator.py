##################################
### picklable/copyable objects ###
##################################
from sys import exc_info, version_info
## minimum version supported ##
if version_info < (3, 5):
    raise ImportError("Python version 3.5 or above is required")

from copy import copy, deepcopy

from functools import partial
from inspect import getsource

from textwrap import dedent
from types import (
    AsyncGeneratorType,
    CodeType,
    CellType,
    CoroutineType,
    FrameType,
    FunctionType,
    GeneratorType,
)
from typing import Any, Union

from gcopy.source_processing import (
    clean_lambda,
    clean_source_lines,
    control_flow_adjust,
    expr_getsource,
    genexpr_adjust,
    get_indent,
    get_loops,
    loop_adjust,
    outer_loop_adjust,
    sign
)
from gcopy.track import track_shift, patches

from gcopy.utils import (
    attr_cmp,
    code_attrs,
    copier,
    empty_generator,
    get_globals,
    get_nonlocals,
    getcode,
    getframe,
    hasattrs,
    catch_errors
)


try:
    from typing import NoReturn
except:
    ## for 3.5 since 3.6.2; there might be alternatives that are better than this for 3.5 ##
    NoReturn = {"NoReturn"}


class Pickler:
    """
    class for allowing general copying and pickling of
    some otherwise uncopyable or unpicklable objects

    Note: on pickling it's assumed that you have static
    attributes _attrs and _not_allowed that determine
    what attributes get pickled
    """

    _not_allowed = tuple()

    ## for copying ##
    def __copy__(self) -> object:
        ## used composition here to avoid tight coupling with Pickler._copier ##
        return copier(self, copy)

    def __deepcopy__(self, memo: dict) -> object:
        return copier(self, deepcopy)

    def copy(self, deep: bool = True) -> object:
        """short hand method for copying"""
        if deep:
            return deepcopy(self)
        return copy(self)

    def _pickler_get(obj: object) -> object:
        """Used on recursive pickling of objects"""
        if issubclass(type(obj), Pickler):
            ## we create a copy to avoid affecting the the original Pickler instances attributes ##
            obj = obj.copy()
            ## subclasses of Pickler will remove attributes on pickling ##
            for attr in obj._not_allowed:
                if hasattr(obj, attr):
                    delattr(obj, attr)
        return obj

    ## for pickling ##
    def __getstate__(self, FUNC: FunctionType = _pickler_get) -> dict:
        """Serializing pickle (what object you want serialized)"""
        dct, attrs = dict(), self._attrs
        for attr in attrs:
            if hasattr(self, attr) and not attr in self._not_allowed:
                dct[attr] = FUNC(getattr(self, attr))
        return dct

    def __setstate__(self, state: dict) -> None:
        """Deserializing pickle (returns an instance of the object with state)"""
        for key, value in state.items():
            setattr(self, key, value)


class code(Pickler):
    """For pickling and copying code objects"""

    _attrs = code_attrs()

    def __init__(self, code_obj: CodeType = None) -> None:
        if code_obj:
            for attr in self._attrs:
                setattr(self, attr, getattr(code_obj, attr, None))

    def __bool__(self) -> bool:
        """Used on i.e. if code_obj:"""
        return hasattrs(self, self._attrs)

    def __eq__(self, obj: Any) -> bool:
        return attr_cmp(self, obj, self._attrs)
    
    def __repr__(self) -> str:
        code = getattr(self, "co_code", None)
        code_attr = (getattr(code,"co_name", ""), getattr(code,"co_filename", ""), getattr(self,"f_lineno",""))
        return super().__repr__()[:-1] + " %s, file '%s', line %s>" % code_attr


class frame(Pickler):
    """
    acts as the initial FrameType

    Note: on pickling ensure f_locals and f_back can be pickled

    Also, this class treats global frames as having no local variables
    to avoid errors in pickling e.g. global frame (on f_back) will have
    its f_locals equal 'None'.
    """

    _attrs = (
        "f_back",
        "f_code",
        "f_lasti",
        "f_lineno",
        "f_locals",
        "f_globals",
        "f_builtins",
        "f_trace",
        "f_trace_lines",
        "f_trace_opcodes",
    )
    _not_allowed = ("f_globals", "f_builtins")

    def __init__(self, frame: FrameType = None) -> None:
        if frame:
            for attr in self._attrs[2:]:
                setattr(self, attr, getattr(frame, attr, None))
            ## to prevent interferrence with pickling
            self.f_back = type(self)(getattr(frame, "f_back", None))
            self.f_code = code(getattr(frame, "f_code", None))
            if self.f_globals == self.f_locals:
                self.f_locals = {}
                ## we have to do this as well since in co_consts you ##
                ## get records of globally defined code objects      ##
                self.f_code = code()
            return
        self.f_locals = {}
        self.f_globals = get_globals()

    def clear(self) -> None:
        """clears f_locals e.g. 'most references held by the frame'"""
        self.f_locals = {}

    ## we have to implement this if I'm going to go 'if frame:' (i.e. in frame.__init__) ##
    def __bool__(self) -> bool:
        """Used on i.e. if frame:"""
        return hasattrs(self, ("f_code", "f_lasti", "f_lineno", "f_locals"))

    def __eq__(self, obj: Any) -> bool:
        attrs = list(self._attrs)
        for attr in self._not_allowed:
            attrs.remove(attr)
        attrs.remove("f_back")
        return attr_cmp(self, obj, attrs)

    def __setstate__(self, state: dict) -> None:
        Pickler.__setstate__(self, state)
        self.f_globals = get_globals()

    def __repr__(self) -> str:
        code = getattr(self, "co_code", None)
        code_attr = (getattr(code,"co_name", ""), getattr(code,"co_filename", ""), getattr(self,"f_lineno",""))
        return super().__repr__()[:-1] + ", file '%s', line %s, code %s>" % (code_attr[1:] + (code_attr[0],))


class EOF(StopIteration, StopAsyncIteration):
    """
    Custom exception to exit out of the generator on return statements.
    For consistency, this class is only used for instance checking
    """


#################
### Generator ###
#################
class BaseGenerator:
    """
    Converts a generator function into a generator
    function that is copyable (e.g. shallow and deepcopy)
    and potentially pickle-able.

    This should be very portable or at least closely so across
    python implementations ideally.

    The dependencies for this to work requires that you've met
    the assumptions under the assumptions requirement section
    in the custom_generator.md file.

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
    AsyncGenerator such that it's very easy to integrate across
    different implementations without losing the familiar api.
    """

    ## Note: by default GeneratorType does not have the  ##
    ## __bool__ (or __nonzero__ in python 2.x) attribute ##
    ## so we don't necessarily have to implement one ##

    __copy__, __deepcopy__, copy = Pickler.__copy__, Pickler.__deepcopy__, Pickler.copy

    def __repr__(self) -> str:
        return super().__repr__()[:-1] + ", Initialized: %s>" % getattr(self, "_internals", {}).get("initialized", "")
    
    def _api_setup(self) -> None:
        """sets up the api; subclasses should override this method for alternate api setup"""
        self._internals = {
            "prefix": "",
            "type": "",
            "version": "",
        }

    def __init__(
        self,
        FUNC: Union[FunctionType, GeneratorType, str] = None,
    ) -> None:
        """
        Takes in a function/generator or its source code as the first argument

        If FUNC=None it will simply initialize as without any attributes, this
        is for the __setstate__ method in Pickler._copier use case

        Note:
         - gi_running: is the generator currently being executed
         - gi_suspended: is the generator currently paused e.g. state is saved

        Also, all attributes are set internally first and then exposed to the api.
        The internals are accessible via the _internals dictionary
        """
        ## for the api setup ##
        self._api_setup()
        ## unused attribute for initialized generator (but will be set to a callable for uninitialized generators) ##
        self.__call__ = Generator_call_error
        ## __setstate__ from Pickler._copier ##
        if FUNC:
            ## Note: make sure lineno is set after clean_source lines since clean_source lines uses it ##

            ## needed to identify certain attributes ##
            prefix = self._internals["prefix"]
            ## running generator ##
            if hasattr(FUNC, prefix + "code"):
                self._internals.update(
                    {
                        "linetable": [],
                        "frame": frame(getframe(FUNC)),
                        "code": code(getcode(FUNC)),
                        ## 'gi_yieldfrom' was introduced in python version 3.5 and yield from ... in 3.3 ##
                        "yieldfrom": getattr(FUNC, prefix + "yieldfrom", None),
                        "suspended": getattr(FUNC, prefix + "suspended", True),
                        "running": getattr(FUNC, prefix + "running", False),
                        "initialized": True, # should be removed
                    }
                )
                ## setup api if it's currently running ##
                for key in ("code", "frame", "suspended", "yieldfrom", "running"):
                    setattr(self, prefix + key, self._internals[key])
                ## co_name is readonly e.g. can't be changed by user ##
                if self._internals["code"].co_name == "<genexpr>":
                    self._internals["source"] = expr_getsource(FUNC)
                    ## remove the internally set .0 if it exists for some reason we need ##
                    ## to do it after expr_getsource otherwise it doesn't get deleted ##
                    genexpr_adjust(self, self._internals["source"])
                ## must be a function ##
                elif self._internals["code"].co_name == "<lambda>":
                    clean_lambda(self, FUNC)
                else:
                    self._internals["source"] = dedent(getsource(getcode(FUNC)))
                    ## we need to record a linetable for the lineno since the source code gets modified ##
                    clean_source_lines(self, True)
                    self._internals["lineno"] = (
                        self._internals["frame"].f_lineno - self._internals["code"].co_firstlineno
                    )
                    ## can't have a lineno of 0 (implies the start of a generator) ##
                    if self._internals["lineno"] == 0:
                        self._internals["lineno"] = 1
                    else:
                        self._internals["lineno"] = self._internals["linetable"][self._internals["lineno"]]
                        #  + lineno_adjust(self._internals["frame"]) ## for compound statements if implementing ##
                        ## only increase if it's not inside a loop ##
                        self._internals["lineno"] += 1 - bool(
                            get_loops(
                                self._internals["lineno"],
                                self._internals.get("jump_positions", []),
                            )
                        )
                    track_shift(FUNC, self._locals().get(".internals", {}))
            ## uninitialized generator ##
            else:
                ## generator function ##
                if isinstance(FUNC, FunctionType):
                    self._internals.update(
                        {
                            "code": code(FUNC.__code__),
                            "frame": frame(), # shouldn't the frame be made on call??
                            "suspended": False,
                            "yieldfrom": None,
                            "running": False,
                            "initialized": False, # might be removed since should use frame instead
                        }
                    )
                    self.__name__ = FUNC.__code__.co_name
                    self.__defaults__ = FUNC.__defaults__
                    ## since it's uninitialized we can bind the signature to __call__ ##
                    ## and overwrite the __call__ signature + other metadata with the functions ##
                    ## Note: globals() is used as the scope to access functions within this module ##
                    self.__call__ = sign(Generator__call__, FUNC, globals(), True)
                    if self.__name__ == "<lambda>":
                        clean_lambda(self, FUNC)
                    else:
                        self._internals["source"] = dedent(getsource(FUNC))
                        clean_source_lines(self)
                        track_shift(FUNC, self._locals().get(".internals", {}))
                else:
                    raise TypeError("type '%s' is an invalid initializer for a Generator" % type(FUNC))
                ## modified every time __next__ is called; always start at line 1 for ##
                ## uninitialized and set it after clean_source_lines (since this modifies it) ##
                self._internals["lineno"] = 1
            if hasattr(FUNC, "__closure__"):
                ## add its closure if it has one. It shouldn't ##
                ## effect the existing locals, only adds the attribute ##
                self._bind(FUNC)
                ## only update locals with nonlocals on init ##
                ## every other instance should require the variables ##
                ## to exist in the local scope first ##
                self._locals().update(get_nonlocals(self))
            ## create the states ##
            self._internals["state"] = self._internals["source_lines"]
            self._internals["state_generator"] = self._init_states()
            f_locals = self._locals()
            internals = {
                "EOF": EOF,
                "exec_info": exc_info,
                "partial": partial,
                ".args": [],
                ".send": None,
                'catch_errors': catch_errors,
            }
            if ".internals" not in f_locals:
                f_locals[".internals"] = internals
            ## i.e. if using track for implicit iterators it will create a .internals variable to store the trackers ##
            else:
                f_locals[".internals"].update(internals)

    def _init_states(self) -> GeneratorType:
        """Initializes the state generation as a generator"""
        if not self._internals["initialized"]:
            ## reset the state_generator to preserve the exception 
            ## (otherwise it'll become a StopIteration error for subsequent 
            ## uses (since it'll become an empty generator) which is 
            ## unusual/unexpected behavior) ##
            self._internals["state_generator"] = self._init_states()
            raise TypeError("Cannot iterate an uninitialized function generator")
        self._internals["loops"] = get_loops(self._internals["lineno"], self._internals.get("jump_positions", []))
        ## if no state then it must be EOF ##
        while self._internals["state"]:
            yield self._create_state()

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
        loops = self._internals["loops"]
        index = self._internals["lineno"] - 1  ## for 0 based indexing ##
        if loops:
            start_pos, end_pos = loops[-1]
            ## adjustment ##
            indexes = []
            ## end_pos should be excluded for python slicing, however, if index and end_pos 
            ## are the same we don't want either to be included
            if index == end_pos:
                blocks = []
            else:
                end_pos += 1
                blocks = self._internals["source_lines"][index:end_pos]
                loops.pop()
                blocks, indexes = control_flow_adjust(
                    blocks,
                    list(range(index, end_pos)),
                    get_indent(self._internals["source_lines"][start_pos]),
                )
                blocks, indexes = loop_adjust(
                    blocks, indexes, self._internals["source_lines"][start_pos:end_pos], *(start_pos, end_pos)
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
        """Short hand method for the current states/frames locals"""
        return self._internals["frame"].f_locals

    def _frame_init(self, exception: str = "", sending: bool = False) -> tuple[int, FunctionType]:
        """
        initializes the frame with the current states
        variables but also adjusts the current state
        """
        try:
            # set the next state and setup the function; it will raise a StopIteration for us
            next(self._internals["state_generator"])
        except StopIteration as e:
            self._close()
            raise e
        ## adjust the current state ##
        if exception:
            indent = get_indent(self._internals["state"][0])
            if self._internals["state"][0][indent:].startswith("try:"):
                self._internals["state"] = [
                    self._internals["state"][0],
                    " " * (indent + 4) + "raise " + exception,
                ] + self._internals["state"][1:]
                index_0 = self._internals["linetable"][0]
                self._internals["linetable"] = [index_0, index_0] + self._internals["linetable"][1:]
            else:
                self._internals["state"] = [" " * indent + "raise " + exception] + self._internals["state"]
                ## -1 so that on +1 (on _update) it will be correct ##
                self._internals["linetable"] = [self._internals["linetable"][0] - 1] + self._internals["linetable"]
        ## initialize the internal locals ##
        f_locals = self._locals()
        if not sending:
            f_locals[".internals"].update({".send": None})
        ## make sure if it has a closure that it's updating the locals (only if it still exists) ##
        for key, value in get_nonlocals(self).items():
            if key in f_locals:
                f_locals[key] = value
        ## adjust the initializers ##
        indent = " " * 4
        init = [
            self._internals["version"] + "def next_state():",
            ## get the variables to update the frame
            indent + "from inspect import currentframe",
            indent + "frame = currentframe()",
            indent + "self = frame.f_back.f_locals['self']",
            indent + "self._locals()['.internals']['.frame'] = frame",
            indent + "locals().update(self._locals())",
            indent + "locals()['.internals']['.self'] = self",
            indent + "del frame, self, currentframe",
        ]
        ## make sure variables are initialized ##
        for key in f_locals:
            if isinstance(key, str) and key.isidentifier():
                init += [" " * 4 + "%s=locals()['.internals']['.self']._locals()[%s]" % (key, repr(key))]
        ## manual variable initialization needs to be added since updating locals does   ##
        ## not update the frames locals; try not to use variables here (otherwise it can ##
        ## mess with the state); 'return EOF()' is appended to help return after a loop  ##
        self.__source__ = init + self._internals["state"] + ["    return locals()['.internals']['EOF']()"]
        ## we need to give the original filename before using exec for the code_context to ##
        ## be correct in track_iter therefore we compile first to provide a filename then exec ##
        code_obj = compile("\n".join(self.__source__), "<Generator>", "exec")
        ## make sure the globals are there ##
        temp_globals = patches
        temp_globals.update(self._internals["frame"].f_globals)
        exec(code_obj, temp_globals, locals())
        return len(init), locals()["next_state"]

    def _update(self, init_length: int) -> None:
        """Update the line position and frame"""
        _frame = self._internals["frame"] = frame(self._locals()[".internals"][".frame"])
        _frame.f_back = None # we're not saving the previous states #

        #### update f_locals ####

        f_locals = _frame.f_locals
        ## remove variables that interfere with pickling ##
        for attr in (".send", ".frame", ".self"):
            f_locals[".internals"].pop(attr, None)

        if ".yieldfrom" in f_locals[".internals"]:
            self._internals["yieldfrom"] = f_locals[".internals"][".yieldfrom"]

        #### update lineno ####

        ## update the frames lineno in accordance with its state (-1 for 0 based indexing) ##
        adjusted_lineno = _frame.f_lineno - init_length - 1
        end_index = len(self._internals["linetable"]) - 1
        ## empty linetable ##
        if end_index == -1:
            ## EOF ##
            self._internals["state"] = None
            self._internals["lineno"] = len(self._internals["source_lines"])
        else:
            ## update the lineno ##
            self._internals["lineno"] = self._internals["linetable"][adjusted_lineno] + 1
            loops = self._internals["loops"] = get_loops(self._internals["lineno"], self._internals.get("jump_positions", []))
            if not loops:
                ## if we can advance the lineno then advance it ##
                ## else (since not in loop) EOF ##
                if end_index > adjusted_lineno:
                    self._internals["lineno"] += 1
                else:
                    ## EOF ##
                    self._internals["state"] = None
                    self._internals["lineno"] = len(self._internals["source_lines"])
            ## if inside a loop and we can advance the lineno then advance it ##
            elif self._internals["lineno"] < loops[-1][1]:
                self._internals["lineno"] += 1

    def _close(self) -> None:
        """
        closes the generator; sets all the internal variables to
        None or False and the generator to an empty generator
        """
        self._internals.update(
            {
                "state_generator": empty_generator(),
                "state": None,
                "frame": None,
                "running": False,
                "suspended": False,
                "yieldfrom": None,
            }
        )

    def __call__(self, *args, **kwargs) -> GeneratorType:
        """
        Calls the instances call method if it has one (only for uninitialized Function generators)
        and does type checking before calling

        Note: Having a __call__ method on a Generator also
        allows Generator.__init__ to be used as a decorator
        """
        if isinstance(self, type):
            raise TypeError(
                "Only instances of types/classes are allowed (Note: this method is for instances of the Generator type)"
            )
        return self.__call__(self, *args, **kwargs)

    def __instancecheck__(self, instance: object) -> bool:
        return isinstance(instance, Union[eval(self._internals["type"]), type(self)])

    def __subclasscheck__(self, subclass: type) -> bool:
        return issubclass(subclass, Union[eval(self._internals["type"]), type(self)])

    def __getstate__(self, FUNC: FunctionType = Pickler._pickler_get) -> dict:
        """Similar to the __getstate__ method of Pickler but pertaining to self._internals"""
        dct = dict()
        for key, value in self._internals.items():
            if key != "state_generator":
                dct[key] = FUNC(value)
        dct = {"_internals": dct}
        for attr in ("__name__", "__defaults__"):
            if hasattr(self, attr):
                dct[attr] = getattr(self, attr, None)
        return dct

    def __setstate__(self, state: dict) -> None:
        """
        Unpickles the generator then sets up the api and the state
        """
        Pickler.__setstate__(self, state)
        ## setup the state api + generator ##
        prefix = self._internals["prefix"]
        for key in ("code", "frame", "suspended", "yieldfrom", "running"):
            setattr(self, prefix + key, self._internals.get(key, None))
        self._internals["state_generator"] = self._init_states()

    def _bind(self, FUNC: FunctionType) -> None:
        """Convenience method to bind a generator to closure cells"""
        self.__closure__ = FUNC.__closure__
        self.__code__ = self._internals["code"]
        ## in case it's doing i.e. recursion and it's caught as a nonlocal ##
        ## this means we need to replace it with its Generator version ##
        if FUNC.__name__ in FUNC.__code__.co_freevars:
            index = FUNC.__code__.co_freevars.index(FUNC.__name__)
            ## we need a copy of the function without itself being in its closure cell ##
            ## then wrap this in a Generator ##
            closure = FUNC.__closure__
            ## remove the function from the closure and replace the current scope with the Generator version ##
            ## we have to modify the code object since FunctionType picks up on this ##
            _code = FUNC.__code__
            kwargs = {attr: getattr(_code, attr) for attr in code_attrs()}
            kwargs["co_freevars"] = kwargs["co_freevars"][:index] + kwargs["co_freevars"][index + 1 :]
            _code = CodeType(*kwargs.values())
            ## create the new function ##
            FUNC = FunctionType(
                _code,
                get_globals(),
                FUNC.__name__,
                FUNC.__defaults__,
                closure[:index] + closure[index + 1 :],
            )
            GEN_FUNC = type(self)(FUNC)
            ## you need to add itself to the closure; importantly, its __call__ method ##
            GEN_FUNC.__closure__ += (CellType(GEN_FUNC.__call__),)
            GEN_FUNC._internals["code"].co_freevars += (FUNC.__name__,)
            ## initialize its locals since this is an uninitialized generator ##
            GEN_FUNC._locals()[FUNC.__name__] = GEN_FUNC.__call__
            ## replace the function with the Generator version ##
            closure = self.__closure__
            self.__closure__ = closure[:index] + (CellType(GEN_FUNC),) + closure[index + 1 :]


def Generator__call__(self, *args, **kwargs) -> GeneratorType:
    """
    initializes the generators locals with arguments and keyword arguments
    but is also a shorthand method to initialize the state generator

    Note: this method must be set on initialisation otherwise for some reason
    it still tries to call this method rather than what sometimes should be
    called is the dynamically created method
    """
    ## get the arguments from the function call ##
    arguments = locals()
    ## we have to make a copy to retain the unintialisation ##
    self_copy = self.copy()
    ## since it's an intialization we bind it to the closure (otherwise this would be unexpected) ##
    if hasattr(self, "__closure__"):
        self_copy._bind(self)
    if len(arguments) > 1:
        del arguments["self"]
        self_copy._locals().update(arguments)
    self_copy.__call__ = Generator_call_error
    self_copy._internals["initialized"] = True
    return self_copy


def Generator_call_error(*args, **kwargs) -> NoReturn:
    """Error for when an initialized generator is called"""
    raise TypeError("Initialized generators cannot be called, only uninitialized Function generators may be called")


class Generator(BaseGenerator):

    def _api_setup(self) -> None:
        """sets up the api; subclasses should override this method for alternate api setup"""
        self._internals = {
            "prefix": "gi_",
            "type": "GeneratorType",  ## has to be a string, otherwise doesn't get pickled ##
            "version": "",  ## specific to 'async ' Generators for _frame_init (don't change) ##
        }

    def __iter__(self) -> GeneratorType:
        """Converts the generator function into an iterable"""
        while True:
            try:
                yield next(self)
            except StopIteration:
                break

    def __next__(self, exception: str = "", sending: bool = False) -> Any:
        """updates the current state and returns the result"""
        ## update with the new state and get the frame ##
        init_length, next_state = self._frame_init(exception, sending)
        try:
            self._internals["running"] = True
            self._internals["suspended"] = False
            result = next_state()
            if isinstance(result, EOF):
                raise StopIteration(*result.args[0:1])
        except Exception as e:
            self._close()
            raise e
        self._internals["running"] = False
        self._internals["suspended"] = True
        self._update(init_length)
        return result

    def send(self, arg: Any) -> Any:
        """
        Send takes exactly one argument 'arg' that
        is sent to the functions yield variable
        """
        if arg is not None and self._internals["lineno"] == 1:
            raise TypeError("can't send non-None value to a just-started generator")
        self._locals()[".internals"][".send"] = arg
        return self.__next__(sending=True)

    def close(self) -> None:
        """
        Throws a GeneratorExit and closes the generator clearing its
        frame, state_generator, and yieldfrom

        return = return
        yield  = return 1
        """
        try:
            if self.__next__("GeneratorExit()"):
                raise RuntimeError("generator ignored GeneratorExit")
        except (GeneratorExit, StopIteration):
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
        raise TypeError("exceptions must be classes or instances deriving from BaseException, not %s" % type(exception))


class AsyncGenerator(BaseGenerator):

    def _api_setup(self) -> None:
        """sets up the api; subclasses should override this method for alternate api setup"""
        self._internals = {
            "prefix": "ag_",
            "type": "AsyncGeneratorType",  ## has to be a string, otherwise doesn't get pickled ##
            "version": "async ",  ## specific to 'async ' Generators for _frame_init ##
        }

    async def __aiter__(self) -> AsyncGeneratorType:
        while True:
            try:
                yield (await anext(self))
            except StopAsyncIteration:
                break

    async def __anext__(self, exception: str = "", sending: bool = False) -> CoroutineType:
        """updates the current state and returns the result"""
        ## catch StopIteration on next(self._internals["state_generator"]) ##
        ## and instead raise a StopAsyncIteration ##
        try:
            ## update with the new state and get the frame ##
            init_length, next_state = self._frame_init(exception, sending)
        except StopIteration as e:
            raise StopAsyncIteration(*e.args[0:1])
        try:
            self._internals["running"] = True
            self._internals["suspended"] = False
            result = await next_state()
            if isinstance(result, EOF):
                ## coroutines can't throw StopIterations, EOF throws a StopIteration e.g. in accordance with its __mro__ ##
                raise StopAsyncIteration(*result.args[0:1])
        except Exception as e:
            self._close()
            raise e
        self._internals["running"] = False
        self._internals["suspended"] = True
        self._update(init_length)
        return result

    async def asend(self, arg: Any) -> CoroutineType:
        """
        Send takes exactly one argument 'arg' that
        is sent to the functions yield variable
        """
        if arg is not None and self._internals["lineno"] == 1:
            raise TypeError("can't send non-None value to a just-started generator")
        self._locals()[".internals"][".send"] = arg
        return await self.__anext__(sending=True)

    async def aclose(self) -> CoroutineType:
        """
        Throws a GeneratorExit and closes the generator clearing its
        frame, state_generator, and yieldfrom
        """
        try:
            if await self.__anext__("GeneratorExit()"):
                raise RuntimeError("generator ignored GeneratorExit")
        except (GeneratorExit, StopAsyncIteration):
            ## This error is internally ignored by generators during closing ##
            pass
        finally:
            self._close()

    async def athrow(self, exception: Exception) -> CoroutineType:
        """
        Raises an exception from the last line in the
        current state e.g. only from what has been
        """
        if issubclass(exception, BaseException):
            if isinstance(exception, type):
                exception = exception.__name__
            else:
                exception = repr(exception)
            return await self.__anext__(exception)
        raise TypeError("exceptions must be classes or instances deriving from BaseException, not %s" % type(exception))
