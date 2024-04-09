import pytest
import sys
import subprocess
from pathlib import Path
import json


@pytest.mark.skipif(sys.platform == 'win32', reason='Unix-only')
def test_isolate_all_ok(tmp_path):
    out = tmp_path / "out.json"
    test_file = str(Path('tests') / 'pyt.py')

    subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out), '--isolate',
                                    '-m', 'pytest', test_file])

    with out.open() as f:
        cov = json.load(f)

    assert test_file in cov['files']
    assert {test_file} == set(cov['files'].keys())
    cov = cov['files'][test_file]
    assert [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14] == cov['executed_lines']
    assert [] == cov['missing_lines']


@pytest.mark.skipif(sys.platform == 'win32', reason='Unix-only')
def test_isolate_nontest_issue(tmp_path):
    out = tmp_path / "out.json"
    test_file = str(Path('tests') / 'pyt.py')

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out), '--isolate',
                                        '-m', 'pytest', '--my-invalid-flag', test_file],
                   check=False)
    assert p.returncode == pytest.ExitCode.USAGE_ERROR


def seq2p(tests_dir, seq):
    return tests_dir / f"test_{seq}.py"


N_TESTS=10
def make_polluted_suite(tests_dir: Path, pollute_fails_collect: bool):
    """In a suite with 10 tests, test 6 fails; test 3 doesn't fail, but causes 6 to fail."""

    for seq in range(N_TESTS):
        seq2p(tests_dir, seq).write_text('def test_foo(): pass')

    polluter = seq2p(tests_dir, 3)
    polluter.write_text("import sys\n" + "sys.foobar = True\n" + "def test_foo(): pass")

    failing = seq2p(tests_dir, 6)
    if pollute_fails_collect:
        failing.write_text("import sys\n" + "assert not getattr(sys, 'foobar', False)\n" + "def test_foo(): pass")
    else:
        failing.write_text("import sys\n" + "def test_foo(): assert not getattr(sys, 'foobar', False)")

    return failing, polluter


def make_failing_suite(tests_dir: Path):
    """In a suite with 10 tests, test 6 fails; test 3 doesn't fail, but causes 6 to fail."""

    for seq in range(N_TESTS):
        seq2p(tests_dir, seq).write_text('def test_foo(): pass')

    failing = seq2p(tests_dir, 6)
    failing.write_text("def test_bar(): assert False")


@pytest.mark.parametrize("pollute_fails_collect", [True, False])
def test_check_suite_fails(tmp_path, monkeypatch, pollute_fails_collect):
    out = tmp_path / "out.json"

    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, pollute_fails_collect)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out),
                                        '-m', 'pytest', tests_dir], check=False)
    assert p.returncode == pytest.ExitCode.INTERRUPTED if pollute_fails_collect else pytest.ExitCode.TESTS_FAILED


@pytest.mark.skipif(sys.platform == 'win32', reason='Unix-only')
@pytest.mark.parametrize("pollute_fails_collect", [True, False])
def test_isolate_polluted(tmp_path, monkeypatch, pollute_fails_collect):
    out = tmp_path / "out.json"

    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, pollute_fails_collect)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out), '--isolate',
                                        '-m', 'pytest', tests_dir], check=False)
    assert p.returncode == pytest.ExitCode.OK

    with out.open() as f:
        cov = json.load(f)

    for seq in range(N_TESTS):
        p = seq2p(tests_dir, seq)
        assert str(p) in cov['files']


@pytest.mark.skipif(sys.platform == 'win32', reason='Unix-only')
def test_pytest_discover_tests(tmp_path, monkeypatch):
    out = tmp_path / "out.json"

    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, pollute_fails_collect=False)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out), '--isolate',
                                        '-m', 'pytest'], check=False) # no tests_dir here
    assert p.returncode == pytest.ExitCode.OK

    with out.open() as f:
        cov = json.load(f)

    for seq in range(N_TESTS):
        p = seq2p(tests_dir, seq)
        assert str(p) in cov['files']

@pytest.mark.skipif(sys.platform == 'win32', reason='Unix-only')
@pytest.mark.parametrize("pollute_fails_collect", [True, False])
def test_isolate_failing(tmp_path, monkeypatch, pollute_fails_collect):
    out = tmp_path / "out.json"

    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, pollute_fails_collect)

    failing = seq2p(tests_dir, 2)
    failing.write_text("def test_bar(): assert False")

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out),
                                        '-m', 'slipcover.isolate', tests_dir], check=False)
    assert p.returncode == pytest.ExitCode.TESTS_FAILED
