# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SlipCover is a fast, near-zero-overhead Python code coverage tool. Unlike traditional coverage tools that use Python's tracing facilities, SlipCover uses just-in-time bytecode instrumentation (Python <3.12) or the `sys.monitoring` API (Python 3.12+) to track executed code with minimal overhead.

## Build and Development Commands

```bash
# Install in development/editable mode
pip install -e .

# Run all tests
pytest

# Run a single test file
pytest tests/test_coverage.py

# Run a specific test
pytest tests/test_coverage.py::test_function_name

# Run with pytest-forked (Unix only, useful for isolation)
pytest --forked

# Clean build artifacts
make clean

# Run benchmarks
make bench
```

## Running SlipCover

```bash
# Run a script with coverage
python -m slipcover myscript.py

# Run with a module (e.g., pytest)
python -m slipcover -m pytest

# Enable branch coverage
python -m slipcover --branch myscript.py

# Output JSON format
python -m slipcover --json --out coverage.json myscript.py
```

## Architecture

### Core Components

- **`src/slipcover/slipcover.py`**: Main `Slipcover` class that manages instrumentation and coverage collection. Contains version-specific code paths for Python <3.12 (bytecode rewriting) vs 3.12+ (sys.monitoring).

- **`src/slipcover/bytecode.py`**: Bytecode manipulation utilities (`Editor` class) for inserting probe calls into Python bytecode. Only used on Python <3.12.

- **`src/slipcover/branch.py`**: AST-based pre-instrumentation for branch coverage. The `preinstrument()` function inserts branch markers before compilation.

- **`src/slipcover/importer.py`**: Custom import machinery (`ImportManager`, `SlipcoverMetaPathFinder`, `SlipcoverLoader`) that intercepts module loading to instrument code. Also contains `FileMatcher` for source file filtering and `wrap_pytest()` for pytest integration.

- **`src/probe.cxx`**: C++ extension module providing low-overhead probe signaling for Python <3.12. Not used on 3.12+ (pure Python there).

### Python Version Handling

The codebase has significant branching based on Python version:
- **Python 3.12+**: Uses `sys.monitoring` API for coverage (no bytecode rewriting, no C++ extension)
- **Python <3.12**: Uses bytecode instrumentation via the `probe` C++ extension

Many functions have `if sys.version_info >= (3,12):` blocks with different implementations.

### Coverage Flow

1. **Script/module execution**: `__main__.py` parses args, creates `Slipcover` and `FileMatcher` instances
2. **Import interception**: `ImportManager` installs a meta path finder that wraps module loaders
3. **Instrumentation**: When matching modules load, their bytecode is instrumented via `Slipcover.instrument()`
4. **Branch coverage** (optional): AST pre-instrumentation via `branch.preinstrument()` adds branch markers before compilation
5. **Collection**: Probes signal line/branch execution to the `Slipcover` instance
6. **De-instrumentation** (Python <3.12): Once coverage is recorded, probes can be disabled to reduce overhead
7. **Reporting**: `get_coverage()` returns JSON-compatible coverage data; output can be text, JSON, or XML

### Test Structure

Tests are in `tests/` and use pytest:
- `test_coverage.py`: End-to-end coverage functionality tests
- `test_instrumentation.py`: Bytecode instrumentation tests
- `test_bytecode.py`: Low-level bytecode editor tests
- `test_branch.py`: Branch coverage and AST pre-instrumentation tests
- `test_importer.py`: Import machinery tests
