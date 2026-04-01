"""Tests for --exclude-lines and def-signature exclusion features."""

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

import slipcover.slipcover as sc

PYTHON_VERSION = sys.version_info[0:2]


# ---------------------------------------------------------------------------
# Unit tests: _filter_excluded_lines
# ---------------------------------------------------------------------------


def _make_coverage_with_source(tmp_path, source, executed, missing):
    """Create a source file and a coverage dict referencing it."""
    f = tmp_path / "mod.py"
    f.write_text(dedent(source))
    fname = str(f)
    files = {
        fname: {
            "executed_lines": executed,
            "missing_lines": missing,
        }
    }
    return files, fname


def test_exclude_lines_single_line(tmp_path):
    """Lines matching an exclude pattern are removed from both executed and missing."""
    source = """\
        x = 1
        if TYPE_CHECKING:
            import os
        y = 2
    """
    files, fname = _make_coverage_with_source(
        tmp_path, source,
        executed=[1, 4],
        missing=[2, 3],
    )
    sci = sc.Slipcover(exclude_lines=["if TYPE_CHECKING:"])
    sci._filter_excluded_lines(files)

    assert 2 not in files[fname]["missing_lines"]
    assert 2 not in files[fname]["executed_lines"]


def test_exclude_lines_block_body(tmp_path):
    """When an excluded line is a block statement, its indented body is also excluded."""
    source = """\
        x = 1
        if TYPE_CHECKING:
            import os
            import sys
        y = 2
    """
    files, fname = _make_coverage_with_source(
        tmp_path, source,
        executed=[1, 5],
        missing=[2, 3, 4],
    )
    sci = sc.Slipcover(exclude_lines=["if TYPE_CHECKING:"])
    sci._filter_excluded_lines(files)

    assert files[fname]["missing_lines"] == []


def test_exclude_lines_decorator_cascade(tmp_path):
    """When an excluded line is a decorator, the decorated function body is excluded."""
    source = """\
        from abc import abstractmethod

        class Base:
            @abstractmethod
            def method(self):
                pass

            def concrete(self):
                return 1
    """
    files, fname = _make_coverage_with_source(
        tmp_path, source,
        executed=[1, 3, 8, 9],
        missing=[4, 5, 6],
    )
    sci = sc.Slipcover(exclude_lines=[r"@(abc\.)?abstractmethod"])
    sci._filter_excluded_lines(files)

    # decorator, def, and body should all be excluded
    assert 4 not in files[fname]["missing_lines"]
    assert 5 not in files[fname]["missing_lines"]
    assert 6 not in files[fname]["missing_lines"]


def test_exclude_lines_stacked_decorators(tmp_path):
    """Stacked decorators before the excluded one are not affected, body is excluded."""
    source = """\
        class Base:
            @property
            @abstractmethod
            def name(self):
                pass
    """
    files, fname = _make_coverage_with_source(
        tmp_path, source,
        executed=[1],
        missing=[2, 3, 4, 5],
    )
    sci = sc.Slipcover(exclude_lines=[r"@(abc\.)?abstractmethod"])
    sci._filter_excluded_lines(files)

    # @abstractmethod line and everything after it (def + body) should be excluded
    assert 3 not in files[fname]["missing_lines"]
    assert 4 not in files[fname]["missing_lines"]
    assert 5 not in files[fname]["missing_lines"]
    # @property is NOT excluded (it's before the matching decorator)
    assert 2 in files[fname]["missing_lines"]


def test_exclude_lines_case_block(tmp_path):
    """case/match statements are recognized as block keywords."""
    source = """\
        match x:
            case 1:
                print("one")
            case _:  # pragma: no cover
                assert_never(x)
    """
    files, fname = _make_coverage_with_source(
        tmp_path, source,
        executed=[1, 2, 3],
        missing=[4, 5],
    )
    sci = sc.Slipcover(exclude_lines=["pragma: no cover"])
    sci._filter_excluded_lines(files)

    assert 4 not in files[fname]["missing_lines"]
    assert 5 not in files[fname]["missing_lines"]


