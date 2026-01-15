###################################################
## tests are for cleaning + adjusting + pickling ##
###################################################

# record_jumps is tested in test_custom_adjustment
#test_generator_block_adjust()  ## finish decorators + definitions e.g. unpack ##
# test_generator_clean_source_lines()  ## do basic tests for most users to see it working ##
# Generator__call__ is tested in test_generator__call__
# test_gen_expr()  ## fix patch_iterators so that it's scoped ##
# test_value_yield()  ## need to add more test cases ##

import pytest ## used to make async tests work
import os ## used in test_picklers for pytest ##
import pickle
from functools import partial
from inspect import currentframe
from sys import exc_info
from collections.abc import Iterable
from types import AsyncGeneratorType, GeneratorType, NoneType
from typing import Any, Union

from gcopy.custom_generator import (
    EOF,
    AsyncGenerator,
    BaseGenerator,
    Generator,
    Pickler,
    code,
    frame
)
from gcopy.source_processing import (
    append_line,
    block_adjust,
    custom_adjustment,
    empty_generator,
    string_collector_adjust,
    unpack,
    update_jump_positions,
)
from gcopy.track import atrack, patch_iterators
from gcopy.utils import (
    attr_cmp,
    copier,
    get_globals,
    get_nonlocals,
    getcode,
    catch_errors
    )

#########################
### testing utilities ###
#########################


## classes need to be globally defined for it to be picklable ##
## e.g. cannot pickle locally defined classes/types ##
class pickler(Pickler):
    _attrs = ("a", "b", "c")


def setup() -> object:
    """setup used for jump_positions"""
    self = type("", tuple(), {})()
    self.jump_positions, self.jump_stack = [
        [1, None],
        [1, None],
    ], [(0, 0), (0, 1)]
    self.stack_adjuster, self.linetable = [], []
    self.lineno = 1
    return self


def simple_generator() -> Generator:
    yield 1
    yield 2
    yield 3


def api_test(gen, flag: bool) -> None:
    """
    Tests if the api is setup correctly

    Note: only for Generators currently e.g. gi_ prefix on attributes
    """
    for key in dir(gen):
        if key.startswith("gi_"):
            assert (getattr(gen, key) is gen._internals[key[3:]]) == flag
    assert gen._internals["state"] == gen._internals["source_lines"]


def init_test(FUNC: Any, flag: bool, self: type, self_type: type) -> None:
    """
    Does two checks:
    1. has the attrs
    2. the attrs values are of the correct type
    """
    gen = self(FUNC)
    api_test(gen, flag)
    for key, value in {
        "state": str,
        "source": str,
        "linetable": int,
        "yieldfrom": Union[NoneType, Iterable, self_type],
        "version": str,
        "jump_positions": list,
        "suspended": bool,
        "prefix": str,
        "lineno": int,
        "code": code,
        "state_generator": GeneratorType,
        "running": bool,
        "source_lines": str,
        "type": str,
        "frame": frame,
    }.items():
        try:
            obj = gen._internals[key]
        except KeyError:
            if key == "jump_positions" and isinstance(FUNC, self_type) and getcode(FUNC).co_name == "<genexpr>":
                continue
            if key != "linetable":
                raise AssertionError("Missing key: %s" % key)
            continue
        if isinstance(obj, list):
            if obj:
                assert isinstance(obj[0], value)
        else:
            assert isinstance(obj, value)


#############
### tests ###
#############


def test_EOF() -> None:
    try:
        raise EOF()
        assert False
    except StopAsyncIteration:
        pass

    try:
        raise EOF()
        assert False
    except StopIteration:
        pass


def test_Pickler(pickler_test: Pickler = None) -> None:
    if pickler_test is None:
        pickler_test = pickler()
        pickler_test.__setstate__(dict(zip(("a", "b", "c"), range(3))))
    if not isinstance(pickler_test, BaseGenerator):
        assert copier(pickler_test, lambda x: x) is not copier(pickler_test, lambda x: x)
    with open("tests/data/test.pkl", "wb") as file:
        pickle.dump(pickler_test, file)
    with open("tests/data/test.pkl", "rb") as file:
        ## they should be identical in terms of the attrs we care about ##
        test_loaded = pickle.load(file)
        if isinstance(pickler_test, BaseGenerator):
            if "frame" in test_loaded._internals:
                assert test_loaded._internals["frame"].f_globals == get_globals()
            ## delete any attrs we don't want to compare ##
            pickler_test = pickler_test._internals
            test_loaded = test_loaded._internals
            for key in pickler_test:
                if key == "state_generator":
                    continue
                if not (key in test_loaded and test_loaded[key] == pickler_test[key]):
                    print(
                        " --- %s attr comparison == False: test_Pickler (_internals comparison key: '%s')"
                        % (pickler_test.__class__.__name__, key)
                    )
            return
        try:
            attrs = ("_attrs",) + pickler_test._attrs
            attrs = list(attrs)
            for i in pickler_test._not_allowed:
                attrs.remove(i)
            assert attr_cmp(test_loaded, pickler_test, attrs)
        except AssertionError:
            ## it'll be the frame ##
            print(" --- %s attr comparison == False: test_Pickler" % (pickler_test.__class__.__name__))


def test_picklers() -> None:
    _frame = frame(currentframe())
    ## we don't need to wrap in a gcopy.code type since frame does this already ##
    test_Pickler(_frame.f_code)
    ## if testing using pytest then we need to remove anything in prior frames ##
    ## that cannot be pickled. For simplicity we remove the previous frame ##
    if os.environ.get("PYTEST_CURRENT_TEST"):
        _frame.f_back = None
    test_Pickler(_frame)
    test_Pickler(Generator())
    test_Pickler(AsyncGenerator())


def test_generator_pickle() -> None:
    gen = Generator(simple_generator)
    attrs_before = dir(gen._internals["frame"])
    test_Pickler(gen)
    ## make sure no change in the attrs ##
    assert attrs_before == dir(gen._internals["frame"])
    ## instantiate the generator since it's not initialized ##
    gen = gen()
    assert next(gen) == 1
    ## copy the generator ##
    gen2 = gen.copy()
    gen3 = gen.copy()
    assert next(gen) == next(gen2) == next(gen3)
    assert next(gen) == next(gen2) == next(gen3)
    prefix = gen._internals["prefix"]
    for key in ("code", "frame", "suspended", "yieldfrom", "running"):
        assert hasattr(gen2, prefix + key)


