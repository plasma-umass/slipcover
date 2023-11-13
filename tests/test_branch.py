import pytest
import ast
import slipcover.branch as br
import sys


PYTHON_VERSION = sys.version_info[0:2]

def ast_parse(s):
    import inspect
    return ast.parse(inspect.cleandoc(s))


def get_branches(code):
    from slipcover.slipcover import Slipcover
    return sorted(Slipcover.branches_from_code(code))


def assign2append(tree: ast.AST):
    """Converts our assign-based markup to appends, so that tests can check for branches detected."""
    class a2av(ast.NodeTransformer):
        def __init__(self):
            pass

        def visit_Assign(self, node: ast.Assign) -> ast.Assign:
            if node.targets and isinstance(node.targets[0], ast.Name) \
               and node.targets[0].id == br.BRANCH_NAME:
                return ast.AugAssign(
                        target=node.targets[0],
                        op=ast.Add(),
                        value=ast.List(elts=[node.value], ctx=ast.Load()),
                        ctx=ast.Load())

            return node

    tree = a2av().visit(tree)
    ast.fix_missing_locations(tree)
    return tree


def test_if():
    t = ast_parse("""
        if x == 0:
            x += 2

        x += 3
    """)

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,2), (1,4)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 5 == g['x']
    assert [(1,2)] == g[br.BRANCH_NAME]

    g = {'x': 1, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 4 == g['x']
    assert [(1,4)] == g[br.BRANCH_NAME]


def test_if_else():
    t = ast_parse("""
        if x == 0:
            x += 1

        else:

            x += 2

        x += 3
    """)

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,2), (1,6)] == get_branches(code)


    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 4 == g['x']
    assert [(1,2)] == g[br.BRANCH_NAME]

    g = {'x': 1, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 6 == g['x']
    assert [(1,6)] == g[br.BRANCH_NAME]


def test_if_elif_else():
    t = ast_parse("""
        if x == 0:
            x += 1
        elif x == 1:
            x += 2
        else:
            x += 3

        x += 3
    """)

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,2), (1,3), (3,4), (3,6)] == get_branches(code)


    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 1, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 6 == g['x']
    assert [(1,3), (3,4)] == g[br.BRANCH_NAME]


