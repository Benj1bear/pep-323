from gcopy.track import *
import asyncio


def iter_init(obj: Iterable | Iterator) -> Iterable:
    """Initializes iterators (for testing)"""
    if obj.__name__ in ("memoryview",):
        return iter(obj(b"abcedfg"))
    elif obj.__name__ in ("enumerate", "reversed"):
        return iter(obj([]))
    elif obj.__name__ == "range":
        return iter(obj(2))
    elif obj.__name__ in ("zip", "filter", "map"):
        return iter(obj([], []))
    else:
        return iter(obj())


def test_track_adjust() -> None:
    dct = {".mapping": [34, 35, 74], ".34": None, ".35": None, ".74": None}
    assert track_adjust(dct)
    assert list(dct.keys()) == [".4", ".8", ".12"]


def test_track_shift() -> None:
    def test():
        pass

    dct = dict.fromkeys([".%s" % i for i in range(8, 20, 4)])
    track_shift(test, dct)
    assert list(dct.keys()) == [".4", ".8", ".12"]


def test_patch_iterators() -> None:
    patch_iterators(globals())
    iterators = get_builtin_iterators()
    for name in iterators:
        assert type(globals()[name]) == track
    ## unpatch the iters ##
    unpatch_iterators(globals())
    for name in iterators:
        assert globals().get(name, None) is None
    ## try in local scope only ##


def test_track_iter() -> None:
    patch_iterators(globals())
    ## range iterators (uses hook) ##
    for i in range(3):
        for j in range(3):
            for k in range(3):
                pass
    test = (
        lambda key, value: currentframe()
        .f_back.f_locals[".internals"][".%s" % key]
        .__repr__()[1:]
        .split()[0]
        == value
    )
    assert test(4, "range_iterator")
    assert test(8, "range_iterator")
    ## other iterators (doesn't use hook) ##
    for i in list([1, 2, 3]):
        for j in track([1, 2, 3]):
            pass
    assert test(4, "list_iterator")
    assert test(8, "list_iterator")


def test_track_iter_inside_exec() -> None:
    FUNC_code = compile(
        """def test():
    for i in range(3):
         return locals()[".internals"][".0"]
""",
        currentframe().f_code.co_filename,
        "exec",
    )
    exec(FUNC_code, globals(), locals())
    range_iterator = locals()["test"]()
    assert [i for i in range_iterator] == [1, 2]


def test_track_iter_inside_Generator() -> None:

    from gcopy.custom_generator import Generator

    @Generator
    def test2():
        for i in range(3):
            yield i

    gen = test2()
    next(gen)
    gen2 = gen.copy()
    assert next(gen._locals()[".internals"][".4"]) == 1
    assert next(gen2._locals()[".internals"][".4"]) == 1


def test_track() -> None:
    iter(track([1, 2, 3]))
    assert [i for i in locals()[".internals"][".4"]] == [1, 2, 3]


async def test_atrack() -> None:
    async def iterator():
        yield 1
        yield 2
        yield 3

    assert [i async for i in atrack(iterator())] == [1, 2, 3]
    aiter(atrack(iterator()))
    assert [i async for i in locals()[".internals"][".4"]] == [1, 2, 3]


test_track_adjust()
test_track_shift()
test_patch_iterators()
test_track_iter()
test_track_iter_inside_exec()
test_track_iter_inside_Generator()
test_track()
asyncio.run(test_atrack())
