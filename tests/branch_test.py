import pytest
import ast
import slipcover.branch as br


def ast_parse(s):
    import inspect
    return ast.parse(inspect.cleandoc(s))


def get_branches_from_ast(tree: ast.AST) -> list:   # TODO this is unused, remove me
    """Returns the set of tuples (from_line, to_line) with branches inserted by *br.preinstrument*."""

    class BranchFinder(ast.NodeVisitor):
        def __init__(self):
            self._branches = set()

        def get_branches(self):
            return self._branches

        def visit_Assign(self, node: ast.Assign):
            if len(node.targets) == 1 and \
               isinstance(node.targets[0], ast.Name) and\
               node.targets[0].id.startswith(br.BRANCH_PREFIX):
                assert isinstance(node.value, ast.Tuple)
                assert 2 == len(node.value.elts)
                self._branches.add((node.value.elts[0].value, node.value.elts[1].value))

    bf = BranchFinder()
    bf.visit(tree)
    return sorted(list(bf.get_branches()))


def get_branches(code):
    import slipcover.bytecode as bc
    import types

    branches = []

    # handle functions-within-functions
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            branches.extend(get_branches(c))

    ed = bc.Editor(code)
    for _, _, br_index in ed.find_const_assignments(br.BRANCH_PREFIX):
        branches.append(code.co_consts[br_index])

    return sorted(branches)


def test_if():
    t = ast_parse("""
        if x == 0:
            x += 2

        x += 3
    """)

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,2), (1,4)] == get_branches(code)

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

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,2), (1,6)] == get_branches(code)

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

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,0), (1,2)] == get_branches(code)

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

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(1,2), (1,7), (3,4), (3,11), (4,5), (4,11), (8,9), (8,10)] == get_branches(code)

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

    t = br.preinstrument(t)
    code = compile(t, "foo", "exec")
    assert [(2,0), (2,3), (6,0), (6,7), (11,0), (11,12)] == get_branches(code)

    g = dict()
    exec(code, g, g)
    assert 'slipcover_branch_2_0' in g

# TODO add For, While
