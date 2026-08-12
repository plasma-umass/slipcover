import dis
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from io import StringIO
from pathlib import Path
from textwrap import dedent

import pytest

import slipcover.branch as br
import slipcover.slipcover as sc

PYTHON_VERSION = sys.version_info[0:2]

def current_line():
    import inspect as i
    return i.getframeinfo(i.currentframe().f_back).lineno

def current_file():
    import inspect as i
    return i.getframeinfo(i.currentframe().f_back).filename

def simple_current_file():
    simp = sc.PathSimplifier()
    return simp.simplify(current_file())

def ast_parse(s):
    import ast
    import inspect
    return ast.parse(inspect.cleandoc(s))



def test_pathsimplifier_not_relative():
    ps = sc.PathSimplifier()
    assert ".." == ps.simplify("..")


def test_function():
    sci = sc.Slipcover()

    base_line = current_line()
    def foo(n): #1
        if n == 42:
            return 666
        x = 0
        for i in range(n):
            x += (i+1)
        return x

    sci.instrument(foo)
    dis.dis(foo)

    assert 6 == foo(3)

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    assert [2, 4, 5, 6, 7] == [l-base_line for l in cov['executed_lines']]
    assert [3] == [l-base_line for l in cov['missing_lines']]


def test_generators():
    sci = sc.Slipcover()

    base_line = current_line()
    def foo(n):
        n += sum(
            x for x in range(10)
            if x % 2 == 0)
        n += [
            x for x in range(123)
            if x == 42][0]
        return n

    X = foo(123)

    sci.instrument(foo)
    dis.dis(foo)

    assert X == foo(123)

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    assert [2, 3, 4, 5, 6, 7, 8] == [l-base_line for l in cov['executed_lines']]

    assert [] == cov['missing_lines']


def test_exception():
    sci = sc.Slipcover()

    base_line = current_line()
    def foo(n): #1
        n += 10
        try:
            n += 10
            raise RuntimeError('just testing')
            n = 0 #6
        except RuntimeError:
            n += 15
        finally:
            n += 42

        return n #12

    orig_code = foo.__code__
    X = foo(42)

    sci.instrument(foo)
    dis.dis(orig_code)

    assert X == foo(42)

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    assert [2, 3, 4, 5, 7, 8, 10, 12] == [l-base_line for l in cov['executed_lines']]

    all_lines = {l-base_line for offset, l in sc.findlinestarts(foo.__code__)}

    if 6 not in all_lines: # 6 is unreachable and may be omitted from the code
        assert [] == [l-base_line for l in cov['missing_lines']]
    else:
        assert [6] == [l-base_line for l in cov['missing_lines']]


def test_threads():
    sci = sc.Slipcover()
    result = None

    base_line = current_line()
    def foo(n):
        nonlocal result
        x = 0
        for i in range(n):
            x += (i+1)
        result = x

    sci.instrument(foo)

    import threading

    t = threading.Thread(target=foo, args=(3,))
    t.start()
    t.join()

    assert 6 == result

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    assert [3, 4, 5, 6] == [l-base_line for l in cov['executed_lines']]
    assert [] == cov['missing_lines']


def test_async_inline():
    sci = sc.Slipcover()
    result = None

    base_line = current_line()
    async def foo(n):
        nonlocal result
        x = 0
        for i in range(n):
            x += (i+1)
        result = x

    sci.instrument(foo)

    import asyncio
    asyncio.run(foo(3))

    assert 6 == result

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    assert [3, 4, 5, 6] == [l-base_line for l in cov['executed_lines']]
    assert [] == cov['missing_lines']


@pytest.mark.parametrize("do_branch", [True, False])
def test_async_file(tmp_path, do_branch):
    code = tmp_path / "t.py"
    out = tmp_path / "out.json"

    code.write_text("""\
import asyncio

async def foo(n):
    x = 0
    for i in range(n):
        x += (i+1)
    result = x

asyncio.run(foo(3))
""")

    subprocess.run([sys.executable, '-m', 'slipcover'] + (['--branch'] if do_branch else []) +\
                   ['--json', '--out', out, code])
    with out.open("r") as f:
        cov = json.load(f)

    assert {str(code)} == cov['files'].keys()

    cov = cov['files'][str(code)]
    assert [1, 3, 4, 5, 6, 7, 9] == cov['executed_lines']
    assert [] == cov['missing_lines']

    if do_branch:
        assert [[5,6], [5,7]] == cov['executed_branches']
        assert [] == cov['missing_branches']
    else:
        assert 'executed_branches' not in cov
        assert 'missing_branches' not in cov


def test_branches():
    t = ast_parse("""
        def foo(x):
            if x >= 0:
                if x > 1:
                    if x > 2:
                        return 2
                    return 1

            else:
                return 0

        foo(2)
    """)
    t = br.preinstrument(t)

    sci = sc.Slipcover(branch=True)
    code = compile(t, 'foo', 'exec')
    code = sci.instrument(code)
#    dis.dis(code)

    g = dict()
    exec(code, g, g)

    cov = sci.get_coverage()
    assert {'foo'} == cov['files'].keys()

    cov = cov['files']['foo']
    assert [1,2,3,4,6,11] == cov['executed_lines']
    assert [5,9] == cov['missing_lines']

    assert [(2,3),(3,4),(4,6)] == cov['executed_branches']
    assert [(2,9),(3,0),(4,5)] == cov['missing_branches']


@pytest.mark.parametrize("x", [5, 20])
def test_branch_into_line_block(x):
    # the 5->7 branch may lead to a jump into the middle of line # 7's block;
    # will it miss its line probe?  Happens with Python 3.10.9.
    t = ast_parse(f"""
        import pytest

        def foo(x):
            y = x + 10
            if y > 20:
                y -= 1
            return y

        foo({x})
    """)
    t = br.preinstrument(t)

    sci = sc.Slipcover(branch=True)
    code = compile(t, 'foo', 'exec')
    code = sci.instrument(code)
    dis.dis(code)

    g = dict()
    exec(code, g, g)

    cov = sci.get_coverage()
    assert {'foo'} == cov['files'].keys()

    cov = cov['files']['foo']
    if (x+10)>20:
        assert [1,3,4,5,6,7,9] == cov['executed_lines']
        assert [] == cov['missing_lines']

        assert [(5,6)] == cov['executed_branches']
        assert [(5,7)] == cov['missing_branches']
    else:
        assert [1,3,4,5,7,9] == cov['executed_lines']
        assert [6] == cov['missing_lines']

        assert [(5,7)] == cov['executed_branches']
        assert [(5,6)] == cov['missing_branches']


@pytest.mark.parametrize("do_branch", [True, False])
def test_meta_in_results(do_branch):
    t = ast_parse("""
        def foo(x):
            if x >= 0:
                if x > 1:
                    if x > 2:
                        return 2
                    return 1

            else:
                return 0

        foo(2)
    """)
    if do_branch:
        t = br.preinstrument(t)

    sci = sc.Slipcover(branch=do_branch)
    code = compile(t, 'foo', 'exec')
    code = sci.instrument(code)

    g = dict()
    exec(code, g, g)

    cov = sci.get_coverage()

    assert 'meta' in cov
    meta = cov['meta']
    assert 'slipcover' == meta['software']
    assert sc.__version__ == meta['version']
    assert 'timestamp' in meta
    assert do_branch == meta['branch_coverage']
    assert meta['show_contexts'] is False


def test_get_coverage_detects_lines():
    base_line = current_line()
    def foo(n):             # 1
        """Foo.

        Bar baz.
        """
        x = 0               # 6

        def bar():          # 8
            x += 42

        # now we loop
        for i in range(n):  # 12
            x += (i+1)

        return x

    sci = sc.Slipcover()
    sci.instrument(foo)

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    assert [6, 8, 9, 12, 13, 15] == [l-base_line for l in cov['missing_lines']]
    assert [] == cov['executed_lines']


