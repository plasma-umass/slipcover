import argparse
import configparser
import json
import subprocess
import sys
from pathlib import Path

import pytest

from slipcover.__main__ import build_parser
from slipcover.config import (apply_config, derive_configurable_keys, find_pyproject,
                              find_rcfile, read_config, read_rcfile)


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


def test_find_rcfile_in_cwd(tmp_path):
    (tmp_path / ".slipcoverrc").write_text("")
    assert find_rcfile(tmp_path) == tmp_path / ".slipcoverrc"


def test_find_rcfile_walks_up(tmp_path):
    (tmp_path / ".slipcoverrc").write_text("")
    child = tmp_path / "a" / "b" / "c"
    child.mkdir(parents=True)
    assert find_rcfile(child) == tmp_path / ".slipcoverrc"


def test_find_rcfile_returns_none(tmp_path):
    # The .git marker bounds the walk at tmp_path, so no .slipcoverrc
    # that happens to exist above it can be reached.
    (tmp_path / ".git").mkdir()
    child = tmp_path / "nowhere"
    child.mkdir()
    assert find_rcfile(child) is None


def test_find_rcfile_stops_at_vcs_root(tmp_path):
    (tmp_path / ".slipcoverrc").write_text("")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    child = project / "src"
    child.mkdir()
    assert find_rcfile(child) is None


def test_find_rcfile_finds_file_at_vcs_root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".slipcoverrc").write_text("")
    child = project / "src"
    child.mkdir()
    assert find_rcfile(child) == project / ".slipcoverrc"