def test_generator_custom_adjustment() -> None:
    self = type("", tuple(), {})()
    self.lineno = 0
    test = partial(custom_adjustment, self)
    ## yield ##
    assert test("yield ... ") == ["return ... "]
    ## yield from ##
    self.jump_positions = []
    assert test("yield from ... ") == [
        "locals()['.internals']['.0']=locals()['.internals']['.yieldfrom']=iter(... )",
        "for locals()['.internals']['.i'] in locals()['.internals']['.yieldfrom']:",
        "    return locals()['.internals']['.i']",
        "    if locals()['.internals']['.send']:",
        "        return locals()['.internals']['.yieldfrom'].send(locals()['.internals']['.send'])",
    ]
    ## check the jump positions ##
    assert self.jump_positions == [[1, 4]]
    assert self.lineno == 4
    ## for ##
    self.jump_positions, self.jump_stack = [], []
    assert test("for ") == ["for "]
    assert self.jump_positions, self.jump_stack == (
        [[0, None]],
        [(0, 0)],
    )
    ## while ##
    assert test("while ") == ["while "]
    assert self.jump_positions, self.jump_stack == (
        [[0, None], [0, None]],
        [(0, 0), (0, 1)],
    )
    ## return ##
    assert test("return ... ") == ["return EOF('... ')"]
    ## nonlocal ##
    assert test("nonlocal ... ") == []
    ## decorator ##
    assert hasattr(self, "decorator") == False
    assert test("@test") == ["@test"]
    assert self.decorator


def test_generator_update_jump_positions() -> None:

    #### Note: jump_positions are by lineno not by index ####

    self = setup()
    self.lineno += 1  ## it won't occur on the same lineno ##
    ## only positions ##
    # with reference indent #
    self.lines = []
    update_jump_positions(self, 4)
    assert self.lines == []
    assert self.jump_positions == [[1, None], [1, None]]
    assert self.jump_stack == [(0, 0), (0, 1)]
    # without reference indent #
    self.lines = []
    update_jump_positions(self)
    assert self.lines == []
    assert self.jump_positions == [[1, 2], [1, 2]]
    assert self.jump_stack == []
    ## with stack adjuster ##
    # self = setup()
    # self.lineno += 1
    # new_lines = ["    pass", "    for i in range(3)", "        pass"]
    # self.stack_adjuster = [[1, new_lines]]
    # ## check: lines, lineno, linetable, jump_positions, stack_adjuster ##
    # self.lines = []
    # update_jump_positions(self)
    # assert self.lines == new_lines
    # assert self.stack_adjuster == []
    # ## since we're on lineno == 2 the new_lines will be 3, 4, 5 ##
    # assert self.linetable == [3, 4, 5]
    # assert self.lineno == 5
    # assert self.jump_positions == [[1, 2], [1, 2], [4, 7]]


def test_generator_append_line() -> None:
    """
    required inputs;
        self,
        index: int,
        char: str,
        source: str,
        source_iter: Iterable,
        running: bool,
        line: str,
        lines: list[str],
        indentation: int,
        indent_adjust: int,

        reqruied outputs:
        index, char, lines, line, indented, indentation, indent_adjust
    """

    def get_returns(self) -> tuple[int, str, list[str], str, bool, int, int]:
        return (
            self.index,
            self.char,
            self.lines,
            self.line,
            self.indented,
            self.indentation,
            self.indent_adjust,
        )

    def manual_test(self, *args) -> tuple:
        (
            self.index,
            self.char,
            self.source,
            self.source_iter,
            self.line,
            self.lines,
            self.indentation,
            self.indent_adjust,
        ) = args
        append_line(self, True)
        return get_returns(self)

    def test(self, start: int, index: int, indentation: int = 0) -> tuple:
        source = "    print('hi')\n    print('hi');\nprint('hi')\n    def hi():\n        print('hi')\n print() ## comment\n    if True:"

        self.index = index
        self.char = source[index]
        self.source = source
        self.source_iter = enumerate(source[index + 1 :], start=index + 1)
        self.line = source[start:index]
        self.lines = []
        self.indentation = indentation
        self.indent_adjust = 0

        append_line(self, True)

        return get_returns(self)

    ## empty line ##

    self = setup()
    self.indented = False
    self.catch = []

    assert manual_test(self, 0, "", "", "", "", [], 0, 0) == (
        0,
        "",
        [],
        "",
        False,
        0,
        0,
    )
    assert manual_test(self, 0, "", "", "", "         ", [], 0, 0) == (
        0,
        "",
        [],
        "",
        False,
        0,
        0,
    )

    ## normal line ##
    assert test(self, 0, 15) == (15, "\n", ["    print('hi')"], "", False, 0, 0)
    ## semi-colon ##
    assert test(self, 16, 31) == (31, ";", ["    print('hi')"], "", True, 0, 0)
    ## comments ##
    assert test(self, 79, 88) == (98, "\n", [" print() "], "", False, 0, 0)
    ## statements/colon ##
    assert test(self, 99, 110) == (110, ":", ["    if True:"], "        ", True, 8, 0)
    ## skip definitions ##
    self.lineno = 1
    self.decorator = False
    assert test(self, 45, 57) == (
        78,
        "\n",
        ["    def hi():", "        print('hi')"],
        "",
        False,
        8,
        0,
    )
    assert self.lineno == 3
    ## decorators ##
    ## using the previous example definition ##
    self.lineno = 1
    self.decorator = True
    assert test(self, 45, 57) == (
        78,
        "\n",
        [
            "    def hi():",
            "        print('hi')",
            "    hi = locals()['.internals']['.decorator'](hi)",
        ],
        "",
        False,
        8,
        0,
    )