def test_format_missing():
    fm = sc.format_missing

    assert "" == fm([],[],[])
    assert "" == fm([], [1,2,3], [])
    assert "2, 4" == fm([2,4], [1,3,5], [])
    assert "2-4, 6, 9" == fm([2,3,4, 6, 9], [1, 5, 7,8], [])

    assert "2-6, 9-11" == fm([2,4,6, 9,11], [1, 7,8], [])

    assert "2-11" == fm([2,4,6, 9,11], [], [])

    assert "2-6, 9-11" == fm([2,4,6, 9,11], [8], [])


    assert "1->3" == fm([], [1,2,3], [(1,3)])
    assert "2->exit" == fm([], [1,2,3], [(2,0)])

    assert "2->exit, 4" == fm([4], [1,2,3], [(2,0)])

    assert "2->exit, 4, 22" == fm([4, 22], [1,2,3,21], [(2,0)])

    # omit missing branches involving lines that are missing
    assert "2, 4" == fm([2,4], [1,3,5], [(2,3), (3,4)])


def test_print_coverage(capsys):
    sci = sc.Slipcover()

    base_line = current_line()
    def foo(n):
        if n == 42:
            return 666 #3
        x = 0
        for i in range(n):
            x += (i+1)
        return x

    sci.instrument(foo)
    foo(3)
    sci.print_coverage(sys.stdout)

    cov = sci.get_coverage()['files'][simple_current_file()]
    execd = len(cov['executed_lines'])
    missd = len(cov['missing_lines'])
    total = execd+missd

    # TODO test more cases (multiple files, etc.)
    output = capsys.readouterr()[0]
    print(output)
    output = output.splitlines()
    assert re.match(f'^tests[/\\\\]test_coverage\\.py + {total} + {missd} +{round(100*execd/total)} +' + str(base_line+3), output[3])


def test_print_coverage_branch(capsys):
    t = ast_parse("""
        def foo(x):
            if x >= 0:
                if x > 1:
                    if x > 2:
                        return 2
                    return 1

            else:
                return 0

        foo(2)
    """)
    t = br.preinstrument(t)

    sci = sc.Slipcover(branch=True)
    code = compile(t, 'foo.py', 'exec')
    code = sci.instrument(code)

    sci.print_coverage(sys.stdout)

    cov = sci.get_coverage()['files']['foo.py']
    exec_l = len(cov['executed_lines'])
    miss_l = len(cov['missing_lines'])
    total_l = exec_l + miss_l
    exec_b = len(cov['executed_branches'])
    miss_b = len(cov['missing_branches'])
    total_b = exec_b + miss_b

    pct = round(100*(exec_l+exec_b)/(total_l+total_b))
    pct_b = round(100*exec_b/total_b)

    # TODO test more cases (multiple files, etc.)
    output = capsys.readouterr()[0]
    print(output)
    output = output.splitlines()
    assert re.match(f'^foo\\.py +{total_l} +{miss_l} +{total_b} +{miss_b} +{pct_b} +{pct}', output[3])


@pytest.mark.parametrize("do_branch", [True, False])
def test_print_coverage_zero_lines(do_branch, capsys):
    t = ast_parse("")
    if do_branch:
        t = br.preinstrument(t)

    sci = sc.Slipcover(branch=do_branch)
    code = compile(t, 'foo.py', 'exec')
    code = sci.instrument(code)
    #dis.dis(code)

    g = dict()
    exec(code, g, g)
    sci.print_coverage(sys.stdout)
    output = capsys.readouterr()[0]
    output = output.splitlines()
    assert re.match(f'^foo\\.py +{"1" if PYTHON_VERSION < (3,11) else "0"} +0{" +0 +0 +0" if do_branch else ""} +100', output[3])


@pytest.mark.parametrize("do_branch", [True, False])
def test_print_coverage_no_coverage(capsys, do_branch):
    sci = sc.Slipcover(branch=do_branch)
    cov = sci.get_coverage()
    sc.print_coverage(cov)


def test_print_coverage_skip_covered():
    p = subprocess.run(f"{sys.executable} -m slipcover --skip-covered tests/importer.py".split(),
                       check=True, capture_output=True)
    output = str(p.stdout)
    print(output)
    assert '__init__.py' in output
    assert 'importer.py' not in output


@pytest.mark.parametrize("do_branch", [True, False])
def test_interpose_on_module_load(tmp_path, do_branch):
    # TODO include in coverage info
    out_file = tmp_path / "out.json"

    subprocess.run(f"{sys.executable} -m slipcover {'--branch ' if do_branch else ''}--json --out {out_file} tests/importer.py".split(),
                   check=True)
    with open(out_file, "r") as f:
        cov = json.load(f)

    module_file = str(Path('tests') / 'imported' / '__init__.py')

    assert module_file in cov['files']
    assert [1,2,3,4,5,6,8] == cov['files'][module_file]['executed_lines']
    assert [9] == cov['files'][module_file]['missing_lines']
    if do_branch:
        assert [[3,4], [4,5], [4,6]] == cov['files'][module_file]['executed_branches']
        assert [[3,6]] == cov['files'][module_file]['missing_branches']
    else:
        assert 'executed_branches' not in cov['files'][module_file]
        assert 'missing_branches' not in cov['files'][module_file]


def test_pytest_interpose(tmp_path):
    # TODO include in coverage info
    out_file = tmp_path / "out.json"

    test_file = str(Path('tests') / 'pyt.py')

    subprocess.run(f"{sys.executable} -m slipcover --json --out {out_file} -m pytest {test_file}".split(),
                   check=True)
    with open(out_file, "r") as f:
        cov = json.load(f)

    assert test_file in cov['files']
    assert {test_file} == set(cov['files'].keys())  # any unrelated files included?
    cov = cov['files'][test_file]
    assert [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14] == cov['executed_lines']
    assert [] == cov['missing_lines']


def test_pytest_interpose_branch(tmp_path):
    # TODO include in coverage info
    test_file = str(Path('tests') / 'pyt.py')
    def cache_files():
        return list(Path("tests/__pycache__").glob(f"pyt*{sys.implementation.cache_tag}-pytest*.pyc"))

    # remove and create a clean pytest cache, to make sure it's not interfering
    for p in cache_files(): p.unlink()
    subprocess.run(f"{sys.executable} -m pytest {test_file}".split(), check=True)
    pytest_cache_files = cache_files()
    assert len(pytest_cache_files) == 1
    pytest_cache_content = pytest_cache_files[0].read_bytes()

    out_file = tmp_path / "out.json"
    subprocess.run(f"{sys.executable} -m slipcover --branch --json --out {out_file} -m pytest {test_file}".split(),
                   check=True)
    with open(out_file, "r") as f:
        cov = json.load(f)

    assert test_file in cov['files']
    assert {test_file} == set(cov['files'].keys())  # any unrelated files included?
    cov = cov['files'][test_file]
    assert [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14] == cov['executed_lines']
    assert [] == cov['missing_lines']
    assert [[3,4], [4,5], [4,6]] == cov['executed_branches']
    assert [[3,6]] == cov['missing_branches']

    new_cache_files = set(cache_files())
    sc_cache_files = set(fn for fn in new_cache_files if ('slipcover-' + sc.__version__) in fn.name)

    # ensure ours is being cached
    assert {} != sc_cache_files

    # and that nothing else changed
    assert set(pytest_cache_files) == new_cache_files - sc_cache_files
    assert (pytest_cache_content == pytest_cache_files[0].read_bytes())


def test_pytest_plugins_visible():
    def pytest_plugins():
        from importlib import metadata
        return [dist.metadata['Name'] for dist in metadata.distributions() \
                if any(ep.group == "pytest11" for ep in dist.entry_points)]

    assert pytest_plugins, "No pytest plugins installed, can't tell if they'd be visible."

    plain = subprocess.run(f"{sys.executable} -m pytest -VV".split(), check=True, capture_output=True)
    with_sc = subprocess.run(f"{sys.executable} -m slipcover --silent -m pytest -VV".split(), check=True,
                             capture_output=True)

    assert plain.stdout == with_sc.stdout


