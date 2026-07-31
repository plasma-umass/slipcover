"""Read and apply slipcover configuration from .slipcoverrc or pyproject.toml."""

import argparse
import configparser
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


# Markers that indicate a project root; stop climbing here.
_ROOT_MARKERS = frozenset({".git", ".hg", ".svn", "setup.py", "setup.cfg"})

# Maximum number of parent directories to walk up from the start.
_MAX_WALK = 3

_RCFILE_NAME = ".slipcoverrc"

# coverage.py splits its settings between these two sections, and users
# reasonably guess either one; both are read, and neither is enforced.
_RCFILE_SECTIONS = ("run", "report")


def _find_upwards(filename, start):
    """Walks up from 'start' (default cwd) looking for 'filename'.

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
        candidate = directory / filename
        if candidate.is_file():
            return candidate

        # Don't climb above a project root, the user's home directory,
        # or more than _MAX_WALK levels.
        if (depth >= _MAX_WALK
                or directory == home
                or any((directory / m).exists() for m in _ROOT_MARKERS)):
            break

    return None


def find_pyproject(start=None):
    """Walks up from 'start' (default cwd) looking for pyproject.toml.

    See _find_upwards() for the boundaries that stop the search.
    """
    return _find_upwards("pyproject.toml", start)


def find_rcfile(start=None):
    """Walks up from 'start' (default cwd) looking for .slipcoverrc.

    Uses the same boundaries as find_pyproject().
    """
    return _find_upwards(_RCFILE_NAME, start)


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


def derive_configurable_keys(ap):
    """Returns the set of TOML keys that structurally look like they should
    be configurable via [tool.slipcover], based on a CLI ArgumentParser.

    This is a test oracle (see tests/test_config.py), not apply_config()'s
    runtime mechanism: the ideal config shape can genuinely diverge from
    the CLI's own flag shape (e.g. --json/--xml/--lcov as three CLI flags
    vs. a single hand-designed format = "xml" TOML setting), so the config
    surface stays hand-maintained in _BOOL_KEYS/_VALUE_KEYS below. This
    function exists purely to catch drift -- a new CLI flag with no
    matching entry anywhere in config.py -- as a loud test failure instead
    of a silently-unsupported key.

    A flag is excluded if it's positional (an invocation target/
    passthrough, not a setting), is the standard -h/--help or --version
    action, is argparse.SUPPRESS'd (the existing, deliberate signal this
    codebase already uses for dev-only or not-applicable-on-this-platform
    flags), belongs to a mutually exclusive group that also contains a
    positional member (a "what to run" mode selector, like -m/--merge/
    script, not a preference), or is --rcfile -- like --merge/-m/script,
    it picks which file to read rather than being a setting itself, but
    it isn't in a mutex group with a positional so the group-based check
    above doesn't catch it.
    """
    positional_dests = {a.dest for a in ap._actions if not a.option_strings}

    keys = set()
    for action in ap._actions:
        if not action.option_strings:
            continue
        if action.dest in ("help", "version", "rcfile"):
            continue
        if action.help == argparse.SUPPRESS:
            continue
        keys.add(action.dest.replace("_", "-"))

    for group in ap._mutually_exclusive_groups:
        dests = {a.dest for a in group._group_actions}
        if dests & positional_dests:
            keys -= {d.replace("_", "-") for d in dests}

    return keys


# Boolean flags (store_true in CLI). Excludes --silent/--dis/--debug/
# --dont-wrap-pytest: those are argparse.SUPPRESS'd, dev-only flags, not
# part of the stable, user-facing config surface.
_BOOL_KEYS = {
    "branch",
    "pretty-print",
    "immediate",
    "skip-covered",
}


def _coerce_comments(value):
    if not isinstance(value, list):
        value = [value]
    return [str(v) for v in value]


def _coerce_format(value):
    choices = ("text", "json", "xml", "lcov")
    if value not in choices:
        raise ValueError(f"must be one of {choices}, got {value!r}")
    return value


# Keys that take a value
_VALUE_KEYS = {
    "format": _coerce_format,
    "out": Path,
    "source": str,
    "omit": str,
    "fail-under": float,
    "threshold": int,
    "missing-width": int,
    "xml-package-depth": int,
    "lcov-test-name": str,
    "lcov-comments": _coerce_comments,
}


def _parse_rcfile_bool(key, value):
    try:
        return configparser.ConfigParser.BOOLEAN_STATES[value.strip().lower()]
    except KeyError:
        raise ValueError(
            f"key '{key}' must be a boolean, got '{value}'"
        ) from None


def read_rcfile(path=None):
    """Returns the slipcover settings held in a .slipcoverrc (INI) file.

    If 'path' is None, find_rcfile() is used to locate the file.
    The [run] and [report] sections are merged into a single dict shaped
    like read_config()'s, ready to hand to apply_config().
    Returns an empty dict when no file is found.
    """
    if path is None:
        path = find_rcfile()

    if path is None:
        return {}

    # No interpolation: a literal '%' in a value (an omit pattern, an
    # output name) is a plain character, not syntax to escape.
    # The default section is renamed out of the way so [DEFAULT] is read as
    # an ordinary -- and thus unknown -- section, rather than seeding every
    # other section's options and colliding with the duplicate check below.
    parser = configparser.ConfigParser(interpolation=None,
                                       default_section="__slipcover_no_default__")
    # utf-8-sig also accepts the BOM Notepad and PowerShell 5.1 write; it
    # is plain utf-8 otherwise.
    with open(path, encoding="utf-8-sig") as f:
        parser.read_file(f)

    for section in parser.sections():
        if section not in _RCFILE_SECTIONS:
            import warnings
            warnings.warn(f"Unknown {path} section: '[{section}]'")

    config = {}

    # A key repeated across the two sections is a legitimate override --
    # [report] is read last and wins -- so only same-section duplicates
    # are checked below.
    for section in _RCFILE_SECTIONS:
        if not parser.has_section(section):
            continue

        spellings = {}

        for name, value in parser.items(section):
            # configparser lowercases names; accept coverage.py's
            # underscores as well as slipcover's own hyphens.
            key = name.replace("_", "-")

            # configparser keeps 'fail-under' and 'fail_under' as distinct
            # options, so normalizing would let the second silently win;
            # an identically-spelled duplicate is a DuplicateOptionError.
            if key in spellings:
                raise ValueError(
                    f"[{section}] key '{key}' given twice, "
                    f"as '{spellings[key]}' and '{name}'"
                )
            spellings[key] = name

            if key in _BOOL_KEYS:
                # apply_config() requires a real bool, and INI has no types.
                config[key] = _parse_rcfile_bool(key, value)
            elif key in ("source", "omit"):
                # coverage.py writes these one per line; the CLI wants them
                # comma-separated.
                config[key] = ",".join(
                    item
                    for line in value.splitlines()
                    for item in (part.strip() for part in line.split(","))
                    if item
                )
            else:
                # Left as a string: apply_config() coerces known keys and
                # warns about the rest.
                config[key] = value

    return config


def apply_config(config, parsed_args, explicit_args=None,
                 source="[tool.slipcover]"):
    """Merges config values into parsed_args.

    Keys whose dest name appears in 'explicit_args' are skipped so that
    command-line flags always take precedence over the config file.
    'source' names where the config came from, for diagnostics.

    Raises TypeError if a value's type is wrong for its key, and
    ValueError if a value can't be coerced to the key's type.
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
                    f"{source} key '{key}' must be a boolean, got {type(value).__name__}"
                )
            setattr(parsed_args, dest, value)

        elif key in _VALUE_KEYS:
            # TOML's idiomatic way to express multiple values is an array;
            # join it the way --source/--omit's comma-separated CLI form
            # expects, rather than stringifying the Python list itself.
            if key in ("source", "omit") and isinstance(value, list):
                value = ",".join(str(v) for v in value)
            # Path("") is Path('.'), so an empty 'out' would only surface much
            # later, as an IsADirectoryError while writing the report.
            if key == "out" and isinstance(value, str) and not value.strip():
                raise ValueError(f"key '{key}': must not be empty")
            try:
                coerced = _VALUE_KEYS[key](value)
            except (ValueError, TypeError) as e:
                raise type(e)(f"key '{key}': {e}") from None
            setattr(parsed_args, dest, coerced)

        else:
            import warnings
            warnings.warn(f"Unknown {source} key: '{key}'")
