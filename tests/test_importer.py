import pytest
import slipcover.importer as im
from pathlib import Path
import subprocess

import sys


def test_filematcher_defaults(tmp_path, monkeypatch):
    base = tmp_path / "foo"
    base.mkdir()

    (base / "myscript.py").write_text("")
    (base / "myscript.pyd").write_text("")
    (base / "myscript.so").write_text("")
    (base / "mymodule").mkdir()
    (base / "mymodule" / "mymodule.py").write_text("")
    (base / "other").mkdir()
    (base / "other" / "other.py").write_text("")
    (tmp_path / "other.py").write_text("")

    monkeypatch.chdir(base)

    fm = im.FileMatcher()

    assert fm.matches('myscript.py')
    assert not fm.matches('built-in')
    assert not fm.matches('myscript.pyd')
    assert not fm.matches('myscript.so')
    assert fm.matches(Path('.') / 'myscript.py')
    assert fm.matches(Path('mymodule') / 'mymodule.py')
    assert fm.matches(Path('.') / 'mymodule' / 'mymodule.py')
    assert fm.matches(Path('other') / 'other.py')
    assert fm.matches(base.resolve() / 'myscript.py')
    assert fm.matches(base.resolve() / 'mymodule' / 'mymodule.py')
    assert not fm.matches(base.resolve().parent / 'other.py')

    import inspect  # should be in python's own lib
    assert not fm.matches(inspect.getfile(inspect))

    # pip is usually in site-packages, but importing it causes warnings
    site_packages = next(Path(p) for p in sys.path if p != '' and (Path(p) / "pip").exists())
    assert not fm.matches(site_packages / 'foo.py')


def test_filematcher_source(tmp_path, monkeypatch):
    base = tmp_path / "foo"
    base.mkdir()

    (base / "myscript.py").write_text("")
    (base / "myscript.pyd").write_text("")
    (base / "myscript.so").write_text("")
    (base / "mymodule").mkdir()
    (base / "mymodule" / "mymodule.py").write_text("")
    (base / "mymodule" / "mymodule.pyd").write_text("")
    (base / "mymodule" / "mymodule.so").write_text("")
    (base / "mymodule" / "foo.py").write_text("")
    (base / "prereq").mkdir()
    (base / "prereq" / "__main__.py").write_text("")
    (base / "other").mkdir()
    (base / "other" / "other.py").write_text("")
    (tmp_path / "other.py").write_text("")

    monkeypatch.chdir(base)

    fm = im.FileMatcher(sources=['mymodule', 'prereq'])

    assert not fm.matches('myscript.py')
    assert not fm.matches(Path('.') / 'myscript.py')
    assert not fm.matches('built-in')
    assert not fm.matches('myscript.pyd')
    assert not fm.matches('myscript.so')
    assert fm.matches(Path('mymodule') / 'mymodule.py')
    assert fm.matches(Path('mymodule') / 'foo.py')
    assert not fm.matches(Path('mymodule') / 'myscript.pyd')
    assert not fm.matches(Path('mymodule') / 'myscript.so')
    assert fm.matches(Path('.') / 'mymodule' / 'mymodule.py')
    assert fm.matches(Path('prereq') / '__main__.py')
    assert not fm.matches(Path('.') / 'other' / 'other.py')
    assert not fm.matches(base.resolve() / 'myscript.py')
    assert fm.matches(base.resolve() / 'mymodule' / 'mymodule.py')
    assert not fm.matches(base.resolve().parent / 'other.py')

    import inspect  # should be in python's own lib
    assert not fm.matches(inspect.getfile(inspect))

    # pip is usually in site-packages, but importing it causes warnings
    site_packages = next(Path(p) for p in sys.path if p != '' and (Path(p) / "pip").exists())
    assert not fm.matches(site_packages / 'foo.py')


def test_filematcher_source_resolved(monkeypatch):
    from pathlib import Path
    monkeypatch.chdir('tests')

    fm = im.FileMatcher(sources=['../src/'])

    p = (Path.cwd() / '..' / 'src' / 'foo.py').resolve()
    assert fm.matches(p)


