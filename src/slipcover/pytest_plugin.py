"""Pytest plugin for slipcover with pytest-xdist support.

This plugin enables coverage collection when using pytest-xdist for parallel testing.
It is automatically activated when SLIPCOVER_ENABLED environment variable is set
(which is done by slipcover's __main__.py when running pytest).

The plugin coordinates coverage collection across xdist workers by:
1. Creating a shared temp directory for coverage files (controller)
2. Having each worker write its coverage to the shared directory
3. Merging all worker coverage in the controller at session end
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import slipcover as sc


# Global state for the plugin
_slipcover_instance: Optional[sc.Slipcover] = None
_file_matcher: Optional[sc.FileMatcher] = None
_import_manager: Optional[sc.ImportManager] = None
_coverage_dir: Optional[str] = None


def _is_xdist_worker() -> bool:
    """Check if running as an xdist worker process."""
    return "PYTEST_XDIST_WORKER" in os.environ


def _get_worker_id() -> str:
    """Get the xdist worker ID (e.g., 'gw0', 'gw1'), or 'main' if not a worker."""
    return os.environ.get("PYTEST_XDIST_WORKER", "main")


def _activate_worker():
    """Activates instrumentation for an xdist worker as early as possible.

    This runs at module import time (see the call at the bottom of this file),
    not inside pytest_configure(): pytest_configure() only fires after pytest
    has already auto-loaded every pytest11 entry-point plugin and read the
    initial conftest.py files, so anything they import would already have
    bypassed ImportManager by the time pytest_configure() ran. This module is
    itself imported via that same entry-point autoload mechanism, so
    top-level code here runs before conftest.py is ever read.
    """
    global _slipcover_instance, _file_matcher, _import_manager, _coverage_dir

    # Only activate if SLIPCOVER_ENABLED is set (by __main__.py when running
    # pytest) and we're in an xdist worker -- the controller is already
    # handled by __main__.py, and this same guard is what pytest_configure()
    # used before, just evaluated earlier.
    if not (os.environ.get("SLIPCOVER_ENABLED") and _is_xdist_worker()):
        return

    # Coverage directory (workers inherit this from the controller's env)
    _coverage_dir = os.environ.get("SLIPCOVER_COVERAGE_DIR")

    # Parse configuration from environment (set by __main__.py)
    branch = os.environ.get("SLIPCOVER_BRANCH") == "1"
    source = os.environ.get("SLIPCOVER_SOURCE")
    omit = os.environ.get("SLIPCOVER_OMIT")
    # The var's mere presence -- not its truthiness -- distinguishes "not
    # configured, use defaults" (unset -> None) from "explicitly resolved"
    # (set, even to "" for exclude-lines = [] in config -> []) -- see
    # __main__.py.
    if "SLIPCOVER_EXCLUDE_LINES" in os.environ:
        raw = os.environ["SLIPCOVER_EXCLUDE_LINES"]
        exclude_lines = raw.split("\n") if raw else []
    else:
        exclude_lines = None

    # Set up file matcher
    _file_matcher = sc.FileMatcher(
        sources=[s.strip() for s in source.split(",") if s.strip()] if source else None,
        omit=[o.strip() for o in omit.split(",") if o.strip()] if omit else None,
    )

    # Create Slipcover instance
    source_list = [s.strip() for s in source.split(",")] if source else None
    omit_list = [o.strip() for o in omit.split(",")] if omit else None
    _slipcover_instance = sc.Slipcover(branch=branch, source=source_list, omit=omit_list, exclude_lines=exclude_lines)

    # Wrap pytest's assertion rewriter for instrumentation
    sc.wrap_pytest(_slipcover_instance, _file_matcher)

    # Start import instrumentation
    _import_manager = sc.ImportManager(_slipcover_instance, _file_matcher)
    _import_manager.__enter__()


_activate_worker()


def pytest_configure(config):
    """Sets up the shared coverage directory in the controller.

    Worker activation itself already happened at import time, above -- this
    hook now only handles the controller side, which does need the `config`
    object (to detect xdist via config.option.numprocesses).
    """
    global _coverage_dir

    # Only activate if SLIPCOVER_ENABLED is set (by __main__.py when running pytest)
    if not os.environ.get("SLIPCOVER_ENABLED"):
        return

    # Check if xdist is being used (look for -n option or xdist plugin config)
    # Note: PYTEST_XDIST_TESTRUNUID is set later, so we check numprocesses
    is_xdist = hasattr(config.option, 'numprocesses') and config.option.numprocesses

    # Controller creates shared coverage directory for workers to write to
    # We detect controller as: xdist is being used AND we're not a worker
    if is_xdist and not _is_xdist_worker():
        _coverage_dir = tempfile.mkdtemp(prefix="slipcover-xdist-")
        os.environ["SLIPCOVER_COVERAGE_DIR"] = _coverage_dir


def pytest_unconfigure(config):
    """Clean up import manager on shutdown."""
    global _import_manager
    if _import_manager:
        _import_manager.__exit__(None, None, None)
        _import_manager = None


def pytest_sessionfinish(session, exitstatus):
    """Handle coverage collection at session end.

    Workers: Write coverage to a file in the shared directory.
    Controller: Merge all worker coverage files into a single merged.json.
    """
    global _slipcover_instance, _coverage_dir

    if not os.environ.get("SLIPCOVER_ENABLED"):
        return

    if _is_xdist_worker() and _slipcover_instance and _coverage_dir:
        # Worker: write coverage to shared directory
        coverage = _slipcover_instance.get_coverage()
        worker_id = _get_worker_id()
        cov_file = Path(_coverage_dir) / f"coverage-{worker_id}.json"
        try:
            with open(cov_file, "w") as f:
                json.dump(coverage, f)
        except Exception as e:
            import warnings
            warnings.warn(f"slipcover: failed to write worker coverage: {e}")

    elif _coverage_dir and not _is_xdist_worker():
        # Controller: merge all worker coverage files
        # We know we're the controller if _coverage_dir is set and we're not a worker
        coverage_dir = Path(_coverage_dir)
        worker_files = list(coverage_dir.glob("coverage-gw*.json"))

        if worker_files:
            # Start with first worker's coverage
            merged = None
            for cov_file in worker_files:
                try:
                    with open(cov_file) as f:
                        worker_cov = json.load(f)
                    if merged is None:
                        merged = worker_cov
                    else:
                        sc.merge_coverage(merged, worker_cov)
                except Exception as e:
                    import warnings
                    warnings.warn(f"slipcover: error reading {cov_file}: {e}")

            if merged:
                # Write merged coverage for __main__.py to read
                merged_file = coverage_dir / "merged.json"
                try:
                    with open(merged_file, "w") as f:
                        json.dump(merged, f)
                except Exception as e:
                    import warnings
                    warnings.warn(f"slipcover: failed to write merged coverage: {e}")
