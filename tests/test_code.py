import pytest

from gcopy.my_copy import Code


def my_generator(a):
    a = a + 2
    yield a
    while True:
        a += 1
        yield a
        a += 2


@pytest.fixture
def code1():
    t1 = my_generator(10)
    code = Code.from_generator(t1)
    return code


def test_from_ge(code1):
    assert code1.lines[0] == "def my_generator(a):"
    assert code1.lines[0:1] == ["def my_generator(a):"]


def test_lines(code1):
    print(code1)
    assert len(code1.lines) == 7 + 1


def test_line_running(code1):
    assert code1.running_line == 0
    assert code1.running_line_txt == "def my_generator(a):"
    next(code1)
    assert code1.running_line == 2
    assert code1.running_line_txt == "    yield a"
    next(code1)
    assert code1.running_line == 5


def test_running_level(code1):
    assert code1.running_level == 0
    next(code1)
    assert code1.running_level == 1
    next(code1)
    assert code1.running_level == 2


def test_block(code1):
    assert code1.block == "root"
    next(code1)
    assert code1.block == "root"
    next(code1)
    assert code1.block == "while"
    assert (
        "".join(code1.block_text.code)
        == "    while True:\n        a += 1\n        yield a\n        a += 2"
    )


def my_generator2():
    a = 1
    b = 2
    c = 3
    if a:
        b += 1
        yield a
        if b:
            yield a + 1
            if c:
                print("hello")
            else:
                while True:
                    a += 5
                    yield a
                    a += 2