def test_filematcher_default_dir_respects_pylib(tmp_path, monkeypatch):
    # Regression test for #79: a script run with no --source auto-scopes to
    # its own directory (via default_dir); that shouldn't bypass stdlib/
    # site-packages exclusion the way an explicit --source does.
    # cwd is deliberately unrelated to script_dir, so a match on
    # script_dir/myscript.py can only succeed via default_dir, not by
    # falling back to (or coincidentally being an ancestor via) cwd.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    script_dir = tmp_path / "proj"
    script_dir.mkdir()
    (script_dir / "myscript.py").write_text("")

    fake_pylib = script_dir / ".venv" / "lib" / "site-packages"
    fake_pylib.mkdir(parents=True)
    (fake_pylib / "somepkg").mkdir()
    (fake_pylib / "somepkg" / "mod.py").write_text("")

    fm = im.FileMatcher(default_dir=script_dir)
    fm.pylib_paths = (*fm.pylib_paths, fake_pylib)

    assert fm.matches(script_dir / "myscript.py")
    assert not fm.matches(fake_pylib / "somepkg" / "mod.py")


def test_filematcher_explicit_source_bypasses_pylib(tmp_path):
    # An explicit --source is trusted completely, even if it points inside
    # what looks like a venv/site-packages -- unlike the default_dir case
    # above, matching how explicit --source already bypasses pylib_paths.
    fake_pylib = tmp_path / "venv-site-packages"
    fake_pylib.mkdir()
    (fake_pylib / "somepkg").mkdir()
    (fake_pylib / "somepkg" / "mod.py").write_text("")

    fm = im.FileMatcher(sources=[fake_pylib])
    fm.pylib_paths = (*fm.pylib_paths, fake_pylib)

    assert fm.matches(fake_pylib / "somepkg" / "mod.py")


@pytest.mark.skipif(sys.platform == 'win32', reason='venv layout differs on Windows')
def test_venv_excluded_from_report_without_source(tmp_path):
    # End-to-end regression test for #79: running a script with no --source,
    # sitting next to a real .venv, shouldn't pull that venv's own
    # site-packages into the coverage report. Uses a real venv (so
    # sysconfig.get_path("purelib") genuinely resolves inside it, as it
    # would for a user's actual virtualenv) rather than faking pylib_paths.
    import json
    import sysconfig
    import venv
    import slipcover as _sc

    proj = tmp_path / "proj"
    proj.mkdir()
    venv_dir = proj / ".venv"
    venv.create(venv_dir, with_pip=False)

    site_packages = next(venv_dir.rglob("site-packages"))

    # Make slipcover (already built/importable in this same interpreter --
    # whether from an editable install pointing at src/, or a regular
    # install in site-packages) and its dependencies (e.g. tomli on <3.11)
    # importable in the new venv, without needing pip or network access.
    # slipcover_parent is wherever the *package* is importable from --
    # covers both install styles; outer_site_packages covers the rest.
    # Neither path is *inside* the new venv, so sysconfig.get_path
    # ("purelib") -- which pylib_paths relies on -- still resolves to the
    # new venv's own site-packages when run via venv_python below.
    slipcover_parent = Path(_sc.__file__).resolve().parent.parent
    outer_site_packages = sysconfig.get_path("purelib")
    (site_packages / "_slipcover_repo.pth").write_text(
        f"{slipcover_parent}\n{outer_site_packages}\n"
    )

    # A fake third-party package "installed" in the venv, as pip would.
    pkg = site_packages / "thirdparty_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def hello():\n    return 1\n")

    script = proj / "run.py"
    script.write_text("import thirdparty_pkg\nthirdparty_pkg.hello()\n")

    venv_python = venv_dir / "bin" / "python"
    out = tmp_path / "out.json"

    subprocess.run([str(venv_python), "-m", "slipcover", "--json", "--out", str(out), str(script)], check=True)

    with out.open() as f:
        cov = json.load(f)

    files = cov['files'].keys()
    assert str(script.resolve()) in files
    assert not any('thirdparty_pkg' in f for f in files)


