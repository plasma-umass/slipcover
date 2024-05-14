import pytest
import sys
import subprocess
from pathlib import Path
import json

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='Unix-only')


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


def test_isolate_nontest_issue(tmp_path):
    out = tmp_path / "out.json"
    test_file = str(Path('tests') / 'pyt.py')

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out), '--isolate',
                                        '-m', 'pytest', '--my-invalid-flag', test_file],
                   check=False)
    assert p.returncode == pytest.ExitCode.USAGE_ERROR


def seq2p(tests_dir, seq):
    return tests_dir / f"test_{seq}.py"



FAILURES = {
    'assert': 'assert False',
    'exception': 'raise RuntimeError("test")',
    'kill': 'os.kill(os.getpid(), 9)',
    'exit': 'pytest.exit("goodbye")',
    'interrupt': 'raise KeyboardInterrupt()'
}

N_TESTS=10
def make_polluted_suite(tests_dir: Path, fail_collect: bool, fail_kind: str):
    """In a suite with 10 tests, test 6 fails; test 3 doesn't fail, but causes 6 to fail."""

    for seq in range(N_TESTS):
        seq2p(tests_dir, seq).write_text('def test_foo(): pass')

    polluter = seq2p(tests_dir, 3)
    polluter.write_text("import sys\n" + "sys.foobar = True\n" + "def test_foo(): pass")

    failing = seq2p(tests_dir, 6)
    failing.write_text(f"""\
import sys
import os
import pytest

def failure():
    {FAILURES[fail_kind]}

def test_foo():
    if getattr(sys, 'foobar', False):
        failure()

{'test_foo()' if fail_collect else ''}
""")

    return failing, polluter


def make_failing_suite(tests_dir: Path):
    """In a suite with 10 tests, test 6 fails."""

    for seq in range(N_TESTS):
        seq2p(tests_dir, seq).write_text('def test_foo(): pass')

    failing = seq2p(tests_dir, 6)
    failing.write_text("def test_bar(): assert False")


@pytest.mark.parametrize("fail_collect", [True, False])
@pytest.mark.parametrize("fail_kind", list(FAILURES.keys() - {'kill'}))
def test_check_suite_fails(tmp_path, monkeypatch, fail_collect, fail_kind):
    out = tmp_path / "out.json"

    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, fail_collect, fail_kind)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out),
                                        '-m', 'pytest', tests_dir], check=False)
    if fail_collect or fail_kind in ('exit', 'interrupt'):
        assert p.returncode == pytest.ExitCode.INTERRUPTED
    else:
        assert p.returncode == pytest.ExitCode.TESTS_FAILED


@pytest.mark.parametrize("fail_collect", [True, False])
@pytest.mark.parametrize("fail_kind", list(FAILURES.keys()))
def test_isolate_polluted(tmp_path, monkeypatch, fail_collect, fail_kind):
    out = tmp_path / "out.json"

    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, fail_collect, fail_kind)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out), '--isolate',
                                        '-m', 'pytest', tests_dir], check=False)
    assert p.returncode == pytest.ExitCode.OK

    with out.open() as f:
        cov = json.load(f)

    for seq in range(N_TESTS):
        p = seq2p(tests_dir, seq)
        assert str(p) in cov['files']


@pytest.mark.parametrize("fail_kind", list(FAILURES.keys()))
def test_pytest_discover_tests(tmp_path, fail_kind, monkeypatch):
    out = tmp_path / "out.json"

    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, fail_collect=False, fail_kind=fail_kind)

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out), '--isolate',
                                        '-m', 'pytest'], check=False) # no tests_dir here
    assert p.returncode == pytest.ExitCode.OK

    with out.open() as f:
        cov = json.load(f)

    for seq in range(N_TESTS):
        p = seq2p(tests_dir, seq)
        assert str(p) in cov['files']


@pytest.mark.parametrize("fail_collect", [True, False])
@pytest.mark.parametrize("fail_kind", list(FAILURES.keys()))
def test_isolate_with_failing_test(tmp_path, monkeypatch, fail_collect, fail_kind):
    out = tmp_path / "out.json"

    monkeypatch.chdir(tmp_path)
    tests_dir = Path('tests')
    tests_dir.mkdir()
    make_polluted_suite(tests_dir, fail_collect, fail_kind)

    # _unconditionally_ failing test
    failing = seq2p(tests_dir, 2)
    failing.write_text(f"""\
import sys
import os
import pytest

def failure():
    {FAILURES[fail_kind]}

def test_foo():
    failure()

{'test_foo()' if fail_collect else ''}
""")

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out),
                                        '-m', 'slipcover.isolate', tests_dir], check=False)
    assert p.returncode == pytest.ExitCode.TESTS_FAILED

    with out.open() as f:
        cov = json.load(f)

    for seq in range(N_TESTS):
        p = seq2p(tests_dir, seq)

        # can't capture coverage if the process gets killed
        if not (p == failing and fail_kind == 'kill'):
            assert str(p) in cov['files']
