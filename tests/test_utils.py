## getcode, getframe raises a runtime warning because we didn't use the coroutine i.e. in an event loop ##
## is_cli is tested in test_cli_findsource ##
from sys import version_info
from types import CodeType, FrameType

from gcopy.utils import (
    attr_cmp,
    cli_findsource,
    code_attrs,
    code_cmp,
    empty_generator,
    get_globals,
    get_nonlocals,
    getcode,
    getframe,
    hasattrs,
    is_cli,
    similar_opcode,
    skip,
    try_set,
    catch_errors
)


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
    case = t()
    assert type(getcode(case)) == CodeType
    case.close()

    ## async generator ##
    async def t():
        yield 1
    case = t()
    assert type(getcode(case)) == CodeType
    case.aclose()

def test_getframe() -> None:
    ## generator ##
    assert type(getframe((i for i in (None,)))) == FrameType

    ## coroutine ##
    async def t():
        pass
    case = t()
    assert type(getframe(case)) == FrameType
    case.close()
    ## async generator ##
    async def t():
        yield 1
    case = t()
    assert type(getframe(case)) == FrameType
    case.aclose()


def test_hasattrs() -> None:
    assert hasattrs(compile("1+1", "", "eval"), code_attrs())


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
    assert similar_opcode(
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
    assert similar_opcode(
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
    assert similar_opcode(Test(), Test(), 151, 1, 0, 0) == False


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

def test_catch_errors() -> None:
    from sys import exc_info

    if version_info >= (3, 11):
        ## ExceptionGroup ##
        try:
            raise ExceptionGroup('', (AssertionError(), TypeError(), ValueError()))
        except:
            exc = exc_info()[1]
            assert catch_errors(exc, AssertionError, TypeError, ValueError)
            assert catch_errors(exc, AssertionError, TypeError, OSError) == False
    ## single Exception ##
    try:
        raise TypeError()
    except (AssertionError, TypeError, ValueError):
        exc = exc_info()[1]
        assert catch_errors(exc, AssertionError, TypeError, ValueError)