def test_filematcher_omit_pattern(tmp_path, monkeypatch):
    base = tmp_path / "foo"
    base.mkdir()

    (base / "myscript.py").write_text("")
    (base / "mymodule").mkdir()
    (base / "mymodule" / "mymodule.py").write_text("")
    (base / "mymodule" / "foo.py").write_text("")
    (base / "mymodule" / "1" / "2" / "3").mkdir(parents=True)
    (base / "mymodule" / "1" / "2" / "3" / "foo.py").write_text("")
    (base / "other").mkdir()
    (base / "other" / "other.py").write_text("")
    (tmp_path / "other.py").write_text("")

    monkeypatch.chdir(base)

    fm = im.FileMatcher(sources=['mymodule'], omit=['*/foo.py'])

    assert not fm.matches('myscript.py')
    assert not fm.matches(Path('.') / 'myscript.py')
    assert fm.matches(Path('mymodule') / 'mymodule.py')
    assert not fm.matches(Path('mymodule') / 'foo.py')
    assert not fm.matches(Path('mymodule') / '1' / '2' / '3' / 'foo.py')
    assert fm.matches(Path('.') / 'mymodule' / 'mymodule.py')
    assert not fm.matches(Path('.') / 'other' / 'other.py')
    assert not fm.matches(base.resolve() / 'myscript.py')
    assert fm.matches(base.resolve() / 'mymodule' / 'mymodule.py')
    assert not fm.matches(base.resolve().parent / 'other.py')

    import inspect  # should be in python's own lib
    assert not fm.matches(inspect.getfile(inspect))

    # pip is usually in site-packages, but importing it causes warnings
    site_packages = next(Path(p) for p in sys.path if p != '' and (Path(p) / "pip").exists())
    assert not fm.matches(site_packages / 'foo.py')

# TODO what about patterns starting with '?'


def test_filematcher_omit_nonpattern(tmp_path, monkeypatch):
    base = tmp_path / "foo"
    base.mkdir()

    (base / "myscript.py").write_text("")
    (base / "mymodule").mkdir()
    (base / "mymodule" / "mymodule.py").write_text("")
    (base / "mymodule" / "foo.py").write_text("")
    (base / "mymodule" / "1" / "2" / "3").mkdir(parents=True)
    (base / "mymodule" / "1" / "2" / "3" / "foo.py").write_text("")
    (base / "other").mkdir()
    (base / "other" / "other.py").write_text("")
    (tmp_path / "other.py").write_text("")

    monkeypatch.chdir(base)

    fm = im.FileMatcher(sources=['mymodule'], omit=['mymodule/foo.py'])

    assert not fm.matches('myscript.py')
    assert not fm.matches(Path('.') / 'myscript.py')
    assert fm.matches(Path('mymodule') / 'mymodule.py')
    assert not fm.matches(Path('mymodule') / 'foo.py')
    assert fm.matches(Path('mymodule') / '1' / '2' / '3' / 'foo.py')
    assert fm.matches(Path('.') / 'mymodule' / 'mymodule.py')
    assert not fm.matches(Path('.') / 'other' / 'other.py')
    assert not fm.matches(base.resolve() / 'myscript.py')
    assert fm.matches(base.resolve() / 'mymodule' / 'mymodule.py')
    assert not fm.matches(base.resolve().parent / 'other.py')


@pytest.mark.skipif(sys.platform == 'win32', reason='Fails due to weird PermissionError in Documents and Settings')
def test_loader_supports_resources(tmp_path):
    import subprocess

    cmdfile = tmp_path / "t.py"
    cmdfile.write_text("""
import sys
sys.path.append('tests')
from pathlib import Path

import importlib.resources as r
import imported

def test():
    if sys.version_info >= (3, 12):
        assert list(r.files('imported').iterdir()) != []
    else:
        assert list(r.contents('imported')) != []
""")

    p = subprocess.run([sys.executable, "-m", "slipcover", "--silent", "-m", "pytest", "-qq", cmdfile])
    assert p.returncode == 0


@pytest.mark.skipif(sys.platform == 'win32', reason='Fails due to weird PermissionError in Documents and Settings')
@pytest.mark.parametrize("do_branch", [True, False])
def test_import_manager_instruments(tmp_path, do_branch):
    import subprocess

    cmdfile = tmp_path / "t.py"
    cmdfile.write_text(f"""
import sys
sys.path.append('tests')
from pathlib import Path

import slipcover as sc

def test():
    sci = sc.Slipcover(branch={do_branch})
    with sc.ImportManager(sci):
        import imported

    imported.do_stuff()

    cov = sci.get_coverage()
    assert str(Path('tests/imported/__init__.py')) in cov['files']
""")

    p = subprocess.run([sys.executable, "-m", "slipcover", "--silent", "-m", "pytest", "-vv", cmdfile])
    assert p.returncode == 0