@pytest.mark.parametrize("do_branch", [True, False])
def test_summary_in_output(tmp_path, do_branch):
    # TODO include in coverage info
    out_file = tmp_path / "out.json"

    subprocess.run(f"{sys.executable} -m slipcover {'--branch ' if do_branch else ''}--json --out {out_file} tests/importer.py".split(),
                   check=True)
    with open(out_file, "r") as f:
        cov = json.load(f)

    for fn in cov['files']:
        assert 'summary' in cov['files'][fn]
        summ = cov['files'][fn]['summary']

        assert len(cov['files'][fn]['executed_lines']) == summ['covered_lines']
        assert len(cov['files'][fn]['missing_lines']) == summ['missing_lines']

        nom = summ['covered_lines']
        den = summ['covered_lines'] + summ['missing_lines']

        if do_branch:
            assert len(cov['files'][fn]['executed_branches']) == summ['covered_branches']
            assert len(cov['files'][fn]['missing_branches']) == summ['missing_branches']

            nom += summ['covered_branches']
            den += summ['covered_branches'] + summ['missing_branches']

        assert pytest.approx(100*nom/den) == summ['percent_covered']

    assert 'summary' in cov
    summ = cov['summary']

    missing_lines = sum(cov['files'][fn]['summary']['missing_lines'] for fn in cov['files'])
    executed_lines = sum(cov['files'][fn]['summary']['covered_lines'] for fn in cov['files'])

    nom = executed_lines
    den = nom + missing_lines

    assert missing_lines == summ['missing_lines']
    assert executed_lines == summ['covered_lines']

    if do_branch:
        missing_branches = sum(cov['files'][fn]['summary']['missing_branches'] for fn in cov['files'])
        executed_branches = sum(cov['files'][fn]['summary']['covered_branches'] for fn in cov['files'])

        nom += executed_branches
        den += missing_branches + executed_branches

        assert missing_branches == summ['missing_branches']
        assert executed_branches == summ['covered_branches']

    assert pytest.approx(100*nom/den) == summ['percent_covered']


@pytest.mark.parametrize("do_branch", [True, False])
def test_summary_in_output_zero_lines(do_branch):
    t = ast_parse("")
    if do_branch:
        t = br.preinstrument(t)

    sci = sc.Slipcover(branch=do_branch)
    code = compile(t, 'foo', 'exec')
    code = sci.instrument(code)
    #dis.dis(code)

    g = dict()
    exec(code, g, g)

    cov = sci.get_coverage()

    for fn in cov['files']:
        assert 'summary' in cov['files'][fn]
        summ = cov['files'][fn]['summary']

        if PYTHON_VERSION >= (3,11):
            assert 0 == summ['covered_lines']
        else:
            assert 1 == summ['covered_lines']

        assert 0 == summ['missing_lines']

        if do_branch:
            assert 0 == summ['covered_branches']
            assert 0 == summ['missing_branches']

        assert 100.0 == summ['percent_covered']


    assert 'summary' in cov
    summ = cov['summary']

    if PYTHON_VERSION >= (3,11):
        assert 0 == summ['covered_lines']
    else:
        assert 1 == summ['covered_lines']
    assert 0 == summ['missing_lines']

    if do_branch:
        assert 0 == summ['missing_branches']
        assert 0 == summ['covered_branches']

    assert 100.0 == summ['percent_covered']


@pytest.mark.parametrize("json_flag", ["", "--json"])
def test_fail_under(tmp_path, json_flag):
    p = subprocess.run(f"{sys.executable} -m slipcover {json_flag} --fail-under 100 tests/branch.py".split(), check=False)
    assert 0 == p.returncode

    p = subprocess.run(f"{sys.executable} -m slipcover {json_flag} --branch --fail-under 85 tests/branch.py".split(), check=False)
    assert 0 == p.returncode

    p = subprocess.run(f"{sys.executable} -m slipcover {json_flag} --branch --fail-under 86 tests/branch.py".split(), check=False)
    assert 2 == p.returncode

    p = subprocess.run(f"{sys.executable} -m slipcover --branch --fail-under 93 -m pytest tests/pyt.py".split(), check=False)
    assert 0 == p.returncode

    p = subprocess.run(f"{sys.executable} -m slipcover --branch --fail-under 94 -m pytest tests/pyt.py".split(), check=False)
    assert 2 == p.returncode


def test_fail_under_precedence_with_nonzero_exit(tmp_path):
    """When the script/pytest run itself fails (nonzero SystemExit) AND
    coverage is below the fail-under threshold, coverage failure (RC 2)
    takes precedence. But when coverage is fine, the run's own nonzero
    exit code must be preserved, not silently replaced with 0.
    """
    script = tmp_path / "script.py"
    script.write_text(dedent("""\
        def foo(x):
            if x:
                return 1
            return 2
        foo(0)
        raise SystemExit(3)
    """))

    # coverage is fine (line 3 "return 1" never runs, but threshold is low) --
    # the script's own exit code (3) must be preserved
    p = subprocess.run(f"{sys.executable} -m slipcover --fail-under 1 {script}".split(), check=False)
    assert 3 == p.returncode

    # coverage is below threshold -- fail-under (2) must override the
    # script's own exit code
    p = subprocess.run(f"{sys.executable} -m slipcover --fail-under 100 {script}".split(), check=False)
    assert 2 == p.returncode


def test_fail_under_precedence_with_failing_pytest_run(tmp_path):
    """Same precedence check as test_fail_under_precedence_with_nonzero_exit,
    but through the `-m pytest` path with a genuinely failing test (pytest's
    own SystemExit(1)), rather than a script raising SystemExit directly.
    """
    test_file = tmp_path / "test_mod.py"
    test_file.write_text(dedent("""\
        def foo(x):
            if x:
                return 1
            return 2

        def test_fail():
            assert foo(0) == 2
            assert False
    """))

    # coverage is fine -- pytest's own failure exit code (1) must be preserved
    p = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--fail-under', '1', '-m', 'pytest', test_file.name],
        cwd=str(tmp_path), check=False)
    assert 1 == p.returncode

    # coverage is below threshold -- fail-under (2) must override pytest's
    # own exit code
    p = subprocess.run(
        [sys.executable, '-m', 'slipcover', '--fail-under', '100', '-m', 'pytest', test_file.name],
        cwd=str(tmp_path), check=False)
    assert 2 == p.returncode


def test_reports_on_other_sources(tmp_path):
    out_file = tmp_path / "out.json"

    subprocess.run((f"{sys.executable} -m slipcover --branch --json --out {out_file} " +\
                    f"--source tests/imported tests/importer.py").split(),
                   check=True)
    with open(out_file, "r") as f:
        cov = json.load(f)

    assert 'tests/importer.py' not in cov['files']
    assert str(Path('tests/importer.py').resolve()) not in cov['files']

    init_file = str(Path('tests') / 'imported' / '__init__.py')
    foo_file = str(Path('tests') / 'imported' / 'foo.py')
    baz_file = str(Path('tests') / 'imported' / 'subdir' / 'baz.PY')

    assert init_file in cov['files']
    assert [1,2,3,4,5,6,8] == cov['files'][init_file]['executed_lines']
    assert [9] == cov['files'][init_file]['missing_lines']
    assert [[3,4], [4,5], [4,6]] == cov['files'][init_file]['executed_branches']
    assert [[3,6]] == cov['files'][init_file]['missing_branches']

    assert foo_file in cov['files']
    assert [] == cov['files'][foo_file]['executed_lines']
    assert [1, 2, 3, 4, 5] == cov['files'][foo_file]['missing_lines']
    assert [] == cov['files'][foo_file]['executed_branches']
    assert [[3,4], [3,5]] == cov['files'][foo_file]['missing_branches']

    assert baz_file in cov['files']
    assert [] == cov['files'][baz_file]['executed_lines']
    assert [1] == cov['files'][baz_file]['missing_lines']
    assert [] == cov['files'][baz_file]['executed_branches']
    assert [] == cov['files'][baz_file]['missing_branches']


def test_resolves_other_sources(tmp_path):
    out_file = tmp_path / "out.json"

    subprocess.run((f"{sys.executable} -m slipcover --branch --json --out {out_file} " +\
                    f"--source tests/../tests/imported tests/importer.py").split(),
                   check=True)
    with open(out_file, "r") as f:
        cov = json.load(f)

    init_file = str(Path('tests') / 'imported' / '__init__.py')
    foo_file = str(Path('tests') / 'imported' / 'foo.py')
    baz_file = str(Path('tests') / 'imported' / 'subdir' / 'baz.PY')

    assert init_file in cov['files']
    assert [1,2,3,4,5,6,8] == cov['files'][init_file]['executed_lines']
    assert [9] == cov['files'][init_file]['missing_lines']
    assert [[3,4], [4,5], [4,6]] == cov['files'][init_file]['executed_branches']
    assert [[3,6]] == cov['files'][init_file]['missing_branches']

    assert foo_file in cov['files']
    assert [] == cov['files'][foo_file]['executed_lines']
    assert [1, 2, 3, 4, 5] == cov['files'][foo_file]['missing_lines']
    assert [] == cov['files'][foo_file]['executed_branches']
    assert [[3,4], [3,5]] == cov['files'][foo_file]['missing_branches']

    assert baz_file in cov['files']
    assert [] == cov['files'][baz_file]['executed_lines']
    assert [1] == cov['files'][baz_file]['missing_lines']
    assert [] == cov['files'][baz_file]['executed_branches']
    assert [] == cov['files'][baz_file]['missing_branches']


