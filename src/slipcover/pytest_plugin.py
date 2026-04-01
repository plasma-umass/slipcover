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


def pytest_configure(config):
    """Initialize slipcover in xdist workers.

    This hook runs in both the controller and worker processes.
    We only activate slipcover if SLIPCOVER_ENABLED is set AND we're in an xdist worker.
    The controller (main process) is already handled by __main__.py.
    """
    global _slipcover_instance, _file_matcher, _import_manager, _coverage_dir

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
        return  # Controller's slipcover is already set up by __main__.py

    # Get coverage directory (workers inherit this from controller)
    _coverage_dir = os.environ.get("SLIPCOVER_COVERAGE_DIR")

    # Only set up slipcover in workers - controller is handled by __main__.py
    if not _is_xdist_worker():
        return

    # Parse configuration from environment (set by __main__.py)
    branch = os.environ.get("SLIPCOVER_BRANCH") == "1"
    source = os.environ.get("SLIPCOVER_SOURCE")
    omit = os.environ.get("SLIPCOVER_OMIT")
    exclude_lines_str = os.environ.get("SLIPCOVER_EXCLUDE_LINES")
    exclude_lines = exclude_lines_str.split("\n") if exclude_lines_str else None

    # Set up file matcher
    _file_matcher = sc.FileMatcher()
    if source:
        for s in source.split(","):
            s = s.strip()
            if s:
                _file_matcher.addSource(s)
    if omit:
        for o in omit.split(","):
            o = o.strip()
            if o:
                _file_matcher.addOmit(o)

    # Create Slipcover instance — workers don't pass source to avoid
    # _add_unseen_source_files adding files with AST-parsed line counts
    # that differ from bytecode-parsed counts.  The main process (via
    # __main__.py) handles unseen-file scanning instead.
    omit_list = [o.strip() for o in omit.split(",") if o.strip()] if omit else None
    _slipcover_instance = sc.Slipcover(branch=branch, omit=omit_list,
                                       exclude_lines=exclude_lines)

    # Wrap pytest's assertion rewriter for instrumentation
    sc.wrap_pytest(_slipcover_instance, _file_matcher)

    # Start import instrumentation
    _import_manager = sc.ImportManager(_slipcover_instance, _file_matcher)
    _import_manager.__enter__()

    # Retroactively instrument modules already in sys.modules (inherited
    # from the main process via execnet fork).  Without this, those modules
    # bypass the ImportManager and their coverage is never recorded.
    #
    # On Python 3.12+, sys.monitoring.set_local_events must be called on
    # the actual live code objects, not freshly compiled ones.  We find
    # all function/method objects in each module and instrument their
    # __code__ attributes directly.
    import ast
    import sys as _sys
    import types

    def _instrument_func(func):
        if isinstance(func, types.FunctionType) and _file_matcher.matches(func.__code__.co_filename):
            _slipcover_instance.instrument(func.__code__)

    visited: set = set()
    for mod in list(_sys.modules.values()):
        if not hasattr(mod, '__file__'):
            continue
        origin = getattr(mod, '__file__', None)
        if origin and _file_matcher.matches(origin):
            _slipcover_instance.register_module(mod)

            # Populate code_lines with ALL source lines (module-level +
            # function bodies) so the merge with the main process works
            # correctly.  The main process has module-level executed_lines
            # from import; workers supply function body executed_lines.
            abs_origin = str(Path(origin).resolve())
            if abs_origin not in _slipcover_instance.code_lines:
                try:
                    source_text = Path(origin).read_text()
                    code = compile(ast.parse(source_text), abs_origin, "exec")
                    _slipcover_instance.code_lines[abs_origin].update(
                        sc.Slipcover.lines_from_code(code)
                    )
                except Exception:
                    pass

            for func in sc.Slipcover.find_functions(mod.__dict__.values(), visited):
                _instrument_func(func)
            # Scan instance attributes of module-level objects for hidden
            # function references (e.g., Hatchet task wrappers store the
            # original function in obj._task.fn).
            _deep_scan_visited: set = set()
            for val in mod.__dict__.values():
                _deep_scan_functions(val, _instrument_func, _deep_scan_visited, _file_matcher, depth=3)
            # Scan containers (dicts, lists) in module and class dicts for
            # lambdas (e.g., column_formatters = {"key": lambda ...}).
            _scan_containers_for_functions(mod, _instrument_func, _file_matcher)


def _instrument_container_functions(container, instrument_fn, visited):
    """Instrument functions found in a dict/list/tuple/set, recursing into nested containers."""
    import types

    items = container.values() if isinstance(container, dict) else container
    for val in items:
        if isinstance(val, types.FunctionType):
            if id(val) not in visited:
                visited.add(id(val))
                instrument_fn(val)
        elif isinstance(val, (dict, list, tuple)):
            _instrument_container_functions(val, instrument_fn, visited)


def _scan_containers_for_functions(mod, instrument_fn, file_matcher):
    """Find functions stored in containers at module and class level."""
    visited: set = set()
    for val in mod.__dict__.values():
        # Module-level containers (dicts, lists)
        if isinstance(val, (dict, list, tuple)):
            _instrument_container_functions(val, instrument_fn, visited)
        # Class-level containers
        elif isinstance(val, type):
            for cls_val in val.__dict__.values():
                if isinstance(cls_val, (dict, list, tuple)):
                    _instrument_container_functions(cls_val, instrument_fn, visited)


def _deep_scan_functions(obj, instrument_fn, visited, file_matcher, depth):
    """Recursively scan object attributes for hidden function references."""
    if depth <= 0 or id(obj) in visited:
        return
    visited.add(id(obj))

    import types

    # Skip basic types, modules, and types themselves
    if isinstance(obj, (str, bytes, int, float, bool, type(None), type, types.ModuleType)):
        return

    try:
        obj_vars = vars(obj)
    except TypeError:
        return

    for val in obj_vars.values():
        if isinstance(val, types.FunctionType):
            instrument_fn(val)
        elif not isinstance(val, (str, bytes, int, float, bool, type(None), list, dict, set, tuple)):
            _deep_scan_functions(val, instrument_fn, visited, file_matcher, depth - 1)


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
