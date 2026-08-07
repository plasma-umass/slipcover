"""Tests for pytest-xdist support."""

import subprocess
import sys
import json
from pathlib import Path
from textwrap import dedent

import pytest

# Skip all tests if pytest-xdist is not installed
pytest.importorskip("xdist")


# Skip on Windows since xdist behavior may differ
pytestmark = pytest.mark.skipif(
    sys.platform == 'win32',
    reason='xdist tests are Unix-specific'
)


def check_summaries(cov):
    """Verify coverage summaries are consistent."""
    import copy
    import slipcover.slipcover as sc

    check = copy.deepcopy(cov)
    sc.add_summaries(check)

    for f in cov['files']:
        assert 'summary' in cov['files'][f]
        assert check['files'][f]['summary'] == cov['files'][f]['summary']

    assert check['summary'] == cov['summary']


def test_xdist_basic(tmp_path):
    """Test basic xdist coverage collection with 2 workers."""
    out = tmp_path / "out.json"
    test_file = str(Path('tests') / 'pyt.py')

    result = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--json', '--out', str(out),
         '-m', 'pytest', '-n', '2', test_file],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)

    check_summaries(cov)

    assert test_file in cov['files'], f"test file not in coverage: {list(cov['files'].keys())}"
    file_cov = cov['files'][test_file]
    # All lines should be covered
    assert [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14] == file_cov['executed_lines']
    assert [] == file_cov['missing_lines']


def test_xdist_multiple_files(tmp_path, monkeypatch):
    """Test xdist coverage collection across multiple test files."""
    monkeypatch.chdir(tmp_path)

    # Create a module to test
    module_file = tmp_path / "mymodule.py"
    module_file.write_text("""\
def branch_a():
    return "a"

def branch_b():
    return "b"

def unused():
    return "unused"
""")

    # Create two test files that exercise different parts of the module
    test_file_a = tmp_path / "test_a.py"
    test_file_a.write_text("""\
from mymodule import branch_a

def test_a():
    assert branch_a() == "a"
""")

    test_file_b = tmp_path / "test_b.py"
    test_file_b.write_text("""\
from mymodule import branch_b

def test_b():
    assert branch_b() == "b"
""")

    out = tmp_path / "out.json"

    result = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--source', str(tmp_path),
         '--json', '--out', str(out),
         '-m', 'pytest', '-n', '2', str(test_file_a), str(test_file_b)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)

    check_summaries(cov)

    # Check that mymodule.py has coverage from both workers
    module_key = str(module_file)
    # The file might be stored with relative path
    module_keys = [k for k in cov['files'].keys() if 'mymodule.py' in k]
    assert len(module_keys) >= 1, f"mymodule.py not found in {list(cov['files'].keys())}"

    module_cov = cov['files'][module_keys[0]]
    executed = set(module_cov['executed_lines'])

    # Both branch_a (line 2) and branch_b (line 5) should be covered
    assert 2 in executed, f"branch_a not covered. Executed: {executed}"
    assert 5 in executed, f"branch_b not covered. Executed: {executed}"

    # unused (line 8) should NOT be covered
    assert 8 not in executed, f"unused should not be covered. Executed: {executed}"


def test_xdist_with_branch_coverage(tmp_path, monkeypatch):
    """Test branch coverage with xdist."""
    monkeypatch.chdir(tmp_path)

    # Create a module with branches
    module_file = tmp_path / "branching.py"
    module_file.write_text("""\
def check(x):
    if x > 0:
        return "positive"
    else:
        return "non-positive"
""")

    # Create two test files that exercise different branches
    test_file_pos = tmp_path / "test_pos.py"
    test_file_pos.write_text("""\
from branching import check

def test_positive():
    assert check(1) == "positive"
""")

    test_file_neg = tmp_path / "test_neg.py"
    test_file_neg.write_text("""\
from branching import check

def test_non_positive():
    assert check(-1) == "non-positive"
""")

    out = tmp_path / "out.json"

    result = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--branch', '--source', str(tmp_path),
         '--json', '--out', str(out),
         '-m', 'pytest', '-n', '2', str(test_file_pos), str(test_file_neg)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)

    check_summaries(cov)

    # Find the branching module in coverage
    module_keys = [k for k in cov['files'].keys() if 'branching.py' in k]
    assert len(module_keys) >= 1, f"branching.py not found in {list(cov['files'].keys())}"

    module_cov = cov['files'][module_keys[0]]

    # Both branches should be covered (merged from both workers)
    executed_branches = [tuple(b) for b in module_cov.get('executed_branches', [])]
    missing_branches = [tuple(b) for b in module_cov.get('missing_branches', [])]

    # The if statement on line 2 should have both branches covered
    # Branch to line 3 (true branch) and branch to line 5 (else branch)
    assert (2, 3) in executed_branches, f"True branch not covered. Executed: {executed_branches}"
    assert (2, 5) in executed_branches, f"Else branch not covered. Executed: {executed_branches}"
    assert len(missing_branches) == 0, f"Should have no missing branches: {missing_branches}"