@pytest.mark.skipif(sys.platform == 'win32', reason='Fails due to weird PermissionError in Documents and Settings')
def test_import_manager_removed(tmp_path):
    import subprocess

    cmdfile = tmp_path / "t.py"
    cmdfile.write_text("""
import sys
sys.path.append('tests')
from pathlib import Path

import slipcover as sc

def test():
    sci = sc.Slipcover()
    with sc.ImportManager(sci):
        pass

    import imported

    imported.do_stuff()

    cov = sci.get_coverage()
    assert str(Path('tests/imported/__init__.py')) not in cov['files']
""")

    p = subprocess.run([sys.executable, "-m", "slipcover", "--silent", "-m", "pytest", "-vv", cmdfile])
    assert p.returncode == 0


@pytest.mark.skipif(sys.platform == 'win32', reason='Fails due to weird PermissionError in Documents and Settings')
@pytest.mark.parametrize("do_branch", [True, False])
def test_import_manager_instruments_everything(tmp_path, do_branch):
    import subprocess

    cmdfile = tmp_path / "t.py"
    cmdfile.write_text(f"""
import sys
sys.path.append('tests')
from pathlib import Path

import slipcover as sc

def test():
    sci = sc.Slipcover(branch={do_branch})
    with sc.ImportManager(sci):
        import pip

    cov = sci.get_coverage()
    assert any(str(Path('pip/__init__.py')) in k for k in cov['files'].keys())
""")

    p = subprocess.run([sys.executable, "-m", "slipcover", "--silent", "-m", "pytest", "-vv", cmdfile])
    assert p.returncode == 0


def test_run_script_argv_is_str(tmp_path):
    cmdfile = tmp_path / "t.py"
    cmdfile.write_text("""
import sys
assert isinstance(sys.argv[0], str)
""")

    subprocess.run([sys.executable, "-m", "slipcover", "--silent", cmdfile], check=True)


