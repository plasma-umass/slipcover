import ast

BRANCH_NAME = "_slipcover_branches"

def preinstrument(tree: ast.AST) -> ast.AST:
    """Prepares an AST for Slipcover instrumentation, inserting assignments indicating where branches happen."""

    class SlipcoverTransformer(ast.NodeTransformer):
        def __init__(self):
            pass

        def _mark_branch(self, from_line: int, to_line: int) -> ast.AST:
            mark = ast.Assign([ast.Name(BRANCH_NAME, ast.Store())],
                               ast.Tuple([ast.Constant(from_line), ast.Constant(to_line)], ast.Load()))

            for node in ast.walk(mark):
                node.lineno = 0 # we ignore line 0, so this avoids generating line trackers

            return [mark]

        def visit_FunctionDef(self, node: ast.AST) -> ast.AST:
            # Mark BRANCH_NAME global, so that our assignment are easier to find (only STORE_NAME/STORE_GLOBAL,
            # but not STORE_FAST, etc.)
            node.body.insert(0, ast.Global([BRANCH_NAME]))
            super().generic_visit(node)
            return node

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
            return self.visit_FunctionDef(node)

        def _mark_branches(self, node: ast.AST) -> ast.AST:
            node.body = self._mark_branch(node.lineno, node.body[0].lineno) + node.body

            if node.orelse:
                node.orelse = self._mark_branch(node.lineno, node.orelse[0].lineno) + node.orelse
            else:
                to_line = node.next_node.lineno if node.next_node else 0 # exit
                node.orelse = self._mark_branch(node.lineno, to_line)

            super().generic_visit(node)
            return node

        def visit_If(self, node: ast.If) -> ast.If:
            return self._mark_branches(node)

        def visit_For(self, node: ast.For) -> ast.For:
            return self._mark_branches(node)

        def visit_While(self, node: ast.While) -> ast.While:
            return self._mark_branches(node)

    # Compute the "next" statement in case a branch flows control out of a node.
    tree.next_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            # no next node, yields (..., 0), i.e., "->exit" branch
            node.next_node = None

        for name, field in ast.iter_fields(node):
            if isinstance(field, ast.AST):
                # if a field is just a node, any execution continues after our node
                field.next_node = node.next_node
            elif isinstance(field, list):
                # if a field is a list, each item but the last one continues with the next item
                prev = None
                for item in field:
                    if isinstance(item, ast.AST):
                        if prev:
                            prev.next_node = item
                        prev = item
                if prev:
                    if isinstance(node, ast.For) or isinstance(node, ast.While):
                        prev.next_node = node
                    else:
                        prev.next_node = node.next_node

    tree = SlipcoverTransformer().visit(tree)
    ast.fix_missing_locations(tree)
    return tree