def test_omit_with_source(tmp_path):
    """Test that --omit works correctly with --source (Issue #74)."""
    out_file = tmp_path / "out.json"

    # Use --source tests/imported and --omit to exclude foo.py files
    subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out_file),
                    '--source', 'tests/imported', '--omit', '*/foo.py', 'tests/importer.py'],
                   check=True)
    with open(out_file, "r") as f:
        cov = json.load(f)

    init_file = str(Path('tests') / 'imported' / '__init__.py')
    foo_file = str(Path('tests') / 'imported' / 'foo.py')
    baz_file = str(Path('tests') / 'imported' / 'subdir' / 'baz.PY')

    # __init__.py and baz.PY should be included
    assert init_file in cov['files']
    assert baz_file in cov['files']

    # foo.py should be omitted due to --omit '*/foo.py'
    assert foo_file not in cov['files']


def check_summaries(cov):
    import copy

    check = copy.deepcopy(cov)
    sc.add_summaries(check)

    for f in cov['files']:
        assert 'summary' in cov['files'][f]
        assert check['files'][f]['summary'] == cov['files'][f]['summary']

    assert check['summary'] == cov['summary']


@pytest.mark.parametrize("do_branch", [True, False, None])
def test_merge_coverage(tmp_path, monkeypatch, do_branch):
    monkeypatch.chdir(tmp_path)

    (tmp_path / "t.py").write_text("""\
import sys

if len(sys.argv) < 2:   # 3
    print("A branch")

else:
    import t2           # 7
    print("B branch")

if not sys.argv:        # 10
    print("I'm unreachable!")

print("all done!")      # 13
""")

    (tmp_path / "t2.py").write_text("""\
print("in t2!")
""")

    subprocess.run([sys.executable, '-m', 'slipcover'] +\
                   (['--branch'] if do_branch else []) +\
                    ['--json', '--out', tmp_path / "a.json", "t.py"], check=True)
    subprocess.run([sys.executable, '-m', 'slipcover'] +\
                   (['--branch'] if do_branch else []) +\
                    ['--json', '--out', tmp_path / "b.json", "t.py", "X"], check=True)

    with (tmp_path / "a.json").open() as f:
        a = json.load(f)
    with (tmp_path / "b.json").open() as f:
        b = json.load(f)

    if do_branch is None:
        del b['meta']['branch_coverage']

    assert 't2.py' not in a['files']
    assert 't2.py' in b['files']
    assert a['files']['t.py']['executed_lines'] != b['files']['t.py']['executed_lines']

    sc.merge_coverage(a, b)

    assert 't.py' in a['files']
    assert [1, 3, 4, 7, 8, 10, 13] == a['files']['t.py']['executed_lines']
    assert [11] == a['files']['t.py']['missing_lines']

    if do_branch:
        assert [[3, 4], [3, 7], [10, 13]] == a['files']['t.py']['executed_branches']
        assert [[10, 11]] == a['files']['t.py']['missing_branches']
    else:
        assert 'executed_branches' not in a['files']['t.py']
        assert 'missing_branches' not in a['files']['t.py']

    assert 't2.py' in a['files']
    assert [1] == a['files']['t2.py']['executed_lines']
    assert [] == a['files']['t2.py']['missing_lines']

    if do_branch:
        assert [] == a['files']['t2.py']['executed_branches']
        assert [] == a['files']['t2.py']['missing_branches']
    else:
        assert 'executed_branches' not in a['files']['t2.py']
        assert 'missing_branches' not in a['files']['t2.py']

    assert bool(do_branch) == a['meta']['branch_coverage']

    check_summaries(a)


@pytest.mark.parametrize("do_branch", [True, False])
def test_merge_coverage_canonicalizes_paths(tmp_path, monkeypatch, do_branch):
    """When the same physical file is recorded under two different path
    spellings (e.g. relative + absolute, or via a symlink), merge_coverage
    should canonicalize the paths and collapse the entries into one.

    This happens in practice when one workload step records files via a
    cwd-relative path (e.g. running `python -m pkg pkg/`) while another step
    imports the same files as a package, causing Python's import machinery
    to expose them via their editable-install absolute path.
    """
    monkeypatch.chdir(tmp_path)

    (tmp_path / "t.py").write_text("""\
import sys
if len(sys.argv) < 2:   # 2
    print("A branch")
else:
    print("B branch")   # 5
""")

    subprocess.run([sys.executable, '-m', 'slipcover'] +
                   (['--branch'] if do_branch else []) +
                   ['--json', '--out', tmp_path / "a.json", "t.py"], check=True)
    subprocess.run([sys.executable, '-m', 'slipcover'] +
                   (['--branch'] if do_branch else []) +
                   ['--json', '--out', tmp_path / "b.json", "t.py", "X"], check=True)

    with (tmp_path / "a.json").open() as f:
        a = json.load(f)
    with (tmp_path / "b.json").open() as f:
        b = json.load(f)

    # Re-key b's entry to the absolute path that the same file resolves to.
    abs_path = str((tmp_path / "t.py").resolve())
    assert abs_path != "t.py"
    b['files'][abs_path] = b['files'].pop('t.py')

    assert 't.py' in a['files']
    assert abs_path in b['files']

    sc.merge_coverage(a, b)

    # Aliases collapse into a single entry.
    t_keys = [k for k in a['files'] if k.endswith('t.py')]
    assert len(t_keys) == 1, f"expected one entry for t.py, got: {t_keys}"

    # The shorter (relative) display form wins when both forms exist.
    assert t_keys[0] == 't.py'

    # Coverage from both runs is unioned.
    # Run a (no extra arg) executes lines 1,2,3; run b (with arg) executes 1,2,5.
    assert {1, 2, 3, 5} <= set(a['files']['t.py']['executed_lines'])
    assert [] == a['files']['t.py']['missing_lines']

    if do_branch:
        # Both branches of the `if` at line 2 should be covered.
        assert [2, 3] in a['files']['t.py']['executed_branches']
        assert [2, 5] in a['files']['t.py']['executed_branches']
        assert [] == a['files']['t.py']['missing_branches']

    check_summaries(a)


@pytest.fixture
def cov_merge_fixture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    (tmp_path / "t.py").write_text("""\
import sys

if len(sys.argv) < 2:   # 3
    print("A branch")
else:
    print("B branch")   # 6

if not sys.argv:        # 8
    print("I'm unreachable!")

print("all done!")      # 11
""")

    yield tmp_path



@pytest.mark.parametrize("branch_in", ['a', 'b'])
def test_merge_coverage_branch_coverage_disagree(cov_merge_fixture, branch_in):
    subprocess.run([sys.executable, '-m', 'slipcover'] +\
                   (['--branch'] if branch_in == 'a' else []) +\
                    ['--json', '--out', "a.json", "t.py"], check=True)
    subprocess.run([sys.executable, '-m', 'slipcover'] +\
                   (['--branch'] if branch_in == 'b' else []) +\
                    ['--json', '--out', "b.json", "t.py", "X"], check=True)

    with Path("a.json").open() as f:
        a = json.load(f)
    with Path("b.json").open() as f:
        b = json.load(f)

    assert [1, 3, 4, 8, 11] == a['files']['t.py']['executed_lines']
    assert [1, 3, 6, 8, 11] == b['files']['t.py']['executed_lines']

    if branch_in == 'a':
        with pytest.raises(sc.SlipcoverError):
            sc.merge_coverage(a, b)

    else:
        sc.merge_coverage(a, b)
        assert False == a['meta']['branch_coverage']

        assert [1, 3, 4, 6, 8, 11] == a['files']['t.py']['executed_lines']
        assert [9] == a['files']['t.py']['missing_lines']

        assert 'executed_branches' not in a['files']['t.py']
        assert 'missing_branches' not in a['files']['t.py']

        check_summaries(a)


