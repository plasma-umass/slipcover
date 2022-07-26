import pytest
from slipcover import slipcover as sc
from slipcover import bytecode as bc
import types
import dis
import sys


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


@pytest.mark.parametrize("stats", [False, True])
def test_tracker_signal(stats):
    from slipcover import tracker

    sci = sc.Slipcover(collect_stats=stats)

    t_123 = tracker.register(sci, "/foo/bar.py", 123, -1)
    tracker.signal(t_123)

    t_42 = tracker.register(sci, "/foo2/baz.py", 42, -1)
    tracker.signal(t_42)
    tracker.signal(t_42)

    t_314 = tracker.register(sci, "/foo2/baz.py", 314, -1)
    tracker.signal(t_314)

    # line never executed
    t_666 = tracker.register(sci, "/foo/beast.py", 666, -1)

    d = sci.new_lines_seen
    assert ["/foo/bar.py", "/foo2/baz.py"] == sorted(d.keys())
    assert [123] == sorted(list(d["/foo/bar.py"]))
    assert [42, 314] == sorted(list(d["/foo2/baz.py"]))

    assert ("/foo2/baz.py", 42, 1, 0, 2) == tracker.get_stats(t_42)
    assert ("/foo2/baz.py", 314, 0, 0, 1) == tracker.get_stats(t_314)

    assert ("/foo/beast.py", 666, 0, 0, 0) == tracker.get_stats(t_666)


@pytest.mark.parametrize("stats", [False, True])
def test_tracker_deinstrument(stats):
    from slipcover import tracker

    sci = sc.Slipcover(collect_stats=stats)

    t = tracker.register(sci, "/foo/bar.py", 123, 3)
    tracker.signal(t)

    assert ["/foo/bar.py"] == sorted(sci.new_lines_seen.keys())

    tracker.signal(t)
    tracker.signal(t)
    tracker.signal(t)   # triggers deinstrument_seen... but not instrumented through sci

    tracker.deinstrument(t) # fake it since sci didn't instrument it
    tracker.signal(t)   # u-miss

    tracker.hit(t)

    assert [] == sorted(sci.new_lines_seen.keys())
    assert ["/foo/bar.py"] == sorted(sci.lines_seen.keys())

    assert ("/foo/bar.py", 123, 3, 1, 6) == tracker.get_stats(t)




def test_pathsimplifier_not_relative():
    from pathlib import Path

    ps = sc.PathSimplifier()

    assert ".." == ps.simplify("..")


def test_filematcher_defaults():
    import os
    from pathlib import Path
    cwd = Path.cwd()

    fm = sc.FileMatcher()

    assert fm.matches('myscript.py')
    assert not fm.matches('built-in')
    assert not fm.matches('myscript.pyd')
    assert not fm.matches('myscript.so')
    assert fm.matches('./myscript.py')
    assert fm.matches('mymodule/mymodule.py')
    assert fm.matches('./mymodule/mymodule.py')
    assert fm.matches('./other/other.py')
    assert fm.matches(cwd / 'myscript.py')
    assert fm.matches(cwd / 'mymodule' / 'mymodule.py')
    assert not fm.matches(Path.cwd().parent / 'other.py')

    import inspect  # should be in python's own lib
    assert not fm.matches(inspect.getfile(inspect))

    # pip is usually in site-packages, but importing it causes warnings
    site_packages = next(Path(p) for p in sys.path if p != '' and (Path(p) / "pip").exists())
    assert not fm.matches(site_packages / 'foo.py')


@pytest.fixture
def return_to_dir():
    import os
    from pathlib import Path
    cwd = str(Path.cwd())
    yield
    os.chdir(cwd)


def test_filematcher_defaults_from_root(return_to_dir):
    import os
    from pathlib import Path

    os.chdir('/')
    fm = sc.FileMatcher()

    assert fm.matches('myscript.py')
    assert not fm.matches('built-in')
    assert not fm.matches('myscript.pyd')
    assert not fm.matches('myscript.so')
    assert fm.matches(Path('.') / 'myscript.py')
    assert fm.matches(Path('mymodule') / 'mymodule.py')
    assert fm.matches(Path('.') / 'mymodule' / 'mymodule.py')
    assert fm.matches(Path('.') / 'other' / 'other.py')

    import inspect  # should be in python's own lib
    assert not fm.matches(inspect.getfile(inspect))

    # pip is usually in site-packages, but importing it causes warnings
    site_packages = next(Path(p) for p in sys.path if p != '' and (Path(p) / "pip").exists())
    assert not fm.matches(site_packages / 'foo.py')

