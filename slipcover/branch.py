import ast

"""Part of preinstrument's implementation."""
class SlipcoverTransformer(ast.NodeTransformer):
    def __init__(self):
        self._branches = set()


    def get_branches(self):
        return self._branches


    def _mark_branch(self, from_line: int, to_line: int) -> ast.AST:
        self._branches.add((from_line, to_line))
        name = 'slipcover_branch_' + str(from_line) + "_" + str(to_line)
        # Mark the "variables" indicating the branches as global, so that they always
        # yield a STORE_NAME (rather than, for example, STORE_FAST)
        return [ast.Global([name]),
                ast.Assign([ast.Name(name, ast.Store())],
                          ast.Tuple([ast.Constant(from_line), ast.Constant(to_line)], ast.Load()))]


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
    # TODO handle IfExp


def preinstrument(tree: ast.AST) -> (ast.AST, set):
    """Prepares an AST for Slipcover instrumentation, inserting assignments indicating where branches happen,
       and also computes a set with all possible branches."""
    tf = SlipcoverTransformer()

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

    tree = tf.visit(tree)
    ast.fix_missing_locations(tree)
    return (tree, tf.get_branches())