def test_if_nothing_after_it():
    t = ast_parse("""
        if x == 0:
            x += 1

    """)

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,0), (1,2)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 1 == g['x']
    assert [(1,2)] == g[br.BRANCH_NAME]

    g = {'x': 3, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 3 == g['x']
    assert [(1,0)] == g[br.BRANCH_NAME]


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

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,2), (1,7), (3,4), (3,11), (4,5), (4,11), (8,9), (8,10)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 1 == g['y']
    assert 0 == g['z']
    assert [(1,2), (3,11)] == g[br.BRANCH_NAME]

    g = {'x': 3, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 2 == g['y']
    assert 0 == g['z']
    assert [(1,2), (3,4), (4,5)] == g[br.BRANCH_NAME]


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

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(2,0), (2,3), (6,0), (6,7), (11,0), (11,12)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {br.BRANCH_NAME: []}
    exec(code, g, g)
    assert [(2,0)] == g[br.BRANCH_NAME]


def test_keep_docstrings():
    t = ast_parse("""
        def foo(x):
            \"\"\"foo something\"\"\"
            if x >= 0:
                return 1

        async def bar(x):
            \"\"\"bar something\"\"\"
            if x == 0:
                return 1

        class Foo:
            \"\"\"Foo something\"\"\"
            def __init__(self, x):
                if x == 0:
                    self.x = 0

        foo(-1)
    """)
#    print(ast.dump(t, indent=True))

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(3,0), (3,4), (8,0), (8,9), (14,0), (14,15)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {br.BRANCH_NAME: []}
    exec(code, g, g)

    assert 'foo something' == g['foo'].__doc__
    assert 'bar something' == g['bar'].__doc__
    assert 'Foo something' == g['Foo'].__doc__


def test_for():
    t = ast_parse("""
        for v in [1, 2]:
            if v > 0:
                x += v

        x += 3
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,2), (1,5), (2,1), (2,3)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 6 == g['x']
    assert [(1,2), (2,3), (1,2), (2,3), (1,5)] == g[br.BRANCH_NAME]


def test_async_for():
    t = ast_parse("""
        import asyncio

        async def fun():
            global x

            async def g():
                yield 1
                yield 2

            async for v in g(): #10
                if v > 0:
                    x += v
            x += 3

        asyncio.run(fun())
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(10,11), (10,13), (11,12), (11,13)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 6 == g['x']
    assert [(10,11), (11,12), (10,11), (11,12), (10,13)] == g[br.BRANCH_NAME]


def test_for_else():
    t = ast_parse("""
        for v in [1, 2]:
            if v > 0:
                x += v
        else:
            x += 3
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,2), (1,5), (2,1), (2,3)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 6 == g['x']
    assert [(1,2), (2,3), (1,2), (2,3), (1,5)] == g[br.BRANCH_NAME]


def test_for_break_else():
    t = ast_parse("""
        for v in [1, 2]:
            if v > 0:
                x += v
            break
        else:
            x += 3
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,2), (1,6), (2,3), (2,4)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 1 == g['x']
    assert [(1,2), (2,3)] == g[br.BRANCH_NAME]


def test_while():
    t = ast_parse("""
        v = 2
        while v > 0:
            v -= 1
            if v > 0:
                x += v

        x += 3
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(2,3), (2,7), (4,2), (4,5)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 4 == g['x']
    assert [(2,3), (4,5), (2,3), (4,2), (2,7)] == g[br.BRANCH_NAME]


def test_while_else():
    t = ast_parse("""
        v = 2
        while v > 0:
            v -= 1
            if v > 0:
                x += v
        else:
            x += 3
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(2,3), (2,7), (4,2), (4,5)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 4 == g['x']
    assert [(2,3), (4,5), (2,3), (4,2), (2,7)] == g[br.BRANCH_NAME]


def test_while_break_else():
    t = ast_parse("""
        v = 2
        while v > 0:
            v -= 1
            if v > 0:
                x += v
            break
        else:
            x += 3
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(2,3), (2,8), (4,5), (4,6)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 1 == g['x']
    assert [(2,3), (4,5)] == g[br.BRANCH_NAME]


@pytest.mark.skipif(PYTHON_VERSION < (3,10), reason="New in 3.10")
def test_match():
    t = ast_parse("""
        v = 2
        match v:
            case 1:
                x = 1
            case 2:
                x = 2
        x += 2
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(2,4), (2,6), (2,7)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 4 == g['x']
    assert [(2,6)] == g[br.BRANCH_NAME]


@pytest.mark.skipif(PYTHON_VERSION < (3,10), reason="New in 3.10")
def test_match_case_with_false_guard():
    t = ast_parse("""
        x = 0
        v = 2
        match v:
            case 1 if x > 0:
                x = 1
            case 2:
                x = 2
        x += 2
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(3,5), (3,7), (3,8)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {br.BRANCH_NAME: []}
    exec(code, g, g)
    assert [(3,7)] == g[br.BRANCH_NAME]


@pytest.mark.skipif(PYTHON_VERSION < (3,10), reason="New in 3.10")
def test_match_branch_to_exit():
    t = ast_parse("""
        v = 5
        match v:
            case 1:
                x = 1
            case 2:
                x = 2
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(2,0), (2,4), (2,6)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {br.BRANCH_NAME: []}
    exec(code, g, g)
    assert [(2,0)] == g[br.BRANCH_NAME]


@pytest.mark.skipif(PYTHON_VERSION < (3,10), reason="New in 3.10")
def test_match_default():
    t = ast_parse("""
        v = 5
        match v:
            case 1:
                x = 1
            case 2:
                x = 2
            case _:
                x = 3
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(2,4), (2,6), (2,8)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 3 == g['x']
    assert [(2,8)] == g[br.BRANCH_NAME]


@pytest.mark.skipif(PYTHON_VERSION < (3,10), reason="New in 3.10")
def test_branch_after_case():
    t = ast_parse("""
        v = 1
        match v:
            case 1:
                if x < 0:  #4
                    x = 1
            case 2:
                if x < 0:  #7
                    x = 1
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(2,0), (2,4), (2,7), (4,0), (4,5), (7,0), (7,8)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 0 == g['x']
    assert [(2,4), (4,0)] == g[br.BRANCH_NAME]


@pytest.mark.skipif(PYTHON_VERSION < (3,10), reason="New in 3.10")
def test_branch_after_case_with_default():
    t = ast_parse("""
        v = 1
        match v:
            case 1:
                if x < 0:  #4
                    x = 1
            case 2:
                if x < 0:  #7
                    x = 1
            case _:
                if x < 0:  #10
                    x = 1
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(2,4), (2,7), (2,10), (4,0), (4,5), (7,0), (7,8), (10,0), (10,11)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 0 == g['x']
    assert [(2,4), (4,0)] == g[br.BRANCH_NAME]


@pytest.mark.skipif(PYTHON_VERSION < (3,10), reason="New in 3.10")
def test_branch_after_case_with_next():
    t = ast_parse("""
        v = 1
        match v:
            case 1:
                if x < 0:  #4
                    x = 1
            case 2:
                if x < 0:  #7
                    x = 1
        x += 1
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(2,4), (2,7), (2,9), (4,5), (4,9), (7,8), (7,9)] == get_branches(code)

    t = assign2append(t)
    code = compile(t, "foo", "exec")

    g = {'x': 0, br.BRANCH_NAME: []}
    exec(code, g, g)
    assert 1 == g['x']
    assert [(2,4), (4,9)] == g[br.BRANCH_NAME]


@pytest.mark.parametrize("star", ['', '*'] if PYTHON_VERSION >= (3,11) else [''])
def test_try_except(star):
    t = ast_parse(f"""
        def foo(x):
            try:
                y = x + 1
                if y < 0:
                    y = 0
            except{star} RuntimeException:
                if y < 2:
                    y = 0
            except{star} FileNotFoundError:
                if y < 2:
                    y = 0

            return 2*y
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(4,5), (4,13), (7,8), (7,13), (10,11), (10,13)] == get_branches(code)


def test_try_finally():
    t = ast_parse("""
        def foo(x):
            try:
                y = x + 1
                if y < 0:
                    y = 0
            finally:
                y = 2*y
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(4,5), (4,7)] == get_branches(code)


@pytest.mark.parametrize("star", ['', '*'] if PYTHON_VERSION >= (3,11) else [''])
def test_try_else(star):
    t = ast_parse(f"""
        def foo(x):
            try:
                y = x + 1
                if y < 0:
                    y = 0
            except{star} RuntimeException:
                if y < 2:
                    y = -1
            else:
                y = 2*y
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(4,5), (4,10), (7,0), (7,8)] == get_branches(code)


@pytest.mark.parametrize("star", ['', '*'] if PYTHON_VERSION >= (3,11) else [''])
def test_try_else_finally(star):
    t = ast_parse(f"""
        def foo(x):
            try:
                y = x + 1
                if y < 0:
                    y = 0
            except{star} RuntimeException:
                if y < 2:
                    y = -1
            else:
                if y > 5:
                    y = 42
            finally:
                y = 2*y
    """)


    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(4,5), (4,10), (7,8), (7,13), (10,11), (10,13)] == get_branches(code)
