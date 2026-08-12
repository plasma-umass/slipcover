import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from slipcover.__main__ import build_parser
from slipcover.config import apply_config, derive_configurable_keys, find_pyproject, read_config


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
    with pytest.warns(UserWarning, match="Unknown.*no-such-key"):
        apply_config({"no-such-key": 42}, args)


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


def test_cli_valid_pyproject_config_applied(tmp_path, monkeypatch):
    """Sanity check that a real subprocess run actually reads and applies
    pyproject.toml config end-to-end (no test currently exercises this).
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.slipcover]\nfail-under = 100.0\n')
    # foo()'s body is never called, so coverage is 50%, below the threshold
    (tmp_path / "script.py").write_text("def foo():\n    pass\n")

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

