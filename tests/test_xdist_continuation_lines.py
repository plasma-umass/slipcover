"""xfail tests for expression continuation lines not tracked in xdist workers.

On Python 3.12+, when modules are pre-imported by the main process (e.g. via
conftest.py) and inherited by xdist workers via fork, the retroactive
instrumentation uses ``find_functions()`` to discover function objects.
However, ``find_functions()`` does not recurse into container attributes
(dicts, lists) — so lambda/function references stored in class-level dicts
like ``column_formatters = {"key": lambda ...}`` are never instrumented.

Each test creates a minimal reproduction with a conftest.py that pre-imports
the target module, then runs slipcover with -n 2 and verifies coverage.
"""

import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("xdist")

pytestmark = [
    pytest.mark.skipif(sys.platform == "win32", reason="xdist tests are Unix-specific"),
    pytest.mark.skipif(sys.version_info < (3, 12), reason="sys.monitoring requires 3.12+"),
]


def _run_slipcover_xdist(tmp_path, module_code, test_code, conftest_code, workers=2):
    """Write module + conftest + test, run slipcover with xdist, return file coverage."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    module_file = src_dir / "target.py"
    module_file.write_text(module_code)

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    conftest = tests_dir / "conftest.py"
    conftest.write_text(conftest_code)

    test_file = tests_dir / "test_target.py"
    test_file.write_text(test_code)

    out = tmp_path / "cov.json"
    env = {**os.environ, "PYTHONPATH": str(src_dir)}
    result = subprocess.run(
        [
            sys.executable, "-m", "slipcover",
            "--source", str(src_dir),
            "--json", "--out", str(out),
            "-m", "pytest", "-n", str(workers), "-q",
            str(tests_dir),
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
    )

    assert result.returncode == 0, (
        f"slipcover failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    with out.open() as f:
        cov = json.load(f)

    keys = [k for k in cov["files"] if "target.py" in k]
    assert keys, f"target.py not in coverage files: {list(cov['files'])}"
    return cov["files"][keys[0]]


# Conftest that forces module import in main process before xdist forks
_CONFTEST = '''\
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import target  # noqa: F401 — pre-import so workers inherit it via fork
'''


# ---------------------------------------------------------------------------
# Test 1: lambda stored in class-level dict (e.g. column_formatters)
# ---------------------------------------------------------------------------

def test_lambda_in_class_dict(tmp_path, monkeypatch):
    """Lambdas stored in class-level dict attributes should be instrumented."""
    monkeypatch.chdir(tmp_path)

    module = '''\
class View:
    formatters = {
        "name": lambda obj: (
            obj.upper()
            if obj
            else "-"
        ),
    }
'''
    test = '''\
from target import View

def test_with_value():
    assert View.formatters["name"]("hello") == "HELLO"

def test_without_value():
    assert View.formatters["name"]("") == "-"
'''
    file_cov = _run_slipcover_xdist(tmp_path, module, test, _CONFTEST)

    assert file_cov["missing_lines"] == [], (
        f"All lines should be covered; missing: {file_cov['missing_lines']}"
    )


# ---------------------------------------------------------------------------
# Test 2: lambda in class dict with multi-line f-string
# ---------------------------------------------------------------------------

def test_lambda_fstring_in_class_dict(tmp_path, monkeypatch):
    """Lambda with f-string stored in class dict should have all lines covered."""
    monkeypatch.chdir(tmp_path)

    module = '''\
class Admin:
    formatters = {
        "link": lambda item: (
            f"<a>{item}</a>"
        ),
    }
'''
    test = '''\
from target import Admin

def test_format_link():
    assert Admin.formatters["link"]("x") == "<a>x</a>"
'''
    file_cov = _run_slipcover_xdist(tmp_path, module, test, _CONFTEST)

    assert file_cov["missing_lines"] == [], (
        f"All lines should be covered; missing: {file_cov['missing_lines']}"
    )


# ---------------------------------------------------------------------------
# Test 3: lambda in nested dict (dict inside dict)
# ---------------------------------------------------------------------------

def test_lambda_in_nested_dict(tmp_path, monkeypatch):
    """Lambdas stored in nested dict structures should be instrumented."""
    monkeypatch.chdir(tmp_path)

    module = '''\
registry = {
    "formatters": {
        "upper": lambda x: (
            x.upper()
            if x
            else ""
        ),
    },
}
'''
    test = '''\
from target import registry

def test_upper():
    assert registry["formatters"]["upper"]("hello") == "HELLO"

def test_empty():
    assert registry["formatters"]["upper"]("") == ""
'''
    file_cov = _run_slipcover_xdist(tmp_path, module, test, _CONFTEST)

    assert file_cov["missing_lines"] == [], (
        f"All lines should be covered; missing: {file_cov['missing_lines']}"
    )


# ---------------------------------------------------------------------------
# Test 4: lambda in list (e.g. validators list)
# ---------------------------------------------------------------------------

def test_lambda_in_list(tmp_path, monkeypatch):
    """Lambdas stored in module-level lists should be instrumented."""
    monkeypatch.chdir(tmp_path)

    module = '''\
validators = [
    lambda x: (
        "ok"
        if x > 0
        else "bad"
    ),
]
'''
    test = '''\
from target import validators

def test_positive():
    assert validators[0](1) == "ok"

def test_negative():
    assert validators[0](-1) == "bad"
'''
    file_cov = _run_slipcover_xdist(tmp_path, module, test, _CONFTEST)

    assert file_cov["missing_lines"] == [], (
        f"All lines should be covered; missing: {file_cov['missing_lines']}"
    )


# ---------------------------------------------------------------------------
# Test 5: multi-line call args inside class method stored in dict
# ---------------------------------------------------------------------------

def test_call_args_in_class_dict_lambda(tmp_path, monkeypatch):
    """Call-arg continuation lines in dict-stored lambdas should be covered."""
    monkeypatch.chdir(tmp_path)

    module = '''\
class Config:
    def __init__(self, a, b):
        self.a = a
        self.b = b

class View:
    builders = {
        "cfg": lambda: Config(
            a="hello",
            b="world",
        ),
    }
'''
    test = '''\
from target import View

def test_builder():
    c = View.builders["cfg"]()
    assert c.a == "hello"
    assert c.b == "world"
'''
    file_cov = _run_slipcover_xdist(tmp_path, module, test, _CONFTEST)

    assert file_cov["missing_lines"] == [], (
        f"All lines should be covered; missing: {file_cov['missing_lines']}"
    )
