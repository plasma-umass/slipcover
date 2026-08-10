"""Tests for issue #26: coverage.py-style exclude_lines/pragma support.

Covers pattern-based line/block exclusion (single-line match, block-body
exclusion, decorator cascade, stacked decorators, case/match, if/try clause
boundaries), the built-in default patterns (`# pragma: no cover`,
`if TYPE_CHECKING:`), `[tool.slipcover] exclude-lines` config-file support,
and branch-data cleanup for excluded lines.
"""

import ast
import json
import subprocess
import sys
from textwrap import dedent

import pytest

import slipcover.branch as br
import slipcover.slipcover as sc


def _run(tmp_path, source, *, branch=False, exclude_lines=None):
    """Compiles, instruments, and runs a real on-disk module, returning its
    file coverage dict. A real file (not an in-memory filename) is needed
    since exclusion matching reads the source text from disk."""
    code_path = tmp_path / "target.py"
    code_path.write_text(dedent(source))

    t = ast.parse(code_path.read_text())
    if branch:
        t = br.preinstrument(t)

    sci = sc.Slipcover(branch=branch, exclude_lines=exclude_lines)
    code = compile(t, str(code_path), "exec")
    code = sci.instrument(code)

    g = dict()
    exec(code, g, g)

    cov = sci.get_coverage()
    return cov['files'][str(code_path)]


def test_default_pragma_excludes_if_block(tmp_path):
    cov = _run(tmp_path, """\
        def foo(x):
            if x < 0:  # pragma: no cover
                return -1
            return 1

        foo(1)
        """)
    assert 2 not in cov['executed_lines'] and 2 not in cov['missing_lines']
    assert 3 not in cov['executed_lines'] and 3 not in cov['missing_lines']
    assert 4 in cov['executed_lines']


def test_default_type_checking_block_excluded(tmp_path):
    cov = _run(tmp_path, """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            import os

        x = 1
        """)
    assert 3 not in cov['executed_lines'] and 3 not in cov['missing_lines']
    assert 4 not in cov['executed_lines'] and 4 not in cov['missing_lines']
    assert 6 in cov['executed_lines']


def test_custom_pattern_is_additive_to_defaults(tmp_path):
    cov = _run(tmp_path, """\
        def foo(x):
            if x < 0:  # pragma: no cover
                return 1
            if x < 0:  # custom-exclude
                return 2
            return 3

        foo(1)
        """, exclude_lines=["custom-exclude"])

    for ln in (2, 3, 4, 5):
        assert ln not in cov['executed_lines'] and ln not in cov['missing_lines']
    assert 6 in cov['executed_lines']


def test_single_line_match_excludes_only_that_line(tmp_path):
    cov = _run(tmp_path, """\
        x = 1
        y = 2  # nocov
        z = 3
        """, exclude_lines=["nocov"])

    assert 2 not in cov['executed_lines'] and 2 not in cov['missing_lines']
    assert 1 in cov['executed_lines']
    assert 3 in cov['executed_lines']


def test_block_body_excluded_for_for_loop(tmp_path):
    cov = _run(tmp_path, """\
        total = 0
        for i in range(3):  # pragma: no cover
            total += i
        print(total)
        """)
    assert 2 not in cov['executed_lines'] and 2 not in cov['missing_lines']
    assert 3 not in cov['executed_lines'] and 3 not in cov['missing_lines']
    assert 1 in cov['executed_lines']
    assert 4 in cov['executed_lines']


def test_block_body_excluded_for_nested_class_and_def(tmp_path):
    cov = _run(tmp_path, """\
        class Widget:  # pragma: no cover
            def render(self):
                return "never called"

        x = 1
        """)
    for ln in (1, 2, 3):
        assert ln not in cov['executed_lines'] and ln not in cov['missing_lines']
    assert 5 in cov['executed_lines']


def test_decorator_cascade_excludes_def_and_body(tmp_path):
    cov = _run(tmp_path, """\
        def deco(f):
            return f

        @deco
        @deco  # exclude-here
        def unused():
            return 1

        x = 2
        """, exclude_lines=["exclude-here"])

    for ln in (5, 6, 7):
        assert ln not in cov['executed_lines'] and ln not in cov['missing_lines']
    assert 1 in cov['executed_lines']  # unrelated code stays tracked
    assert 9 in cov['executed_lines']


def test_decorator_cascade_excludes_from_match_onward_only(tmp_path):
    """A decorator's own source line is never independently trackable as a
    code_line (confirmed empirically: slipcover's line tracking never
    records a distinct line for decorator application, even with two
    different decorators, not just identical ones) -- so "decorators before
    the matched one are unaffected" isn't observable through a real
    coverage run at all, and is verified directly against the excluded-line
    set instead."""
    code_path = tmp_path / "target.py"
    code_path.write_text(dedent("""\
        def deco(f):
            return f

        @deco
        @deco  # exclude-here
        def unused():
            return 1

        x = 2
        """))
    sci = sc.Slipcover(exclude_lines=["exclude-here"])
    excluded = sci._compute_excluded_lines(code_path.read_text())

    assert 4 not in excluded  # decorator preceding the match is unaffected
    assert excluded == {5, 6, 7}


