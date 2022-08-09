def foo(n):
    r = 0
    if n >= 0:
        for i in range(1, n+1):
            r += i
    return r

def test_some():
    assert 0 == foo(0)
    assert 1 == foo(1)
    assert 6 == foo(3)

def test_some_more():
    assert 10 == foo(4)
