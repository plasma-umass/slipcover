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

    lines_seen = sc.get_coverage()
    assert set(range(first_line, last_line)) == lines_seen[current_file()]


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
    sc.deinstrument(foo, set(range(first_line, last_line)))
    assert 6 == foo(3)

    assert not sc.get_coverage()