def test_find_rcfile_stops_at_home(tmp_path, monkeypatch):
    """Patches Path.home() directly -- see test_find_pyproject_stops_at_home."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    (tmp_path / ".slipcoverrc").write_text("")
    child = fake_home / "projects" / "foo"
    child.mkdir(parents=True)
    assert find_rcfile(child) is None


def test_find_rcfile_stops_after_max_walk(tmp_path):
    from slipcover.config import _MAX_WALK

    (tmp_path / ".slipcoverrc").write_text("")
    deep = tmp_path
    for i in range(_MAX_WALK + 1):
        deep = deep / f"d{i}"
    deep.mkdir(parents=True)
    assert find_rcfile(deep) is None

    shallow = tmp_path
    for i in range(_MAX_WALK):
        shallow = shallow / f"s{i}"
    shallow.mkdir(parents=True)
    assert find_rcfile(shallow) == tmp_path / ".slipcoverrc"


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

    assert find_rcfile(root) is None
    assert find_pyproject(root) is None


@pytest.mark.parametrize("text,expected", [
    ("true", True), ("True", True), ("TRUE", True),
    ("yes", True), ("on", True), ("1", True),
    ("false", False), ("False", False),
    ("no", False), ("off", False), ("0", False),
])
def test_read_rcfile_boolean_states(tmp_path, text, expected):
    rc = tmp_path / ".slipcoverrc"
    rc.write_text(f"[run]\nbranch = {text}\n")
    assert read_rcfile(rc) == {"branch": expected}


def test_read_rcfile_bad_boolean_raises(tmp_path):
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[run]\nbranch = maybe\n")
    with pytest.raises(ValueError, match="'branch' must be a boolean"):
        read_rcfile(rc)


def test_read_rcfile_values_stay_strings_and_apply_config_coerces(tmp_path):
    rc = tmp_path / ".slipcoverrc"
    rc.write_text(
        "[report]\n"
        "fail-under = 80.5\n"
        "threshold = 75\n"
        "missing-width = 120\n"
        "xml-package-depth = 3\n"
        "out = coverage.json\n"
    )
    cfg = read_rcfile(rc)
    assert cfg["fail-under"] == "80.5"     # INI has no types; apply_config coerces

    args = _make_args()
    apply_config(cfg, args)
    assert args.fail_under == 80.5
    assert args.threshold == 75
    assert args.missing_width == 120
    assert args.xml_package_depth == 3
    assert isinstance(args.out, Path)
    assert str(args.out) == "coverage.json"


def test_read_rcfile_bad_numeric_raises_in_apply_config(tmp_path):
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[report]\nfail-under = not-a-number\n")
    with pytest.raises(ValueError, match="key 'fail-under'"):
        apply_config(read_rcfile(rc), _make_args())


def test_read_config_bad_numeric_names_the_key(tmp_path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text('[tool.slipcover]\nthreshold = "high"\n')
    with pytest.raises(ValueError, match="key 'threshold'"):
        apply_config(read_config(toml), _make_args())


@pytest.mark.parametrize("value,expected", [
    ("src,lib", "src,lib"),
    ("src, lib", "src,lib"),
    ("\n    src\n    lib", "src,lib"),
    ("\n    src\n\n    lib\n", "src,lib"),
    ("\n    src, lib\n    extra", "src,lib,extra"),
])
def test_read_rcfile_source_forms(tmp_path, value, expected):
    rc = tmp_path / ".slipcoverrc"
    rc.write_text(f"[run]\nsource ={value}\n")
    assert read_rcfile(rc) == {"source": expected}


def test_read_rcfile_omit_newline_separated(tmp_path):
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[run]\nomit =\n    tests/*\n    *.pyc\n")
    cfg = read_rcfile(rc)
    assert cfg == {"omit": "tests/*,*.pyc"}

    args = _make_args()
    apply_config(cfg, args)
    assert args.omit == "tests/*,*.pyc"


def test_read_rcfile_underscore_keys_normalized(tmp_path):
    """coverage.py spells these with underscores; slipcover with hyphens."""
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[report]\nfail_under = 80.0\nskip_covered = yes\nmissing_width = 100\n")
    assert read_rcfile(rc) == {
        "fail-under": "80.0", "skip-covered": True, "missing-width": "100",
    }


def test_read_rcfile_merges_both_sections(tmp_path):
    """Neither section's membership is enforced -- a key in the 'wrong'
    one still works.
    """
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[run]\nfail-under = 80.0\n\n[report]\nbranch = true\n")
    assert read_rcfile(rc) == {"fail-under": "80.0", "branch": True}


def test_read_rcfile_percent_is_literal(tmp_path):
    """A '%' is a plain character, not interpolation syntax to escape."""
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[run]\nomit = a%b,*%(name)s*\n\n[report]\nout = cov-%d.json\n")
    assert read_rcfile(rc) == {"omit": "a%b,*%(name)s*", "out": "cov-%d.json"}


def test_read_rcfile_mixed_spelling_duplicate_raises(tmp_path):
    """Hyphen/underscore spellings of one key are distinct options to
    configparser; merging them would let the second silently win.
    """
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[run]\nfail-under = 10\nfail_under = 90\n")
    with pytest.raises(ValueError, match=r"fail-under.*fail-under.*fail_under"):
        read_rcfile(rc)


def test_read_rcfile_same_key_in_both_sections_overrides(tmp_path):
    """Across sections it's a legitimate override, not a duplicate:
    [report] is read last and wins.
    """
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[run]\nfail-under = 10\n\n[report]\nfail_under = 90\n")
    assert read_rcfile(rc) == {"fail-under": "90"}


def test_read_rcfile_warns_unknown_section(tmp_path):
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[nonsense]\nbranch = true\n")
    with pytest.warns(UserWarning, match=r"Unknown .* section"):
        assert read_rcfile(rc) == {}


def test_read_rcfile_unknown_section_warning_names_the_file(tmp_path):
    """The warning must name the file read, not the default rc file name."""
    rc = tmp_path / "other.rc"
    rc.write_text("[nonsense]\nbranch = true\n")
    with pytest.warns(UserWarning, match=r"Unknown .*other\.rc section: '\[nonsense\]'"):
        read_rcfile(rc)


def test_read_rcfile_default_section_does_not_seed_other_sections(tmp_path):
    """[DEFAULT] is read as an ordinary unknown section: its options stay
    out of [run], so a section value is neither shadowed nor mistaken for
    a mixed-spelling duplicate.
    """
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[DEFAULT]\nfail_under = 10\n\n[run]\nfail-under = 20\n")
    with pytest.warns(UserWarning, match=r"Unknown .* section: '\[DEFAULT\]'"):
        assert read_rcfile(rc) == {"fail-under": "20"}


def test_read_rcfile_accepts_utf8_bom(tmp_path):
    """Notepad and PowerShell 5.1 write a BOM; it isn't a syntax error."""
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[run]\nbranch = true\n", encoding="utf-8-sig")
    assert rc.read_bytes().startswith(b"\xef\xbb\xbf")
    assert read_rcfile(rc) == {"branch": True}


