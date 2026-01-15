################
### tracking ###
################
import builtins  # # for consistency (it switches between a module and a dict) ##
# import itertools, collections # to get the rest of the iterators
from inspect import currentframe, getframeinfo, getsourcelines
from types import FrameType, FunctionType

## imports used for the monkey patching ##
from typing import Any, Iterable, Iterator, Union
from gcopy.utils import Wrapper, get_history_item, getcode, is_cli

## used for python versions prior to PEP 667 in order to update the f_locals properly ##
from sys import version_info
import ctypes


def get_indent(line: str) -> int:
    """Gets the number of spaces used in an indentation"""
    count = 0
    for char in line:
        if char != " ":
            break
        count += 1
    return count


def track_iter(obj: Union[Iterator, Iterable], frame: FrameType) -> Union[Iterator, Iterable]:
    """
    Tracks an iterator in the local scope initiated by a for loop

    This function has a specific use case where the initialization
    of an iterator via a for loop implicitly does not allow for
    reliable extraction from the garbage collector and thus manually
    assigning the iterator for tracking is used

    Note: variables are signified as '.%s' % number_of_indents
    i.e.
        for i in range(3) is 4 indents and thus is assigned '.4'

    This way makes it more effective to retrieve the iterator
    rather than appending iterators. This means only numbers
    that are divisble by 4 should not be used in general usage
    by users.

    When tracking generator expressions it uses the current
    bytecode instruction index instead
    """
    ## i.e. in case we're checking if it's the same code object in source_processing.extract_source_from_comparison ##
    if frame.f_code.co_filename == "<Don't track>":
        return obj
    f_locals = frame.f_locals
    if ".internals" not in f_locals:
        f_locals[".internals"] = {}
    if frame.f_code.co_name == "<genexpr>":
        if ".mapping" not in f_locals[".internals"]:
            iterator = f_locals.pop(".0")
            f_locals[".internals"].update(
                {
                    ".mapping": [0],
                    ".0": iterator,
                }
            )
        key = frame.f_lasti
        if key not in f_locals[".internals"][".mapping"]:
            f_locals[".internals"][".mapping"] += [key]
    else:
        if is_cli():
            code_context = get_history_item(-frame.f_lineno)
        else:
            ## specific to the Generator class ##
            if frame.f_code.co_filename == "<Generator>":
                source = frame.f_back.f_locals["self"].__source__
                code_context = source[frame.f_lineno - 1]
                ## we have to do it this way since '.internals' is not initiailized in the current f_locals ##
                f_locals = f_locals[".internals"][".self"]._locals()
            else:
                code_context = getframeinfo(frame).code_context[0]
        key = get_indent(code_context)
        ## won't work for compound statements that are in block statements ##
        ## therefore, we check for a block statement and add 4 if so ##
        ## e.g. if iter(k): iter(j); iter(f) e.g. how to get j and f set correctly ##
        # temp = code_context[key:]
        ## needs fixing e.g. lineno_adjust somewhere ##
        ## also why does it not have other block conditions?? e.g. except, elif,case,default etc. ##
        # if (
        #     temp.startswith("if ")
        #     or temp.startswith("for ")
        #     or temp.startswith("while ")
        #     or is_definition(temp)
        # ) and lineno_adjust(frame) == 0:
        #     key += 4
    f_locals[".internals"][".%s" % key] = obj
    return obj


def track_adjust(f_locals: dict) -> None:
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
    for index, key in enumerate(f_locals.pop(".mapping", []), start=1):
        f_locals[".%s" % (index * 4)] = f_locals.pop(".%s" % key)


def track_shift(FUNC: FunctionType, internals: dict) -> None:
    """adjust the indentation based trackers to a minimum of 4 spaces"""
    indent = get_indent(getsourcelines(getcode(FUNC))[0][0])
    for key in tuple(internals.keys()):
        if isinstance(key, str) and key[0] == "." and key[1:].isdigit():
            new_key = int(key[1:])
            if new_key % 4 == 0:
                internals[".%s" % (new_key - indent)] = internals.pop(key)


####################
## monkey patches ##
####################


