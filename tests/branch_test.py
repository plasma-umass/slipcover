import pytest
import ast
import slipcover.branch


def ast_parse(s):
    import inspect
    return ast.parse(inspect.cleandoc(s))


def test_if():
    t = ast_parse("""
        if x == 0:
            x += 2

        x += 3
    """)

    t, branches = slipcover.branch.preinstrument(t)

    assert [(1,2), (1,4)] == sorted(list(branches))

    code = compile(t, "foo", "exec")

    g = {'x': 0}
    exec(code, g, g)
    assert 5 == g['x']
    assert 'slipcover_branch_1_2' in g

    g = {'x': 1}
    exec(code, g, g)
    assert 4 == g['x']
    assert 'slipcover_branch_1_4' in g


def test_if_else():
    t = ast_parse("""
        if x == 0:
            x += 1

        else:

            x += 2

        x += 3
    """)

    t, branches = slipcover.branch.preinstrument(t)

    assert [(1,2), (1,6)] == sorted(list(branches))

    code = compile(t, "foo", "exec")

    g = {'x': 0}
    exec(code, g, g)
    assert 4 == g['x']
    assert 'slipcover_branch_1_2' in g

    g = {'x': 1}
    exec(code, g, g)
    assert 6 == g['x']
    assert 'slipcover_branch_1_6' in g


def test_if_nothing_after_it():
    t = ast_parse("""
        if x == 0:
            x += 1

    """)

    t, branches = slipcover.branch.preinstrument(t)

    assert [(1, 0), (1, 2)] == sorted(list(branches))

    code = compile(t, "foo", "exec")

    g = {'x': 0}
    exec(code, g, g)
    assert 1 == g['x']
    assert 'slipcover_branch_1_2' in g

    g = {'x': 3}
    exec(code, g, g)
    assert 3 == g['x']
    assert 'slipcover_branch_1_0' in g


def test_if_nested():
    t = ast_parse("""
        if x >= 0:
            y = 1
            if x > 1:
                if x > 2:
                    y = 2
        else:
            y = 4
            if x < 1:
                y = 3
            y += 10
        z = 0
    """)

    t, branches = slipcover.branch.preinstrument(t)

    assert [(1,2), (1,7), (3,4), (3,11), (4,5), (4,11), (8,9), (8,10)] == sorted(list(branches))

    code = compile(t, "foo", "exec")

    g = {'x': 0}
    exec(code, g, g)
    assert 1 == g['y']
    assert 0 == g['z']
    assert 'slipcover_branch_1_2' in g
    assert 'slipcover_branch_3_11' in g

    g = {'x': 3}
    exec(code, g, g)
    assert 2 == g['y']
    assert 0 == g['z']
    assert 'slipcover_branch_1_2' in g
    assert 'slipcover_branch_3_4' in g
    assert 'slipcover_branch_4_5' in g


def test_if_in_function():
    t = ast_parse("""
        def foo(x):
            if x >= 0:
                return 1

        async def bar(x):
            if x == 0:
                return 1

        class Foo:
            def __init__(self, x):
                if x == 0:
                    self.x = 0

        foo(-1)
    """)

    t, branches = slipcover.branch.preinstrument(t)

    assert [(2,0), (2,3), (6,0), (6,7), (11,0), (11,12)] == sorted(list(branches))

    code = compile(t, "foo", "exec")
    import dis
    dis.dis(code)

    g = dict()
    exec(code, g, g)
    assert 'slipcover_branch_2_0' in g

# TODO add For, While