def test_filematcher_source():
    from pathlib import Path
    cwd = str(Path.cwd())

    fm = sc.FileMatcher()
    fm.addSource('mymodule')
    fm.addSource('prereq')

    assert not fm.matches('myscript.py')
    assert not fm.matches('./myscript.py')
    assert not fm.matches('built-in')
    assert not fm.matches('myscript.pyd')
    assert not fm.matches('myscript.so')
    assert fm.matches('mymodule/mymodule.py')
    assert fm.matches('mymodule/foo.py')
    assert not fm.matches('mymodule/myscript.pyd')
    assert not fm.matches('mymodule/myscript.so')
    assert fm.matches('./mymodule/mymodule.py')
    assert fm.matches('prereq/__main__.py')
    assert not fm.matches('./other/other.py')
    assert not fm.matches(cwd + '/myscript.py')
    assert fm.matches(cwd + '/mymodule/mymodule.py')
    assert not fm.matches(str(Path.cwd().parent) + '/other.py')

    import inspect  # should be in python's own lib
    assert not fm.matches(inspect.getfile(inspect))

    # pip is usually in site-packages, but importing it causes warnings
    site_packages = next(Path(p) for p in sys.path if p != '' and (Path(p) / "pip").exists())
    assert not fm.matches(site_packages / 'foo.py')


def test_filematcher_omit_pattern():
    from pathlib import Path
    cwd = str(Path.cwd())

    fm = sc.FileMatcher()
    fm.addSource('mymodule')
    fm.addOmit('*/foo.py')

    assert not fm.matches('myscript.py')
    assert not fm.matches('./myscript.py')
    assert fm.matches('mymodule/mymodule.py')
    assert not fm.matches('mymodule/foo.py')
    assert not fm.matches('mymodule/1/2/3/foo.py')
    assert fm.matches('./mymodule/mymodule.py')
    assert not fm.matches('./other/other.py')
    assert not fm.matches(cwd + '/myscript.py')
    assert fm.matches(cwd + '/mymodule/mymodule.py')
    assert not fm.matches(str(Path.cwd().parent) + '/other.py')

    import inspect  # should be in python's own lib
    assert not fm.matches(inspect.getfile(inspect))

    # pip is usually in site-packages, but importing it causes warnings
    site_packages = next(Path(p) for p in sys.path if p != '' and (Path(p) / "pip").exists())
    assert not fm.matches(site_packages / 'foo.py')

# TODO what about patterns starting with '?'


def test_filematcher_omit_nonpattern():
    from pathlib import Path
    cwd = str(Path.cwd())

    fm = sc.FileMatcher()
    fm.addSource('mymodule')
    fm.addOmit('mymodule/foo.py')

    assert not fm.matches('myscript.py')
    assert not fm.matches('./myscript.py')
    assert fm.matches('mymodule/mymodule.py')
    assert not fm.matches('mymodule/foo.py')
    assert fm.matches('mymodule/1/2/3/foo.py')
    assert fm.matches('./mymodule/mymodule.py')
    assert not fm.matches('./other/other.py')
    assert not fm.matches(cwd + '/myscript.py')
    assert fm.matches(cwd + '/mymodule/mymodule.py')
    assert not fm.matches(str(Path.cwd().parent) + '/other.py')


@pytest.mark.parametrize("stats", [False, True])
def test_instrument(stats):
    sci = sc.Slipcover(collect_stats=stats)

    base_line = current_line()
    def foo(n): #1
        if n == 42:
            return 666
        x = 0
        for i in range(n):
            x += (i+1)
        return x

    dis.dis(foo)
    sci.instrument(foo)

    assert foo.__code__.co_stacksize >= bc.calc_max_stack(foo.__code__.co_code)
    assert '__slipcover__' in foo.__code__.co_consts

    # Are all lines where we expect?
    for (offset, _) in dis.findlinestarts(foo.__code__):
        assert bc.op_NOP == foo.__code__.co_code[offset]

    dis.dis(foo)
    assert 6 == foo(3)

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    if PYTHON_VERSION >= (3,11):
        assert [1, 2, 4, 5, 6, 7] == [l-base_line for l in cov['executed_lines']]
    else:
        assert [2, 4, 5, 6, 7] == [l-base_line for l in cov['executed_lines']]
    assert [3] == [l-base_line for l in cov['missing_lines']]