def test_read_rcfile_unknown_key_passes_through(tmp_path):
    """One code path for the unknown-key warning: apply_config's."""
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[run]\nno-such-key = 42\n")
    cfg = read_rcfile(rc)
    assert cfg == {"no-such-key": "42"}

    with pytest.warns(UserWarning, match="Unknown.*no-such-key"):
        apply_config(cfg, _make_args())


def test_read_rcfile_rcfile_is_not_a_config_key(tmp_path):
    """--rcfile is a per-invocation choice, not a setting."""
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[run]\nrcfile = other.rc\n")
    args = _make_args(rcfile=None)
    with pytest.warns(UserWarning, match="Unknown.*rcfile"):
        apply_config(read_rcfile(rc), args)
    assert args.rcfile is None


def test_read_rcfile_malformed_raises(tmp_path):
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[run\nbranch = true\n")
    with pytest.raises(configparser.Error):
        read_rcfile(rc)


def test_read_rcfile_empty_sections(tmp_path):
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[run]\n[report]\n")
    assert read_rcfile(rc) == {}


def test_read_rcfile_no_file(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()  # bound the walk; see test_find_rcfile_returns_none
    monkeypatch.chdir(tmp_path)
    assert read_rcfile(None) == {}


def test_read_rcfile_discovers_from_cwd(tmp_path, monkeypatch):
    (tmp_path / ".slipcoverrc").write_text("[run]\nbranch = true\nsource = src\n")
    monkeypatch.chdir(tmp_path)
    assert read_rcfile() == {"branch": True, "source": "src"}


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


def _make_args(**kwargs):
    defaults = dict(
        branch=False, format='text', pretty_print=False,
        xml_package_depth=99, lcov_test_name=None, lcov_comments=None,
        out=None, source=None, omit=None,
        immediate=False, skip_covered=False, fail_under=0,
        threshold=50, missing_width=80, silent=False, dis=False,
        debug=False, dont_wrap_pytest=False, sigterm=False,
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


def test_apply_config_empty_out_from_rcfile_raises(tmp_path):
    rc = tmp_path / ".slipcoverrc"
    rc.write_text("[report]\nout =\n")
    assert read_rcfile(rc) == {"out": ""}
    with pytest.raises(ValueError, match="key 'out'"):
        apply_config(read_rcfile(rc), _make_args())


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
    with pytest.warns(UserWarning, match=r"Unknown \.slipcoverrc key: 'brunch'"):
        apply_config({"brunch": "true"}, args, source=".slipcoverrc")


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


def test_cli_valid_rcfile_applied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".slipcoverrc").write_text("[report]\nfail-under = 100.0\n")
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 2  # fail-under from .slipcoverrc kicks in
    assert 'Traceback' not in p.stderr


def test_cli_rcfile_beats_pyproject(tmp_path, monkeypatch):
    """A .slipcoverrc wins outright; [tool.slipcover] is ignored entirely."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 100.0\n')
    (tmp_path / ".slipcoverrc").write_text("[report]\nfail-under = 1.0\n")
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0  # pyproject's fail-under would have given 2
    assert 'Traceback' not in p.stderr


def test_cli_rcfile_in_parent_beats_pyproject_in_cwd(tmp_path, monkeypatch):
    """The two files are discovered independently, so a .slipcoverrc found
    further up still wins over a nearer pyproject.toml.
    """
    (tmp_path / ".slipcoverrc").write_text("[report]\nfail-under = 100.0\n")
    cwd = tmp_path / "project"
    cwd.mkdir()
    (cwd / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 1.0\n')
    (cwd / "script.py").write_text(_HALF_COVERED)
    monkeypatch.chdir(cwd)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 2  # pyproject's fail-under would have given 0
    assert 'Traceback' not in p.stderr


def test_cli_empty_rcfile_leaves_pyproject_alone(tmp_path, monkeypatch):
    """An empty .slipcoverrc sets no keys, so it overrides nothing and
    [tool.slipcover] still applies in full.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".slipcoverrc").write_text("")
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 100.0\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 2  # pyproject's fail-under still kicks in
    assert 'Traceback' not in p.stderr


def test_cli_rcfile_key_overrides_pyproject_key_by_key(tmp_path, monkeypatch):
    """An rc file setting one key must not discard the rest of
    [tool.slipcover]: the keys it doesn't mention still apply.
    """
    monkeypatch.chdir(tmp_path)
    # branch comes from the rc file; fail-under survives from pyproject.toml
    (tmp_path / ".slipcoverrc").write_text("[run]\nbranch = true\n")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.slipcover]\nfail-under = 100.0\nformat = "json"\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 2        # pyproject's fail-under was NOT dropped
    assert 'Traceback' not in p.stderr
    cov = json.loads(p.stdout)      # pyproject's format = "json" was NOT dropped
    assert 'meta' in cov and cov['meta']['branch_coverage'] is True  # rc's branch won