def test_xdist_four_workers(tmp_path):
    """Test xdist with 4 workers to ensure scaling works."""
    out = tmp_path / "out.json"
    test_file = str(Path('tests') / 'pyt.py')

    result = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--json', '--out', str(out),
         '-m', 'pytest', '-n', '4', test_file],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)

    check_summaries(cov)

    assert test_file in cov['files']
    file_cov = cov['files'][test_file]
    # All lines should still be covered with more workers
    assert [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14] == file_cov['executed_lines']
    assert [] == file_cov['missing_lines']


# ---------------------------------------------------------------------------
# Regression tests for modules imported by a conftest.py before pytest_configure()
# runs in an xdist worker (issue #84's "pre-imported modules" report). Adapted
# from PR #85 (https://github.com/plasma-umass/slipcover/pull/85, author @nurikk),
# who first diagnosed this gap and prototyped a fix by retroactively instrumenting
# already-imported objects after the fact. Unfortunately, that approach has some
# significant issues: on Python <3.12 the rewritten bytecode wasn't reinstalled,
# and on 3.12+ branch coverage came back as a false 100% (no AST-level branch
# preinstrumentation for modules that were already compiled). The fix here takes
# a different angle: activate ImportManager earlier, before conftest.py is ever
# read, so these modules go through the normal instrumentation path from the
# start and need no after-the-fact repair.
# ---------------------------------------------------------------------------


_CONFTEST_PREIMPORT = """\
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
import target  # noqa: F401 -- imported before pytest_configure() runs in the worker
"""


def test_xdist_preimported_module_covered(tmp_path, monkeypatch):
    """A module imported by conftest.py before collection should still be covered."""
    monkeypatch.chdir(tmp_path)

    (tmp_path / "target.py").write_text("""\
def greet(name):
    return f"hello {name}"
""")
    (tmp_path / "conftest.py").write_text(_CONFTEST_PREIMPORT)
    (tmp_path / "test_it.py").write_text("""\
from target import greet

def test_greet():
    assert greet("world") == "hello world"
""")

    out = tmp_path / "out.json"
    result = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--source', str(tmp_path),
         '--json', '--out', str(out),
         '-m', 'pytest', '-n', '2', '-q', 'test_it.py'],
        cwd=str(tmp_path), capture_output=True, text=True
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)
    check_summaries(cov)

    keys = [k for k in cov['files'] if 'target.py' in k]
    assert keys, f"target.py not in coverage: {list(cov['files'].keys())}"
    assert cov['files'][keys[0]]['missing_lines'] == []


def test_xdist_preimported_property_covered(tmp_path, monkeypatch):
    """Property getter bodies in a pre-imported module should be covered."""
    monkeypatch.chdir(tmp_path)

    (tmp_path / "target.py").write_text("""\
class Config:
    @property
    def name(self):
        return "test"

    @property
    def value(self):
        return 42
""")
    (tmp_path / "conftest.py").write_text(_CONFTEST_PREIMPORT)
    (tmp_path / "test_it.py").write_text("""\
from target import Config

def test_name():
    assert Config().name == "test"

def test_value():
    assert Config().value == 42
""")

    out = tmp_path / "out.json"
    result = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--source', str(tmp_path),
         '--json', '--out', str(out),
         '-m', 'pytest', '-n', '2', '-q', 'test_it.py'],
        cwd=str(tmp_path), capture_output=True, text=True
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)
    check_summaries(cov)

    keys = [k for k in cov['files'] if 'target.py' in k]
    assert keys, f"target.py not in coverage: {list(cov['files'].keys())}"
    assert cov['files'][keys[0]]['missing_lines'] == []


def test_xdist_preimported_wrapped_function_covered(tmp_path, monkeypatch):
    """functools.wraps-decorated function bodies in a pre-imported module should be covered."""
    monkeypatch.chdir(tmp_path)

    (tmp_path / "target.py").write_text("""\
import functools

def decorator(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper

@decorator
def compute(x):
    return x * 2
""")
    (tmp_path / "conftest.py").write_text(_CONFTEST_PREIMPORT)
    (tmp_path / "test_it.py").write_text("""\
from target import compute

def test_compute():
    assert compute(21) == 42
""")

    out = tmp_path / "out.json"
    result = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--source', str(tmp_path),
         '--json', '--out', str(out),
         '-m', 'pytest', '-n', '2', '-q', 'test_it.py'],
        cwd=str(tmp_path), capture_output=True, text=True
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)
    check_summaries(cov)

    keys = [k for k in cov['files'] if 'target.py' in k]
    assert keys, f"target.py not in coverage: {list(cov['files'].keys())}"
    # line 6: "return fn(*args, **kwargs)" inside the wrapped function body
    assert 6 not in cov['files'][keys[0]]['missing_lines']