@pytest.mark.parametrize("stats", [False, True])
def test_instrument_generators(stats):
    sci = sc.Slipcover(collect_stats=stats)

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

#    dis.dis(foo)
    sci.instrument(foo)

    assert foo.__code__.co_stacksize >= bc.calc_max_stack(foo.__code__.co_code)
    assert '__slipcover__' in foo.__code__.co_consts

    # Are all lines where we expect?
    for (offset, _) in dis.findlinestarts(foo.__code__):
        assert bc.op_NOP == foo.__code__.co_code[offset]

#    dis.dis(foo)
    assert X == foo(123)

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    if PYTHON_VERSION >= (3,11):
        assert [1, 2, 3, 4, 5, 6, 7, 8] == [l-base_line for l in cov['executed_lines']]
    else:
        assert [2, 3, 4, 5, 6, 7, 8] == [l-base_line for l in cov['executed_lines']]

    assert [] == cov['missing_lines']


@pytest.mark.parametrize("stats", [False, True])
def test_instrument_exception(stats):
    sci = sc.Slipcover(collect_stats=stats)

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

    assert foo.__code__.co_stacksize >= orig_code.co_stacksize
    assert '__slipcover__' in foo.__code__.co_consts

    # Are all lines where we expect?
    for (offset, _) in dis.findlinestarts(foo.__code__):
        assert bc.op_NOP == foo.__code__.co_code[offset]

    dis.dis(foo)
    assert X == foo(42)

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    if PYTHON_VERSION >= (3,11):
        assert [1, 2, 3, 4, 5, 7, 8, 10, 12] == [l-base_line for l in cov['executed_lines']]
    else:
        assert [2, 3, 4, 5, 7, 8, 10, 12] == [l-base_line for l in cov['executed_lines']]

    if PYTHON_VERSION >= (3,10):
        # #6 is unreachable and is omitted from the code
        assert [] == [l-base_line for l in cov['missing_lines']]
    else:
        assert [6] == [l-base_line for l in cov['missing_lines']]


@pytest.mark.skipif(PYTHON_VERSION != (3,10), reason="N/A: only 3.10 seems to generate code like this")
def test_instrument_code_before_first_line():
    sci = sc.Slipcover()

    first_line = current_line()+1
    def foo(n):
        for i in range(n+1):
            yield i
    last_line = current_line()

    dis.dis(foo)
    print([str(l) for l in bc.LineEntry.from_code(foo.__code__)])

    # Generators in 3.10 start with a GEN_START that's not assigned to any lines;
    # that's what we're trying to test here
    first_line_offset, _ = next(dis.findlinestarts(foo.__code__))
    assert 0 != first_line_offset

    sci.instrument(foo)
    dis.dis(foo)

    # Are all lines where we expect?
    for (offset, _) in dis.findlinestarts(foo.__code__):
        assert bc.op_NOP == foo.__code__.co_code[offset]

    assert 6 == sum(foo(3))

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    assert [*range(first_line+1, last_line)] == cov['executed_lines']
    assert [] == cov['missing_lines']


def test_instrument_threads():
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
    if PYTHON_VERSION >= (3,11):
        assert [1, 3, 4, 5, 6] == [l-base_line for l in cov['executed_lines']]
    else:
        assert [3, 4, 5, 6] == [l-base_line for l in cov['executed_lines']]
    assert [] == cov['missing_lines']