@pytest.mark.skipif(sys.platform == 'win32', reason='pytest-forked is Unix-specific')
def test_pytest_forked(tmp_path):
    out = tmp_path / "out.json"
    test_file = str(Path('tests') / 'pyt.py')

    subprocess.run([sys.executable, '-m', 'slipcover', '--json', '--out', str(out),
                                    '-m', 'pytest', '--forked', test_file], check=True)

    with out.open() as f:
        cov = json.load(f)

    check_summaries(cov)

    assert test_file in cov['files']
    assert {test_file} == set(cov['files'].keys())
    cov = cov['files'][test_file]
    assert [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14] == cov['executed_lines']
    assert [] == cov['missing_lines']


@pytest.mark.skipif(sys.platform == 'win32', reason='fork() and pytest-forked are Unix-specific')
def test_forked_twice(tmp_path, monkeypatch):
    source = (Path('tests') / 'pyt.py').resolve()
    out = tmp_path / "out.json"

    monkeypatch.chdir(tmp_path)
    test_file = 't.py'
    Path(test_file).write_text(source.read_text())

    script = tmp_path / "foo.py"
    script.write_text(f"""\
import os
import sys
import pytest

if (pid := os.fork()):
    pid, status = os.waitpid(pid, 0)
    if status:
        if os.WIFSIGNALED(status):
            exitstatus = os.WTERMSIG(status) + 128
        else:
            exitstatus = os.WEXITSTATUS(status)
    else:
        exitstatus = 0

    sys.exit(exitstatus)
else:
    print(os.getpid(), "calling pytest")
    os._exit(pytest.main(['--forked', '{test_file}']))
""")

    subprocess.run([sys.executable, '-m', 'slipcover', '--debug', '--json', '--out', str(out), script])

    with out.open() as f:
        cov = json.load(f)

    check_summaries(cov)

    assert test_file in cov['files']
    cov = cov['files'][test_file]
    assert [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14] == cov['executed_lines']
    assert [] == cov['missing_lines']


@pytest.mark.skipif(sys.platform == 'win32', reason='fork() and and other functions are Unix-specific')
def test_fork_close(tmp_path, monkeypatch, capfd):
    source = (Path('tests') / 'pyt.py').resolve()
    out = tmp_path / "out.json"

    script = tmp_path / "foo.py"
    script.write_text("""\
import os
import sys

if (pid := os.fork()):
    pid, status = os.waitpid(pid, 0)
    if status:
        if os.WIFSIGNALED(status):
            exitstatus = os.WTERMSIG(status) + 128
        else:
            exitstatus = os.WEXITSTATUS(status)
    else:
        exitstatus = 0

    sys.exit(exitstatus)
else:
    os.closerange(3, os.sysconf("SC_OPEN_MAX")) #16
""")

    # don't use capture_output here to let pytest manage/display the output.
    subprocess.run([sys.executable, '-m', 'slipcover', '--debug', '--json', '--out', str(out), script])

    with out.open() as f:
        cov = json.load(f)

     # no warnings about not being able to read from subprocess JSON coverage file
    assert capfd.readouterr().err == ""

    check_summaries(cov)

    script = str(script)
    assert script in cov['files']
    cov = cov['files'][script]
    assert 16 not in  cov['executed_lines']


def test_merge_flag(cov_merge_fixture):
    subprocess.run([sys.executable, '-m', 'slipcover', '--branch',
                    '--json', '--out', "a.json", "t.py"], check=True)
    subprocess.run([sys.executable, '-m', 'slipcover', '--branch',
                    '--json', '--out', "b.json", "t.py", "X"], check=True)

    subprocess.run([sys.executable, '-m', 'slipcover', '--merge',
                    'a.json', 'b.json', '--out', 'c.json'], check=True)

    with Path("c.json").open() as f:
        c = json.load(f)

    assert [1, 3, 4, 6, 8, 11] == c['files']['t.py']['executed_lines']
    assert [9] == c['files']['t.py']['missing_lines']
    assert True == c['meta']['branch_coverage']

    check_summaries(c)


def test_merge_flag_no_out(cov_merge_fixture):
    subprocess.run([sys.executable, '-m', 'slipcover', '--branch',
                    '--json', '--out', "a.json", "t.py"], check=True)
    subprocess.run([sys.executable, '-m', 'slipcover', '--branch',
                    '--json', '--out', "b.json", "t.py", "X"], check=True)

    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run([sys.executable, '-m', 'slipcover', '--merge', 'a.json', 'b.json'], check=True)

def test_xml_flag(cov_merge_fixture: Path):
    p = subprocess.run([sys.executable, '-m', 'slipcover', '--xml', '--out', "out.xml", "t.py"], check=True)
    assert 0 == p.returncode

    xtext = (cov_merge_fixture / 'out.xml').read_text(encoding='utf8')
    dom = ET.fromstring(xtext)

    assert dom.tag == 'coverage'

    assert dom.get('lines-valid') == '7'
    assert dom.get('lines-covered') == '5'
    assert dom.get('line-rate') == '0.7143'
    assert dom.get('branch-rate') == '0'
    assert dom.get('complexity') == '0'

    sources = dom.findall('.//sources/source')
    assert [elt.text for elt in sources] == [str(Path.cwd())]

    package = dom.find('.//packages/package')
    assert package.get('name') == '.'
    assert package.get('line-rate') == '0.7143'
    assert package.get('branch-rate') == '0'
    assert package.get('complexity') == '0'

    class_ = package.find('.//classes/class')
    assert class_.get('name') == 't.py'
    assert class_.get('filename') == 't.py'
    assert class_.get('complexity') == '0'
    assert class_.get('line-rate') == '0.7143'
    assert class_.get('branch-rate') == '0'

    lines = class_.findall('.//lines/line')
    assert len(lines) == 7

    assert lines[0].get('number') == '1'
    assert lines[0].get('hits') == '1'
    assert lines[0].get('branch') is None
    assert lines[0].get('condition-coverage') is None
    assert lines[0].get('missing-branches') is None

    assert lines[1].get('number') == '3'
    assert lines[1].get('hits') == '1'
    assert lines[1].get('branch') is None
    assert lines[1].get('condition-coverage') is None
    assert lines[1].get('missing-branches') is None

    assert lines[2].get('number') == '4'
    assert lines[2].get('hits') == '1'
    assert lines[2].get('branch') is None
    assert lines[2].get('condition-coverage') is None
    assert lines[2].get('missing-branches') is None

    assert lines[3].get('number') == '6'
    assert lines[3].get('hits') == '0'
    assert lines[3].get('branch') is None
    assert lines[3].get('condition-coverage') is None
    assert lines[3].get('missing-branches') is None

    assert lines[4].get('number') == '8'
    assert lines[4].get('hits') == '1'
    assert lines[4].get('branch') is None
    assert lines[4].get('condition-coverage') is None
    assert lines[4].get('missing-branches') is None

    assert lines[5].get('number') == '9'
    assert lines[5].get('hits') == '0'
    assert lines[5].get('branch') is None
    assert lines[5].get('condition-coverage') is None
    assert lines[5].get('missing-branches') is None

    assert lines[6].get('number') == '11'
    assert lines[6].get('hits') == '1'
    assert lines[6].get('branch') is None
    assert lines[6].get('condition-coverage') is None
    assert lines[6].get('missing-branches') is None


