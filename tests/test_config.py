import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from slipcover.__main__ import build_parser
from slipcover.config import (apply_config, derive_configurable_keys, find_pyproject,
                              find_slipcover_toml, pyproject_has_config, read_config,
                              read_slipcover_toml)


def test_find_pyproject_in_cwd(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    assert find_pyproject(tmp_path) == tmp_path / "pyproject.toml"


def test_find_pyproject_walks_up(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    child = tmp_path / "a" / "b" / "c"
    child.mkdir(parents=True)
    assert find_pyproject(child) == tmp_path / "pyproject.toml"


def test_find_pyproject_returns_none(tmp_path):
    # _MAX_WALK bounds the search to a few levels under tmp_path, which
    # sits deep under a system temp dir with no pyproject.toml in any
    # ancestor -- deterministic without needing an explicit VCS marker.
    child = tmp_path / "nowhere"
    child.mkdir()
    assert find_pyproject(child) is None


def test_find_pyproject_stops_at_vcs_root(tmp_path):
    """Should not walk past a directory containing .git."""
    # Place pyproject.toml above the VCS root — it should NOT be found.
    (tmp_path / "pyproject.toml").write_text("")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()          # VCS root marker
    child = project / "src"
    child.mkdir()
    assert find_pyproject(child) is None


def test_find_pyproject_finds_file_at_vcs_root(tmp_path):
    """pyproject.toml sitting right next to .git should still be found."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "pyproject.toml").write_text("")
    child = project / "src"
    child.mkdir()
    assert find_pyproject(child) == project / "pyproject.toml"


def test_find_pyproject_stops_at_home(tmp_path, monkeypatch):
    """Should not walk above the user's home directory.

    Patches Path.home() directly rather than the HOME env var: Path.home()
    resolves via USERPROFILE on Windows, not HOME, so setting HOME alone
    has no effect there and doesn't control what find_pyproject() sees.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    # Place pyproject.toml above the fake home — should NOT be found.
    (tmp_path / "pyproject.toml").write_text("")
    child = fake_home / "projects" / "foo"
    child.mkdir(parents=True)
    assert find_pyproject(child) is None


def test_find_pyproject_stops_after_max_walk(tmp_path):
    """Should not walk more than _MAX_WALK levels up."""
    from slipcover.config import _MAX_WALK

    # Build a chain deeper than _MAX_WALK and place pyproject.toml at the top.
    (tmp_path / "pyproject.toml").write_text("")
    deep = tmp_path
    for i in range(_MAX_WALK + 1):
        deep = deep / f"d{i}"
    deep.mkdir(parents=True)
    assert find_pyproject(deep) is None

    # One level shallower should still find it.
    shallow = tmp_path
    for i in range(_MAX_WALK):
        shallow = shallow / f"s{i}"
    shallow.mkdir(parents=True)
    assert find_pyproject(shallow) == tmp_path / "pyproject.toml"


def test_find_slipcover_toml_in_cwd(tmp_path):
    (tmp_path / "slipcover.toml").write_text("")
    assert find_slipcover_toml(tmp_path) == tmp_path / "slipcover.toml"


def test_find_slipcover_toml_walks_up(tmp_path):
    (tmp_path / "slipcover.toml").write_text("")
    child = tmp_path / "a" / "b" / "c"
    child.mkdir(parents=True)
    assert find_slipcover_toml(child) == tmp_path / "slipcover.toml"


def test_find_slipcover_toml_returns_none(tmp_path):
    # The .git marker bounds the walk at tmp_path, so no slipcover.toml
    # that happens to exist above it can be reached.
    (tmp_path / ".git").mkdir()
    child = tmp_path / "nowhere"
    child.mkdir()
    assert find_slipcover_toml(child) is None


def test_find_slipcover_toml_stops_at_vcs_root(tmp_path):
    (tmp_path / "slipcover.toml").write_text("")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    child = project / "src"
    child.mkdir()
    assert find_slipcover_toml(child) is None


def test_find_slipcover_toml_finds_file_at_vcs_root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "slipcover.toml").write_text("")
    child = project / "src"
    child.mkdir()
    assert find_slipcover_toml(child) == project / "slipcover.toml"


def test_find_slipcover_toml_stops_at_home(tmp_path, monkeypatch):
    """Patches Path.home() directly -- see test_find_pyproject_stops_at_home."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    (tmp_path / "slipcover.toml").write_text("")
    child = fake_home / "projects" / "foo"
    child.mkdir(parents=True)
    assert find_slipcover_toml(child) is None


def test_find_slipcover_toml_stops_after_max_walk(tmp_path):
    from slipcover.config import _MAX_WALK

    (tmp_path / "slipcover.toml").write_text("")
    deep = tmp_path
    for i in range(_MAX_WALK + 1):
        deep = deep / f"d{i}"
    deep.mkdir(parents=True)
    assert find_slipcover_toml(deep) is None

    shallow = tmp_path
    for i in range(_MAX_WALK):
        shallow = shallow / f"s{i}"
    shallow.mkdir(parents=True)
    assert find_slipcover_toml(shallow) == tmp_path / "slipcover.toml"


def test_find_stops_when_out_of_parent_directories(tmp_path, monkeypatch):
    """The walk can also end by running out of parents, without reaching
    any of the boundaries that break out of it.

    The filesystem root has no parents, so it exercises that exit in one
    iteration. The root markers are cleared and home pointed elsewhere so
    whatever the machine happens to keep at the root can't end the walk
    early instead.
    """
    import slipcover.config as config

    monkeypatch.setattr(config, "_ROOT_MARKERS", frozenset())
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    root = Path(tmp_path.anchor)

    assert find_slipcover_toml(root) is None
    assert find_pyproject(root) is None


def test_read_slipcover_toml_top_level_keys(tmp_path):
    """No enclosing header: the file holds what would have gone inside
    [tool.slipcover], and TOML gives every value its real type.
    """
    rc = tmp_path / "slipcover.toml"
    rc.write_text(
        "branch = true\n"
        "fail-under = 80.5\n"
        "threshold = 75\n"
        'out = "coverage.json"\n'
    )
    assert read_slipcover_toml(rc) == {
        "branch": True, "fail-under": 80.5, "threshold": 75, "out": "coverage.json",
    }


def test_read_slipcover_toml_matches_pyproject_table(tmp_path):
    """The two files' formats are identical, so the same settings written
    each way must produce the same dict -- that equivalence is the whole
    design, and it's what lets both feed one apply_config().
    """
    settings = 'branch = true\nsource = ["src", "lib"]\nfail-under = 80.0\n'
    rc = tmp_path / "slipcover.toml"
    rc.write_text(settings)
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[tool.slipcover]\n" + settings)

    assert read_slipcover_toml(rc) == read_config(toml)


def test_read_slipcover_toml_arrays_stay_lists(tmp_path):
    """TOML arrays arrive as lists; apply_config joins them for the CLI."""
    rc = tmp_path / "slipcover.toml"
    rc.write_text('source = ["src", "lib"]\nomit = ["tests/*", "*.pyc"]\n')
    cfg = read_slipcover_toml(rc)
    assert cfg == {"source": ["src", "lib"], "omit": ["tests/*", "*.pyc"]}

    args = _make_args()
    apply_config(cfg, args)
    assert args.source == "src,lib"
    assert args.omit == "tests/*,*.pyc"


def test_read_slipcover_toml_bad_type_raises_in_apply_config(tmp_path):
    """TOML has real types, so a quoted boolean is a type error rather than
    the string-coercion INI would have needed.
    """
    rc = tmp_path / "slipcover.toml"
    rc.write_text('branch = "true"\n')
    with pytest.raises(TypeError, match="'branch' must be a boolean"):
        apply_config(read_slipcover_toml(rc), _make_args())


def test_read_slipcover_toml_bad_numeric_raises_in_apply_config(tmp_path):
    rc = tmp_path / "slipcover.toml"
    rc.write_text('fail-under = "not-a-number"\n')
    with pytest.raises(ValueError, match="key 'fail-under'"):
        apply_config(read_slipcover_toml(rc), _make_args())


def test_read_config_bad_numeric_names_the_key(tmp_path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text('[tool.slipcover]\nthreshold = "high"\n')
    with pytest.raises(ValueError, match="key 'threshold'"):
        apply_config(read_config(toml), _make_args())


def test_read_slipcover_toml_unknown_key_passes_through(tmp_path):
    """One code path for the unknown-key warning: apply_config's."""
    rc = tmp_path / "slipcover.toml"
    rc.write_text("no-such-key = 42\n")
    cfg = read_slipcover_toml(rc)
    assert cfg == {"no-such-key": 42}

    with pytest.warns(UserWarning, match="Unknown.*no-such-key"):
        apply_config(cfg, _make_args())


def test_read_slipcover_toml_tool_header_is_an_unknown_key(tmp_path):
    """Carrying the pyproject header over into slipcover.toml is the likely
    mistake; it nests everything under 'tool', which warns rather than
    silently configuring nothing.
    """
    rc = tmp_path / "slipcover.toml"
    rc.write_text("[tool.slipcover]\nbranch = true\n")
    args = _make_args()
    with pytest.warns(UserWarning, match="Unknown.*'tool'"):
        apply_config(read_slipcover_toml(rc), args)
    assert args.branch is False


def test_read_slipcover_toml_malformed_raises(tmp_path):
    """TOMLDecodeError subclasses ValueError, which is what __main__ catches
    to turn a malformed file into a clean error instead of a traceback.
    """
    rc = tmp_path / "slipcover.toml"
    rc.write_text("branch = \n")
    with pytest.raises(ValueError):
        read_slipcover_toml(rc)


def test_read_slipcover_toml_empty_file(tmp_path):
    rc = tmp_path / "slipcover.toml"
    rc.write_text("")
    assert read_slipcover_toml(rc) == {}


def test_read_slipcover_toml_no_file(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()  # bound the walk; see test_find_slipcover_toml_returns_none
    monkeypatch.chdir(tmp_path)
    assert read_slipcover_toml(None) == {}


def test_read_slipcover_toml_discovers_from_cwd(tmp_path, monkeypatch):
    (tmp_path / "slipcover.toml").write_text('branch = true\nsource = "src"\n')
    monkeypatch.chdir(tmp_path)
    assert read_slipcover_toml() == {"branch": True, "source": "src"}


@pytest.mark.parametrize("text,expected", [
    ('[tool.slipcover]\nbranch = true\n', True),
    ('[tool.slipcover]\n', False),          # present but empty
    ('[tool.other]\nbranch = true\n', False),   # no slipcover table
    ('', False),
    ('branch = [\n', False),                # malformed: ignored, not raised
])
def test_pyproject_has_config(tmp_path, text, expected):
    toml = tmp_path / "pyproject.toml"
    toml.write_text(text)
    assert pyproject_has_config(toml) is expected


def test_pyproject_has_config_missing_file(tmp_path):
    assert pyproject_has_config(tmp_path / "nope.toml") is False


def test_read_config_full(tmp_path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[tool.slipcover]\nbranch = true\nsource = \"src\"\nfail-under = 80.0\n")
    cfg = read_config(toml)
    assert cfg == {"branch": True, "source": "src", "fail-under": 80.0}


def test_read_config_missing_section(tmp_path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[project]\nname = 'foo'\n")
    assert read_config(toml) == {}


def test_read_config_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert read_config(None) == {}


def test_read_config_all_keys(tmp_path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text(
        "[tool.slipcover]\n"
        "branch = true\n"
        "json = true\n"
        "pretty-print = true\n"
        "xml = false\n"
        "xml-package-depth = 3\n"
        'out = "coverage.json"\n'
        'source = "src,lib"\n'
        'omit = "tests/*"\n'
        "immediate = true\n"
        "skip-covered = true\n"
        "fail-under = 90.0\n"
        "threshold = 75\n"
        "missing-width = 120\n"
    )
    cfg = read_config(toml)
    assert cfg["branch"] is True
    assert cfg["json"] is True
    assert cfg["pretty-print"] is True
    assert cfg["xml"] is False
    assert cfg["xml-package-depth"] == 3
    assert cfg["out"] == "coverage.json"
    assert cfg["source"] == "src,lib"
    assert cfg["omit"] == "tests/*"
    assert cfg["immediate"] is True
    assert cfg["skip-covered"] is True
    assert cfg["fail-under"] == 90.0
    assert cfg["threshold"] == 75
    assert cfg["missing-width"] == 120


def test_config_keys_match_cli_flags():
    """Catches drift between config.py's hand-maintained _BOOL_KEYS/
    _VALUE_KEYS and the actual CLI flags in __main__.py -- e.g. --lcov was
    added to the CLI without a matching config.py update. If this fails:
    add the new flag to _BOOL_KEYS/_VALUE_KEYS (most common case), or if
    it's deliberately not configurable, exclude it via argparse.SUPPRESS
    in build_parser() (matching --silent/--dis/etc), or represent it
    differently on purpose (e.g. --json/--xml/--lcov could map to a single
    hand-designed format = ... key instead of one key per flag).
    """
    from slipcover.config import _BOOL_KEYS, _VALUE_KEYS

    expected = derive_configurable_keys(build_parser())
    actual = set(_BOOL_KEYS) | set(_VALUE_KEYS)

    missing = expected - actual
    assert not missing, f"CLI flags with no matching config.py key: {sorted(missing)}"


@pytest.mark.skipif(sys.version_info[:2] != (3, 12), reason=(
    "argparse's own output changed across Python versions (e.g. the "
    "'options:' vs 'optional arguments:' heading, 3.9 vs 3.10+) -- "
    "README.md's transcript is captured from 3.12, so only compare there"
))
def test_readme_help_matches_cli():
    """Catches drift between the '--help' transcript embedded in README.md's
    "Command-line options" section and the actual current output -- e.g.
    a flag's help= text changing without the README being refreshed. If
    this fails: run tools/update_readme_help.py (with a 3.12 interpreter)
    and commit the result.
    """
    import re

    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    m = re.search(
        r'\[//\]: # \(help-output\)\n```console\n\$ python3 -m slipcover --help\n(.*?)\n```',
        readme, flags=re.S
    )
    assert m, "README.md is missing its [//]: # (help-output) marked section"

    assert m.group(1) == build_parser().format_help().rstrip('\n')


def _make_args(**kwargs):
    defaults = dict(
        branch=False, format='text', pretty_print=False,
        xml_package_depth=99, lcov_test_name=None, lcov_comments=None,
        out=None, source=None, omit=None,
        immediate=False, skip_covered=False, fail_under=0,
        threshold=50, missing_width=80, silent=False, dis=False,
        debug=False, dont_wrap_pytest=False, sigterm=False,
        exclude_lines=None, exclude_also=None,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_apply_config_sigterm():
    args = _make_args()
    apply_config({"sigterm": True}, args)
    assert args.sigterm is True


def test_apply_config_lcov_keys():
    args = _make_args()
    apply_config({"format": "lcov", "lcov-test-name": "Suite", "lcov-comments": ["a", "b"]}, args)
    assert args.format == "lcov"
    assert args.lcov_test_name == "Suite"
    assert args.lcov_comments == ["a", "b"]


def test_apply_config_lcov_comments_scalar_becomes_list():
    args = _make_args()
    apply_config({"lcov-comments": "just one"}, args)
    assert args.lcov_comments == ["just one"]


def test_apply_config_exclude_lines():
    args = _make_args()
    apply_config({"exclude-lines": ["foo", "bar"]}, args)
    assert args.exclude_lines == ["foo", "bar"]


def test_apply_config_exclude_lines_scalar_becomes_list():
    args = _make_args()
    apply_config({"exclude-lines": "just one"}, args)
    assert args.exclude_lines == ["just one"]


def test_apply_config_exclude_also():
    args = _make_args()
    apply_config({"exclude-also": ["foo", "bar"]}, args)
    assert args.exclude_also == ["foo", "bar"]


def test_apply_config_format_bad_value_raises():
    args = _make_args()
    with pytest.raises(ValueError, match="must be one of"):
        apply_config({"format": "bogus"}, args)


@pytest.mark.parametrize("key", ["json", "xml", "lcov"])
def test_apply_config_old_boolean_format_keys_now_unknown(key):
    """json/xml/lcov as individual boolean config keys are no longer
    recognized -- format = "..." replaces them (see build_parser()).
    """
    args = _make_args()
    with pytest.warns(UserWarning, match="Unknown"):
        apply_config({key: True}, args)


def test_apply_config_sets_values():
    args = _make_args()
    apply_config({"branch": True, "fail-under": 85.5, "source": "src"}, args)
    assert args.branch is True
    assert args.fail_under == 85.5
    assert args.source == "src"


def test_apply_config_cli_precedence():
    args = _make_args(branch=True)
    apply_config({"branch": False, "fail-under": 90.0}, args, explicit_args={"branch"})
    assert args.branch is True      # explicit, kept
    assert args.fail_under == 90.0   # not explicit, applied


def test_apply_config_out_becomes_path():
    args = _make_args()
    apply_config({"out": "coverage.json"}, args)
    assert isinstance(args.out, Path)
    assert str(args.out) == "coverage.json"


def test_apply_config_type_error_on_bad_bool():
    args = _make_args()
    with pytest.raises(TypeError, match="must be a boolean"):
        apply_config({"branch": "yes"}, args)


def test_apply_config_type_error_names_the_key(tmp_path):
    """A coercion TypeError names its key too -- Path(3)'s own message
    doesn't say which setting was wrong. It stays a TypeError.
    """
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[tool.slipcover]\nout = 3\n")
    with pytest.raises(TypeError, match="key 'out'"):
        apply_config(read_config(toml), _make_args())


@pytest.mark.parametrize("value", ["", "   "])
def test_apply_config_empty_out_raises(value):
    """Path("") is Path('.'); left alone it fails at exit with an
    IsADirectoryError instead of a config error.
    """
    args = _make_args()
    with pytest.raises(ValueError, match="key 'out'"):
        apply_config({"out": value}, args)
    assert args.out is None


def test_apply_config_empty_out_from_config_file_raises(tmp_path):
    rc = tmp_path / "slipcover.toml"
    rc.write_text('out = ""\n')
    assert read_slipcover_toml(rc) == {"out": ""}
    with pytest.raises(ValueError, match="key 'out'"):
        apply_config(read_slipcover_toml(rc), _make_args())


def test_apply_config_source_array_is_joined():
    """TOML's idiomatic way to express multiple values is an array;
    join it the same way --source's comma-separated CLI form expects,
    instead of stringifying the Python list representation.
    """
    args = _make_args()
    apply_config({"source": ["src", "lib"]}, args)
    assert args.source == "src,lib"


def test_apply_config_omit_array_is_joined():
    args = _make_args()
    apply_config({"omit": ["tests/*", "*.pyc"]}, args)
    assert args.omit == "tests/*,*.pyc"



def test_apply_config_warns_unknown_key():
    args = _make_args()
    with pytest.warns(UserWarning, match=r"Unknown \[tool\.slipcover\] key: 'no-such-key'"):
        apply_config({"no-such-key": 42}, args)


def test_apply_config_unknown_key_names_its_source():
    """The warning must name the file the key actually came from."""
    args = _make_args()
    with pytest.warns(UserWarning, match=r"Unknown slipcover\.toml key: 'brunch'"):
        apply_config({"brunch": "true"}, args, source="slipcover.toml")


@pytest.mark.parametrize("key", ["silent", "dis", "debug", "dont-wrap-pytest"])
def test_apply_config_rejects_dev_only_flags(key):
    """silent/dis/debug/dont-wrap-pytest are argparse.SUPPRESS'd,
    dev-only flags (see __main__.py) -- they shouldn't be part of the
    stable, user-facing [tool.slipcover] config surface, same as
    --merge/-m/the script argument/--version/--help are already excluded.
    """
    args = _make_args()
    with pytest.warns(UserWarning, match="Unknown"):
        apply_config({key: True}, args)
    assert getattr(args, key.replace("-", "_")) is False  # left at default


def test_apply_config_int_coercion():
    args = _make_args()
    apply_config({"threshold": 75, "missing-width": 100, "xml-package-depth": 5}, args)
    assert args.threshold == 75
    assert args.missing_width == 100
    assert args.xml_package_depth == 5


def test_apply_config_skip_covered_and_pretty_print():
    args = _make_args()
    apply_config({"skip-covered": True, "pretty-print": True}, args)
    assert args.skip_covered is True
    assert args.pretty_print is True


def test_integration_pyproject_applied(tmp_path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[tool.slipcover]\nbranch = true\nfail-under = 95.0\nsource = \"mypackage\"\n")
    cfg = read_config(toml)
    args = _make_args()
    apply_config(cfg, args)
    assert args.branch is True
    assert args.fail_under == 95.0
    assert args.source == "mypackage"


def test_integration_empty_section(tmp_path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[tool.slipcover]\n")
    cfg = read_config(toml)
    args = _make_args()
    apply_config(cfg, args)
    assert args.branch is False
    assert args.fail_under == 0


def test_cli_malformed_toml_clean_error(tmp_path, monkeypatch):
    """A broken pyproject.toml must produce a clean, informative CLI error
    (matching black/ruff/mypy/pytest convention) -- not an unhandled
    Python traceback.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[tool.slipcover\nbranch = true\n")
    (tmp_path / "script.py").write_text("x = 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode != 0
    assert 'Traceback' not in p.stderr
    assert 'pyproject.toml' in p.stderr


def test_cli_bad_config_value_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = "not-a-number"\n')
    (tmp_path / "script.py").write_text("x = 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode != 0
    assert 'Traceback' not in p.stderr


# foo()'s body is never called, so these scripts come out 50% covered.
_HALF_COVERED = "def foo():\n    pass\n"


def test_cli_valid_pyproject_config_applied(tmp_path, monkeypatch):
    """Sanity check that a real subprocess run actually reads and applies
    pyproject.toml config end-to-end (no test currently exercises this).
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 100.0\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 2  # fail-under from pyproject.toml kicks in
    assert 'Traceback' not in p.stderr


def test_cli_lcov_config_applied(tmp_path, monkeypatch):
    """The lcov/lcov-test-name/lcov-comments keys added to close the drift
    this test oracle caught actually work end-to-end, not just at the
    apply_config() unit level.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.slipcover]\n'
        'format = "lcov"\n'
        'lcov-test-name = "MySuite"\n'
        'lcov-comments = ["hello", "world"]\n'
    )
    (tmp_path / "script.py").write_text("x = 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0
    assert '# hello' in p.stdout
    assert '# world' in p.stdout
    assert 'TN:MySuite' in p.stdout
    assert 'SF:script.py' in p.stdout


def test_cli_json_and_xml_together_is_an_error(tmp_path, monkeypatch):
    """--json and --xml are alternative output formats -- picking both
    should be a clear CLI error, not a silent pick of whichever the
    if/elif/else chain in printit() checks first.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text("x = 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--xml', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode != 0
    assert 'Traceback' not in p.stderr


def test_cli_json_alone_still_works(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text("x = 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0
    assert 'Traceback' not in p.stderr


def test_cli_format_json_equivalent_to_json_flag(tmp_path, monkeypatch):
    """--format=json is the primary spelling; --json is a shortcut alias
    for it (dest='format' is shared) -- both must produce identical output.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text("x = 1\n")

    p_flag = subprocess.run([sys.executable, '-m', 'slipcover', '--json', 'script.py'],
                             capture_output=True, text=True)
    p_format = subprocess.run([sys.executable, '-m', 'slipcover', '--format=json', 'script.py'],
                               capture_output=True, text=True)

    assert p_flag.returncode == 0 == p_format.returncode

    flag_out = json.loads(p_flag.stdout)
    format_out = json.loads(p_format.stdout)
    del flag_out['meta']['timestamp'], format_out['meta']['timestamp']
    assert flag_out == format_out


def test_cli_format_and_alias_together_is_an_error(tmp_path, monkeypatch):
    """--format=json and --xml are different actions sharing the same
    dest -- mixing the new and old spellings must still be rejected.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text("x = 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--format=json', '--xml', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode != 0
    assert 'Traceback' not in p.stderr


def test_cli_format_bad_choice_is_a_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text("x = 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--format=bogus', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode != 0
    assert 'Traceback' not in p.stderr


def test_cli_valid_slipcover_toml_applied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "slipcover.toml").write_text("fail-under = 100.0\n")
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 2  # fail-under from slipcover.toml kicks in
    assert 'Traceback' not in p.stderr


def test_cli_slipcover_toml_beats_pyproject(tmp_path, monkeypatch):
    """A slipcover.toml wins outright; [tool.slipcover] is ignored entirely."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 100.0\n')
    (tmp_path / "slipcover.toml").write_text("fail-under = 1.0\n")
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0  # pyproject's fail-under would have given 2
    assert 'Traceback' not in p.stderr


def test_cli_slipcover_toml_in_parent_beats_pyproject_in_cwd(tmp_path, monkeypatch):
    """The two files are discovered independently, so a slipcover.toml found
    further up still wins over a nearer pyproject.toml.
    """
    (tmp_path / "slipcover.toml").write_text("fail-under = 100.0\n")
    cwd = tmp_path / "project"
    cwd.mkdir()
    (cwd / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 1.0\n')
    (cwd / "script.py").write_text(_HALF_COVERED)
    monkeypatch.chdir(cwd)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 2  # pyproject's fail-under would have given 0
    assert 'Traceback' not in p.stderr


def test_cli_empty_slipcover_toml_still_shadows_pyproject(tmp_path, monkeypatch):
    """Precedence is per file, not per key: the mere presence of a
    slipcover.toml takes [tool.slipcover] out of play, even when the file
    sets nothing at all.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "slipcover.toml").write_text("")
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 100.0\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0  # pyproject's fail-under would have given 2
    assert 'Traceback' not in p.stderr


def test_cli_slipcover_toml_does_not_merge_with_pyproject(tmp_path, monkeypatch):
    """The keys slipcover.toml doesn't mention fall back to the defaults,
    not to [tool.slipcover].
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "slipcover.toml").write_text('branch = true\nformat = "json"\n')
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 100.0\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0         # pyproject's fail-under was dropped
    assert 'Traceback' not in p.stderr
    cov = json.loads(p.stdout)       # slipcover.toml's own keys did apply
    assert cov['meta']['branch_coverage'] is True


def test_cli_shadowed_pyproject_table_warns(tmp_path, monkeypatch):
    """Dropping a table that holds real settings is worth saying out loud;
    the warning names both files so it's clear which one is in play.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "slipcover.toml").write_text("branch = true\n")
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 100.0\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0
    assert 'Traceback' not in p.stderr
    assert 'slipcover.toml' in p.stderr
    assert 'pyproject.toml' in p.stderr
    assert '[tool.slipcover]' in p.stderr


def test_cli_no_shadow_warning_without_a_table(tmp_path, monkeypatch):
    """A pyproject.toml with no [tool.slipcover] table isn't being shadowed
    -- nearly every project has one, so warning there would be noise.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "slipcover.toml").write_text("branch = true\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "whatever"\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0
    assert 'ignored' not in p.stderr


def test_cli_slipcover_toml_wins_on_conflicting_key(tmp_path, monkeypatch):
    """Where both files set the same key, slipcover.toml's value is used."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "slipcover.toml").write_text("fail-under = 1.0\n")
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 100.0\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0  # slipcover.toml's 1.0 beat pyproject's 100.0
    assert 'Traceback' not in p.stderr


def test_cli_unknown_slipcover_toml_key_warning_names_the_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "slipcover.toml").write_text("brunch = true\n")
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0
    assert "brunch" in p.stderr
    assert "slipcover.toml" in p.stderr
    assert "[tool.slipcover]" not in p.stderr


def test_cli_unknown_pyproject_key_warning_names_the_table(tmp_path, monkeypatch):
    """Symmetric with the slipcover.toml case: the warning must name where
    the key came from.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nbrunch = true\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0
    assert "brunch" in p.stderr
    assert "[tool.slipcover]" in p.stderr


def test_cli_no_config_file_of_either_kind(tmp_path, monkeypatch):
    """The commonest invocation: neither slipcover.toml nor pyproject.toml
    exists, so nothing is configured and the run proceeds normally.
    """
    (tmp_path / ".git").mkdir()  # bound the walk; see test_find_slipcover_toml_returns_none
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0     # no fail-under configured
    assert 'Traceback' not in p.stderr
    assert 'script.py' in p.stdout
    assert '50' in p.stdout      # the usual table, half covered


def test_cli_flag_beats_slipcover_toml(tmp_path, monkeypatch):
    """--fail-under overrides slipcover.toml's value, while 'format' -- which no
    flag contradicts -- still takes effect, proving the file was read.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "slipcover.toml").write_text('fail-under = 100.0\nformat = "json"\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--fail-under', '1', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0    # slipcover.toml's fail-under would have given 2
    assert 'Traceback' not in p.stderr
    assert json.loads(p.stdout)["files"]    # slipcover.toml's format = "json" did apply


def test_cli_flag_beats_pyproject(tmp_path, monkeypatch):
    """--fail-under overrides pyproject.toml's value, while 'format' -- which no
    flag contradicts -- still takes effect, proving pyproject.toml was read.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.slipcover]\nfail-under = 100.0\nformat = "json"\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--fail-under', '1', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0    # pyproject's fail-under would have given 2
    assert 'Traceback' not in p.stderr
    assert json.loads(p.stdout)["files"]    # pyproject's format = "json" did apply


def test_cli_flag_applies_with_no_config_file(tmp_path, monkeypatch):
    """With neither config file present there is nothing to override, but the
    flag itself must still take effect rather than falling back to defaults.
    """
    (tmp_path / ".git").mkdir()  # bound the walk; see test_find_slipcover_toml_returns_none
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--fail-under', '100', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 2    # the flag's fail-under kicked in; default is 0
    assert 'Traceback' not in p.stderr


def test_cli_malformed_slipcover_toml_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "slipcover.toml").write_text("branch = \n")
    (tmp_path / "script.py").write_text("x = 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode != 0
    assert 'Traceback' not in p.stderr
    assert 'slipcover.toml' in p.stderr


def test_cli_bad_slipcover_toml_value_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "slipcover.toml").write_text('branch = "maybe"\n')
    (tmp_path / "script.py").write_text("x = 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode != 0
    assert 'Traceback' not in p.stderr
    assert 'slipcover.toml' in p.stderr