@pytest.mark.skipif(sys.platform == 'win32', reason='Fails due to weird PermissionError')
def test_wrap_spec_from_file_location(tmp_path, monkeypatch):
    """Test that files loaded via spec_from_file_location are covered."""
    import json

    # Create a Python file to be loaded dynamically
    dynamic_module = tmp_path / "dynamic_module.py"
    dynamic_module.write_text('''
x = 1  # line 2
y = 2  # line 3
z = x + y  # line 4
''')

    # Create a script that loads the module via spec_from_file_location
    script = tmp_path / "main_script.py"
    script.write_text(f"""
import importlib.util
spec = importlib.util.spec_from_file_location("dynamic_module", "{dynamic_module}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.z == 3
""")

    monkeypatch.chdir(tmp_path)

    out = tmp_path / "coverage.json"
    result = subprocess.run(
        [sys.executable, "-m", "slipcover", "--json", "--out", str(out),
         "--source", str(tmp_path), str(script)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)

    # Check that the dynamically loaded file was covered
    dynamic_files = [k for k in cov['files'].keys() if 'dynamic_module.py' in k]
    assert dynamic_files, f"Dynamic module not in coverage: {list(cov['files'].keys())}"

    # Check that lines were executed
    file_cov = cov['files'][dynamic_files[0]]
    executed_lines = file_cov['executed_lines']
    assert 2 in executed_lines and 3 in executed_lines and 4 in executed_lines, \
        f"Lines not executed, got: {executed_lines}"


try:
    import alembic
    HAS_ALEMBIC = True
except ImportError:
    HAS_ALEMBIC = False


@pytest.mark.skipif(sys.platform == 'win32', reason='Fails due to weird PermissionError')
@pytest.mark.skipif(not HAS_ALEMBIC, reason='Alembic not installed')
def test_wrap_spec_from_file_location_alembic(tmp_path, monkeypatch):
    """Test that Alembic migrations are covered (integration test for spec_from_file_location)."""
    import json

    # Create a minimal alembic setup
    migrations_dir = tmp_path / "migrations"
    versions_dir = migrations_dir / "versions"
    versions_dir.mkdir(parents=True)

    # Create alembic.ini
    alembic_ini = tmp_path / "alembic.ini"
    alembic_ini.write_text(f"""
[alembic]
script_location = {migrations_dir}
sqlalchemy.url = sqlite:///:memory:
""")

    # Create env.py
    env_py = migrations_dir / "env.py"
    env_py.write_text("""
from alembic import context

def run_migrations_offline():
    context.configure(url="sqlite:///:memory:", literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    from sqlalchemy import create_engine
    connectable = create_engine("sqlite:///:memory:")
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
""")

    # Create script.py.mako (required by alembic)
    script_mako = migrations_dir / "script.py.mako"
    script_mako.write_text("")

    # Create a migration file
    migration_file = versions_dir / "001_test_migration.py"
    migration_file.write_text('''
"""test migration"""
revision = '001'
down_revision = None

def upgrade():
    x = 1
    y = 2

def downgrade():
    pass
''')

    # Create a script that runs the alembic migration
    script = tmp_path / "run_migration.py"
    script.write_text(f"""
import sys
sys.path.insert(0, '{tmp_path}')
from alembic.config import Config
from alembic import command

alembic_cfg = Config('{alembic_ini}')
command.upgrade(alembic_cfg, 'head')
""")

    monkeypatch.chdir(tmp_path)

    out = tmp_path / "coverage.json"
    result = subprocess.run(
        [sys.executable, "-m", "slipcover", "--json", "--out", str(out),
         "--source", str(versions_dir), str(script)],
        capture_output=True,
        text=True
    )

    # The script should complete (may have warnings, but not crash)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)

    # Check that the migration file was covered
    # The path might be stored as relative or absolute depending on the working directory
    migration_files = [k for k in cov['files'].keys() if '001_test_migration.py' in k]
    assert migration_files, f"Migration file not in coverage: {list(cov['files'].keys())}"

    # Check that lines in the upgrade function were executed
    file_cov = cov['files'][migration_files[0]]
    executed_lines = file_cov['executed_lines']
    # Lines 7 and 8 are inside upgrade() function (x=1, y=2)
    assert 7 in executed_lines or 8 in executed_lines, f"upgrade() lines not executed, executed: {executed_lines}"


def test_wrap_spec_from_file_location_no_double_wrap(tmp_path, monkeypatch):
    """Test that spec_from_file_location wrapper doesn't double-wrap already wrapped loaders."""
    import importlib.util
    
    # Create a test file
    test_file = tmp_path / "test_module.py"
    test_file.write_text('''
x = 1
y = 2
''')
    
    monkeypatch.chdir(tmp_path)
    
    # Set up slipcover and file matcher
    import slipcover as sc
    sci = sc.Slipcover()
    fm = im.FileMatcher(sources=[tmp_path])
    
    # Wrap spec_from_file_location
    im.wrap_spec_from_file_location(sci, fm)
    
    # Get the current (wrapped) spec_from_file_location
    wrapped_spec_from_file_location = importlib.util.spec_from_file_location
    
    # Call wrapped function to get a spec with a wrapped loader
    spec = wrapped_spec_from_file_location("test_module", test_file)
    assert spec is not None
    assert spec.loader is not None
    assert isinstance(spec.loader, im.SlipcoverLoader), \
        f"Expected SlipcoverLoader, got {type(spec.loader)}"
    
    # Save the wrapped loader
    first_wrapper = spec.loader
    
    # Simulate the defensive check scenario: pass the spec with already-wrapped loader
    # back through the wrapper by manipulating what the original function returns.
    # We do this by calling spec_from_file_location with the already-wrapped loader
    # as the loader parameter.
    spec2 = wrapped_spec_from_file_location(
        "test_module2", test_file, loader=first_wrapper
    )
    assert spec2 is not None
    assert spec2.loader is not None
    
    # The defensive check should have prevented double-wrapping
    assert isinstance(spec2.loader, im.SlipcoverLoader), \
        f"Expected SlipcoverLoader, got {type(spec2.loader)}"
    assert spec2.loader is first_wrapper, \
        "Defensive check failed: loader should not be wrapped again"
    
    # Verify that the original loader is not another SlipcoverLoader
    assert not isinstance(first_wrapper.orig_loader, im.SlipcoverLoader), \
        "Loader was double-wrapped: orig_loader should not be a SlipcoverLoader"


@pytest.mark.skipif(sys.platform == 'win32', reason='Fails due to weird PermissionError')
def test_wrap_spec_from_file_location_with_branch(tmp_path, monkeypatch):
    """Test that files loaded via spec_from_file_location get branch coverage."""
    import json

    # Create a Python file with a branch to be loaded dynamically
    dynamic_module = tmp_path / "dynamic_module.py"
    dynamic_module.write_text('''
x = 1
if x > 0:  # branch
    y = 2
else:
    y = 3
z = y
''')

    # Create a script that loads the module via spec_from_file_location
    script = tmp_path / "main_script.py"
    script.write_text(f"""
import importlib.util
spec = importlib.util.spec_from_file_location("dynamic_module", "{dynamic_module}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.z == 2
""")

    monkeypatch.chdir(tmp_path)

    out = tmp_path / "coverage.json"
    result = subprocess.run(
        [sys.executable, "-m", "slipcover", "--branch", "--json", "--out", str(out),
         "--source", str(tmp_path), str(script)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)

    # Check that the dynamically loaded file was covered
    dynamic_files = [k for k in cov['files'].keys() if 'dynamic_module.py' in k]
    assert dynamic_files, f"Dynamic module not in coverage: {list(cov['files'].keys())}"

    # Check that branch info is present
    file_cov = cov['files'][dynamic_files[0]]
    assert 'executed_branches' in file_cov, "Branch coverage not recorded"


@pytest.mark.skipif(sys.platform == 'win32', reason='Fails due to weird PermissionError')
@pytest.mark.skipif(not HAS_ALEMBIC, reason='Alembic not installed')
def test_wrap_spec_from_file_location_with_branch_alembic(tmp_path, monkeypatch):
    """Test that Alembic migrations get branch coverage (integration test)."""
    import json

    # Create a minimal alembic setup
    migrations_dir = tmp_path / "migrations"
    versions_dir = migrations_dir / "versions"
    versions_dir.mkdir(parents=True)

    # Create alembic.ini
    alembic_ini = tmp_path / "alembic.ini"
    alembic_ini.write_text(f"""
[alembic]
script_location = {migrations_dir}
sqlalchemy.url = sqlite:///:memory:
""")

    # Create env.py
    env_py = migrations_dir / "env.py"
    env_py.write_text("""
from alembic import context

def run_migrations_offline():
    context.configure(url="sqlite:///:memory:", literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    from sqlalchemy import create_engine
    connectable = create_engine("sqlite:///:memory:")
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
""")

    # Create script.py.mako (required by alembic)
    script_mako = migrations_dir / "script.py.mako"
    script_mako.write_text("")

    # Create a migration file with a branch
    migration_file = versions_dir / "001_test_migration.py"
    migration_file.write_text('''
"""test migration"""
revision = '001'
down_revision = None

def upgrade():
    x = 1
    if x > 0:  # branch
        y = 2
    else:
        y = 3

def downgrade():
    pass
''')

    # Create a script that runs the alembic migration
    script = tmp_path / "run_migration.py"
    script.write_text(f"""
import sys
sys.path.insert(0, '{tmp_path}')
from alembic.config import Config
from alembic import command

alembic_cfg = Config('{alembic_ini}')
command.upgrade(alembic_cfg, 'head')
""")

    monkeypatch.chdir(tmp_path)

    out = tmp_path / "coverage.json"
    result = subprocess.run(
        [sys.executable, "-m", "slipcover", "--branch", "--json", "--out", str(out),
         "--source", str(versions_dir), str(script)],
        capture_output=True,
        text=True
    )

    # The script should complete (may have warnings, but not crash)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    with out.open() as f:
        cov = json.load(f)

    # Check that the migration file was covered
    migration_files = [k for k in cov['files'].keys() if '001_test_migration.py' in k]
    assert migration_files, f"Migration file not in coverage: {list(cov['files'].keys())}"

    # Check that branch info is present
    file_cov = cov['files'][migration_files[0]]
    assert 'executed_branches' in file_cov, "Branch coverage not recorded"
