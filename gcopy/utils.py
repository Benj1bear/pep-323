from copy import copy, deepcopy

## needed to access c level memory for the builtin iterators ##
from ctypes import POINTER, Structure, c_ssize_t, cast, py_object
from dis import _unpack_opargs
from functools import wraps
from inspect import currentframe
from readline import get_current_history_length, get_history_item
from sys import version_info
from types import CodeType, FrameType, FunctionType, GeneratorType
from typing import Any, Callable, Iterable, Iterator

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


def code_cmp(code_obj1: CodeType, code_obj2: CodeType) -> bool:
    """compares 2 code objects to see if they are essentially the same"""

    def code_setup(code_obj: CodeType) -> bytes:
        """makes sure the code objects headers don't get in the way of the comparison"""
        RESUME = opmap["RESUME"]
        opargs = _unpack_opargs(code_obj.co_code)
        for index, opcode, item_index in opargs:
            if opcode == RESUME:
                break
        return opargs

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


def is_running(iter: Iterable) -> bool:
    """Determines if an iterator is running"""
    if issubclass(type(iter), Wrapper):
        return getattr(iter, "running", False)
    index = get_iter_index(iter)
    return index > 0 or index < -1

## used in get_iter_index for an instance based check since no such type is in .py stdlib (I think) ##
memory_iterator = type(iter(memoryview(bytearray())))


def get_iter_index(iterator: Iterable) -> int:
    """Gets the current builtin iterators index via its __reduce__ method or c level inspection"""
    if isinstance(iterator, memory_iterator):
        return SetIteratorView(iterator).set
    try:
        ## builtin iterators have a reduce that enables copying ##
        ## formated i.e. as (function_iter, (instance,), index) ##
        reduction = iterator.__reduce__()
    except TypeError:
        raise TypeError(
            "Cannot use method '__reduce__' on object %s . Try wrapping it with 'track' or 'atrack' to determine if the iterator is running"
            % iterator
        )
    if isinstance(reduction[-1], int):
        return reduction[-1]
    elif reduction[0] == enumerate:
        return reduction[-1][-1]
    elif reduction[0] == zip:
        for index in range(2):
            try:
                return get_iter_index(reduction[1][index])
            except:
                pass
    elif reduction[0] in (map, filter):
        return get_iter_index(reduction[1][1])
    ## set_iterator and dict_iterator require c level inspection ##
    elif reduction[0] == iter:
        return SetIteratorView(iterator).size - iterator.__length_hint__()
    raise ValueError("Could not determine the iterators current index")


class SetIteratorView(Structure):
    """
    Used to access c level variables of the set_iterator builtin

    class follows on from the builtin layout:
    i.e.
    # iter
    https://github.com/python/cpython/blob/6aa88a2cb36240fe2b587f2e82043873270a27cf/Objects/iterobject.c#L11C1-L15C17
    ## but we're interested in:
    # dict_iterator
    https://github.com/python/cpython/blob/6aa88a2cb36240fe2b587f2e82043873270a27cf/Objects/dictobject.c#L5022C1-L5029C18
    # set_iterator
    https://github.com/python/cpython/blob/6aa88a2cb36240fe2b587f2e82043873270a27cf/Objects/setobject.c#L807C1-L813C17

    ## Note: dict iterator and set iterator are very similar in their memory layout (variables in their structs) and
    ## thus even though this class is intended for a set_iterator it'll work for dict_key_iterator for determining the size ##

    we can also do memory views where 'set' is the current index:
    https://github.com/python/cpython/blob/6aa88a2cb36240fe2b587f2e82043873270a27cf/Objects/memoryobject.c#L3455C1-L3461C20
    """

    _fields_ = [
        ## from macro PyObject_HEAD ##
        ("refcount", c_ssize_t),  # Reference count
        ("type", POINTER(py_object)),  # Type
        ## relevant other fields (Note: fields are in their order and are required up to what's used) ##
        ("set", c_ssize_t),  # set used (is also the index position for memory view)
        ("size", c_ssize_t),  # original size
    ]

    def __init__(self, set_or_dict_key_iterator: Iterable | Iterator) -> None:
        c_iterator = cast(id(set_or_dict_key_iterator), POINTER(SetIteratorView))
        for attr in self._fields_:
            attr = attr[0]
            setattr(self, attr, getattr(c_iterator.contents, attr))