class track(Wrapper):
    """Wrapper class to track iterators (we need to track iterators so they show up in locals)"""

    _expected = ["__iter__", "__next__"]

    def __iter__(self) -> Iterator:
        new_obj = iter(self.obj)
        ## for some reason it doesn't work if we reinstantiate (shouldn't be doing so anyway) ##
        if self.obj is new_obj:
            return self
        frame = currentframe().f_back
        new_obj = type(self)(new_obj)
        return track_iter(new_obj, frame)

    def __next__(self) -> Any:
        self.running = True
        return next(self.obj)


class atrack(Wrapper):
    """Wrapper class to track async iterators (we need to track iterators so they show up in locals)"""

    _expected = ["__aiter__", "__anext__"]

    def __aiter__(self) -> Iterator:
        # Async iterators always return awaitables ##
        new_obj = type(self)(aiter(self.obj))
        frame = currentframe().f_back
        return track_iter(new_obj, frame)

    async def __anext__(self) -> Any:
        self.running = True
        return await anext(self.obj)


def wrapper_proxy(FUNC: FunctionType) -> FunctionType:
    """
    Proxy for type checking when using the tracked iterators
    
    e.g. modifies for arg1 in isinstance(arg1, arg2)
    """

    def wrapper(obj, class_or_tuple: Union[type, tuple]) -> bool:
        if type(class_or_tuple) in (track, atrack):
            class_or_tuple = class_or_tuple.obj
        return FUNC(obj, class_or_tuple)

    return wrapper


def get_iterators(*modules: Iterable[Union[type, object]], merge: bool = True) -> dict:
    """
    Gets all the attributes that are iterators/iterable objects
    
    merge = True; will merge all the iterators into one dictionary without module names
    """
    dct = {}
    temp = {}
    for module in modules:
        for name, obj in vars(module).items():
            if isinstance(obj, type) and issubclass(obj, Union[Iterator, Iterable]):
                temp[name] = obj
        if not merge:
            dct[module.__name__] = temp
            temp = {}
    dct.update(temp)
    return dct


## Note: Can't change syntactical initiations e.g. (,), [], {}, and {...:...} ## include the type checker patches as well ##
# , itertools, collections, merge=True
patches = {name: track(obj) for name, obj in get_iterators(builtins).items()}
patches.update({FUNC.__name__: wrapper_proxy(FUNC) for FUNC in (isinstance, issubclass)})

def patch_iterators(scope: dict = None) -> None:
    """
    Sets all builtin iterators in the current scope to their tracked versions

    Note: make sure to patch iterators before using them else Iterator.running
    will be incorrect; this is also true for saving the iterator as well.

    Examples of how to use:

    ## globally ##
    patch_iterators()
    
    ## only for the functions scope ##
    @patch_iterators
    def test():
        ...
    
    ## only for the classes scope ##
    class test:
        patch_iterators()
    """
    frame = None
    if scope is None:
        frame = currentframe()
        scope = frame.f_back.f_locals
    elif isinstance(scope, FunctionType):
        ## for some reason the scopes don't work with dict.update e.g. # temp_globals = scope.__globals__;temp_globals.update(patches)##
        ## might be because of using as pointers rather than creating a separate new dict ##
        temp_globals = {**scope.__globals__, **patches} #  scope.__globals__ | patches ## is also possible
        return FunctionType(scope.__code__, temp_globals, scope.__name__, scope.__defaults__, scope.__closure__)
    if not isinstance(scope, dict):
        raise TypeError("expected type 'dict' but recieved '%s'" % type(scope).__name__)
    scope.update(patches)
    ## prior to PEP 667 ##
    if frame and version_info < (3, 13):
        ctypes.pythonapi.PyFrame_LocalsToFast(ctypes.py_object(frame), ctypes.c_int(0))


def unpatch_iterators(scope: dict = None) -> None:
    """Assumes all iterators are patched and deletes them from the scope"""
    frame = None
    if scope is None:
        frame = currentframe()
        scope = frame.f_back.f_locals
    if not isinstance(scope, dict):
        raise TypeError("expected dict, got %s" % type(scope).__name__)
    ## Note: Can't change syntactical initiations e.g. (,), [], {}, and {...:...} ##
    for name in patches.keys():
        scope.pop(name, None)
    ## prior to PEP 667 ##
    if frame and version_info < (3, 13):
        ctypes.pythonapi.PyFrame_LocalsToFast(ctypes.py_object(frame), ctypes.c_int(1))