@pytest.mark.skipif(PYTHON_VERSION >= (3,11), reason="N/A, I think -- how to replicate?", run=False)
@pytest.mark.parametrize("N", [260])#, 65600])
def test_instrument_doesnt_interrupt_ext_sequence(N):
    EXT = bc.op_EXTENDED_ARG

    sci = sc.Slipcover()

    # create code with >256 constants
    src = 'x=0\n' + ''.join([f'y={i}; x += y\n' for i in range(1, N+1)])
    code = compile(src, 'foo', 'exec')


    # Move offsets so that an EXTENDED_ARG is on one line and the rest on another
    # Python 3.9.10 actually generated code like that:
    #
    # 2107        1406 LOAD_NAME               31 (ignore_warnings)
    # 2109        1408 EXTENDED_ARG             1
    # 2108        1410 LOAD_CONST             267 ((False, 'float64'))
    #
    lines = bc.LineEntry.from_code(code)
    for i in range(len(lines)):
        if lines[i].number > 257:
            assert EXT == code.co_code[lines[i].start]
            lines[i].start = lines[i-1].end = lines[i-1].end + 2

    if PYTHON_VERSION == (3,10):
        code = code.replace(co_linetable=bc.LineEntry.make_linetable(1, lines))
    else:
        code = code.replace(co_lnotab=bc.LineEntry.make_lnotab(1, lines))

    orig = {}
    exec(code, globals(), orig)

    instr = {}
    code = sci.instrument(code)
    exec(code, globals(), instr)

    assert orig['x'] == instr['x']

    cov = sci.get_coverage()
    assert {'foo'} == cov['files'].keys()

    cov = cov['files']['foo']
    assert [*range(1, N+2)] == cov['executed_lines']
    assert [] == cov['missing_lines']


def test_get_coverage_detects_lines():
    sci = sc.Slipcover()
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
    if PYTHON_VERSION >= (3,11):
        assert [1, 6, 8, 9, 12, 13, 15] == [l-base_line for l in cov['missing_lines']]
    else:
        assert [6, 8, 9, 12, 13, 15] == [l-base_line for l in cov['missing_lines']]
    assert [] == cov['executed_lines']


def gen_long_jump_code(N):
    return "x = 0\n" + \
           "for _ in range(1):\n" + \
           "    " + ("x += 1;" * N) + "pass\n"

