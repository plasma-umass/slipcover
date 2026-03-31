"""Tests for xdist-specific fixes: omit propagation, fail_under, retroactive instrumentation."""

import json
import os
import subprocess
import sys
from textwrap import dedent

import pytest

pytest.importorskip("xdist")

pytestmark = [
    pytest.mark.skipif(sys.platform == "win32", reason="xdist tests are Unix-specific"),
    pytest.mark.skipif(sys.version_info < (3, 12), reason="retroactive instrumentation requires 3.12+"),
]


def _run_slipcover(args, *, cwd, env=None):
    """Run slipcover as subprocess, return (returncode, stdout, stderr)."""
    full_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        [sys.executable, "-m", "slipcover", *args],
        capture_output=True, text=True, cwd=str(cwd), env=full_env,
    )
    return result


def _setup_project(tmp_path, module_code, test_code, conftest_code=""):
    """Create src/target.py + tests/test_target.py + optional tests/conftest.py."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "target.py").write_text(dedent(module_code))

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_target.py").write_text(dedent(test_code))
    if conftest_code:
        (tests / "conftest.py").write_text(dedent(conftest_code))

    return src, tests


def _get_file_cov(cov_path, filename="target.py"):
    """Load JSON coverage and return file coverage for the given filename."""
    with open(cov_path) as f:
        cov = json.load(f)
    keys = [k for k in cov["files"] if filename in k]
    assert keys, f"{filename} not in {list(cov['files'])}"
    return cov["files"][keys[0]], cov


_CONFTEST_PREIMPORT = '''\
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
    import target  # noqa: F401
'''


# ---------------------------------------------------------------------------
# Test: --omit propagated to xdist workers
# ---------------------------------------------------------------------------


def test_xdist_omit_propagation(tmp_path):
    """Files matching --omit should not appear in coverage even with xdist."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "included.py").write_text("def inc(): return 1\n")
    (src / "excluded.py").write_text("def exc(): return 2\n")

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_it.py").write_text(dedent("""\
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src"))
        from included import inc

        def test_inc():
            assert inc() == 1
    """))

    out = tmp_path / "cov.json"
    result = _run_slipcover(
        ["--source", str(src), "--omit", str(src / "excluded.py"),
         "--json", "--out", str(out),
         "-m", "pytest", "-n", "2", "-q", str(tests)],
        cwd=tmp_path, env={"PYTHONPATH": str(src)},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    with open(out) as f:
        cov = json.load(f)

    filenames = list(cov["files"].keys())
    assert not any("excluded.py" in f for f in filenames), (
        f"excluded.py should be omitted, found: {filenames}"
    )


# ---------------------------------------------------------------------------
# Test: --fail-under uses merged xdist coverage
# ---------------------------------------------------------------------------


def test_xdist_fail_under_uses_merged_coverage(tmp_path):
    """--fail-under should use merged coverage from all workers, not just main process."""
    src, tests = _setup_project(
        tmp_path,
        module_code="""\
            def branch_a():
                return "a"

            def branch_b():
                return "b"
        """,
        test_code="""\
            import sys
            sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src"))
            from target import branch_a, branch_b

            def test_a():
                assert branch_a() == "a"

            def test_b():
                assert branch_b() == "b"
        """,
    )

    out = tmp_path / "cov.json"
    result = _run_slipcover(
        ["--source", str(src), "--fail-under", "100",
         "--json", "--out", str(out),
         "-m", "pytest", "-n", "2", "-q", str(tests)],
        cwd=tmp_path, env={"PYTHONPATH": str(src)},
    )

    # Should pass: merged coverage from 2 workers covers both branches
    assert result.returncode == 0, (
        f"fail-under should pass with merged coverage.\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Test: retroactive instrumentation of pre-imported modules
# ---------------------------------------------------------------------------


def test_xdist_preinported_module_covered(tmp_path):
    """Modules imported before xdist forks should still be covered in workers."""
    src, tests = _setup_project(
        tmp_path,
        module_code="""\
            def greet(name):
                return f"hello {name}"
        """,
        test_code="""\
            from target import greet

            def test_greet():
                assert greet("world") == "hello world"
        """,
        conftest_code=_CONFTEST_PREIMPORT,
    )

    out = tmp_path / "cov.json"
    result = _run_slipcover(
        ["--source", str(src), "--json", "--out", str(out),
         "-m", "pytest", "-n", "2", "-q", str(tests)],
        cwd=tmp_path, env={"PYTHONPATH": str(src)},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    file_cov, _ = _get_file_cov(out)
    assert file_cov["missing_lines"] == [], (
        f"pre-imported module should be fully covered; missing: {file_cov['missing_lines']}"
    )


# ---------------------------------------------------------------------------
# Test: properties instrumented in pre-imported modules
# ---------------------------------------------------------------------------


def test_xdist_property_bodies_covered(tmp_path):
    """Property getter bodies should be covered even when pre-imported."""
    src, tests = _setup_project(
        tmp_path,
        module_code="""\
            class Config:
                @property
                def name(self):
                    return "test"

                @property
                def value(self):
                    return 42
        """,
        test_code="""\
            from target import Config

            def test_name():
                assert Config().name == "test"

            def test_value():
                assert Config().value == 42
        """,
        conftest_code=_CONFTEST_PREIMPORT,
    )

    out = tmp_path / "cov.json"
    result = _run_slipcover(
        ["--source", str(src), "--json", "--out", str(out),
         "-m", "pytest", "-n", "2", "-q", str(tests)],
        cwd=tmp_path, env={"PYTHONPATH": str(src)},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    file_cov, _ = _get_file_cov(out)
    assert file_cov["missing_lines"] == [], (
        f"property bodies should be covered; missing: {file_cov['missing_lines']}"
    )


# ---------------------------------------------------------------------------
# Test: __wrapped__ functions instrumented
# ---------------------------------------------------------------------------


def test_xdist_wrapped_functions_covered(tmp_path):
    """Functions with __wrapped__ (functools.wraps) should be covered."""
    src, tests = _setup_project(
        tmp_path,
        module_code="""\
            import functools

            def decorator(fn):
                @functools.wraps(fn)
                def wrapper(*args, **kwargs):
                    return fn(*args, **kwargs)
                return wrapper

            @decorator
            def compute(x):
                return x * 2
        """,
        test_code="""\
            from target import compute

            def test_compute():
                assert compute(21) == 42
        """,
        conftest_code=_CONFTEST_PREIMPORT,
    )

    out = tmp_path / "cov.json"
    result = _run_slipcover(
        ["--source", str(src), "--json", "--out", str(out),
         "-m", "pytest", "-n", "2", "-q", str(tests)],
        cwd=tmp_path, env={"PYTHONPATH": str(src)},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    file_cov, _ = _get_file_cov(out)
    # The wrapped function body (line 11: return x * 2) should be covered
    assert 11 not in file_cov["missing_lines"], (
        f"wrapped function body should be covered; missing: {file_cov['missing_lines']}"
    )


# ---------------------------------------------------------------------------
# Test: deep scan finds functions in nested object attributes
# ---------------------------------------------------------------------------


def test_xdist_deep_scan_nested_attrs(tmp_path):
    """Functions stored in nested object attributes (e.g., task.fn) should be covered."""
    src, tests = _setup_project(
        tmp_path,
        module_code="""\
            class Task:
                def __init__(self, fn):
                    self.fn = fn

            class Workflow:
                def __init__(self, task):
                    self._task = task

            def _impl(x):
                return x + 1

            workflow = Workflow(Task(_impl))
        """,
        test_code="""\
            from target import workflow

            def test_workflow():
                assert workflow._task.fn(41) == 42
        """,
        conftest_code=_CONFTEST_PREIMPORT,
    )

    out = tmp_path / "cov.json"
    result = _run_slipcover(
        ["--source", str(src), "--json", "--out", str(out),
         "-m", "pytest", "-n", "2", "-q", str(tests)],
        cwd=tmp_path, env={"PYTHONPATH": str(src)},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    file_cov, _ = _get_file_cov(out)
    # _impl body (line 10) should be covered
    assert 10 not in file_cov["missing_lines"], (
        f"nested attr function should be covered; missing: {file_cov['missing_lines']}"
    )


# ---------------------------------------------------------------------------
# Test: --exclude-lines propagated to xdist workers
# ---------------------------------------------------------------------------


def test_xdist_exclude_lines_propagation(tmp_path):
    """--exclude-lines should apply in xdist workers via env var."""
    src, tests = _setup_project(
        tmp_path,
        module_code="""\
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                import os

            def foo():
                return 1
        """,
        test_code="""\
            from target import foo

            def test_foo():
                assert foo() == 1
        """,
        conftest_code=_CONFTEST_PREIMPORT,
    )

    out = tmp_path / "cov.json"
    result = _run_slipcover(
        ["--source", str(src),
         "--exclude-lines", "if TYPE_CHECKING:",
         "--json", "--out", str(out),
         "-m", "pytest", "-n", "2", "-q", str(tests)],
        cwd=tmp_path, env={"PYTHONPATH": str(src)},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    file_cov, _ = _get_file_cov(out)
    # TYPE_CHECKING block should be excluded
    assert 3 not in file_cov["missing_lines"]
    assert 4 not in file_cov["missing_lines"]
    assert 3 not in file_cov["executed_lines"]
    assert 4 not in file_cov["executed_lines"]
