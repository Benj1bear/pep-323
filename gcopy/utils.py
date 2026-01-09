from copy import copy, deepcopy

from dis import _unpack_opargs
from functools import wraps
from inspect import currentframe
from readline import get_current_history_length, get_history_item
from sys import version_info
from types import CodeType, FrameType, FunctionType, GeneratorType
from typing import Any, Callable, Iterable

from opcode import opmap

_opmap = dict(zip(opmap.values(), opmap.keys()))


def is_cli() -> bool:
    """Determines if using get_history_item is possible e.g. for CLIs"""
    return bool(get_current_history_length())


def cli_findsource() -> list[str]:
    """Finds the source assuming CLI"""
    return [get_history_item(-i) for i in range(get_current_history_length() - 1, 0, -1)]


def skip(iter_val: Iterable, n: int) -> None:
    """Skips the next n iterations in a for loop"""
    for _ in range(n):
        next(iter_val)


def empty_generator() -> GeneratorType:
    """Creates a simple empty generator"""
    return
    yield


def code_attrs() -> tuple[str, ...]:
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


def attr_cmp(obj1: Any, obj2: Any, attrs: Iterable[str]) -> bool:
    """Compares two objects by a collection of their attrs"""
    for attr in attrs:
        flag1, flag2 = hasattr(obj1, attr), hasattr(obj2, attr)
        ## both must have the attr or not to preceed ##
        if flag1 == flag2:
            if flag1 and flag2 and getattr(obj1, attr) != getattr(obj2, attr):
                return False
        else:
            return False
    return True


def getcode(obj: Any) -> CodeType:
    """Gets the code object from an object via commonly used attrs"""
    for attr in ["__code__", "gi_code", "ag_code", "cr_code"]:
        if hasattr(obj, attr):
            return getattr(obj, attr)
    raise AttributeError("code object not found")


def getframe(obj: Any) -> FrameType:
    """Gets the frame object from an object via commonly used attrs"""
    for attr in ["gi_frame", "ag_frame", "cr_frame"]:
        if hasattr(obj, attr):
            return getattr(obj, attr)
    raise AttributeError("frame object not found")


def hasattrs(self: Any, attrs: Iterable[str]) -> bool:
    """hasattr check over a collection of attrs"""
    for attr in attrs:
        if not hasattr(self, attr):
            return False
    return True


def get_nonlocals(FUNC: FunctionType) -> dict:
    """Gets the nonlocals or closure variables of a function"""
    cells = getattr(FUNC, "__closure__", None)
    nonlocals = {}
    if cells:
        for key, value in zip(FUNC.__code__.co_freevars, cells, strict=True):
            try:
                nonlocals[key] = value.cell_contents
            except ValueError as e:
                ## if doing recursion, the function can get recorded as nonlocal ##
                if key == FUNC.__name__:
                    nonlocals[key] = FUNC
                    continue
                raise e
    return nonlocals


def try_set(self, key: Any, value: Any, default: Any = None) -> None:
    """
    Tries to set a value to a key on an
    object if the object is not the default
    """
    if self != default:
        self[key] = value


def get_globals() -> dict:
    """Gets the globals of the originating module that was called from"""
    frame = currentframe()
    while frame.f_code.co_name != "<module>":
        frame = frame.f_back
    return frame.f_globals


def similar_opcode(
    code_obj1: CodeType,
    code_obj2: CodeType,
    opcode1: int,
    opcode2: int,
    item_index1: int,
    item_index2: int,
) -> bool:
    """
    Determines if the opcodes lead to practically the same result
    (for similarity between code objects that differ by the variable type attributed to it)
    """
    ## i.e. LOAD, STORE, DELETE ##
    name1 = _opmap[opcode1].split("_")
    name2 = _opmap[opcode2].split("_")
    if name1[0] != name2[0]:
        return False
    mapping = {
        "DEREF": "co_freevars",
        "CLOSURE": "co_cellvars",
        "FAST": "co_varnames",
        "GLOBAL": "co_names",
    }

    def get_code_attr(code_obj: CodeType, name: list[str], item_index: int) -> Any:
        """Gets the attr by key and index"""
        attr = mapping[name[1]]
        array = getattr(code_obj, attr)
        if attr == "co_freevars":
            item_index -= getattr(code_obj, "co_nlocals")
        return array[item_index]

    try:
        return get_code_attr(code_obj1, name1, item_index1) == get_code_attr(code_obj2, name2, item_index2)
    except (IndexError, KeyError):
        return False

code_setup = _unpack_opargs

if version_info >= (3, 11):
    def code_setup(code_obj: CodeType) -> bytes:
        """makes sure the code objects headers don't get in the way of the comparison"""
        opargs = _unpack_opargs(code_obj.co_code)
        if version_info >= (3, 11):
            RESUME = opmap["RESUME"]
            for index, opcode, item_index in opargs:
                if opcode == RESUME:
                    break
        return opargs


