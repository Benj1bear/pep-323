# test_lineno_adjust() ## not going to be implemented at present time ##
## tested in unpack_genexpr: update_line
## tested in test_unpack: named_adjust, unpack_adjust, update_lines, check_ID
# tested in control_flow_adjust: statement_adjust
## Generator source cleaning is tested in test_custom_generator ##

from sys import version_info
from types import FunctionType
from typing import Iterable

from gcopy.source_processing import (
    collect_definition,
    collect_lambda,
    collect_multiline_string,
    collect_string,
    control_flow_adjust,
    except_adjust,
    except_catch_adjust,
    expr_getsource,
    extract_as,
    end_offset_adjust,
    extract_function,
    extract_genexpr,
    extract_lambda,
    extract_source_from_comparison,
    get_indent,
    get_loops,
    get_signature,
    indent_lines,
    inverse_bracket,
    is_alternative_statement,
    is_definition,
    is_item,
    is_loop,
    is_statement,
    iter_adjust,
    line_adjust,
    loop_adjust,
    outer_loop_adjust,
    setup_next_line,
    sign,
    signature,
    singly_space,
    skip_alternative_statements,
    skip_blocks,
    skip_line_continuation,
    skip_source_definition,
    string_collector_proxy,
    ternary_adjust,
    unpack,
    unpack_genexpr,
    unpack_lambda,
    update_depth,
    yield_adjust,
)


def assert_cases(FUNC: FunctionType, *args, compare: list = []) -> None:
    try:
        if compare:
            for arg in args:
                assert FUNC(arg) == compare.pop(0)
            return
        for arg in args:
            assert FUNC(arg)
    except AssertionError:
        raise AssertionError(f"{FUNC.__name__} failed on {arg}" + " on compare" * bool(compare))


def test_update_depth() -> None:
    assert update_depth(0, "(") == 1
    assert update_depth(0, ")") == -1


def test_get_indent() -> None:
    assert get_indent("  asdf") == 2


# def test_lineno_adjust() -> None:
#     from inspect import currentframe
#     frame = currentframe()
#     1
#     True
#     True
#     print(frame.f_lasti)
#     import dis
#     dis.dis(frame.f_code)
#     # print(lineno_adjust(frame))


def test_line_adjust() -> None:
    ## adjusted ##
    assert line_adjust("for i in ... if ...", []) == ("... ", ["for i in ... if:"])
    ## not adjusted ##
    assert line_adjust("i if ... else ...", [], False) == ("", ["i if ... else ..."])
    assert line_adjust(" ...", [], False) == ("", ["..."])


def test_unpack_genexpr() -> None:
    """
    Note: line_adjust is tested within this test
    """

    assert unpack_genexpr("(i for\\i in range(3))") == [
        "    for i in range(3):",
        "        return i",
    ]
    assert unpack_genexpr("(i for i in range(3) for j in range(5))") == [
        "    for i in range(3):",
        "        for j in range(5):",
        "            return i",
    ]
    assert unpack_genexpr("(i for i in range(3) for j in range(5) if i==True)") == [
        "    for i in range(3):",
        "        for j in range(5):",
        "            if i==True:",
        "                return i",
    ]


def test_skip_line_continuation() -> None:
    source = "\\     \n     hi"
    source_iter = enumerate(source)
    index, char = next(source_iter)
    skip_line_continuation(source_iter, source, index)
    assert "".join(char for index, char in source_iter) == "hi"


def test_skip_source_definition() -> None:
    source = """@method1
@method2(*args,**kwargs)
def function():pass"""
    assert skip_source_definition(source) == "pass"
    source = """@method1
@method2(*args,**kwargs)
async def function():pass"""
    assert skip_source_definition(source) == "pass"


def aux_test(source: str, f_string: bool = False) -> tuple[Iterable, str, str]:
    """for setting up the string collector tests"""
    source_iter = enumerate(source)
    for i in range(1 + f_string):
        index, char = next(source_iter)
    return source_iter, char, source


def test_collect_string() -> None:

    ## normal string ##

    source_iter, char, source = aux_test('"""hello world"""')

    assert collect_string(source_iter, 0, char, source) == (1, ['""'], 0)
    next(source_iter)
    assert collect_string(source_iter, 1, char, source) == (14, ['"hello world"'], 0)
    next(source_iter)
    assert collect_string(source_iter, 14, char, source) == (16, ['""'], 0)

    ## f-string ##

    # single bracket #
    source_iter, char, source = aux_test('f"asdf{(yield 3)}" -----', True)
    assert collect_string(source_iter, 0, char, source) == (
        17,
        [
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "\"asdf{locals()['.internals']['.args'].pop()}\"",
        ],
        0,
    )
    # double bracket #
    source_iter, char, source = aux_test('f"asdf{{(yield 3)}}"', True)
    assert collect_string(source_iter, 0, char, source) == (
        19,
        ['"asdf{{(yield 3)}}"'],
        0,
    )