def test_generator_block_adjust() -> None:
    """
    # self,
    # current_lines: list[str],
    # new_lines: list[str],
    # final_line: str,
    # source: str,
    # source_iter: Iterable,
    """

    gen = type("", tuple(), {"lineno": 0, "stack_adjuster": [], "catches": [[]], "catch": []})()

    ## if ##
    def test(line, current=[]):
        return block_adjust(gen, current, *unpack("", enumerate(line), line)[:-2])

    test("    if     (yield 3):\n        return 4\n")
    assert gen.lines == [
        "return  3",
        "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        "if      locals()['.internals']['.args'].pop():",
    ]
    ## elif ##
    test("    elif (yield 3):\n        return 4\n")
    assert gen.lines == [
        "else:",
        "    return  3",
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        "    if      locals()['.internals']['.args'].pop():",
    ]
    ## except ##
    gen.catch = []
    test("    except (yield 3):\n        return 4\n", ["    try:", "        pass"])
    assert gen.lines == [
        "    try:",
        "        try:",
        "            pass",
        "        except:",
        "            locals()['.internals']['.error'] = locals()['.internals']['exc_info']()[1]",
        "        return  3",
        "        locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        "        if locals()['.internals']['.catch_errors'](locals()['.internals']['.error'], locals()['.internals']['.args'].pop()):",
        "            locals()['.continue_error'] = False",
    ]
    ## additional catch ##
    test("    except (yield 3):\n        return 4\n", gen.lines)
    assert gen.lines == [
        "    try:",
        "        try:",
        "            pass",
        "        except:",
        "            locals()['.internals']['.error'] = locals()['.internals']['exc_info']()[1]",
        "        return  3",
        "        locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        "        if locals()['.internals']['.catch_errors'](locals()['.internals']['.error'], locals()['.internals']['.args'].pop()):",
        "            locals()['.continue_error'] = False",
        "        else:",
        "            return  3",
        "            locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        "            if locals()['.internals']['.catch_errors'](locals()['.internals']['.error'], locals()['.internals']['.args'].pop()):",
        "                locals()['.continue_error'] = False",
    ]
    ## for ##
    new_lines = [
        "    return  3",
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
    ]
    test_answer = lambda expr: test("    %s (yield 3):\n        return 4\n" % expr) == new_lines + [
        "    %s locals()['.internals']['.args'].pop():" % expr
    ]
    ## while ##
    gen.lineno, gen.stack_adjuster = 0, []
    test_answer("while")
    assert gen.lineno == 3
    assert gen.stack_adjuster == [
        [0]
        + [
            "    return  3",
            "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ]
    ]
    ## decorator ##
    gen.lineno = 1
    gen.decorator = True
    test("@function(a=(yield 3))")
    assert gen.lines == [
        "return  3",
        "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        "locals()['.internals']['.decorator'] = locals()['.internals']['.decorator'](locals()['.internals']['partial'](function, a =locals()['.internals']['.args'].pop())",
    ]
    ## definition with and without decorator ##
    gen = type("", tuple(), {"lineno": 0, "jump_stack_adjuster": []})()
    gen.fixed_lines = 0
    gen.source_iter = enumerate(empty_generator())
    gen.lines = []
    gen.lineno = 1
    gen.source = "def f(a=(yield 3)):\n    pass\n"
    gen.line = gen.source.split("\n")[0]
    gen.index = 7
    gen.char = ""
    gen.decorator = False
    test(gen.line)
    assert gen.lines == [
        "return  3",
        "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        "def f(a =locals()['.internals']['.args'].pop())",
    ]
    assert gen.lineno == 6
    ## jump positions e.g. (yield from) ##
    gen.jump_positions, gen.jump_stack = [], []
    gen.lineno = 1
    test("    if (yield from range(3)):")
    assert gen.lines == [
        "locals()['.internals']['.0']=locals()['.internals']['.yieldfrom']=iter( range(3))",
        "for locals()['.internals']['.i'] in locals()['.internals']['.yieldfrom']:",
        "    return locals()['.internals']['.i']",
        "    if locals()['.internals']['.send']:",
        "        return locals()['.internals']['.yieldfrom'].send(locals()['.internals']['.send'])",
        "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        "if      locals()['.internals']['.args'].pop():",
    ]
    assert gen.jump_positions == [[3, None]]
    assert gen.jump_stack == [(0, 0)]


def test_generator_string_collector_adjust() -> None:
    """
    required inputs:
    self,
    index: int,
    char: str,
    prev: tuple[int, int, str],
    source_iter: Iterable,
    line: str,
    source: str,
    lines: list[str],

    required outputs:
    index | line, prev, lines
    """

    source = "    print('hi')\n    print(f'hello {(yield 3)}')\n    print(f'hello {{(yield 3)}}')"

    def test(line_start: int, start: int, *answer: tuple[str, tuple[int, int, str], list]) -> tuple[Iterable, int, str]:
        line = source[line_start:start]
        source_iter = enumerate(source[start:], start=start)

        def setup():
            index, char = next(source_iter)
            self = type(
                "",
                tuple(),
                {
                    "lineno": 1,
                    "index": index,
                    "char": char,
                    "prev": (0, 0, ""),
                    "source_iter": source_iter,
                    "line": line,
                    "source": source,
                    "lines": [],
                    "jump_positions": [[None, None]],
                },
            )
            return self

        self = setup()
        string_collector_adjust(self)
        assert self.line == answer[0]
        assert self.prev == answer[1]
        assert self.lines == answer[2]

    ## string collection ##
    test(None, 10, *("    print('hi'", (10, 13, "'"), []))
    ## f-string ##
    test(
        16,
        27,
        *(
            "",
            (27, 45, "'"),
            [
                "    return  3",
                "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
                "    print(f'hello {locals()['.internals']['.args'].pop()}')",
            ],
        ),
    )
    ## string f-string ##
    test(
        48,
        59,
        *(
            "    print(f'hello {{(yield 3)}}'",
            (59, 79, "'"),
            [],
        ),
    )


def test_generator_clean_source_lines() -> None:

    ## make sure the jump_positions are forming correctly ##

    def test():
        yield 1
        for i in range(3):
            yield i
        for i in range(3):
            yield i

    gen = Generator(test())
    assert gen._internals["jump_positions"] == [[2, 3], [4, 5]]

    a = None

    def test() -> Generator:
        """
        single test case that attempts to test most cases:

        ## value yields ##
        ## comments ##
        ## definitions ##
        ## statements ##
        ## named expressions ##
        ## strings ##
        ## f-strings ##
        ## returns ##
        """
        nonlocal a
        yield

        (yield (yield), (yield 3)) == (yield 5), (yield 6)

        if (yield):
            yield from simple_generator()
            return 3
        while 3 < next((yield 3)):
            print(3)
        for i in (yield 2):
            print(2)
        for i in f"{(yield 2)}":
            print(2)
        if i in (yield 2):
            pass
        if i in f"{(yield 2)}":

            pass

        print(f"hi {(yield 2),(yield (yield 2))}")  ## f-string ##
        string = """def test():
    pass
"""
        print(string)

        (a := (yield (a := (yield 3)))) == (yield 3)

        try:
            print()
        except (yield 3):
            pass
        try:
            print()
        except f"hi there{(yield 3)}":
            pass
        if True:
            pass
        elif (yield 3):

            pass

        def test2():
            yield 3

        async def test2():
            yield 3

        class test2:
            def __init__(self):
                yield 3

        func()
        return (yield 3)
        ## issue where variable assignment isn't working correctly only on yields/yield froms ##
        ##  without brackets (e.g. works on value yields but not regular yields) ##

    gen = Generator(test)
    for line in gen._internals["source_lines"]:
        print(repr(line))
    
    ## test sending yields (without brackets) making sure the adjustments are also correct ##
    @Generator
    def test():
        a = yield [1,2,3]
        b = yield from [1,2,3]

    assert test()._internals["source_lines"] == [
        "    locals()['.internals']['.args'] += [1]",
        "    return [locals()['.internals']['.args'].pop(0) ,2 ,3]",
        "    a = locals()['.internals']['.send']",
        "    locals()['.internals']['.args'] += [1]",
        "    locals()['.internals']['.0']=locals()['.internals']['.yieldfrom']=iter( [locals()['.internals']['.args'].pop(0) ,2 ,3])",
        "    for locals()['.internals']['.i'] in locals()['.internals']['.yieldfrom']:",
        "        return locals()['.internals']['.i']",
        "        if locals()['.internals']['.send']:",
        "            return locals()['.internals']['.yieldfrom'].send(locals()['.internals']['.send'])",
        "    b = locals()['.internals']['.send']"
        ]

    ## make sure brackets are forming correctly ##
    def brackets():
        print ( 1+(2+ (yield 60)+22, 2+ (yield 60)+22,55+(yield 0) + 3)+4 )
        (yield 3)
        (yield 5)
        print((   yield 3))
        ( 
            1+( 
                2+ (yield 60),(yield 0) + 3
                )+4 
        )
        ( 1+(2+ (yield 60)+22, 2+ (yield 60)+22,55+(yield 0) + 3)+4 )
        yield (yield 60),(yield 0)
        (yield 1), (yield 2) , print((yield 3    )   ) + 4
        raise ( (yield 3))
        (yield (yield 3)),(3+ (yield (yield 3)))
        [(yield 3)]
        [(yield 3)]

    assert Generator(brackets)._internals["source_lines"] == [
        '    return  60', "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        '    return  60', "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        '    return  0', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        "    print ( 1+(2+ locals()['.internals']['.args'].pop(0) +22 , 2 +locals()['.internals']['.args'].pop(0) +22 ,55 +locals()['.internals']['.args'].pop(0) + 3)+4 )", 
        '    return  3', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'].pop()", 
        '    return  5', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'].pop()", 
        '    return  3', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    print(locals()['.internals']['.args'].pop())", 
        '    return  60', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        '    return  0', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        "    (  1+(  2+ locals()['.internals']['.args'].pop(0) ,locals()['.internals']['.args'].pop(0) + 3            )+4  )", 
        '    return  60', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        '    return  60', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        '    return  0', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        "    ( 1+(2+ locals()['.internals']['.args'].pop(0) +22 , 2 +locals()['.internals']['.args'].pop(0) +22 ,55 +locals()['.internals']['.args'].pop(0) + 3)+4 )", 
        '    return  60', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        '    return  0', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    return locals()['.internals']['.args'].pop(0) ,locals()['.internals']['.args'].pop()", 
        '    return  1', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        '    return  2', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        '    return  3', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [print(locals()['.internals']['.args'].pop() )]", 
        "    locals()['.internals']['.args'].pop(0) ,locals()['.internals']['.args'].pop(0) ,locals()['.internals']['.args'].pop(0) + 4", 
        '    return  3', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    raise ( locals()['.internals']['.args'].pop())", 
        '    return  3', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    return  locals()['.internals']['.args'].pop()", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]", 
        '    return  3', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    return  locals()['.internals']['.args'].pop()", 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    locals()['.internals']['.args'].pop(0) ,(3+ locals()['.internals']['.args'].pop())", 
        '    return  3', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    [locals()['.internals']['.args'].pop()]", 
        '    return  3', 
        "    locals()['.internals']['.args'] += [locals()['.internals']['.send']]", 
        "    [locals()['.internals']['.args'].pop()]"
    ]


def test_generator_create_state() -> None:
    gen = Generator()
    gen._internals = {
        "lineno": 1,
        "jump_positions": [],
        "source_lines": [
            "    return 1",
            "    if True:",
            "        return 2",
            "    else:",
            "        return 3",
            "    return 4",
        ],
        "loops": [],
    }

    def test(lineno: int) -> tuple[list[str], list[int]]:
        gen._internals["lineno"] = lineno
        gen._create_state()
        return gen._internals["state"], gen._internals["linetable"]

    ## control_flow_adjust e.g. no loops ##
    assert test(3) == (["    return 2", "    return 4"], [2, 5])
    assert test(5) == (["    return 3", "    return 4"], [4, 5])

    ## with loops ##
    gen._internals["source_lines"] = [
        "    for i in range(3):",
        "        print(i)",
        "        for j in range(4):",
        "            print(j)",
        "            for k in range(4):",
        "               return 1",
        "               if True:",
        "                   return 2",
        "               else:",
        "                   return 3",
        "               return 4",
        "            print(j)",
        "        print(i)",
    ]
    ## Note: the jump_positions are lineno ##
    ## based get_loops changes them to index based ##
    start_indexes = [0, 2, 4]
    end_indexes = [12, 11, 10]
    gen._internals["loops"] = list(zip(start_indexes, end_indexes))
    assert test(8) == (
        [
            "    return 2",
            "    return 4",
            "    for k in locals()['.internals']['.12']:",
            "       return 1",
            "       if True:",
            "           return 2",
            "       else:",
            "           return 3",
            "       return 4",
            "    for j in locals()['.internals']['.8']:",
            "        print(j)",
            "        for k in range(4):",
            "           return 1",
            "           if True:",
            "               return 2",
            "           else:",
            "               return 3",
            "           return 4",
            "        print(j)",
            "    for i in locals()['.internals']['.4']:",
            "        print(i)",
            "        for j in range(4):",
            "            print(j)",
            "            for k in range(4):",
            "               return 1",
            "               if True:",
            "                   return 2",
            "               else:",
            "                   return 3",
            "               return 4",
            "            print(j)",
            "        print(i)",
        ],
        [
            7,
            10,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            0,
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
        ],
    )


def test_generator_init_states() -> None:
    def test(gen) -> None:
        ## show the state_generator is dependent on external variables ##
        for _ in range(2):
            next(gen._internals["state_generator"])
            assert gen._internals["state"] == gen._internals["source_lines"]
        ## EOF ##
        gen._internals["state"] = None
        assert next(gen._internals["state_generator"], True)

    ## uninitialized generator ##
    try:
        test(Generator(simple_generator))
        assert False
    except TypeError:
        pass
    ## initialized generator ##
    test(Generator(simple_generator()))


def test_generator__init__() -> None:

    ## function generator ##
    # uninitialized - this should imply that use as a decorator works also ##
    init_test(simple_generator, False, Generator, GeneratorType)
    # initialized #
    init_test(simple_generator(), True, Generator, GeneratorType)
    ## generator expression ##
    gen = (i for i in range(3))
    init_test(gen, True, Generator, GeneratorType)

    ## test if the function related attrs get transferred ##

    closure_cell = 1

    def test2(FUNC: Any) -> None:
        """docstring"""
        closure_cell

    gen = Generator(test2)

    assert gen.__call__.__annotations__ == test2.__annotations__
    assert gen.__call__.__doc__ == test2.__doc__
    assert get_nonlocals(gen.__closure__) == get_nonlocals(test2.__closure__)


def test_generator__call__() -> None:
    def test(a, b, c=3):
        yield a
        yield b
        yield c

    gen = Generator(test)
    assert gen._internals["initialized"] == False
    ## make sure you cannot iterate over it ##
    for i in range(3):
        try:
            next(gen)
            assert False
        except TypeError:
            pass
    del gen._internals["state_generator"]
    ## initializes but also returns itself ##
    gen = gen(1, 2)
    assert gen is not None
    assert gen._internals["initialized"]
    gen._internals["frame"].f_locals
    assert gen._internals["frame"].f_locals == {
        ".internals": {
            "EOF": EOF,
            "exec_info": exc_info,
            "partial": partial,
            ".args": [],
            ".send": None,
            "catch_errors": catch_errors,
        },
        "a": 1,
        "b": 2,
        "c": 3,
    }
    api_test(gen, True)
    assert [i for i in gen] == [1, 2, 3]
    assert gen._internals["state_generator"]


def test_generator_locals() -> None:
    gen = Generator()
    gen._internals["frame"] = frame()
    gen._locals()["a"] = 1
    assert gen._internals["frame"].f_locals == {"a": 1}


def test_generator_frame_init() -> None:
    gen = Generator(simple_generator())

    ### state adjustments ###

    ## exception ##
    gen._frame_init("Exception")
    assert gen._internals["state"] == [
        "    raise Exception",
        "    return 1",
        "    return 2",
        "    return 3",
    ]
    assert gen._internals["linetable"] == [-1, 0, 1, 2]

    ## exception with try block ##
    def test():
        try:
            yield 3
        except:
            pass

    gen2 = Generator(test())
    gen2._frame_init("Exception")
    assert gen2._internals["state"] == [
        "    try:",
        "        raise Exception",
        "        return 3",
        "    except:",
        "        pass",
    ]
    assert gen2._internals["linetable"] == [0, 0, 1, 2, 3]

    ### frame adjustments ###

    ## no local variables stored ##
    init_length, _ = gen._frame_init()
    assert init_length == 8
    ## with local variables stored ##
    gen._internals["frame"].f_locals.update({"a": 3, "b": 2, "c": 1})
    init_length, _ = gen._frame_init()
    assert init_length == 11


def test_generator_update() -> None:
    gen = Generator()
    gen._internals.update(
        {
            "frame": None,
            "linetable": [],
            "source_lines": [],
            "jump_positions": [],
        }
    )

    def test(lineno: int = 0) -> frame:
        new_frame = frame()
        new_frame.f_locals = {
            "a": 1,
            "b": 2,
            "c": 3,
            ".internals": {".send": 1},
        }
        # for __bool__
        new_frame.f_code = 1
        new_frame.f_lasti = 1
        new_frame.f_lineno = lineno
        return new_frame

    ## With previous frame (Note: in order for it to work it needs a frame initailized e.g. a previous frame) ##
    ## old frame (f_back) ##
    gen._internals["frame"] = test()
    ## new/internal frame (frame) ##
    gen._locals()[".internals"][".frame"] = test()
    gen._update(0)
    ## new frame locals takes precedence ##
    assert gen._internals["frame"].f_locals == {
        "a": 1,
        "b": 2,
        "c": 3,
        ".internals": {},
    }
    ## old frame locals are preserved ##
    assert gen._internals["frame"].f_back is None

    ### lineno ###

    ## no linetable / EOF ##
    gen._internals["source_lines"] = ["a", "b", "c"]
    gen._internals["state"] = 1
    gen._locals()[".internals"][".frame"] = test(5)
    gen._update(5)
    assert gen._internals["lineno"] == 3
    assert gen._internals["state"] is None
    ## with linetable ##
    gen._internals["state"] = 1
    gen._internals["linetable"] = [0, 1, 2]
    gen._locals()[".internals"][".frame"] = test(5)
    gen._update(5)
    assert gen._internals["lineno"] == 4
    assert gen._internals["state"] == 1


def test_generator__next__() -> None:
    gen = Generator(simple_generator())
    assert gen._internals["state"] == gen._internals["source_lines"]
    assert next(gen) == 1
    assert gen._locals()[".internals"] == {
        "EOF": EOF,
        "exec_info": exc_info,
        "partial": partial,
        ".args": [],
        # ".send": None, ## this shouldn't show up
        "catch_errors": catch_errors,
    }
    assert gen._internals["state"] == gen._internals["source_lines"]
    assert next(gen) == 2
    assert gen._internals["state"] == gen._internals["source_lines"][1:]
    assert next(gen) == 3
    assert gen._internals["state"] is None
    assert next(gen, True)
    assert gen._internals["frame"] is None


def test_generator__iter__() -> None:
    """
    Test if the generator is iterable

    only test uninitialized to initialized generators
    since the initialized generators are expected to be patched
    which only adds the additional requirement to patch first
    
    Note:
    patches are applied on _frame_init since this is from
    an uninitialized generator. However, initialized generators
    are expected to be patched before _frame_init
    """
    assert [i for i in Generator(simple_generator())] == [1, 2, 3]

    @Generator
    def gen(*args, **kwargs) -> Generator:
        yield 1
        yield 2
        return 3

    assert [i for i in gen()] == [1, 2]

    @Generator
    def test_case():
        yield 1
        for i in range(3):
            yield i

    gen = test_case()
    assert [i for i in gen] == [1, 0, 1, 2]


def test_generator__close() -> None:
    gen = Generator()
    gen._internals = {}
    assert gen._close() is None
    for key, value in {
        "frame": None,
        "running": False,
        "suspended": False,
        "yieldfrom": None,
    }.items():
        assert gen._internals[key] == value
    count = 0
    for i in gen._internals["state_generator"]:
        count += 1
    assert count == 0


def test_generator_close() -> None:
    gen = Generator(simple_generator())
    assert gen.close() is None
    assert gen._internals["frame"] is None

    def test(case: int = 0) -> Generator:
        yield 0
        try:
            yield 1
            yield 2
        except GeneratorExit:
            if case == 0:
                raise GeneratorExit()
            if case == 1:
                yield 4
            return 30

    gen = Generator(test())
    ## start ##
    assert gen.close() is None
    assert gen._internals["frame"] is None

    ### catched ###

    # GeneratorExit #
    gen = Generator(test())
    next(gen)
    assert gen.close() is None
    assert gen._internals["frame"] is None
    # yield #
    gen = Generator(test(1))
    next(gen)
    try:
        gen.close()
        assert False
    except RuntimeError:
        pass
    # return #
    gen = Generator(test(2))
    next(gen)
    assert gen.close() is None
    assert gen._internals["frame"] is None

    ## make sure it doesn't run after closing ##
    assert next(gen, True)


def test_generator_send() -> None:
    ## value yield ##
    gen = Generator()
    f = frame()
    f.f_locals = {
        ".internals": {
            "EOF": EOF,
            "exec_info": exc_info,
            "partial": partial,
            ".args": [],
            ".send": None,
        },
    }
    source_lines = [
        "    return 1",
        "    return 2",
        "    a = locals()['.internals']['.send']",
        "    return a",
    ]
    gen._internals.update(
        {
            "frame": f,
            "code": None,
            "lineno": 1,
            "source_lines": source_lines,
            "jump_positions": [],
            "state": source_lines,
            "running": False,
            "suspended": False,
            "yieldfrom": None,
            "initialized": True,
        }
    )
    gen._internals["state_generator"] = gen._init_states()
    ## can't send if not running ##
    try:
        gen.send(1)
        assert False
    except TypeError:
        pass
    ## send doesn't change non value recieving yields ##
    assert next(gen) == 1
    assert gen.send(1) == 2
    ## send changes value recieving yield ##
    assert gen.send(1) == 1


def test_generator_throw() -> None:
    gen = Generator(simple_generator())
    try:
        gen.throw(ImportError)
        assert False
    except ImportError:
        assert gen._internals["linetable"] == [-1, 0, 1, 2]
        assert gen._internals["state"] is None

    def test():
        try:
            yield 1
        except ImportError:
            pass
        yield 2
        yield 3

    gen = Generator(test())
    assert gen.throw(ImportError) == 2
    assert gen._internals["state"][2:] == gen._internals["source_lines"][1:]
    assert gen._internals["linetable"] == [0, 0, 1, 2, 3, 4, 5]


def test_generator_type_checking() -> None:
    gen = Generator()
    assert isinstance(gen, (GeneratorType, Generator)) and issubclass(type(gen), (GeneratorType, Generator))
    gen = AsyncGenerator()
    assert isinstance(gen, (AsyncGeneratorType, AsyncGenerator)) and issubclass(
        type(gen), (AsyncGeneratorType, AsyncGenerator)
    )


def test_closure() -> None:
    def test():

        closure_cell = 1

        @Generator
        def test_case():
            yield closure_cell
            yield closure_cell
            yield closure_cell
            yield closure_cell

        gen = test_case()
        assert next(gen) == 1
        closure_cell = 2
        assert next(gen) == 2
        gen_copy = gen.copy()
        closure_cell = 3
        ## copies don't retain the closure binding ##
        assert next(gen_copy) == 2
        assert next(gen) == 3
        ## if wanting to bind to a closure ##
        ## then we can be set manually ##
        gen_copy._bind(gen)
        closure_cell = 4
        assert next(gen_copy) == 4
        assert next(gen) == 4

    test()


def test_yieldfrom() -> None:
    @Generator
    def test():
        yield from range(3)

    assert [i for i in test()] == [0, 1, 2]

    @Generator
    def test():
        yield from range(3)
        for i in range(3):
            yield i
    
    assert test()._internals["jump_positions"] == [[2, 5], [6, 7]]


def test_recursion() -> None:
    @Generator
    def test(depth=0):
        depth += 1
        yield depth
        yield from test(depth)

    gen = test()
    assert [next(gen) for i in range(10)] == list(range(1, 11))


def test_gen_expr() -> None:
    patch_iterators(globals())
    gen = Generator(i for i in range(3))
    assert gen._internals["source_lines"] == [
        "    for i in range(3):",
        "        return i",
    ]

    assert [i for i in gen] == [0, 1, 2]

    ##################################################
    # uninitialized #

    gen = Generator((i, j) for i in range(3) for j in range(2))
    assert gen._internals["source_lines"] == [
        "    for i in range(3):",
        "        for j in range(2):",
        "            return (i, j)",
    ]

    assert gen._locals().pop(".0", None) is None

    assert [i for i in gen] == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]

    # initialized #

    gen = ((i, j) for i in range(3) for j in range(2))
    next(gen)
    next(gen)
    gen = Generator(gen)
    assert [i for i in gen] == [(1, 0), (1, 1), (2, 0), (2, 1)]


def test_lambda_expr() -> None:
    ## gen_expr not running + running ##
    test = lambda: (i for i in range(3))
    gen = Generator(test())
    assert gen._internals["source_lines"] == [
        "    for i in range(3):",
        "        return i",
    ]
    assert gen._internals["lineno"] == 1
    temp = (i for i in range(3))
    next(temp)
    gen = Generator(temp)
    assert gen._internals["source_lines"] == [
        "    for i in range(3):",
        "        return i",
    ]
    assert gen._internals["lineno"] == 2
    assert next(gen) == 1
    ## lambda with value yields ##
    test = lambda: (yield)
    gen = Generator(test())
    assert gen._internals["source_lines"] == [
        "return",
        "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        " locals()['.internals']['.args'].pop()",
    ]
    ## running ##
    test = lambda: (yield (yield 3))
    gen = test()
    next(gen)
    gen = Generator(gen)
    assert gen._internals["source_lines"] == [
        "return  3",
        "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        "return  locals()['.internals']['.args'].pop()",
        "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        " locals()['.internals']['.args'].pop()",
    ]
    ## not implemented (e.g. determining linenos from encapsulated value yields) ##
    # assert gen._internals["lineno"] == ...


def test_initialized() -> None:
    ## transfer over the source and lineno ##
    gen = simple_generator()
    next(gen)
    assert [i for i in Generator(gen)] == [2, 3]

    ## transfer over variables ##

    def test():
        c = 1
        b = 2
        a = 3
        yield a
        yield b
        yield c

    gen = test()
    next(gen)
    gen = Generator(gen)
    # assert
    keys = gen._locals().keys()
    for key in ("a", "b", "c"):
        assert key in keys
    assert [i for i in gen] == [2, 1]

    # patch_iterators(locals())

    def test():
        for i in range(5):
            yield i

    gen = test()
    next(gen)
    next(gen)
    gen = Generator(gen)
    assert gen._locals()["i"] == 1
    assert [i for i in gen] == [2, 3, 4]


def test_value_yield() -> None:

    def test(test_case, answer: str) -> None:
        assert ("\n".join(test_case()._internals["source_lines"]) == answer)

    ### exceptions ###

    ## make sure the end section is added ##
    answer = """    try:
        try:
            return 1
        except:
            locals()['.internals']['.error'] = locals()['.internals']['exc_info']()[1]
        return  1
        locals()['.internals']['.args'] += [locals()['.internals']['.send']]
        if locals()['.internals']['.catch_errors'](locals()['.internals']['.error'], locals()['.internals']['.args'].pop()):
            locals()['.continue_error'] = False
            return 2
    finally:
        pass"""
    @Generator
    def test_case():
        try:
            yield 1
        except (yield 1):
            yield 2
    ## TODO: fix case
    # test(test_case, answer)
    ## with exception group ##
    @Generator
    def test_case():
        try:
            yield 1
        except* (yield 1):
            yield 2
    ## TODO: fix case
    # test(test_case, answer)
    ## multiple catches ##
    @Generator
    def test_case():
        try:
            yield 1
        except (yield):
            yield 2
        except (yield):
            yield 3
        except Exception:
            yield 4
        else:
            yield 5
        finally:
            yield 6

    answer = """    try:
        try:
            return 1
        except:
            locals()['.internals']['.error'] = locals()['.internals']['exc_info']()[1]
        return
        locals()['.internals']['.args'] += [locals()['.internals']['.send']]
        if locals()['.internals']['.catch_errors'](locals()['.internals']['.error'], locals()['.internals']['.args'].pop()):
            locals()['.continue_error'] = False
            return 2
        else:
            return
            locals()['.internals']['.args'] += [locals()['.internals']['.send']]
            if locals()['.internals']['.catch_errors'](locals()['.internals']['.error'], locals()['.internals']['.args'].pop()):
                locals()['.continue_error'] = False
                return 3
            else:
                if locals()['.internals']['.catch_errors'](locals()['.internals']['.error'], Exception):
                    locals()['.continue_error'] = False
                    return 4
                else:
                    locals()['.internals']['.continue_error'] = False
                    raise locals()['.internals']['.error']
    except:
        raise locals()['.internals']['exc_info']()[1]
    else:
        return 5
    finally:
        return 6"""
    ## TODO: fix case
    # test(test_case, answer)

    ### nested exceptions ###
    ## try focused ##
    # @Generator
    # def test_case():
    #     try:
    #         try:
    #             try:
    #                 yield 3
    #             except (yield c):
    #                 yield 4
    #         except (yield b):
    #             pass
    #     except (yield a):
    #         pass


    ## except focused ##
    # @Generator
    # def test_case():
    #     try:
    #         yield 1
    #     except (yield a):
    #         try:
    #             yield 2
    #         except (yield b):
    #             try:
    #                 yield 3
    #             except (yield c):
    #                 yield 4
    ## try and except focused ##
    # @Generator
    # def test_case():
    #     try:
    #         try:
    #             try:
    #                 yield 1
    #             except (yield a):
    #                 yield 2
    #         except (yield a):
    #             try:
    #                 yield 1
    #             except (yield a):
    #                 yield 2
    #     except (yield b):
    #         try:
    #             try:
    #                 yield 1
    #             except (yield a):
    #                 yield 2
    #         except (yield c):
    #             try:
    #                 yield 1
    #             except (yield a):
    #                 yield 2

    ## exception groups + nested exceptions
    # @Generator
    # def test_case():
    #     try:
    #         print(1)
    #         try:
    #             print(2)
    #             try:
    #                 raise ExceptionGroup('', (AssertionError(), TypeError(), ValueError()))
    #             except* (AssertionError, TypeError, ZeroDivisionError):
    #                 exc = exc_info()[1]
    #                 assert catch_errors(exc, AssertionError, TypeError, ValueError) == False
    #             print(3)
    #         except* ValueError:
    #             raise Exception()
    #     except (Exception, ZeroDivisionError):
    #         print(4)
    ### loops in exceptions ###

####################################
### asynchronous generator tests ###
####################################


async def simple_asyncgenerator():
    yield 1
    yield 2
    yield 3

@pytest.mark.asyncio
async def test_asyncgenerator_pickle() -> None:

    gen = AsyncGenerator(simple_asyncgenerator)

    attrs_before = dir(gen._internals["frame"])
    test_Pickler(gen)
    ## make sure no change in the attrs ##
    assert attrs_before == dir(gen._internals["frame"])
    ## instantiate the generator since it's not initialized ##
    gen = gen()
    assert await anext(gen) == 1
    # ## copy the generator ##
    gen2 = gen.copy()
    gen3 = gen.copy()
    assert await anext(gen) == await anext(gen2) == await anext(gen3)
    assert await anext(gen) == await anext(gen2) == await anext(gen3)
    prefix = gen._internals["prefix"]
    for key in ("code", "frame", "suspended", "yieldfrom", "running"):
        assert hasattr(gen2, prefix + key)

@pytest.mark.asyncio
async def test_asyncgenerator_asend() -> None:
    ## value yield ##
    gen = AsyncGenerator()
    f = frame()
    f.f_locals = {
        ".internals": {
            "EOF": EOF,
            "exec_info": exc_info,
            "partial": partial,
            ".args": [],
            ".send": None,
        },
    }
    source_lines = [
        "    return 1",
        "    return 2",
        "    a = locals()['.internals']['.send']",
        "    return a",
    ]
    gen._internals.update(
        {
            "frame": f,
            "code": None,
            "lineno": 1,
            "source_lines": source_lines,
            "jump_positions": [],
            "state": source_lines,
            "running": False,
            "suspended": False,
            "yieldfrom": None,
            "initialized": True,
        }
    )
    gen._internals["state_generator"] = gen._init_states()
    ## can't send if not running ##
    try:
        await gen.asend(1)
        assert False
    except TypeError:
        pass

    ## send doesn't change non value recieving yields ##
    assert await anext(gen) == 1
    assert await gen.asend(1) == 2
    ## send changes value recieving yield ##
    assert await gen.asend(1) == 1

@pytest.mark.asyncio
async def test_asyncgenerator_aclose() -> None:
    gen = AsyncGenerator(simple_asyncgenerator())
    assert await gen.aclose() is None
    assert gen._internals["frame"] is None

    @AsyncGenerator
    def test(case: int = 0) -> Generator:
        yield 0
        try:
            yield 1
            yield 2
        except GeneratorExit:
            if case == 0:
                raise GeneratorExit()
            if case == 1:
                yield 4
            return 30

    gen = test()
    ## start ##
    assert await gen.aclose() is None
    assert gen._internals["frame"] is None

    ### catched ###

    # GeneratorExit #
    gen = test()
    await anext(gen)
    assert await gen.aclose() is None
    assert gen._internals["frame"] is None
    # yield #
    gen = test(1)
    await anext(gen)
    try:
        await gen.aclose()
        assert False
    except RuntimeError:
        pass
    # return #
    gen = test(2)
    await anext(gen)
    # gen._close()
    assert await gen.aclose() is None
    assert gen._internals["frame"] is None

    ## make sure it doesn't run after closing ##
    assert await anext(gen, True)

@pytest.mark.asyncio
async def test_asyncgenerator_athrow() -> None:
    gen = AsyncGenerator(simple_asyncgenerator())
    try:
        await gen.athrow(ImportError)
        assert False
    except ImportError:
        assert gen._internals["linetable"] == [-1, 0, 1, 2]
        assert gen._internals["state"] is None

    @AsyncGenerator
    def test():
        try:
            yield 1
            assert False
        except ImportError:
            pass
        yield 2
        yield 3

    gen = test()

    assert await gen.athrow(ImportError) == 2
    assert gen._internals["state"][2:] == gen._internals["source_lines"][1:]
    assert gen._internals["linetable"] == [0, 0, 1, 2, 3, 4, 5, 6]

@pytest.mark.asyncio
async def test_asyncgenerator__init__() -> None:
    ## function generator ##
    # uninitilized - this should imply that use as a decorator works also ##
    init_test(simple_asyncgenerator, False, AsyncGenerator, AsyncGeneratorType)
    # initilized #
    init_test(simple_asyncgenerator(), True, AsyncGenerator, AsyncGeneratorType)
    ## generator expression ##
    gen = (i async for i in atrack(simple_asyncgenerator()))
    init_test(gen, True, AsyncGenerator, AsyncGeneratorType)

    ## test if the function related attrs get transferred ##

    closure_cell = 1

    def test2(FUNC: Any) -> None:
        """docstring"""
        closure_cell

    gen = AsyncGenerator(test2)

    assert gen.__call__.__annotations__ == test2.__annotations__
    assert gen.__call__.__doc__ == test2.__doc__
    assert get_nonlocals(gen.__closure__) == get_nonlocals(test2.__closure__)

@pytest.mark.asyncio
async def test_asyncgenerator__anext__() -> None:
    gen = AsyncGenerator(simple_asyncgenerator())
    assert gen._internals["state"] == gen._internals["source_lines"]
    assert await anext(gen) == 1
    assert gen._locals()[".internals"] == {
        "EOF": EOF,
        "exec_info": exc_info,
        "partial": partial,
        ".args": [],
        "catch_errors": catch_errors,
    }
    assert gen._internals["state"] == gen._internals["source_lines"]
    assert await anext(gen) == 2
    assert gen._internals["state"] == gen._internals["source_lines"][1:]
    assert await anext(gen) == 3
    assert gen._internals["state"] is None
    assert await anext(gen, True)
    assert gen._internals["frame"] is None

@pytest.mark.asyncio
async def test_asyncgenerator__aiter__() -> None:
    assert [i async for i in AsyncGenerator(simple_asyncgenerator())] == [1, 2, 3]

    @AsyncGenerator
    def gen(*args, **kwargs) -> Generator:
        yield 1
        yield 2
        return 3

    assert [i async for i in gen()] == [1, 2]

    @AsyncGenerator
    def test_case():
        yield 1
        for i in range(3):
            yield i

    gen = test_case()
    ## because it's not from an already running generator ##
    ## the fishook patches on the iterators are already applied ##
    assert [i async for i in gen] == [1, 0, 1, 2]
