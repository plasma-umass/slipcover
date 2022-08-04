import ast

BRANCH_PREFIX = "slipcover_branch_"

def preinstrument(tree: ast.AST) -> ast.AST:
    """Prepares an AST for Slipcover instrumentation, inserting assignments indicating where branches happen."""

    class SlipcoverTransformer(ast.NodeTransformer):
        def __init__(self):
            pass

        def _mark_branch(self, from_line: int, to_line: int) -> ast.AST:
            name = BRANCH_PREFIX + str(from_line) + "_" + str(to_line)
            # Mark the "variables" indicating the branches as global, so that our assignments
            # always yield STORE_NAME / STORE_GLOBAL, making them easier to find.
            br = [ast.Global([name]),
                  ast.Assign([ast.Name(name, ast.Store())],
                             ast.Tuple([ast.Constant(from_line), ast.Constant(to_line)], ast.Load()))]

            for item in br:
                for node in ast.walk(item):
                    node.lineno = 0 # we ignore line 0, so this avoids generating line trackers

            return br

        def visit_If(self, node: ast.If) -> ast.If:
            node.body = self._mark_branch(node.lineno, node.body[0].lineno) + node.body

            if node.orelse:
                node.orelse = self._mark_branch(node.lineno, node.orelse[0].lineno) + node.orelse
            else:
                to_line = node.next_node.lineno if node.next_node else 0 # exit
                node.orelse = self._mark_branch(node.lineno, to_line)

            super().generic_visit(node)
            return node

        # TODO handle For, While
        # TODO handle IfExp?

    # Compute the "next" statement in case a branch flows control out of a node.
    tree.next_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            node.next_node = None

        for name, field in ast.iter_fields(node):
            if isinstance(field, ast.AST):
                field.next_node = node.next_node
            elif isinstance(field, list):
                prev = None
                for item in field:
                    if isinstance(item, ast.AST):
                        if prev:
                            prev.next_node = item
                        prev = item
                if prev:
                    prev.next_node = node.next_node

    tree = SlipcoverTransformer().visit(tree)
    ast.fix_missing_locations(tree)
    return tree