def test_collect_multiline_string() -> None:
    source_iter, char, source = aux_test('"""hello world"""')
    assert collect_multiline_string(source_iter, 0, char, source) == (
        len(source) - 1,
        [source],
        0,
    )

    ## f-string ##

    # single bracket #
    source_iter, char, source = aux_test('f"""hello {(yield 3)} world"""', True)
    assert collect_multiline_string(source_iter, 0, char, source) == (
        29,
        [
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            '"""hello {locals()[\'.internals\'][\'.args\'].pop()} world"""',
        ],
        0,
    )
    # double bracket #
    source_iter, char, source = aux_test('f"""hello {{(yield 3)}} world"""', True)
    assert collect_multiline_string(source_iter, 0, char, source) == (
        31,
        ['"""hello {{(yield 3)}} world"""'],
        0,
    )


def test_string_collector_proxy(recursion: int = 1) -> None:
    """Checks for both skipping and collection cases"""
    source = '"""hello world"""'
    source_iter = enumerate(source)
    prev = (0, 0, "")
    line = ""
    if recursion:
        temp = ['""', '"""hello world"""']
    else:
        temp = [None, None]
    answer = [(temp.pop(0), (0, 1, '"')), (temp.pop(0), (2, 16, '"'))]
    for index, char in source_iter:
        ## collect strings ##
        if char == "'" or char == '"':
            args = (index, char, prev, source_iter)
            if recursion:
                args += (line,)
            ## we need to save line and prev ##
            line, prev, fixed_lines = string_collector_proxy(*args)
            assert (line, prev) == answer.pop(0)
            assert fixed_lines == 0
    if recursion:
        test_string_collector_proxy(0)


def test_inverse_bracket() -> None:
    compare = list("([{}])")
    assert_cases(inverse_bracket, *compare[:3], compare=compare[3:][::-1])


def test_is_item() -> None:
    assert is_item("a")
    assert is_item("a)") == False
    assert is_item("await b")
    assert is_item("await b)") == False
    assert is_item("yield from g")


