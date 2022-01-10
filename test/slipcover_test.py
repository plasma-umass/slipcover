import pytest
from slipcover import slipcover as sc


def current_line():
    import inspect as i
    return i.getframeinfo(i.currentframe().f_back).lineno

def current_file():
    import inspect as i
    return i.getframeinfo(i.currentframe().f_back).filename


@pytest.fixture(autouse=True)
def clear_slipcover():
    # XXX have slipcover use an object, so that it's destroyed and this isn't needed?
    sc.clear()


def test_instrument():
    first_line = current_line()+2
    def foo(n):
        x = 0
        for i in range(n):
            x += (i+1)
        return x
    last_line = current_line()

    sc.instrument(foo)
    assert 6 == foo(3)

    assert {current_file(): {*range(first_line, last_line)}} == sc.get_coverage()


@pytest.mark.parametrize("N", [0, 20, 256, 512, 4096])#, 8192, 65536, 131072])
def test_instrument_long_jump(N):
    first_line = current_line()+2
    src = "x = 0\n" + "x += 1\n" * N 

    code = compile(src, "foo", "exec")
    code = sc.instrument(code)
    exec(code, locals(), globals())
    assert N == x
    assert {"foo": {*range(1, 1+N+1)}} == sc.get_coverage()


def test_deinstrument():
    first_line = current_line()+2
    def foo(n):
        x = 0
        for i in range(n):
            x += (i+1)
        return x
    last_line = current_line()

    assert not sc.get_coverage()

    sc.instrument(foo)
    sc.deinstrument(foo, {*range(first_line, last_line)})
    assert 6 == foo(3)
    assert not sc.get_coverage()


def test_deinstrument_some():
    first_line = current_line()+2
    def foo(n):
        x = 0
        for i in range(n):
            x += (i+1)
        return x
    last_line = current_line()

    assert not sc.get_coverage()

    sc.instrument(foo)
    sc.deinstrument(foo, {first_line, last_line-1})

    assert 6 == foo(3)
    assert {current_file(): {*range(first_line+1, last_line-1)}} == sc.get_coverage()


@pytest.mark.parametrize("N", [0, 20, 256, 512, 4096])#, 8192, 65536, 131072])
def test_deinstrument_long_jump(N):
    first_line = current_line()+2
    src = "x = 0\n" + "x += 1\n" * N 

    code = compile(src, "foo", "exec")
    code = sc.instrument(code)
    code = sc.deinstrument(code, {*range(1, 1+N+1)})
    exec(code, locals(), globals())
    assert N == x
    assert not sc.get_coverage()