@pytest.mark.skipif(sys.version_info < (3, 10), reason="match/case requires 3.10+")
def test_case_match_block_excluded(tmp_path):
    cov = _run(tmp_path, """\
        def classify(x):
            match x:
                case 1:
                    return "one"
                case _:  # pragma: no cover
                    return "other"

        classify(1)
        """)
    for ln in (5, 6):
        assert ln not in cov['executed_lines'] and ln not in cov['missing_lines']
    assert 3 in cov['executed_lines']


def test_branch_exclusion_removes_branch_tuples(tmp_path):
    """Excluding the line an if-branch originates from must also remove its
    branch tuples, not just its own line entries -- otherwise stray
    (executed|missing)_branches remain for a decision point that no longer
    shows up as a line at all."""
    cov = _run(tmp_path, """\
        def check(x):
            if x > 0:  # pragma: no cover
                return "positive"
            else:
                return "non-positive"

        check(1)
        """, branch=True)

    assert 2 not in cov['executed_lines'] and 2 not in cov['missing_lines']
    assert 3 not in cov['executed_lines'] and 3 not in cov['missing_lines']
    # the else clause is a sibling of the excluded if-body, not part of it --
    # matching coverage.py, a pragma on the `if` line doesn't also swallow
    # an unmarked `else:`, so its own lines stay tracked normally.
    assert 5 in cov['missing_lines']

    for b in cov['executed_branches'] + cov['missing_branches']:
        assert b[0] != 2, f"branch {b} originates from excluded line 2"


def test_if_exclusion_does_not_sweep_sibling_else(tmp_path):
    """Regression test for a bug found while implementing this: ast.If
    bundles the whole if/elif/else chain into one node, with end_lineno
    reaching through the *last* elif/else clause -- naively using
    (node.lineno, node.end_lineno) as the span for a match on just the `if`
    line would incorrectly exclude the else clause too. The else branch is
    actually exercised here (check(-1)), so it must show up as executed,
    not silently swallowed by the if's exclusion."""
    cov = _run(tmp_path, """\
        def check(x):
            if x > 0:  # pragma: no cover
                return "positive"
            else:
                return "non-positive"

        check(-1)
        """)
    assert 2 not in cov['executed_lines'] and 2 not in cov['missing_lines']
    assert 3 not in cov['executed_lines'] and 3 not in cov['missing_lines']
    assert 5 in cov['executed_lines']


def test_try_exclusion_does_not_sweep_except_or_finally(tmp_path):
    """Same class of bug as the if/else case: ast.Try's end_lineno reaches
    through handlers/orelse/finalbody, so a pragma on just the `try:` line
    must not exclude the except or finally clauses too -- both actually run
    here and must show up as executed."""
    cov = _run(tmp_path, """\
        marks = []

        def mark():
            marks.append(1)

        def run(x):
            try:  # pragma: no cover
                return 1 / x
            except ZeroDivisionError:
                return -1
            finally:
                mark()

        run(0)
        """)
    for ln in (7, 8):
        assert ln not in cov['executed_lines'] and ln not in cov['missing_lines']
    assert 10 in cov['executed_lines']
    assert 12 in cov['executed_lines']


def test_cli_exclude_lines_flag_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text(
        "def foo(x):\n"
        "    if x < 0:  # custom-nocov\n"
        "        return 1\n"
        "    return 2\n"
        "foo(1)\n"
    )

    p = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--exclude-lines', 'custom-nocov',
         '--json', 'script.py'],
        capture_output=True, text=True
    )
    assert p.returncode == 0, f"stderr: {p.stderr}"

    cov = json.loads(p.stdout)
    keys = [k for k in cov['files'] if 'script.py' in k]
    assert keys, f"script.py not in coverage: {list(cov['files'].keys())}"
    # line 2 ("if x < 0:") always executes regardless of exclusion, so it's
    # never a meaningful signal here -- line 3 ("return 1") is genuinely
    # dead code (foo(1) never takes this branch) and would show up as
    # missing without the fix.
    assert 3 not in cov['files'][keys[0]]['missing_lines']


def test_cli_exclude_lines_config_applied(tmp_path, monkeypatch):
    """[tool.slipcover] exclude-lines is what issue #26 literally asks for
    ("the exclude_lines configuration file setting") -- confirm it actually
    takes effect end-to-end, not just at the apply_config() unit level."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.slipcover]\n'
        'exclude-lines = ["custom-nocov"]\n'
    )
    (tmp_path / "script.py").write_text(
        "def foo(x):\n"
        "    if x < 0:  # custom-nocov\n"
        "        return 1\n"
        "    return 2\n"
        "foo(1)\n"
    )

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', 'script.py'],
                        capture_output=True, text=True)
    assert p.returncode == 0, f"stderr: {p.stderr}"

    cov = json.loads(p.stdout)
    keys = [k for k in cov['files'] if 'script.py' in k]
    assert keys, f"script.py not in coverage: {list(cov['files'].keys())}"
    # line 2 ("if x < 0:") always executes regardless of exclusion, so it's
    # never a meaningful signal here -- line 3 ("return 1") is genuinely
    # dead code (foo(1) never takes this branch) and would show up as
    # missing without the fix.
    assert 3 not in cov['files'][keys[0]]['missing_lines']
