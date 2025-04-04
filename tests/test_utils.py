from gcopy.utils import *
from typing import Iterator
import warnings


def test_cli_findsource() -> None:
    ## you need to be in a cli to test this ##
    if is_cli():
        print(cli_findsource())


def test_skip() -> None:
    i = iter(range(3))
    skip(i, 2)
    assert next(i) == 2


def test_empty_generator() -> None:
    count = 0
    for i in empty_generator():
        count += 1
    assert count == 0


def test_code_attrs() -> None:
    code_attrs()


def test_attr_cmp() -> None:
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
    code_obj_1 = compile("1+1", "", "eval")
    code_obj_2 = compile("1+1", "<string>", "eval")
    assert attr_cmp(code_obj_1, code_obj_2, attrs)
    assert attr_cmp(code_obj_1, code_obj_2, attrs + ("co_filename",)) == False


def test_getcode() -> None:
    ## generator ##
    assert type(getcode((i for i in (None,)))) == CodeType

    ## coroutine ##
    async def t():
        pass

    assert type(getcode(t())) == CodeType

    ## async generator ##
    async def t():
        yield 1

    assert type(getcode(t())) == CodeType


def test_getframe() -> None:
    ## generator ##
    assert type(getframe((i for i in (None,)))) == FrameType

    ## coroutine ##
    async def t():
        pass

    assert type(getframe(t())) == FrameType

    ## async generator ##
    async def t():
        yield 1

    assert type(getframe(t())) == FrameType


def test_hasattrs() -> None:
    assert hasattrs(compile("1+1", "", "eval"), code_attrs())


def test_chain() -> None:
    ls = list(range(1, 5))
    for i in chain([1, 2], [3, 4]):
        assert i == ls.pop(0)


def test_get_nonlocals() -> None:
    def test():
        b = None
        a = 3

        def case():
            a
            b

        case2 = lambda: print(a, b)
        return case, case2

    f1, f2 = test()

    assert get_nonlocals(f1) == {"a": 3, "b": None}
    assert get_nonlocals(f2) == {"a": 3, "b": None}


def test_try_set() -> None:
    dct = {"a": 3}
    try_set(dct, "a", 4)
    assert dct == {"a": 4}
    try_set(None, "a", 4)
    assert dct == {"a": 4}


def test_get_globals() -> None:
    assert get_globals() == globals()


def test_similar_opcode() -> None:
    ## class for testing ##
    class Test:
        def __init__(self):
            for attr in ("co_freevars", "co_cellvars", "co_varnames", "co_names"):
                setattr(self, attr, [0])

    ## same ##
    assert similiar_opcode(
        Test(),
        Test(),
        ## LOAD_GLOBAL ##
        116,
        ## LOAD_GLOBAL ##
        116,
        0,
        0,
    )
    ## essentially the same (for our purposes) ##
    assert similiar_opcode(
        Test(),
        Test(),
        ## LOAD_GLOBAL ##
        116,
        ## LOAD_FAST ##
        124,
        0,
        0,
    )
    ## different ##
    assert similiar_opcode(Test(), Test(), 151, 1, 0, 0) == False


def test_code_cmp() -> None:
    test = lambda line: getcode(eval(line))
    ## same code object ##
    assert code_cmp(test("lambda x: x"), test("lambda x: x"))

    ## essentially the same code object ##
    def test_case():
        j = 3
        f = lambda: j
        return getcode(f)

    assert code_cmp(test("lambda: j"), test_case())
    ## different code objects ##
    assert code_cmp(test("lambda x: x"), test("lambda x: x + 1")) == False


def test_is_running() -> None:
    ## without tracking ##
    def test_case():
        yield 1

    try:
        is_running(test_case())
        assert False
    except TypeError:
        pass
    ## with tracking ##
    from gcopy.track import track

    iterator = track(test_case())
    assert is_running(iterator) == False
    next(iterator)
    assert is_running(iterator)

    ## iterator with end index ##
    def test(iterator: Iterator) -> None:
        iterator = iter(iterator)
        assert is_running(iterator) == False
        next(iterator)
        assert is_running(iterator)

    test(range(3))
    ## requiring c level memory access ##
    test(memoryview(bytearray([1, 2, 3])))
    test({1, 2, 3})
    test(frozenset({1, 2, 3}))
    test({"a": 1, "b": 2, "c": 3})
    ## zip ##
    test(zip([1, 2, 3], [1, 2, 3]))
    ## enumerate ##
    test(enumerate([1, 2, 3]))
    ## map + filter ##
    test(map(lambda x: x, [1, 2, 3]))
    test(filter(lambda x: x, [1, 2, 3]))


## is_cli is tested in test_cli_findsource ##
test_cli_findsource()
test_skip()
test_empty_generator()
test_code_attrs()
test_attr_cmp()
with warnings.catch_warnings():
    ## raises a runtime warning because we didn't use the coroutine i.e. in an event loop ##
    warnings.simplefilter("ignore")
    test_getcode()
    test_getframe()
test_hasattrs()
test_chain()
test_get_nonlocals()
test_try_set()
test_get_globals()
test_similar_opcode()
test_code_cmp()
test_is_running()