def test_exclude_lines_pragma_no_cover(tmp_path):
    """The classic pragma: no cover pattern works."""
    source = """\
        def foo():
            if debug:  # pragma: no cover
                log()
            return 1
    """
    files, fname = _make_coverage_with_source(
        tmp_path, source,
        executed=[1, 4],
        missing=[2, 3],
    )
    sci = sc.Slipcover(exclude_lines=["pragma: no cover"])
    sci._filter_excluded_lines(files)

    assert files[fname]["missing_lines"] == []


# ---------------------------------------------------------------------------
# Unit tests: _exclude_def_signature_lines
# ---------------------------------------------------------------------------


def test_signature_lines_excluded(tmp_path):
    """Multi-line function signature continuation lines are excluded."""
    source = """\
        def foo(
            x: int,
            y: str,
        ) -> bool:
            return True
    """
    files, fname = _make_coverage_with_source(
        tmp_path, source,
        executed=[1, 5],
        missing=[2, 3, 4],
    )
    sc.Slipcover._exclude_def_signature_lines(files)

    # Lines 2-4 (parameters + return type) should be excluded
    assert files[fname]["missing_lines"] == []


def test_signature_lines_async_def(tmp_path):
    """Async function signature continuation lines are excluded."""
    source = """\
        async def handler(
            request: Request,
            db: Session,
        ) -> Response:
            return Response()
    """
    files, fname = _make_coverage_with_source(
        tmp_path, source,
        executed=[1, 5],
        missing=[2, 3, 4],
    )
    sc.Slipcover._exclude_def_signature_lines(files)

    assert files[fname]["missing_lines"] == []


def test_signature_lines_class_bases(tmp_path):
    """Multi-line class base list continuation lines are excluded."""
    source = """\
        class MyView(
            BaseAdmin,
            SomeMixin,
        ):
            pass
    """
    files, fname = _make_coverage_with_source(
        tmp_path, source,
        executed=[1, 5],
        missing=[2, 3, 4],
    )
    sc.Slipcover._exclude_def_signature_lines(files)

    assert files[fname]["missing_lines"] == []


def test_single_line_def_unaffected(tmp_path):
    """Single-line function defs are not affected by signature exclusion."""
    source = """\
        def foo(x: int) -> bool:
            return True
    """
    files, fname = _make_coverage_with_source(
        tmp_path, source,
        executed=[1],
        missing=[2],
    )
    sc.Slipcover._exclude_def_signature_lines(files)

    # Body line should remain as missing
    assert files[fname]["missing_lines"] == [2]


# ---------------------------------------------------------------------------
# CLI integration test: --exclude-lines flag
# ---------------------------------------------------------------------------


def test_exclude_lines_cli(tmp_path):
    """--exclude-lines flag is passed through CLI and filters coverage."""
    mod = tmp_path / "mod.py"
    mod.write_text(dedent("""\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            import os

        def foo():
            return 1
    """))

    test = tmp_path / "test_mod.py"
    test.write_text(dedent("""\
        import sys
        sys.path.insert(0, '.')
        from mod import foo

        def test_foo():
            assert foo() == 1
    """))

    out = tmp_path / "cov.json"
    result = subprocess.run(
        [
            sys.executable, "-m", "slipcover",
            "--source", str(tmp_path),
            "--exclude-lines", "if TYPE_CHECKING:",
            "--json", "--out", str(out),
            "-m", "pytest", "-q", str(test),
        ],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)

    keys = [k for k in cov["files"] if "mod.py" in k]
    assert keys
    file_cov = cov["files"][keys[0]]

    # TYPE_CHECKING body (line 4) should be excluded from both missing and executed.
    # Line 3 (the `if` itself) is executed at runtime (condition evaluates to False)
    # but should not appear as missing.
    assert 3 not in file_cov["missing_lines"]
    assert 4 not in file_cov["missing_lines"]
    assert 4 not in file_cov["executed_lines"]