def gen_test_sequence():
    code = compile(gen_long_jump_code(64*1024), "foo", "exec")
    branches = bc.Branch.from_code(code)

    b = next(b for b in branches if b.is_relative)

    # we want to generate Ns so that Slipcover's instrumentation forces
    # the "if" branch to grow in length (with an additional extended_arg)
    return [(64*1024*arg)//b.arg() for arg in [0xFF, 0xFFFF]]#, 0xFFFFFF]]


@pytest.mark.skipif(sys.version.split()[0] == '3.11.0b4', reason='brittle test')
@pytest.mark.parametrize("N", gen_test_sequence())
def test_instrument_long_jump(N):
    sci = sc.Slipcover()

    # each 'if' adds a branch
    src = gen_long_jump_code(N)

    code = compile(src, "foo", "exec")
    dis.dis(code)

    orig_branches = bc.Branch.from_code(code)
    assert 2 <= len(orig_branches)

    sci = sc.Slipcover()
    code = sci.instrument(code)

    dis.dis(code)

    # Are all lines where we expect?
    for (offset, _) in dis.findlinestarts(code):
        # This catches any lines not where we expect,
        # such as any not adjusted after adjusting branch lengths
        assert bc.op_NOP == code.co_code[offset]

    exec(code, locals(), globals())
    assert N == x

    cov = sci.get_coverage()['files']['foo']
    assert [*range(1, 4)] == cov['executed_lines']
    assert [] == cov['missing_lines']

    # we want at least one branch to have grown in length
    print([b.arg() for b in orig_branches])
    print([b.arg() for b in bc.Branch.from_code(code)])
    assert any(b.length > orig_branches[i].length for i, b in enumerate(bc.Branch.from_code(code)))


@pytest.mark.parametrize("stats", [False, True])
def test_deinstrument(stats):
    sci = sc.Slipcover(collect_stats=stats)

    base_line = current_line()
    def foo(n):
        def bar(n):
            return n+1
        x = 0
        for i in range(bar(n)):
            x += i
        return x
    last_line = current_line()

    sci = sc.Slipcover()
    assert not sci.get_coverage()['files'].keys()

    sci.instrument(foo)
    sci.deinstrument(foo, {*range(base_line+1, last_line)})
    dis.dis(foo)
    assert 6 == foo(3)
    assert [] == sci.get_coverage()['files'][simple_current_file()]['executed_lines']


@pytest.mark.parametrize("stats", [False, True])
def test_deinstrument_with_many_consts(stats):
    sci = sc.Slipcover(collect_stats=stats)

    N = 1024
    src = 'x=0\n' + ''.join([f'x = {i}\n' for i in range(1, N)])

    code = compile(src, "foo", "exec")

    assert len(code.co_consts) >= N

    code = sci.instrument(code)

    # this is the "important" part of the test: check that it can
    # update the tracker(s) even if it requires processing EXTENDED_ARGs
    code = sci.deinstrument(code, set(range(1, N)))
    dis.dis(code)

    exec(code, locals(), globals())
    assert N-1 == x

    cov = sci.get_coverage()['files']['foo']
    assert [N] == cov['executed_lines']
    assert [*range(1,N)] == cov['missing_lines']


@pytest.mark.parametrize("stats", [False, True])
def test_deinstrument_some(stats):
    sci = sc.Slipcover(collect_stats=stats)

    base_line = current_line()
    def foo(n):
        x = 0
        for i in range(n): #3
            x += (i+1)
        return x

    assert not sci.get_coverage()['files'].keys()

    sci.instrument(foo)
    sci.deinstrument(foo, {base_line+3, base_line+4})

    assert 6 == foo(3)
    cov = sci.get_coverage()['files'][simple_current_file()]
    if PYTHON_VERSION >= (3,11):
        assert [1, 2, 5] == [l-base_line for l in cov['executed_lines']]
    else:
        assert [2, 5] == [l-base_line for l in cov['executed_lines']]
    assert [3, 4] == [l-base_line for l in cov['missing_lines']]


def test_deinstrument_seen_d_threshold():
    sci = sc.Slipcover()

    first_line = current_line()+1
    def foo(n):
        x = 0;
        for _ in range(100):
            x += n
        return x
    last_line = current_line()

    assert not sci.get_coverage()['files']

    sci.instrument(foo)
    old_code = foo.__code__

    foo(0)

    assert old_code != foo.__code__, "Code never de-instrumented"

    foo(1)

    cov = sci.get_coverage()['files'][simple_current_file()]
    if PYTHON_VERSION >= (3,11):
        assert [*range(first_line, last_line)] == cov['executed_lines']
    else:
        assert [*range(first_line+1, last_line)] == cov['executed_lines']
    assert [] == cov['missing_lines']


def test_deinstrument_seen_d_threshold_doesnt_count_while_deinstrumenting():
    sci = sc.Slipcover()

    base_line = current_line()
    def foo(n):
        class Desc:  # https://docs.python.org/3/howto/descriptor.html
            def __get__(self, obj, objtype=None):
                return 10   # 4 <-- shouldn't be seen
        class Bar:
            v = Desc()
        x = 0
        for _ in range(100):
            x += n
        return x

    assert not sci.get_coverage()['files']

    sci.instrument(foo)
    old_code = foo.__code__

    foo(0)

    assert old_code != foo.__code__, "Code never de-instrumented"

    foo(1)

    cov = sci.get_coverage()['files'][simple_current_file()]
    if PYTHON_VERSION >= (3,11):
        assert [1, 2, 3, 5, 6, 7, 8, 9, 10] == [l-base_line for l in cov['executed_lines']]
    else:
        assert [2, 3, 5, 6, 7, 8, 9, 10] == [l-base_line for l in cov['executed_lines']]
    assert [4] == [l-base_line for l in cov['missing_lines']]


def test_deinstrument_seen_descriptor_not_invoked():
    sci = sc.Slipcover()

    base_line = current_line()
    def foo(n):
        class Desc:  # https://docs.python.org/3/howto/descriptor.html
            def __get__(self, obj, objtype=None):
                raise TypeError("just testing!") #4
        class Bar:
            v = Desc()
        x = 0
        for _ in range(100):
            x += n
        return x
    last_line = current_line()

    assert not sci.get_coverage()['files']

    sci.instrument(foo)
    old_code = foo.__code__

    foo(0)

    assert old_code != foo.__code__, "Code never de-instrumented"

    foo(1)

    cov = sci.get_coverage()['files'][simple_current_file()]
    if PYTHON_VERSION >= (3,11):
        assert [1, 2, 3, 5, 6, 7, 8, 9, 10] == [l-base_line for l in cov['executed_lines']]
    else:
        assert [2, 3, 5, 6, 7, 8, 9, 10] == [l-base_line for l in cov['executed_lines']]
    assert [4] == [l-base_line for l in cov['missing_lines']]


def test_no_deinstrument_seen_negative_threshold():
    sci = sc.Slipcover(d_threshold=-1)

    first_line = current_line()+2
    def foo(n):
        x = 0;
        for _ in range(100):
            x += n
        return x
    last_line = current_line()

    assert not sci.get_coverage()['files']

    sci.instrument(foo)
    old_code = foo.__code__

    foo(0)

    assert old_code == foo.__code__, "Code de-instrumented"


def test_format_missing():
    fm = sc.Slipcover.format_missing

    assert "" == fm([],[])
    assert "" == fm([], [1,2,3])
    assert "2, 4" == fm([2,4], [1,3,5])
    assert "2-4, 6, 9" == fm([2,3,4, 6, 9], [1, 5, 7,8])

    assert "2-6, 9-11" == fm([2,4,6, 9,11], [1, 7,8])

    assert "2-11" == fm([2,4,6, 9,11], [])

    assert "2-6, 9-11" == fm([2,4,6, 9,11], [8])


@pytest.mark.parametrize("stats", [False, True])
def test_print_coverage(stats, capsys):
    sci = sc.Slipcover(collect_stats=stats)

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

    import re

    # TODO test more cases (multiple files, etc.)
    output = capsys.readouterr()[0].splitlines()
    print(output)
    assert re.match(f'^tests[/\\\\]slipcover_test\\.py + {total} + {missd} +{int(100*execd/total)} +' + str(base_line+3), output[3])

    if stats:
        assert re.match('^tests[/\\\\]slipcover_test\\.py +[\\d.]+ +0', output[8])


def func_names(funcs):
    return sorted(map(lambda f: f.__name__, funcs))

def test_find_functions():
    import class_test as t

    assert ["b", "b_classm", "b_static", "f1", "f2", "f3", "f4", "f5", "f7",
            "f_classm", "f_static"] == \
           func_names(sc.Slipcover.find_functions(t.__dict__.values(), set()))

    assert ["b", "b_classm", "b_static", "f1", "f2", "f3", "f4",
            "f_classm", "f_static"] == \
           func_names(sc.Slipcover.find_functions([t.Test], set()))

    assert ["f5", "f7"] == \
           func_names(sc.Slipcover.find_functions([t.f5, t.f7], set()))

    visited = set()
    assert ["b", "b_classm", "b_static", "f1", "f2", "f3", "f4", "f5", "f7",
            "f_classm", "f_static"] == \
           func_names(sc.Slipcover.find_functions([*t.__dict__.values(), t.Test.Inner],
                                                  visited))

    assert [] == \
           func_names(sc.Slipcover.find_functions([*t.__dict__.values(), t.Test.Inner],
                                                  visited))


def test_interpose_on_module_load(tmp_path):
    # TODO include in coverage info
    from pathlib import Path
    import subprocess
    import json

    out_file = tmp_path / "out.json"

    subprocess.run(f"{sys.executable} -m slipcover --json --out {out_file} tests/importer.py".split(),
                   check=True)
    with open(out_file, "r") as f:
        cov = json.load(f)

    module_file = str(Path('tests') / 'imported' / '__init__.py')

    assert module_file in cov['files']
    assert list(range(1,5+1)) == cov['files'][module_file]['executed_lines']
    assert [] == cov['files'][module_file]['missing_lines']


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
    assert [1, 2, 3, 4, 5, 7, 8, 9, 10, 12, 13] == cov['executed_lines']
    assert [] == cov['missing_lines']


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


def test_loader_supports_resources(tmp_path):
    import subprocess

    cmdfile = tmp_path / "t.py"
    cmdfile.write_text("""
import importlib.resources as r
import tests.imported

def test_resources():
    assert len(r.contents('tests.imported')) > 1
""")

    p = subprocess.run([sys.executable, "-m", "slipcover", "--silent", "-m", "pytest", "-qq", cmdfile])
    assert p.returncode == 0