def test_unpack() -> None:
    """
    Note:

    unpack_adjust
    update_lines
    named_adjust

    may not all be separately tested as independent testable
    units since they are tied closely in with the unpack
    function using it in recursion, therefore, these will
    get tested along with the unpack function.
    """

    test = lambda line: unpack("", enumerate(line), line)

    ## unpacking ##

    # general unpacking #
    assert test("a = yield 3 *= 5 == 5") == (
        [
            "return 3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "a  =locals()['.internals']['.args'].pop(0) *= 5  == 5",
        20,
        0,
    )

    # tuple unpacking #
    assert test("a = (yield 3),(yield 5),(yield 7) = 5") == (
        [
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]",
            "return  5",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]",
            "return  7",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]",
        ],
        "a  =locals()['.internals']['.args'].pop(0) ,locals()['.internals']['.args'].pop(0) ,locals()['.internals']['.args'].pop(0) = 5",
        36,
        0,
    )

    ## unwrapping ##

    assert test("(yield 3)") == (
        [
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "locals()['.internals']['.args'].pop()",
        5,
        0,
    )

    assert test("(yield 3,(yield 5))") == (
        [
            "return  5",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return  3 ,locals()['.internals']['.args'].pop()",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "locals()['.internals']['.args'].pop()",
        5,
        0,
    )

    assert test("a = yield (     yield    (yield 3 )  ) = 5") == (
        [
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return  locals()['.internals']['.args'].pop()",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return locals()['.internals']['.args'].pop()",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "a  =locals()['.internals']['.args'].pop(0) = 5",
        41,
        0,
    )

    assert test("(yield 3),(yield (yield 3))") == (
        [
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]",
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return  locals()['.internals']['.args'].pop()",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "locals()['.internals']['.args'].pop(0) ,locals()['.internals']['.args'].pop()",
        15,
        0,
    )

    ## with named expression ##

    assert test("a = (b:=(c:=next(j)) ) = 5") == (
        ["locals()['.internals']['.args'] += [(b:=(c:=next(j)) )]"],
        "a  =locals()['.internals']['.args'].pop(0) = 5",
        25,
        0,
    )

    assert test("a = (b:=next(j) ) = 5") == (
        ["locals()['.internals']['.args'] += [(b:=next(j) )]"],
        "a  =locals()['.internals']['.args'].pop(0) = 5",
        20,
        0,
    )

    assert test("a = (b:=(yield 3) +a) = 5") == (
        [
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "locals()['.internals']['.args'] += [(b:=locals()['.internals']['.args'].pop()  +a)]",
        ],
        "a  =locals()['.internals']['.args'].pop(0) = 5",
        24,
        0,
    )

    assert test("(b := (yield (a := (yield (c := (yield 33)))))) == (yield 3)") == (
        [
            "return  33",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return  (c := locals()['.internals']['.args'].pop())",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return  (a := locals()['.internals']['.args'].pop())",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "locals()['.internals']['.args'] += [(b := locals()['.internals']['.args'].pop())]",
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "locals()['.internals']['.args'].pop(0) == locals()['.internals']['.args'].pop()",
        56,
        0,
    )

    assert test("(yield (yield (yield (yield 3)))) == (yield 4)") == (
        [
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return  locals()['.internals']['.args'].pop()",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return  locals()['.internals']['.args'].pop()",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return  locals()['.internals']['.args'].pop()",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]",
            "return  4",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "locals()['.internals']['.args'].pop(0) == locals()['.internals']['.args'].pop()",
        42,
        0,
    )

    ## f-string ##
    assert test("a = f'hi{(yield 3)}' = yield 3 = 5") == (
        [
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "locals()['.internals']['.args'] += [f'hi{locals()['.internals']['.args'].pop()}']",
            "return 3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "a  =locals()['.internals']['.args'].pop(0) =locals()['.internals']['.args'].pop(0) = 5",
        33,
        0,
    )

    assert test("a = f'hi{(yield 3),(yield (yield 3))}' = yield 3 = 5") == (
        [
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]",
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return  locals()['.internals']['.args'].pop()",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "locals()['.internals']['.args'] += [f'hi{locals()['.internals']['.args'].pop(0) ,locals()['.internals']['.args'].pop()}']",
            "return 3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "a  =locals()['.internals']['.args'].pop(0) =locals()['.internals']['.args'].pop(0) = 5",
        51,
        0,
    )

    ## with dictionary assignment ##
    assert test("a = locals()['a'+next(j)] = 'hi '+'hi{(yield 3)} (yield 3)' = yield 3 = 5 = ") == (
        [
            "locals()['.internals']['.args'] += ['a']",
            "locals()['.internals']['.args'] += [locals()[locals()['.internals']['.args'].pop(0) +next(j)]]",
            "locals()['.internals']['.args'] += ['hi ']",
            "locals()['.internals']['.args'] += ['hi{(yield 3)} (yield 3)']",
            "return 3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "a  =locals()['.internals']['.args'].pop(0) =locals()['.internals']['.args'].pop(0) +locals()['.internals']['.args'].pop(0) =locals()['.internals']['.args'].pop(0) = 5  = ",
        75,
        0,
    )
    ## ternary statements ##
    assert test("a = 1 if 2 else 3 = 5") == (
        [
            "if  2 :",
            "    locals()['.internals']['.args'] += [1]",
            "else:",
            "    locals()['.internals']['.args'] += [3]",
        ],
        "a  =locals()['.internals']['.args'].pop()= 5",
        20,
        0,
    )
    assert test("a = (1 if 2 else 3) if True else False = 5") == (
        [
            "if  2 :",
            "    locals()['.internals']['.args'] += [1]",
            "else:",
            "    if  True :",
            "        locals()['.internals']['.args'] += [3]",
            "    else:",
            "        locals()['.internals']['.args'] += [False]",
        ],
        "a  =locals()['.internals']['.args'].pop()= 5",
        8,
        0,
    )
    ## function definition ##
    assert test("def function(a=(yield), b= (yield 3))") == (
        [
            "return",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "locals()['.internals']['.args'] += [locals()['.internals']['.args'].pop()]",
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "def function(a =locals()['.internals']['.args'].pop(0) , b = locals()['.internals']['.args'].pop())",
        36,
        0,
    )
    ## collect_lambda ##
    assert test("lambda a=(yield), b= (yield 3): (yield)") == (
        [
            "return",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "lambda a=locals()['.internals']['.args'].pop(), b= locals()['.internals']['.args'].pop(): (yield)",
        5,
        0,
    )
    ## decorator ##
    assert test("@function(a=(yield 3))") == (
        [
            "return  3",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "@function(a =locals()['.internals']['.args'].pop())",
        21,
        0,
    )
    ## issue where variable assignment isn't working correctly only on yields/yield froms ##
    ##  without brackets (e.g. works on value yields but not regular yields) ##
    ## TODO write tests for these
    # a=(yield [1,2,3])
    # b=(yield from [1,2,3])


def test_ternary_adjust() -> None:
    case = """if True:
    1
else:
    if False:
        2
    else:
        3"""
    assert ternary_adjust(case.split("\n")) == [
        "if True:",
        "    locals()['.internals']['.args'] += [1]",
        "else:",
        "    if False:",
        "        locals()['.internals']['.args'] += [2]",
        "    else:",
        "        locals()['.internals']['.args'] += [3]",
    ]


def test_collect_definition() -> None:
    def setup_test() -> object:
        line = source.split("\n")[0]
        return type(
            "",
            tuple(),
            {
                "line": line,
                "lines": [],
                "index": 0,
                "lineno": 0,
                "source": source,
                "source_iter": enumerate(source),
                "fixed_lines": 0,
            },
        )

    source = """def function():
    pass
    print('''hello world''')"""
    self = setup_test()
    collect_definition(self, 0, 0)
    assert self.index == len(source) - 1
    assert self.char == ")"
    assert self.lineno == 3
    assert self.lines == source.split("\n")
    ## with yields ##
    source = """def function(x=(yield), y = (yield) ):
    pass
    print('''hello world''')"""
    self = setup_test()
    collect_definition(self, 0, 0)
    assert self.index == len(source) - 1
    assert self.char == ")"
    assert self.lineno == 3
    assert self.lines == [
        "return",
        "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        "return",
        "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        "def function(x=locals()['.internals']['.args'].pop(), y = locals()['.internals']['.args'].pop() ):",
        "",
        "    pass",
        "    print('''hello world''')",
    ]
    source = """def function():
    '''

    '''
    pass
    print('''
    hello world
    ''')"""
    self = setup_test()
    collect_definition(self, 0, 0)
    assert self.index == len(source) - 1
    assert self.char == ")"
    assert self.lineno == 8
    assert self.lines == [
        "def function():",
        "    '''\n\n    '''",
        "    pass",
        "    print('''\n    hello world\n    ''')",
    ]


def test_is_loop() -> None:
    assert_cases(is_loop, "for ", "while ", "async     for ")


def test_is_alternative_statement() -> None:
    assert_cases(is_alternative_statement, "elif:", "else:")
    if (3, 10) <= version_info:
        assert_cases(is_alternative_statement, "case:", "default:")


def test_is_definition() -> None:
    assert_cases(is_definition, "def ", "async def ", "class ")


def test_skip_alternative_statements() -> None:
    blocks = [
        "    if True:",
        "        pass",
        "    elif True:",
        "        pass",
        "    else:",
        "        pass",
        "try:",
        "    pass",
        "except:",
        "    pass",
    ]
    ## shouldn't skip ##
    assert skip_alternative_statements(enumerate(blocks), 4) == (
        0,
        1,
        blocks[0],
        get_indent(blocks[0]),
    )
    ## should skip through all through 1:4 ##
    assert skip_alternative_statements(enumerate(blocks[1:4]), 4) == (
        2,
        0,
        blocks[1 + 2],
        get_indent(blocks[1 + 2]),
    )  ## shift is 1
    ## should skip all through towards the 'try:' (excepts are not skipped since you could still be have an exception) ##
    for shift in range(1, 6):
        assert skip_alternative_statements(enumerate(blocks[shift:]), 4) == (
            6 - shift,
            1,
            blocks[6],
            get_indent(blocks[6]),
        )
    blocks = [
        "match 'word':",
        "    case 'word 1':",
        "        return 1",
        "    case 'word 2':",
        "        return 2",
        "    default:",
        "        return 3",
    ]
    for shift in range(1, 6):
        ## it should skip over all of them ##
        assert skip_alternative_statements(enumerate(blocks[shift:]), 4) == (
            6 - shift,
            0,
            blocks[-1],
            get_indent(blocks[-1]),
        )


def test_control_flow_adjust() -> None:
    ## you need to test for if/elif/else/try/except/match/case/default and when these are sliced ##
    ## and what the resulting index changes are ##
    blocks = [
        "    match ...:",
        "        case ...:",
        "            if True:",
        "                0",
        "            elif True:",
        "                1",
        "            else:",
        "                2",
        "            try:",
        "                3",
        "            except:",
        "                4",
        "        case ...:",
        "            5",
        "        default:",
        "            6",
    ]
    end_pos = len(blocks)
    test = lambda start_pos: control_flow_adjust(blocks[start_pos:], list(range(start_pos, end_pos)))
    ## match ##
    assert test(0) == (blocks, list(range(0, end_pos)))
    ### between + start alternative statements ###

    temp = lambda index: (
        [blocks[index][12:]] + indent_lines(blocks[8:12], -8),
        [index] + list(range(8, 12)),
    )

    ## if ##
    assert test(2) == (indent_lines(blocks[2:12], -8), list(range(2, 12)))
    assert test(3) == temp(3)

    ## elif, else ##
    for i in range(5, 9, 2):
        assert test(i) == temp(i)
        assert test(i - 1) == (
            ["    try:", "        3", "    except:", "        4"],
            [8, 9, 10, 11],
        )
    ## try ##
    assert test(9) == (indent_lines(blocks[8:12], -8), [9] + list(range(9, 12)))
    ## except ##
    assert test(11) == (["    4"], [11])
    assert test(10) == (
        ["    try:", "        pass", "    except:", "        4"],
        [10, 10, 10, 11],
    )
    ## case ##
    assert test(13) == ([blocks[13][8:]], [13])
    assert test(12) == ([""], [])
    ## default ##
    assert test(15) == ([blocks[15][8:]], [15])
    assert test(14) == ([""], [])
    ## try-except with multiple except catches + finally ##
    blocks = [
        "    try:",
        "        try:",
        "            try:",
        "                1",
        "            except:",
        "                2",
        "            except:",
        "                3",
        "            except:",
        "                4",
        "            finally:",
        "                5",
        "        except:",
        "            6",
        "        except:",
        "            7",
        "    except:",
        "        8",
    ]
    end_pos = len(blocks)
    ## check 'except' ##
    assert test(6) == (
        [
            "    try:",
            "        try:",
            "            try:",
            "                pass",
            "            except:",
            "                3",
            "            except:",
            "                4",
            "            finally:",
            "                5",
            "        except:",
            "            6",
            "        except:",
            "            7",
            "    except:",
            "        8",
        ],
        [6, 6, 6, 6, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
    )
    assert test(7) == (
        [
            "    try:",
            "        try:",
            "            try:",
            "                3",
            "            except:",
            "                4",
            "            finally:",
            "                5",
            "        except:",
            "            6",
            "        except:",
            "            7",
            "    except:",
            "        8",
        ],
        [7, 7, 7, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
    )
    ## check 'finally' ##
    assert test(10) == (
        [
            "    try:",
            "        try:",
            "            try:",
            "                pass",
            "            finally:",
            "                5",
            "        except:",
            "            6",
            "        except:",
            "            7",
            "    except:",
            "        8",
        ],
        [10, 10, 10, 10, 10, 11, 12, 13, 14, 15, 16, 17],
    )
    assert test(11) == (
        [
            "    try:",
            "        try:",
            "            5",
            "        except:",
            "            6",
            "        except:",
            "            7",
            "    except:",
            "        8",
        ],
        [11, 11, 11, 12, 13, 14, 15, 16, 17],
    )
    ## check nesting ##
    assert test(12) == (
        [
            "    try:",
            "        try:",
            "            pass",
            "        except:",
            "            6",
            "        except:",
            "            7",
            "    except:",
            "        8",
        ],
        [12, 12, 12, 12, 13, 14, 15, 16, 17],
    )
    assert test(13) == (
        [
            "    try:",
            "        try:",
            "            6",
            "        except:",
            "            7",
            "    except:",
            "        8",
        ],
        [13, 13, 13, 14, 15, 16, 17],
    )
    assert test(15) == (
        ["    try:", "        7", "    except:", "        8"],
        [15, 15, 16, 17],
    )


def test_indent_lines() -> None:
    lines = ["line 1", "line 2", "line 3"]
    indented_lines = indent_lines(lines)
    assert indented_lines == ["    line 1", "    line 2", "    line 3"]
    assert indent_lines(indented_lines, -4) == lines
    assert indent_lines(lines, 0) == lines


def test_iter_adjust() -> None:
    indents = 4
    test = lambda test_case: (" " * indents + "%s i in range(3):" % test_case, indents)
    assert iter_adjust(*test("for")) == "    for i in locals()['.internals']['.4']:"
    assert iter_adjust(*test("while")) == "    while i in locals()['.internals']['.4']:"


def test_is_statement() -> None:
    assert is_statement("continue", "continue")
    assert is_statement("continue\\", "continue") == False
    assert is_statement("continued", "continue") == False


def test_skip_blocks() -> None:
    blocks = [
        "    for i in range(3):",
        "        0",
        "    while True:",
        "        1",
        "    def func():",
        "        2",
        "    async def func():",
        "        3",
        "    class func:",
        "        4",
    ]
    length = len(blocks)
    for shift in range(0, length, 2):
        line_iter = enumerate(blocks[shift:])
        index, line = next(line_iter)
        assert skip_blocks([], line_iter, index, line) == (
            indent_lines(blocks[shift:], -4),
            None,
            None,
        )


def test_loop_adjust() -> None:
    block = [
        "    for i in range(3):",
        "        for j in range(5):",
        "            continue",
        "            break",
        "            while True:",
        "                pass",
        "            def func():",
        "                pass",
        "            for k in range(7):",
        "                pass",
        "            print('hi')",
    ]
    length = len(block)
    # 0 based indexes #
    indexes = list(range(length))
    ## adjustments ##
    assert loop_adjust(block[2:], indexes[2:], block[1:], *(1, length)) == (
        [
            "    locals()['.internals']['.continue']=True",
            "    for _ in (locals().get('_'),):",
            "        break",
            "        locals()['.internals']['.continue']=False",
            "        break",
            "        while True:",
            "            pass",
            "        def func():",
            "            pass",
            "        for k in range(7):",
            "            pass",
            "    if locals()['.internals']['.continue']:",
            "        for j in locals()['.internals']['.8']:",
            "            continue",
            "            break",
            "            while True:",
            "                pass",
            "            def func():",
            "                pass",
            "            for k in range(7):",
            "                pass",
            "            print('hi')",
        ],
        [
            None,
            None,
            2,
            None,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            None,
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
        ],
    )
    ## no adjustments ##
    assert loop_adjust(block[6:], indexes[6:], block[1:], *(1, length)) == (
        [
            "    def func():",
            "        pass",
            "    for k in range(7):",
            "        pass",
            "    print('hi')",
            "    for j in locals()['.internals']['.8']:",
            "        continue",
            "        break",
            "        while True:",
            "            pass",
            "        def func():",
            "            pass",
            "        for k in range(7):",
            "            pass",
            "        print('hi')",
        ],
        [6, 7, 8, 9, 10, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    )


def test_yield_adjust() -> None:

    assert yield_adjust("yield 3", "") == ["return 3"]

    assert yield_adjust("yield from range(3)", "") == [
        "locals()['.internals']['.0']=locals()['.internals']['.yieldfrom']=iter(range(3))",
        "for locals()['.internals']['.i'] in locals()['.internals']['.yieldfrom']:",
        "    return locals()['.internals']['.i']",
        "    if locals()['.internals']['.send']:",
        "        return locals()['.internals']['.yieldfrom'].send(locals()['.internals']['.send'])",
    ]


def test_get_loops() -> None:
    assert get_loops(3, [(1, 5), (2, 4), (6, 8)]) == [(0, 4), (1, 3)]


def test_extract_source_from_comparison() -> None:
    ## lambda extractor ##
    code_obj = eval("lambda x: print('hi')").__code__
    source = "lambda x:x,lambda y:lambda z:z, lambda a:a, lambda x: print('hi')"
    assert extract_source_from_comparison(code_obj, source, extract_lambda) == "lambda x: print('hi')"
    ## genexpr extractor ##
    code_obj = eval("(i for i \\\n   in range(3))").gi_code
    source = "iter1, iter2 = (i for i in range(3)), (j for j in (i for i in range(5)) if j in (i for i in range(2)) )"
    assert extract_source_from_comparison(code_obj, source, extract_genexpr) == "(i for i in range(3))"
    ## function extractor ##
    def test():
        print(1)
        return 1
    code_obj = test.__code__
    source = """
    def test():
        print(2)
        return 2
    def test():
        print(1)
        return 1"""
    args = (code_obj, 
        source, 
        extract_function, 
        test.__globals__, 
        {}, 
        "exec")
    assert extract_source_from_comparison(*args) == """def test():
    print(2)
    return 2"""
    assert extract_source_from_comparison(*args, strictness=2) == """def test():
    print(1)
    return 1"""
    ## make sure strictness is validated ##
    def test(error: Exception, *args, strictness: int) -> None:
        try:
            extract_source_from_comparison(*args, strictness=strictness)
        except error:
            return
        raise AssertionError("Error %s not raised for strictness %s" % (error, strictness))
    ## negative value, zero, non-integer, exceeding value ##
    cases = ((ValueError, -1),(ValueError, 0),(Exception, 0.4),(Exception, 3))
    for error, strict in cases:
        test(error, *args, strictness=strict)


def test_expr_getsource() -> None:
    ## simple function ##
    a, b = lambda x: x, (i for i in range(3))
    assert expr_getsource(a) == "lambda x: x"
    assert expr_getsource(b) == "(i for i in range(3))"

    ## closure ##
    def test():
        j = 3
        f = lambda: j
        
        yield f
        f = (j for i in range(3))
        yield f
        f = (f for i in range(3))
        yield f
    gen = test()
    assert expr_getsource(next(gen)) == "lambda: j"
    assert expr_getsource(next(gen)) == "(j for i in range(3))"
    assert expr_getsource(next(gen)) == "(f for i in range(3))"
    ## functions (test is sensitive to indentations) ##
    assert expr_getsource(test) == """def test():
    j = 3
    f = lambda: j
    yield f
    f = (j for i in range(3))
    yield f
    f = (f for i in range(3))
    yield f"""


def test_extract_genexpr() -> None:
    source = "iter1, iter2 = (i for i in range(3)), (j for j in (i for i in range(5)) if j in (i for i in range(2)) )"
    pos = [(15, 36), (50, 71), (80, 101), (38, 103)]
    for offsets in extract_genexpr(source):
        assert offsets == pos.pop(0)
    source = "((i,j) for i in range(3) for j in range(2))"
    assert next(extract_genexpr(source)) == (0, 43)


def test_extract_lambda() -> None:
    source = "lambda x:x,lambda y:lambda z:z, lambda a:a, lambda: j"
    pos = [(0, 10), (20, 30), (11, 30), (32, 42), (44, None)]
    for index, offsets in enumerate(extract_lambda(source)):
        try:
            assert offsets == pos.pop(0)
        except AssertionError:
            print(index, offsets, pos)


def test_end_offset_adjust() -> int:
    cases = [
        ("yield 1\n", 2),
        ("yield 1\n\ng    ", 8),
    ]
    for case, expected in cases:
        assert end_offset_adjust(case) == expected
    try:
        end_offset_adjust("yield 1")
        assert False
    except ValueError:
        pass


def test_extract_function() -> None:

    def test(source: str, offsets: list[tuple[int, int]]) -> None:
        for offset in extract_function(source):
            assert offset == offsets.pop(0)

    ## test with functions close to each other and with inner functions ##
    source = """
print()

def func(): pass
def k():
    pass
pritn()
def j(): pass
def t():
    def a():
        def b():
            pass
"""
    offsets = [
        ## first test ##
        (9, 26),
        (26, 44),
        (52, 66),
        (88, None),
        (75, None),
        (66, None),
        ## second test ##
        (0, 167),
        (454, None),
        ## third test ##
        (0, 82),
        (82, 95),
        (101, 130),
        (131, None),
        ## fourth test ##
        (0, 43),
        (43, 93),
        (93, 136),
        (136, None),
    ]
    test(source, offsets)
    ## variety test ##
    source = """    def test():
        j = 3
        f = lambda: j
        yield f
        f = (j for i in range(3))
        yield f
        f = (f for i in range(3))
        yield f

    gen = test()
    assert expr_getsource(next(gen)) == "lambda: j"
    assert expr_getsource(next(gen)) == "(j for i in range(3))"
    assert expr_getsource(next(gen)) == "(f for i in range(3))"
    ## functions ##
    print("--------------------")
    print(expr_getsource(test))



def test_extract_genexpr() -> None:
    source = "iter1, iter2 = (i for i in range(3)), (j for j in (i for i in range(5)) if j in (i for i in range(2)) )"    pos = [(15, 36), (50, 71), (80, 101), (38, 103)]"""
    test(source, offsets)
    ## testing gaps, spacing, and single line functions ##
    source = """
                def a():



                    #pass
                    gen = 3
def b():pass






def c(): pass;pass;    pass;

def d():
    pass;pass
"""
    test(source, offsets)
    ## testing strings ##
    source = '''
    def a(): """docstring""""string"; pass
    def b():
        """docstring"""
        pass
    def a(): ''\'docstring''\''string'; pass
    def b():
        ''\'docstring''\'
        pass
'''
    test(source, offsets)


def test_except_adjust() -> None:
    result = except_adjust(
        ["try:", "    pass"],
        [
            "return value",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "except locals()['.internals']['.args'].pop():",
    )
    answer = """try:
    try:
        pass
    except:
        locals()['.internals']['.error'] = locals()['.internals']['exc_info']()[1]
    return value
    locals()['.internals']['.args'] += [locals()['.internals']['.send']]
    if locals()['.internals']['.catch_errors'](locals()['.internals']['.error'], locals()['.internals']['.args'].pop()):
        locals()['.continue_error'] = False"""
    assert "\n".join(result[0]) == answer
    assert result[1] == 0


def test_extract_as() -> None:
    assert extract_as("except Exception as e:") == ("except Exception", "e:")


def test_except_catch_adjust() -> None:
    reference = [
        '        a',
        '        b',
        '        c',
        "        if locals()['.internals']['.catch_errors'](locals()['.internals']['.error'], Exception):",
        "            locals()['.continue_error'] = False",
        "            e = locals()['.internals']['.error']"
        ]
    ## with as keyword and multiple lines ##
    assert except_catch_adjust("    except Exception as e:", ["a","b","c"]) == reference
    ## exception groups ##
    if version_info >= (3, 11):
        assert except_catch_adjust("    except* Exception as e :", ["a","b","c"]) == reference
    reference.pop()
    ## without as keyword ##
    assert except_catch_adjust("    except Exception:", ["a","b","c"]) == reference
    ## without multiple lines ##
    assert except_catch_adjust("    except Exception:", []) == reference[3:]


def test_singly_space() -> None:
    line, source, indented, space = "    for i in [1    , 3  , 5]:  ", "", False, -1
    for index, char in enumerate(line):
        if char == " ":
            source, index, indented = singly_space(index, char, source, space, indented)
            space = index
        else:
            source += char

    assert source == "    for i in [1 , 3 , 5]: "


def test_outer_loop_adjust() -> None:
    source_lines = [
        "    for i in range(3):",
        "        print(i)",
        "        for j in range(4):",
        "            print(j)",
        "            for k in range(4):",
        "                print(k)",
        "            print(j)",
        "        print(i)",
    ]
    ## are in linenos ##
    length = len(source_lines) - 1
    loops = [(2 * i, length - i) for i in range(0, 3)]
    end_pos = loops[-1][1]
    assert outer_loop_adjust([], [], source_lines, loops, end_pos) == (
        [
            "    for k in locals()['.internals']['.12']:",
            "        print(k)",
            "    for j in locals()['.internals']['.8']:",
            "        print(j)",
            "        for k in range(4):",
            "            print(k)",
            "        print(j)",
            "    for i in locals()['.internals']['.4']:",
            "        print(i)",
            "        for j in range(4):",
            "            print(j)",
            "            for k in range(4):",
            "                print(k)",
            "            print(j)",
            "        print(i)",
        ],
        [4, 5, 2, 3, 4, 5, 6, 0, 1, 2, 3, 4, 5, 6, 7],
    )

    ## case needs testing ##
    assert outer_loop_adjust(
        [],
        [],
        [
            "    for i in range(3):",
            "        for j in range(2):",
            "            return (i,j)",
        ],
        [(0, 2), (1, 2)],
        2,
    ) == (
        [
            "    for j in locals()['.internals']['.8']:",
            "        return (i,j)",
            "    for i in locals()['.internals']['.4']:",
            "        for j in range(2):",
            "            return (i,j)",
        ],
        [1, 2, 0, 1, 2],
    )


def test_setup_next_line() -> None:
    self = type("", tuple(), {})()

    def test(*args, expected=None):
        setup_next_line(self, *args)

        assert (self.line, self.indented) == expected

    test(":", 1, expected=(" ", True))
    test(";", 1, expected=(" ", True))
    test("\n", expected=("", False))


def test_unpack_lambda() -> None:
    assert unpack_lambda("lambda x: x") == [" x"]


def test_get_signature() -> None:
    assert get_signature("def func():") == "func"
    assert get_signature("def func():", True) == ("func", "")
    assert get_signature("def func(*args, **kwargs):", True) == (
        "func",
        "*args, **kwargs",
    )


def test_collect_lambda() -> None:
    def test(source: str) -> None:
        line = "lambda "
        left = source[len(line) :]
        return collect_lambda(line, enumerate(left, start=len(line)), source, (0, 0, ""), len(line))

    assert test("lambda x: x") == ([], "lambda x: x", 0, "x")
    assert test("lambda x=(yield): (yield)") == (
        [
            "return",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "lambda x=locals()['.internals']['.args'].pop(): (yield)",
        0,
        ")",
    )

    assert test("lambda x=(yield), y = (yield): (yield)") == (
        [
            "return",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
            "return",
            "locals()['.internals']['.args'] += [locals()['.internals']['.send']]",
        ],
        "lambda x=locals()['.internals']['.args'].pop(), y = locals()['.internals']['.args'].pop(): (yield)",
        0,
        ")",
    )


def test_sign() -> None:
    from gcopy.custom_generator import Generator

    def test(*args, a=True):
        """docstring"""
        pass

    gen = Generator()
    f = sign(gen.__call__, test)
    assert f.__name__ == test.__name__
    assert signature(f) == signature(test)
    assert f.__doc__ == test.__doc__
    assert f.__annotations__ == test.__annotations__