def test_xdist_preimported_nested_attr_covered(tmp_path, monkeypatch):
    """A function stashed on a nested object attribute in a pre-imported module
    should be covered -- demonstrating early activation needs no bespoke
    object-graph walking to handle shapes like this."""
    monkeypatch.chdir(tmp_path)

    (tmp_path / "target.py").write_text("""\
class Task:
    def __init__(self, fn):
        self.fn = fn

class Workflow:
    def __init__(self, task):
        self._task = task

def _impl(x):
    return x + 1

workflow = Workflow(Task(_impl))
""")
    (tmp_path / "conftest.py").write_text(_CONFTEST_PREIMPORT)
    (tmp_path / "test_it.py").write_text("""\
from target import workflow

def test_workflow():
    assert workflow._task.fn(41) == 42
""")

    out = tmp_path / "out.json"
    result = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--source', str(tmp_path),
         '--json', '--out', str(out),
         '-m', 'pytest', '-n', '2', '-q', 'test_it.py'],
        cwd=str(tmp_path), capture_output=True, text=True
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)
    check_summaries(cov)

    keys = [k for k in cov['files'] if 'target.py' in k]
    assert keys, f"target.py not in coverage: {list(cov['files'].keys())}"
    # line 10: "return x + 1" inside _impl
    assert 10 not in cov['files'][keys[0]]['missing_lines']


def test_xdist_preimported_module_branch_coverage(tmp_path, monkeypatch):
    """Branch coverage for a pre-imported module must reflect real, not vacuous,
    coverage: only the branch actually exercised should be covered, and the
    untaken branch must show up in missing_branches rather than a false 100%."""
    monkeypatch.chdir(tmp_path)

    (tmp_path / "target.py").write_text("""\
def check(x):
    if x > 0:
        return "positive"
    else:
        return "non-positive"
""")
    (tmp_path / "conftest.py").write_text(_CONFTEST_PREIMPORT)
    (tmp_path / "test_it.py").write_text("""\
from target import check

def test_positive():
    assert check(1) == "positive"
""")

    out = tmp_path / "out.json"
    result = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--branch', '--source', str(tmp_path),
         '--json', '--out', str(out),
         '-m', 'pytest', '-n', '2', '-q', 'test_it.py'],
        cwd=str(tmp_path), capture_output=True, text=True
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)
    check_summaries(cov)

    keys = [k for k in cov['files'] if 'target.py' in k]
    assert keys, f"target.py not in coverage: {list(cov['files'].keys())}"
    module_cov = cov['files'][keys[0]]

    executed_branches = [tuple(b) for b in module_cov.get('executed_branches', [])]
    missing_branches = [tuple(b) for b in module_cov.get('missing_branches', [])]

    # Only the true branch (line 2 -> line 3) was exercised; the else branch
    # (line 2 -> line 5) was never taken and must show up as missing -- a vacuous
    # "0 missing branches" here is exactly the false-100% bug being guarded against.
    assert (2, 3) in executed_branches, f"true branch not covered: {executed_branches}"
    assert (2, 5) in missing_branches, f"else branch should be missing: {missing_branches}"


def test_xdist_fail_under_uses_merged_coverage(tmp_path):
    """--fail-under must be checked against the merged (all-workers) coverage,
    not just the coordinator process' own view. Under xdist, actual test code
    runs only in worker subprocesses -- the coordinator's own local coverage
    has no files at all, which trivially (and silently) reports as 100%,
    defeating --fail-under entirely if the local, unmerged view is used.
    """
    test_file = tmp_path / "test_partial.py"
    test_file.write_text(dedent("""\
        def foo(x):
            if x:
                return 1
            return 2

        def bar(y):
            if y:
                return 3
            return 4

        def test_foo():
            assert foo(0) == 2

        def test_bar():
            assert bar(0) == 4
    """))

    # real merged coverage is 10/12 = 83.3% (the "return 1"/"return 3"
    # branches are never taken) -- comfortably above 50, so this must pass.
    # The coordinator's own local, unmerged view would incorrectly see 0%
    # (it discovers the file via cwd-matching but never executes it itself,
    # since actual test execution happens only in the xdist workers), which
    # would incorrectly fail this same check.
    result = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--fail-under', '50',
         '-m', 'pytest', '-n', '2', test_file.name],
        cwd=str(tmp_path),
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
