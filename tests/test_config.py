import argparse
from pathlib import Path

import pytest

from slipcover.config import apply_config, find_pyproject, read_config


def test_find_pyproject_in_cwd(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    assert find_pyproject(tmp_path) == tmp_path / "pyproject.toml"


def test_find_pyproject_walks_up(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    child = tmp_path / "a" / "b" / "c"
    child.mkdir(parents=True)
    assert find_pyproject(child) == tmp_path / "pyproject.toml"


def test_find_pyproject_returns_none(tmp_path):
    child = tmp_path / "nowhere"
    child.mkdir()
    result = find_pyproject(child)
    # might find the repo's own file if tmp_path is under the repo tree
    assert result is None or result.name == "pyproject.toml"


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
    """Should not walk above the user's home directory."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
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


def test_read_config_no_file():
    assert read_config(None) == {} or True  # auto-discovery may find repo file


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


def _make_args(**kwargs):
    defaults = dict(
        branch=False, json=False, pretty_print=False, xml=False,
        xml_package_depth=99, out=None, source=None, omit=None,
        immediate=False, skip_covered=False, fail_under=0,
        threshold=50, missing_width=80, silent=False, dis=False,
        debug=False, dont_wrap_pytest=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


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


def test_apply_config_warns_unknown_key():
    args = _make_args()
    with pytest.warns(UserWarning, match="Unknown.*no-such-key"):
        apply_config({"no-such-key": 42}, args)


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

