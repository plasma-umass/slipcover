"""Read and apply [tool.slipcover] configuration from pyproject.toml."""

from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


# Markers that indicate a project root; stop climbing here.
_ROOT_MARKERS = frozenset({".git", ".hg", ".svn", "setup.py", "setup.cfg"})

# Maximum number of parent directories to walk up from the start.
_MAX_WALK = 3


def find_pyproject(start=None):
    """Walks up from 'start' (default cwd) looking for pyproject.toml.

    The search stops and returns None when any of these boundaries is
    reached without finding the file:

    - a directory containing a VCS/project root marker
      (.git, .hg, .svn, setup.py, setup.cfg)
    - the user's home directory
    - more than _MAX_WALK parent directories have been visited
    """
    if start is None:
        start = Path.cwd()
    start = start.resolve()

    home = Path.home()

    for depth, directory in enumerate((start, *start.parents)):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate

        # Don't climb above a project root, the user's home directory,
        # or more than _MAX_WALK levels.
        if (depth >= _MAX_WALK
                or directory == home
                or any((directory / m).exists() for m in _ROOT_MARKERS)):
            break

    return None


def read_config(path=None):
    """Returns the [tool.slipcover] table from a pyproject.toml.

    If 'path' is None, find_pyproject() is used to locate the file.
    Returns an empty dict when no file is found or the section is absent.
    """
    if path is None:
        path = find_pyproject()

    if path is None:
        return {}

    with open(path, "rb") as f:
        data = tomllib.load(f)

    return data.get("tool", {}).get("slipcover", {})


# Boolean flags (store_true in CLI)
_BOOL_KEYS = {
    "branch",
    "json",
    "pretty-print",
    "xml",
    "immediate",
    "skip-covered",
    "silent",
    "dis",
    "debug",
    "dont-wrap-pytest",
}

# Keys that take a value
_VALUE_KEYS = {
    "out": Path,
    "source": str,
    "omit": str,
    "fail-under": float,
    "threshold": int,
    "missing-width": int,
    "xml-package-depth": int,
}


def apply_config(config, parsed_args, explicit_args=None):
    """Merges config values into parsed_args.

    Keys whose dest name appears in 'explicit_args' are skipped so that
    command-line flags always take precedence over the config file.

    Raises TypeError if a boolean key has a non-boolean value.
    Emits a UserWarning for unrecognised keys.
    """
    if explicit_args is None:
        explicit_args = set()

    for key, value in config.items():
        dest = key.replace("-", "_")

        # CLI flags always win
        if dest in explicit_args:
            continue

        if key in _BOOL_KEYS:
            if not isinstance(value, bool):
                raise TypeError(
                    f"[tool.slipcover] key '{key}' must be a boolean, got {type(value).__name__}"
                )
            setattr(parsed_args, dest, value)

        elif key in _VALUE_KEYS:
            setattr(parsed_args, dest, _VALUE_KEYS[key](value))

        else:
            import warnings
            warnings.warn(f"Unknown [tool.slipcover] key: '{key}'")
