################
### tracking ###
################
from .source_processing import get_indent  # , is_definition, lineno_adjust
from .utils import is_cli, get_history_item, getcode, Wrapper
from inspect import currentframe, getframeinfo, getsourcelines
import builtins  ## for consistency (it switches between a module and a dict) ##

## for the monkey patching ##
from typing import Iterator, Iterable, Any
from types import FrameType, FunctionType


def track_iter(obj: Iterator | Iterable, frame: FrameType) -> Iterator | Iterable:
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

    When tracking generator expressions it uses the current
    bytecode instruction index instead
    """
    f_locals = frame.f_locals
    ## in case we're checking if it's the same code object in source_processing.extract_source_from_comparison ##
    try:
        code = frame.f_back.f_code
        if (
            code.co_name == "extract_source_from_comparison"
            and code.co_filename.split("\\")[-1] == "source_processing.py"
        ):
            return obj
    except:
        pass
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


def track_adjust(f_locals: dict) -> bool:
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
    index = 0
    ## make sure enumerate starts at 0 since we shouldn't consider the first iterator ##
    ## since this can only be determined manually if it's just by itself ##
    for index, key in enumerate(f_locals.pop(".mapping", [])):
        ## index + 1 since we start at 0 ##
        f_locals[".%s" % ((index + 1) * 4)] = f_locals.pop(".%s" % key)
    return bool(index)


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
    """Wrapper class to track iterators"""

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
    """Wrapper class to track async iterators"""

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
    """Proxy for type checking when using the tracked iterators"""

    def wrapper(obj, class_or_tuple: type | tuple) -> bool:
        if type(class_or_tuple) in (track, atrack):
            class_or_tuple = class_or_tuple.obj
        return FUNC(obj, class_or_tuple)

    return wrapper


def get_builtin_iterators() -> dict:
    """Gets all the builtin iterators"""
    dct = {}
    for name, obj in vars(builtins).items():
        if isinstance(obj, type) and issubclass(obj, Iterator | Iterable):
            dct[name] = obj
    return dct


def patch_iterators(scope: dict = None) -> None:
    """
    Sets all builtin iterators in the current scope to their tracked versions

    Note: make sure to patch iterators before using them else Iterator.running
    will be incorrect; this is also true for saving the iterator as well.
    """
    if scope is None:
        scope = currentframe().f_back.f_locals
    if not isinstance(scope, dict):
        raise TypeError("expected type 'dict' but recieved '%s'" % type(scope).__name__)
    ## Note: Can't change syntactical initiations e.g. (,), [], {}, and {...:...} ##
    for name, obj in get_builtin_iterators().items():
        scope[name] = track(obj)
    for FUNC in ("isinstance", "issubclass"):
        scope[FUNC] = wrapper_proxy(getattr(builtins, FUNC))


def unpatch_iterators(scope: dict = None) -> None:
    """Assumes all iterators are patched and deletes them from the scope"""
    if scope is None:
        scope = currentframe().f_back.f_locals
    if not isinstance(scope, dict):
        raise TypeError("expected dict, got %s" % type(scope).__name__)
    ## Note: Can't change syntactical initiations e.g. (,), [], {}, and {...:...} ##
    for name in get_builtin_iterators():
        del scope[name]
    for FUNC in ("isinstance", "issubclass"):
        del scope[FUNC]