def test_xml_file_outside_cwd(tmp_path: Path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    external_file = tmp_path / "outside" / "external.py"
    external_file.parent.mkdir()
    external_file.touch()
    monkeypatch.chdir(cwd)

    output = StringIO()
    sc.print_xml(
        {
            "files": {
                str(external_file): {
                    "executed_lines": [1],
                    "missing_lines": [],
                }
            }
        },
        source_paths=[str(cwd)],
        outfile=output,
    )

    dom = ET.fromstring(output.getvalue())
    assert [source.text for source in dom.findall('.//sources/source')] == [
        str(cwd)
    ]
    assert dom.find('.//classes/class').get('filename') == str(external_file).replace(
        "\\", "/"
    )

def test_xml_flag_with_branches(cov_merge_fixture: Path):
    p = subprocess.run([sys.executable, '-m', 'slipcover', '--branch', '--xml', '--out', "out.xml", "t.py"], check=True)
    assert 0 == p.returncode

    xtext = (cov_merge_fixture / 'out.xml').read_text(encoding='utf8')
    dom = ET.fromstring(xtext)

    assert dom.tag == 'coverage'

    assert dom.get('lines-valid') == '7'
    assert dom.get('lines-covered') == '5'
    assert dom.get('line-rate') == '0.7143'
    assert dom.get('branch-rate') == '0.5'
    assert dom.get('complexity') == '0'

    sources = dom.findall('.//sources/source')
    assert [elt.text for elt in sources] == [str(Path.cwd())]

    package = dom.find('.//packages/package')
    assert package.get('name') == '.'
    assert package.get('line-rate') == '0.7143'
    assert package.get('branch-rate') == '0.5'
    assert package.get('complexity') == '0'

    class_ = package.find('.//classes/class')
    assert class_.get('name') == 't.py'
    assert class_.get('filename') == 't.py'
    assert class_.get('complexity') == '0'
    assert class_.get('line-rate') == '0.7143'
    assert class_.get('branch-rate') == '0.5'

    lines = class_.findall('.//lines/line')
    assert len(lines) == 7

    assert lines[0].get('number') == '1'
    assert lines[0].get('hits') == '1'
    assert lines[0].get('branch') is None
    assert lines[0].get('condition-coverage') is None
    assert lines[0].get('missing-branches') is None

    assert lines[1].get('number') == '3'
    assert lines[1].get('hits') == '1'
    assert lines[1].get('branch') == 'true'
    assert lines[1].get('condition-coverage') == '50% (1/2)'
    assert lines[1].get('missing-branches') == '6'

    assert lines[2].get('number') == '4'
    assert lines[2].get('hits') == '1'
    assert lines[2].get('branch') is None
    assert lines[2].get('condition-coverage') is None
    assert lines[2].get('missing-branches') is None

    assert lines[3].get('number') == '6'
    assert lines[3].get('hits') == '0'
    assert lines[3].get('branch') is None
    assert lines[3].get('condition-coverage') is None
    assert lines[3].get('missing-branches') is None

    assert lines[4].get('number') == '8'
    assert lines[4].get('hits') == '1'
    assert lines[4].get('branch') == 'true'
    assert lines[4].get('condition-coverage') == '50% (1/2)'
    assert lines[4].get('missing-branches') == '9'

    assert lines[5].get('number') == '9'
    assert lines[5].get('hits') == '0'
    assert lines[5].get('branch') is None
    assert lines[5].get('condition-coverage') is None
    assert lines[5].get('missing-branches') is None

    assert lines[6].get('number') == '11'
    assert lines[6].get('hits') == '1'
    assert lines[6].get('branch') is None
    assert lines[6].get('condition-coverage') is None
    assert lines[6].get('missing-branches') is None

def test_xml_flag_with_pytest(tmp_path):
    out_file = tmp_path / "out.xml"

    test_file = str(Path('tests') / 'pyt.py')

    subprocess.run(f"{sys.executable} -m slipcover --xml --out {out_file} -m pytest {test_file}".split(),
                   check=True)
    xtext = out_file.read_text(encoding='utf8')
    dom = ET.fromstring(xtext)

    assert dom.tag == 'coverage'

    elts = dom.findall(".//sources/source")
    assert [elt.text for elt in elts] == [str(Path.cwd())]

    assert dom.get('lines-valid') == '12'
    assert dom.get('lines-covered') == '12'
    assert dom.get('line-rate') == '1'
    assert dom.get('branch-rate') == '0'
    assert dom.get('complexity') == '0'

    sources = dom.findall('.//sources/source')
    assert [elt.text for elt in sources] == [str(Path.cwd())]

    package = dom.find('.//packages/package')
    assert package.get('name') == 'tests'
    assert package.get('line-rate') == '1'
    assert package.get('branch-rate') == '0'
    assert package.get('complexity') == '0'

    class_ = package.find('.//classes/class')
    assert class_.get('name') == 'pyt.py'
    assert class_.get('filename') == 'tests/pyt.py'
    assert class_.get('complexity') == '0'
    assert class_.get('line-rate') == '1'
    assert class_.get('branch-rate') == '0'

    lines = class_.findall('.//lines/line')
    assert len(lines) == 12

    assert lines[0].get('number') == '1'
    assert lines[0].get('hits') == '1'
    assert lines[0].get('branch') is None
    assert lines[0].get('condition-coverage') is None
    assert lines[0].get('missing-branches') is None

    assert lines[1].get('number') == '2'
    assert lines[1].get('hits') == '1'
    assert lines[1].get('branch') is None
    assert lines[1].get('condition-coverage') is None
    assert lines[1].get('missing-branches') is None

    assert lines[2].get('number') == '3'
    assert lines[2].get('hits') == '1'
    assert lines[2].get('branch') is None
    assert lines[2].get('condition-coverage') is None
    assert lines[2].get('missing-branches') is None

    assert lines[3].get('number') == '4'
    assert lines[3].get('hits') == '1'
    assert lines[3].get('branch') is None
    assert lines[3].get('condition-coverage') is None
    assert lines[3].get('missing-branches') is None

    assert lines[4].get('number') == '5'
    assert lines[4].get('hits') == '1'
    assert lines[4].get('branch') is None
    assert lines[4].get('condition-coverage') is None
    assert lines[4].get('missing-branches') is None

    assert lines[5].get('number') == '6'
    assert lines[5].get('hits') == '1'
    assert lines[5].get('branch') is None
    assert lines[5].get('condition-coverage') is None
    assert lines[5].get('missing-branches') is None

    assert lines[6].get('number') == '8'
    assert lines[6].get('hits') == '1'
    assert lines[6].get('branch') is None
    assert lines[6].get('condition-coverage') is None
    assert lines[6].get('missing-branches') is None

    assert lines[7].get('number') == '9'
    assert lines[7].get('hits') == '1'
    assert lines[7].get('branch') is None
    assert lines[7].get('condition-coverage') is None
    assert lines[7].get('missing-branches') is None
    
    assert lines[8].get('number') == '10'
    assert lines[8].get('hits') == '1'
    assert lines[8].get('branch') is None
    assert lines[8].get('condition-coverage') is None
    assert lines[8].get('missing-branches') is None

    assert lines[9].get('number') == '11'
    assert lines[9].get('hits') == '1'
    assert lines[9].get('branch') is None
    assert lines[9].get('condition-coverage') is None
    assert lines[9].get('missing-branches') is None

    assert lines[10].get('number') == '13'
    assert lines[10].get('hits') == '1'
    assert lines[10].get('branch') is None
    assert lines[10].get('condition-coverage') is None
    assert lines[10].get('missing-branches') is None

    assert lines[11].get('number') == '14'
    assert lines[11].get('hits') == '1'
    assert lines[11].get('branch') is None
    assert lines[11].get('condition-coverage') is None
    assert lines[11].get('missing-branches') is None


def test_xml_flag_with_branches_and_pytest(tmp_path):
    out_file = tmp_path / "out.xml"

    test_file = str(Path('tests') / 'pyt.py')

    subprocess.run(f"{sys.executable} -m slipcover --branch --xml --out {out_file} -m pytest {test_file}".split(),
                   check=True)
    xtext = out_file.read_text(encoding='utf8')
    dom = ET.fromstring(xtext)

    assert dom.tag == 'coverage'

    elts = dom.findall(".//sources/source")
    assert [elt.text for elt in elts] == [str(Path.cwd())]

    assert dom.get('lines-valid') == '12'
    assert dom.get('lines-covered') == '12'
    assert dom.get('line-rate') == '1'
    assert dom.get('branch-rate') == '0.75'
    assert dom.get('complexity') == '0'

    sources = dom.findall('.//sources/source')
    assert [elt.text for elt in sources] == [str(Path.cwd())]

    package = dom.find('.//packages/package')
    assert package.get('name') == 'tests'
    assert package.get('line-rate') == '1'
    assert package.get('branch-rate') == '0.75'
    assert package.get('complexity') == '0'

    class_ = package.find('.//classes/class')
    assert class_.get('name') == 'pyt.py'
    assert class_.get('filename') == 'tests/pyt.py'
    assert class_.get('complexity') == '0'
    assert class_.get('line-rate') == '1'
    assert class_.get('branch-rate') == '0.75'

    lines = class_.findall('.//lines/line')
    assert len(lines) == 12

    assert lines[0].get('number') == '1'
    assert lines[0].get('hits') == '1'
    assert lines[0].get('branch') is None
    assert lines[0].get('condition-coverage') is None
    assert lines[0].get('missing-branches') is None

    assert lines[1].get('number') == '2'
    assert lines[1].get('hits') == '1'
    assert lines[1].get('branch') is None
    assert lines[1].get('condition-coverage') is None
    assert lines[1].get('missing-branches') is None

    assert lines[2].get('number') == '3'
    assert lines[2].get('hits') == '1'
    assert lines[2].get('branch') == 'true'
    assert lines[2].get('condition-coverage') == '50% (1/2)'
    assert lines[2].get('missing-branches') == '6'

    assert lines[3].get('number') == '4'
    assert lines[3].get('hits') == '1'
    assert lines[3].get('branch') == 'true'
    assert lines[3].get('condition-coverage') == '100% (2/2)'
    assert lines[3].get('missing-branches') is None

    assert lines[4].get('number') == '5'
    assert lines[4].get('hits') == '1'
    assert lines[4].get('branch') is None
    assert lines[4].get('condition-coverage') is None
    assert lines[4].get('missing-branches') is None

    assert lines[5].get('number') == '6'
    assert lines[5].get('hits') == '1'
    assert lines[5].get('branch') is None
    assert lines[5].get('condition-coverage') is None
    assert lines[5].get('missing-branches') is None

    assert lines[6].get('number') == '8'
    assert lines[6].get('hits') == '1'
    assert lines[6].get('branch') is None
    assert lines[6].get('condition-coverage') is None
    assert lines[6].get('missing-branches') is None

    assert lines[7].get('number') == '9'
    assert lines[7].get('hits') == '1'
    assert lines[7].get('branch') is None
    assert lines[7].get('condition-coverage') is None
    assert lines[7].get('missing-branches') is None
    
    assert lines[8].get('number') == '10'
    assert lines[8].get('hits') == '1'
    assert lines[8].get('branch') is None
    assert lines[8].get('condition-coverage') is None
    assert lines[8].get('missing-branches') is None

    assert lines[9].get('number') == '11'
    assert lines[9].get('hits') == '1'
    assert lines[9].get('branch') is None
    assert lines[9].get('condition-coverage') is None
    assert lines[9].get('missing-branches') is None

    assert lines[10].get('number') == '13'
    assert lines[10].get('hits') == '1'
    assert lines[10].get('branch') is None
    assert lines[10].get('condition-coverage') is None
    assert lines[10].get('missing-branches') is None

    assert lines[11].get('number') == '14'
    assert lines[11].get('hits') == '1'
    assert lines[11].get('branch') is None
    assert lines[11].get('condition-coverage') is None
    assert lines[11].get('missing-branches') is None


def test_lcov_flag(cov_merge_fixture: Path):
    p = subprocess.run([sys.executable, '-m', 'slipcover', '--lcov', '--out', "out.lcov", "t.py"], check=True)
    assert 0 == p.returncode

    lcov_text = (cov_merge_fixture / 'out.lcov').read_text(encoding='utf8')
    lines = lcov_text.strip().split('\n')

    # Check basic structure
    assert 'SF:t.py' in lines[0]

    # Parse line coverage data
    da_lines = [line for line in lines if line.startswith('DA:')]
    assert len(da_lines) == 7  # 7 total lines

    # Check specific line coverage
    assert 'DA:1,1' in da_lines  # Line 1 is executed
    assert 'DA:3,1' in da_lines  # Line 3 is executed
    assert 'DA:4,1' in da_lines  # Line 4 is executed
    assert 'DA:6,0' in da_lines  # Line 6 is not executed
    assert 'DA:8,1' in da_lines  # Line 8 is executed
    assert 'DA:9,0' in da_lines  # Line 9 is not executed
    assert 'DA:11,1' in da_lines  # Line 11 is executed

    # Check summary
    assert 'LF:7' in lines  # 7 lines found
    assert 'LH:5' in lines  # 5 lines hit
    assert 'end_of_record' in lines


def test_lcov_flag_with_branches(cov_merge_fixture: Path):
    p = subprocess.run([sys.executable, '-m', 'slipcover', '--branch', '--lcov', '--out', "out.lcov", "t.py"], check=True)
    assert 0 == p.returncode

    lcov_text = (cov_merge_fixture / 'out.lcov').read_text(encoding='utf8')
    lines = lcov_text.strip().split('\n')

    # Check basic structure
    assert 'SF:t.py' in lines[0]

    # Parse branch coverage data
    brda_lines = [line for line in lines if line.startswith('BRDA:')]
    assert len(brda_lines) == 4  # 4 total branches (2 from each if statement)

    # Check branch coverage summary
    assert 'BRF:4' in lines  # 4 branches found
    assert 'BRH:2' in lines  # 2 branches hit

    # Parse line coverage data
    da_lines = [line for line in lines if line.startswith('DA:')]
    assert len(da_lines) == 7  # 7 total lines

    # Check specific line coverage
    assert 'DA:1,1' in da_lines  # Line 1 is executed
    assert 'DA:3,1' in da_lines  # Line 3 is executed
    assert 'DA:4,1' in da_lines  # Line 4 is executed
    assert 'DA:6,0' in da_lines  # Line 6 is not executed
    assert 'DA:8,1' in da_lines  # Line 8 is executed
    assert 'DA:9,0' in da_lines  # Line 9 is not executed
    assert 'DA:11,1' in da_lines  # Line 11 is executed

    # Check summary
    assert 'LF:7' in lines  # 7 lines found
    assert 'LH:5' in lines  # 5 lines hit
    assert 'end_of_record' in lines


def test_lcov_flag_branch_taken_status_is_specific(cov_merge_fixture: Path):
    """BRF/BRH aggregate counts alone can't tell a correctly-mapped result
    from one with taken/not-taken inverted (a fixture with a symmetric
    hit/miss split, like this one, would still show the same BRH count
    either way) -- assert each individual BRDA line instead.
    """
    p = subprocess.run([sys.executable, '-m', 'slipcover', '--branch', '--lcov', '--out', "out.lcov", "t.py"], check=True)
    assert 0 == p.returncode

    lcov_text = (cov_merge_fixture / 'out.lcov').read_text(encoding='utf8')
    brda_lines = [line for line in lcov_text.strip().split('\n') if line.startswith('BRDA:')]

    # line 3 ("if len(sys.argv) < 2:"): 3->4 taken, 3->6 not taken
    assert 'BRDA:3,0,0,1' in brda_lines
    assert 'BRDA:3,0,1,-' in brda_lines
    # line 8 ("if not sys.argv:"): 8->9 not taken, 8->11 taken
    assert 'BRDA:8,0,0,-' in brda_lines
    assert 'BRDA:8,0,1,1' in brda_lines


def test_lcov_flag_with_test_name(cov_merge_fixture: Path):
    p = subprocess.run([sys.executable, '-m', 'slipcover', '--lcov', '--lcov-test-name', 'MyTestSuite', 
                       '--out', "out.lcov", "t.py"], check=True)
    assert 0 == p.returncode

    lcov_text = (cov_merge_fixture / 'out.lcov').read_text(encoding='utf8')
    lines = lcov_text.strip().split('\n')

    # Check that TN: is present with the test name
    assert 'TN:MyTestSuite' in lines[0]
    assert 'SF:t.py' in lines[1]


def test_lcov_flag_with_comments(cov_merge_fixture: Path):
    p = subprocess.run([sys.executable, '-m', 'slipcover', '--lcov', 
                       '--lcov-comment', 'Generated by slipcover',
                       '--lcov-comment', 'Test run on 2025-01-01',
                       '--out', "out.lcov", "t.py"], check=True)
    assert 0 == p.returncode

    lcov_text = (cov_merge_fixture / 'out.lcov').read_text(encoding='utf8')
    lines = lcov_text.strip().split('\n')

    # Check that comments are present at the beginning
    assert '# Generated by slipcover' == lines[0]
    assert '# Test run on 2025-01-01' == lines[1]
    assert 'SF:t.py' in lines[2]


def test_lcov_flag_with_test_name_and_comments(cov_merge_fixture: Path):
    p = subprocess.run([sys.executable, '-m', 'slipcover', '--lcov', 
                       '--lcov-test-name', 'IntegrationTest',
                       '--lcov-comment', 'Coverage report',
                       '--out', "out.lcov", "t.py"], check=True)
    assert 0 == p.returncode

    lcov_text = (cov_merge_fixture / 'out.lcov').read_text(encoding='utf8')
    lines = lcov_text.strip().split('\n')

    # Check that comment is present at the beginning
    assert '# Coverage report' == lines[0]
    # Check that TN: is present with the test name
    assert 'TN:IntegrationTest' in lines[1]
    assert 'SF:t.py' in lines[2]


def test_lcov_normalizes_windows_paths():
    """LCOV's SF: entry must use forward slashes, matching xmlreport.py's
    own path normalization (genhtml/lcov tooling expects '/'-style paths).
    """
    import io

    coverage = {
        'meta': {'software': 'slipcover', 'version': '0', 'timestamp': '', 'branch_coverage': False},
        'files': {
            r'src\pkg\mod.py': {
                'executed_lines': [1],
                'missing_lines': [],
            }
        },
    }

    out = io.StringIO()
    sc.print_lcov(coverage, outfile=out)
    lcov_text = out.getvalue()

    assert 'SF:src/pkg/mod.py' in lcov_text
    assert '\\' not in lcov_text


def test_lcov_flag_empty_file(tmp_path, monkeypatch):
    """An empty .py file has no missing coverage. The exact line count is
    NOT asserted: Python 3.9/3.10 report one (trivially-executed) line for
    an empty module, while 3.11+ report none -- both are correct, since
    what matters here is that nothing is reported as missing.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "empty.py").write_text("")

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--lcov', '--out', "out.lcov", "empty.py"], check=True)
    assert 0 == p.returncode

    lcov_text = (tmp_path / 'out.lcov').read_text(encoding='utf8')
    lines = lcov_text.strip().split('\n')

    assert 'SF:empty.py' in lines[0]
    assert not any(line.startswith('DA:') and line.endswith(',0') for line in lines)
    assert 'end_of_record' in lines


def test_lcov_flag_full_coverage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "full.py").write_text("x = 1\ny = 2\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--lcov', '--out', "out.lcov", "full.py"], check=True)
    assert 0 == p.returncode

    lcov_text = (tmp_path / 'out.lcov').read_text(encoding='utf8')
    lines = lcov_text.strip().split('\n')

    assert 'DA:1,1' in lines
    assert 'DA:2,1' in lines
    assert 'LF:2' in lines
    assert 'LH:2' in lines


def test_lcov_flag_zero_coverage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "unused.py").write_text("def foo():\n    return 1\n")

    p = subprocess.run([sys.executable, '-m', 'slipcover', '--lcov', '--out', "out.lcov", "unused.py"], check=True)
    assert 0 == p.returncode

    lcov_text = (tmp_path / 'out.lcov').read_text(encoding='utf8')
    lines = lcov_text.strip().split('\n')

    assert 'DA:2,0' in lines  # "return 1" body never executes
    assert 'LH:0' not in lines or 'LF:0' not in lines  # sanity: file isn't itself empty
    assert 'LH:1' in lines  # only the "def foo():" line (module-level) executes
    assert 'LF:2' in lines


def test_lcov_flag_with_merge(cov_merge_fixture):
    subprocess.run([sys.executable, '-m', 'slipcover', '--branch',
                    '--json', '--out', "a.json", "t.py"], check=True)
    subprocess.run([sys.executable, '-m', 'slipcover', '--branch',
                    '--json', '--out', "b.json", "t.py", "X"], check=True)

    subprocess.run([sys.executable, '-m', 'slipcover', '--merge',
                    'a.json', 'b.json', '--branch', '--lcov', '--out', 'c.lcov'], check=True)

    lcov_text = Path("c.lcov").read_text(encoding='utf8')
    lines = lcov_text.strip().split('\n')

    assert 'SF:t.py' in lines[0]
    da_lines = [line for line in lines if line.startswith('DA:')]
    # merged coverage: both the "A branch" (line 4) and "B branch" (line 6) taken
    assert 'DA:4,1' in da_lines
    assert 'DA:6,1' in da_lines
    assert 'DA:9,0' in da_lines
    assert 'end_of_record' in lines


@pytest.mark.skipif(sys.platform == 'win32', reason='SIGTERM is Unix-specific')
def test_sigterm_top_level_writes_single_correct_report(tmp_path, monkeypatch):
    """A SIGTERM'd top-level process must produce exactly one coverage
    report. The original bug called sci_atexit() manually and then let
    atexit run it again via sys.exit(), printing the table twice.
    """
    import signal
    import time

    monkeypatch.chdir(tmp_path)
    script = tmp_path / "script.py"
    script.write_text(dedent("""\
        import time
        x = 1
        with open("started.txt", "w") as f:
            f.write("1")
        time.sleep(10)
        y = 2  # must never execute -- process is killed during sleep
    """))

    proc = subprocess.Popen(
        [sys.executable, '-m', 'slipcover', '--sigterm', 'script.py'],
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    # Wait for the script to actually reach the sleep, rather than guessing
    # a fixed duration: too short races the SIGTERM against slipcover's own
    # startup, too long just wastes time -- polling for a concrete
    # readiness marker adapts to whatever the environment actually needs.
    started_file = tmp_path / "started.txt"
    for _ in range(100):  # up to ~5s
        if started_file.exists():
            break
        time.sleep(0.05)
    else:
        proc.kill()
        pytest.fail("script never started")

    proc.send_signal(signal.SIGTERM)
    stdout, stderr = proc.communicate(timeout=30)

    assert proc.returncode == 0, f"stdout={stdout}\nstderr={stderr}"
    # the report table's header appears exactly once per report -- the
    # original bug printed it twice
    assert stdout.count('#lines') == 1, f"expected exactly one report, got:\n{stdout}"
    assert 'script.py' in stdout


@pytest.mark.skipif(sys.platform == 'win32', reason='SIGTERM/fork are Unix-specific')
def test_sigterm_forked_child_writes_partial_coverage_safely(tmp_path, monkeypatch):
    """A forked child killed by SIGTERM must exit through the shimmed
    os._exit() (writing its own partial coverage to a tempfile for the
    parent to merge) rather than racing the parent through the top-level
    report path -- exercised via the real --sigterm flag and a real
    os.fork() in the target script, not by calling internal functions
    directly.
    """
    import os
    import signal
    import time

    monkeypatch.chdir(tmp_path)
    script = tmp_path / "script.py"
    script.write_text(dedent("""\
        import os, time

        pid = os.fork()
        if pid == 0:
            x = 1
            time.sleep(10)
            y = 2  # must never execute -- child is killed during sleep
        else:
            with open("child_pid.txt", "w") as f:
                f.write(str(pid))
            os.waitpid(pid, 0)
    """))

    proc = subprocess.Popen(
        [sys.executable, '-m', 'slipcover', '--sigterm', '--json', '--out', 'out.json', 'script.py'],
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    pid_file = tmp_path / "child_pid.txt"
    child_pid = None
    for _ in range(100):  # up to ~5s
        # both errors mean "not ready yet": the file may not exist, or it
        # may exist but not be flushed/visible yet (empty content)
        try:
            child_pid = int(pid_file.read_text())
            break
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(0.05)
    else:
        proc.kill()
        pytest.fail("forked child never started")
    os.kill(child_pid, signal.SIGTERM)

    stdout, stderr = proc.communicate(timeout=30)
    assert proc.returncode == 0, f"stdout={stdout}\nstderr={stderr}"

    cov = json.loads((tmp_path / "out.json").read_text())
    file_cov = cov['files']['script.py']
    assert 5 in file_cov['executed_lines']       # x = 1, in the child
    assert 7 not in file_cov['executed_lines']   # y = 2, never reached
