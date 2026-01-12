"""Tests for pytest-xdist support."""

import subprocess
import sys
import json
from pathlib import Path

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
