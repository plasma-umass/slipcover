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

    fm = im.FileMatcher()
    fm.addSource('mymodule')
    fm.addSource('prereq')

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

    fm = im.FileMatcher()
    fm.addSource('../src/')

    p = (Path.cwd() / '..' / 'src' / 'foo.py').resolve()
    assert fm.matches(p)


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

    fm = im.FileMatcher()
    fm.addSource('mymodule')
    fm.addOmit('*/foo.py')

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

    fm = im.FileMatcher()
    fm.addSource('mymodule')
    fm.addOmit('mymodule/foo.py')

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