def test_cli_rcfile_wins_on_conflicting_key(tmp_path, monkeypatch):
    """Where both files set the same key, the rc file's value is used."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".slipcoverrc").write_text("[run]\nfail-under = 1.0\n")
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 100.0\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0  # rc's 1.0 beat pyproject's 100.0
    assert 'Traceback' not in p.stderr


def test_cli_unknown_rcfile_key_warning_names_the_rcfile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".slipcoverrc").write_text("[run]\nbrunch = true\n")
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0
    assert "brunch" in p.stderr
    assert ".slipcoverrc" in p.stderr
    assert "[tool.slipcover]" not in p.stderr


def test_cli_unknown_pyproject_key_warning_names_the_table(tmp_path, monkeypatch):
    """Symmetric with the .slipcoverrc case: the warning must name where
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
    """The commonest invocation: neither .slipcoverrc nor pyproject.toml
    exists, so nothing is configured and the run proceeds normally.
    """
    (tmp_path / ".git").mkdir()  # bound the walk; see test_find_rcfile_returns_none
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0     # no fail-under configured
    assert 'Traceback' not in p.stderr
    assert 'script.py' in p.stdout
    assert '50' in p.stdout      # the usual table, half covered


def test_cli_explicit_rcfile_bypasses_discovery(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".slipcoverrc").write_text("[report]\nfail-under = 1.0\n")
    (tmp_path / "other.rc").write_text("[report]\nfail-under = 100.0\n")
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--rcfile', 'other.rc', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 2  # the discovered .slipcoverrc would have given 0
    assert 'Traceback' not in p.stderr


def test_cli_flag_beats_rcfile(tmp_path, monkeypatch):
    """--fail-under overrides the rc file's value, while 'format' -- which no
    flag contradicts -- still takes effect, proving the rc file was read.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".slipcoverrc").write_text("[report]\nfail-under = 100.0\nformat = json\n")
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--fail-under', '1', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 0    # rc file's fail-under would have given 2
    assert 'Traceback' not in p.stderr
    assert json.loads(p.stdout)["files"]    # rc file's format = json did apply


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
    (tmp_path / ".git").mkdir()  # bound the walk; see test_find_rcfile_returns_none
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--fail-under', '100', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 2    # the flag's fail-under kicked in; default is 0
    assert 'Traceback' not in p.stderr


def test_cli_malformed_rcfile_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".slipcoverrc").write_text("[run\nbranch = true\n")
    (tmp_path / "script.py").write_text("x = 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode != 0
    assert 'Traceback' not in p.stderr
    assert '.slipcoverrc' in p.stderr


def test_cli_bad_rcfile_value_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".slipcoverrc").write_text("[run]\nbranch = maybe\n")
    (tmp_path / "script.py").write_text("x = 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode != 0
    assert 'Traceback' not in p.stderr
    assert '.slipcoverrc' in p.stderr


def test_cli_missing_rcfile_clean_error(tmp_path, monkeypatch):
    """An explicit --rcfile that doesn't exist is a user error, not a
    silent fallback to pyproject.toml.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 100.0\n')
    (tmp_path / "script.py").write_text(_HALF_COVERED)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--rcfile', 'nope.rc', 'script.py'],
                        capture_output=True, text=True)

    assert p.returncode == 1
    assert 'Traceback' not in p.stderr
    assert 'nope.rc' in p.stderr