def code_cmp(code_obj1: CodeType, code_obj2: CodeType) -> bool:
    """compares 2 code objects to see if they are essentially the same"""
    try:
        for (index1, opcode1, item_index1), (index2, opcode2, item_index2) in zip(
            code_setup(code_obj1), code_setup(code_obj2), strict=True
        ):
            if opcode1 != opcode2 and not similar_opcode(
                code_obj1, code_obj2, opcode1, opcode2, item_index1, item_index2
            ):
                return False
    ## catch the error if the code objects are not the same length ##
    except ValueError:
        return False
    return True


def wrap(self, method: FunctionType) -> FunctionType:
    """
    wrapper function to ensure methods assigned are instance based
    and the dunder methods return values are wrapped in a Wrapper type
    """

    @wraps(method)  ## retains the docstring
    def wrapper(*args, **kwargs):
        return type(self)(method(*args[1:], **kwargs))

    return wrapper


def get_error():
    """raises an error on calling for the Wrapper classes attribute when the attribute does not exist"""
    raise AttributeError("the required attribute does not exist on the original object")


def copier(self, FUNC: FunctionType) -> object:
    """copying will create a new generator object out of a copied version of the current instance"""
    obj = type(self)()
    obj.__setstate__(self.__getstate__(FUNC))
    return obj


class Wrapper:
    """
    Wraps an object in a chain pattern to ensure certain attributes are recorded

    Note: type checking will fail. Therefore, you may consider monkey patching
    i.e. isinstance and issubclass if necessary.

    The reason why it should fail is because we're only using it by the instance
    and not the type. If we wanted it by the type then we should create a metaclass.

    Also, the intended use case doesn't support i.e. binary operations or type
    casting therefore it's not support by this wrapper. The wrapper is only as
    storage for instance based members (data and methods)
    """

    def __init__(self, obj: Any = None) -> None:
        if obj is not None:
            expected = self._expected
            self.obj = obj
            not_allowed = [
                "__class__",
                "__getattribute__",
                "__getattr__",
                "__dir__",
                "__set_name__",
                "__init_subclass__",
                "__mro_entries__",
                "__prepare__",
                "__instancecheck__",
                "__subclasscheck__",
                "__sizeof__",
                "__fspath__",
                "__subclasses__",
                "__subclasshook__",
                "__init__",
                "__new__",
                "__setattr__",
                "__delattr__",
                "__get__",
                "__set__",
                "__delete__",
                "__dict__",
                "__doc__",
                "__call__",
                "__name__",
                "__qualname__",
                "__module__",
                "__abstractmethods__",
                "__repr__",
                "__getstate__",
                "__setstate__",
                "__reduce__",
                "__reduce_ex__",
                "__getnewargs__",
                "__getnewargs_ex__",
                "__copy__",
                "__deepcopy__",
                "__weakref__",
            ]
            for attr in dir(obj):

                if attr in not_allowed:
                    not_allowed.remove(attr)
                else:
                    value = getattr(obj, attr)
                    if isinstance(value, Callable):
                        setattr(self, attr, wrap(self, value))
                        if attr in expected:
                            expected.remove(attr)
                    else:
                        setattr(self, attr, value)
            ## makes sure an error gets raised if the method doesn't exist ##
            for attr in expected:
                setattr(self, attr, get_error)

    def __call__(self, *args, **kwargs):
        new_self = type(self)(self.obj(*args, **kwargs))
        return new_self

    def __repr__(self) -> str:
        return repr(self.obj)

    def __copy__(self) -> object:
        return copier(self, copy)

    def __deepcopy__(self, memo: dict) -> object:
        return copier(self, deepcopy)

    def __getstate__(self, FUNC: FunctionType = lambda x: x) -> dict:
        return {"obj": FUNC(self.obj)}

    def __setstate__(self, state: dict) -> None:
        self.__init__(state["obj"])


def get_state(self) -> str:
    """
    returns the state of the generator as a string
    based on the internal state regardless of i.e. async
    or not.

    In general, this should be a stand alone funtion 
    but classes may choose to use this as a property.

    Note: follows on from the inspect module 
    e.g. inspect.getgeneratorstate and inspect.getasyncgenstate
    e.g. see:
    https://github.com/python/cpython/blob/cbf9b8cc08364cdcf355fe1c897f698331b49a41/Lib/inspect.py#L1806C1-L1821C23
    and
    https://github.com/python/cpython/blob/cbf9b8cc08364cdcf355fe1c897f698331b49a41/Lib/inspect.py#L1887C1-L1902C24
    respectively
    """
    state: dict.get = self._internals.get
    if state("running"):
        return "RUNNING"
    if state("suspended"):
        return "SUSPENDED"
    if state("frame"):
        return "CREATED"
    return "CLOSED"


if version_info < (3,11):
    ## it shouldn't matter what this is set to as long as it doesn't have .exceptions attribute ##
    ExceptionGroup = None


def catch_errors(error: BaseException, *filter: tuple[BaseException]) -> bool:
    """
    checks if an error is in filter

    If the error is an ExceptionGroup all exceptions must be in filter to be caught
    otherwise any exceptions that are in filter they will be caught
    """
    if hasattr(error, "exceptions") and ExceptionGroup not in filter:
        ## all of error must be in filter ##
        return all(any(isinstance(exception, subgroup) for subgroup in filter) for exception in error.exceptions)
    return any(isinstance(error, exception) for exception in filter)
