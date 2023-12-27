import pytest
import slipcover.slipcover as sc
import slipcover.branch as br
import types
import dis
import sys
import platform
import re


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
    from pathlib import Path

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

    all_lines = {l-base_line for offset, l in dis.findlinestarts(foo.__code__)}

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
    assert sc.VERSION == meta['version']
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
    fm = sc.Slipcover.format_missing

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


def test_print_coverage_skip_covered():
    import subprocess

    p = subprocess.run(f"{sys.executable} -m slipcover --skip-covered tests/importer.py".split(), check=True, capture_output=True)
    output = str(p.stdout)
    assert '__init__.py' in output
    assert 'importer.py' not in output


@pytest.mark.parametrize("do_branch", [True, False])
def test_interpose_on_module_load(tmp_path, do_branch):
    # TODO include in coverage info
    from pathlib import Path
    import subprocess
    import json

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
    from pathlib import Path
    import subprocess
    import json

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
    from pathlib import Path
    import subprocess
    import json

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
    sc_cache_files = set(fn for fn in new_cache_files if ('slipcover-' + sc.VERSION) in fn.name)

    # ensure ours is being cached
    assert {} != sc_cache_files

    # and that nothing else changed
    assert set(pytest_cache_files) == new_cache_files - sc_cache_files
    assert (pytest_cache_content == pytest_cache_files[0].read_bytes())


def test_pytest_plugins_visible():
    import subprocess

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
    from pathlib import Path
    import subprocess
    import json

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
def test_fail_under(json_flag):
    import subprocess

    p = subprocess.run(f"{sys.executable} -m slipcover {json_flag} --fail-under 100 tests/branch.py".split(), check=False)
    assert 0 == p.returncode

    p = subprocess.run(f"{sys.executable} -m slipcover {json_flag} --branch --fail-under 83 tests/branch.py".split(), check=False)
    assert 0 == p.returncode

    p = subprocess.run(f"{sys.executable} -m slipcover {json_flag} --branch --fail-under 84 tests/branch.py".split(), check=False)
    assert 2 == p.returncode


def test_reports_on_other_sources(tmp_path):
    from pathlib import Path
    import subprocess
    import json

    out_file = tmp_path / "out.json"

    subprocess.run((f"{sys.executable} -m slipcover --branch --json --out {out_file} " +\
                    f"--source tests/imported tests/importer.py").split(),
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
