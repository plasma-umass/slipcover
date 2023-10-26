import pytest
import sys

PYTHON_VERSION = sys.version_info[0:2]

if PYTHON_VERSION >= (3,12):
    pytest.skip(allow_module_level=True)

import slipcover.slipcover as sc
import slipcover.bytecode as bc
import slipcover.branch as br
import types
import dis
import platform
import re

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


def test_probe_signal():
    from slipcover import probe

    sci = sc.Slipcover()

    t_123 = probe.new(sci, "/foo/bar.py", 123, -1)
    probe.signal(t_123)

    t_42 = probe.new(sci, "/foo2/baz.py", 42, -1)
    probe.signal(t_42)
    probe.signal(t_42)

    t_314 = probe.new(sci, "/foo2/baz.py", 314, -1)
    probe.signal(t_314)

    # line never executed
    t_666 = probe.new(sci, "/foo/beast.py", 666, -1)

    d = sci.newly_seen
    assert ["/foo/bar.py", "/foo2/baz.py"] == sorted(d.keys())
    assert [123] == sorted(list(d["/foo/bar.py"]))
    assert [42, 314] == sorted(list(d["/foo2/baz.py"]))


def test_probe_deinstrument():
    from slipcover import probe

    sci = sc.Slipcover()

    t = probe.new(sci, "/foo/bar.py", 123, 3)
    probe.signal(t)

    assert ["/foo/bar.py"] == sorted(sci.newly_seen.keys())

    probe.signal(t)
    probe.signal(t)
    probe.signal(t)   # triggers deinstrument_seen... but not instrumented through sci

    probe.mark_removed(t) # fake it since sci didn't instrument it
    probe.signal(t)   # u-miss

    assert [] == sorted(sci.newly_seen.keys())
    assert ["/foo/bar.py"] == sorted(sci.all_seen.keys())


def check_line_probes(code):
    # Are all lines where we expect?
    for (offset, line) in dis.findlinestarts(code):
        if line:
            print(f"checking {code.co_name} line {line}")
            if bc.op_RESUME == code.co_code[offset]:
                continue

            assert bc.op_NOP == code.co_code[offset], f"NOP missing at offset {offset}"
            probe_len = bc.branch2offset(code.co_code[offset+1])
            it = iter(bc.unpack_opargs(code.co_code[offset+2:offset+2+probe_len]))

            if PYTHON_VERSION >= (3,11):
                op_offset, op_len, op, op_arg = next(it)
                assert op == bc.op_PUSH_NULL

            op_offset, op_len, op, op_arg = next(it)
            assert op == bc.op_LOAD_CONST

            op_offset, op_len, op, op_arg = next(it)
            assert op == bc.op_LOAD_CONST

            op_offset, op_len, op, op_arg = next(it)
            if PYTHON_VERSION >= (3,11):
                assert op == bc.op_PRECALL
                op_offset, op_len, op, op_arg = next(it)
                assert op == bc.op_CALL
            else:
                assert op == bc.op_CALL_FUNCTION

            op_offset, op_len, op, op_arg = next(it)
            assert op == bc.op_POP_TOP

            assert next(it, None) is None   # check end of probe

    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            check_line_probes(const)


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

    assert foo.__code__.co_stacksize >= bc.calc_max_stack(foo.__code__.co_code)
    assert '__slipcover__' in foo.__code__.co_consts

    check_line_probes(foo.__code__)

    assert 6 == foo(3)


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

    assert foo.__code__.co_stacksize >= bc.calc_max_stack(foo.__code__.co_code)
    assert '__slipcover__' in foo.__code__.co_consts

    check_line_probes(foo.__code__)

    assert X == foo(123)


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

    assert foo.__code__.co_stacksize >= orig_code.co_stacksize
    assert '__slipcover__' in foo.__code__.co_consts

    check_line_probes(foo.__code__)

    assert X == foo(42)


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

    assert 'executed_branches' not in cov
    assert 'missing_branches' not in cov


def test_instrument_branches():
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

    check_line_probes(code)

    g = dict()
    exec(code, g, g)


@pytest.mark.parametrize("x", [5, 20])
def test_instrument_branch_into_line_block(x):
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

    check_line_probes(code)

    g = dict()
    exec(code, g, g)


def test_instrument_branches_pypy_crash():
    """In Python 3.9, the branch instrumentation at the beginning of foo's code
       object shows as being on line 5; that leads to a branch probe and a line
       probe being inserted at the same offset (0), but the instrumentation loop
       used to assume that insertion offsets rose monotonically."""
    t = ast_parse("""
        # this comment and the whitespace below are important



        def foo():
            while True:
                f()
    """)
    t = br.preinstrument(t)

    sci = sc.Slipcover(branch=True)
    code = compile(t, 'foo', 'exec')
    code = sci.instrument(code)
    dis.dis(code)

    check_line_probes(code)


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


@pytest.mark.skipif(PYTHON_VERSION == (3,11), reason='brittle test')
@pytest.mark.parametrize("N", gen_test_sequence())
def test_instrument_long_jump(N):
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

    # we want at least one branch to have grown in length
    print([b.arg() for b in orig_branches])
    print([b.arg() for b in bc.Branch.from_code(code)])
    assert any(b.length > orig_branches[i].length for i, b in enumerate(bc.Branch.from_code(code)))

    exec(code, locals(), globals())
    assert N == x

    cov = sci.get_coverage()['files']['foo']
    assert [*range(1, 4)] == cov['executed_lines']
    assert [] == cov['missing_lines']


def test_deinstrument():
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


@pytest.mark.skipif(platform.python_implementation() == 'PyPy', reason="Immediate de-instrumentation does not work with PyPy")
def test_deinstrument_immediately():
    base_line = current_line()
    def foo(n):
        def bar(n):
            return n+1
        x = 0
        for i in range(bar(n)):
            x += i
        return x
    last_line = current_line()

    sci = sc.Slipcover(immediate=True)
    assert not sci.get_coverage()['files'].keys()

    sci.instrument(foo)

    check_line_probes(foo.__code__)

    assert 6 == foo(3)

    for off, *_ in dis.findlinestarts(foo.__code__):
        if bc.op_RESUME == foo.__code__.co_code[off]:
            continue
        assert foo.__code__.co_code[off] == bc.op_JUMP_FORWARD


def test_deinstrument_with_many_consts():
    sci = sc.Slipcover()

    N = 1024
    src = 'x=0\n' + ''.join([f'x = {i}\n' for i in range(1, N)])

    code = compile(src, "foo", "exec")

    assert len(code.co_consts) >= N

    code = sci.instrument(code)

    # this is the "important" part of the test: check that it can
    # update the probe(s) even if it requires processing EXTENDED_ARGs
    code = sci.deinstrument(code, set(range(1, N)))
    dis.dis(code)

    exec(code, locals(), globals())
    assert N-1 == x

    cov = sci.get_coverage()['files']['foo']
    assert [N] == cov['executed_lines']
    assert [*range(1,N)] == cov['missing_lines']


def test_deinstrument_some():
    sci = sc.Slipcover()

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
    assert [2, 5] == [l-base_line for l in cov['executed_lines']]
    assert [3, 4] == [l-base_line for l in cov['missing_lines']]


@pytest.mark.parametrize("do_branch", [False, True])
def test_deinstrument_seen_upon_d_miss_threshold(do_branch):
    from slipcover import probe as pr

    t = ast_parse("""
        def foo(n):
            x = 0;
            for _ in range(100):
                x += n
            return x    # line 5
    """)
    if do_branch:
        t = br.preinstrument(t)
    g = dict()
    exec(compile(t, "foo", "exec"), g, g)
    foo = g['foo']

    sci = sc.Slipcover(branch=do_branch)
    assert not sci.get_coverage()['files']

    sci.instrument(foo)
    old_code = foo.__code__

    foo(0)

    assert old_code != foo.__code__, "Code never de-instrumented"
    assert sum(pr.was_removed(t) for t in old_code.co_consts if type(t).__name__ == 'PyCapsule') > 0

    cov = sci.get_coverage()['files']['foo']
    assert [2,3,4,5] == cov['executed_lines']
    assert [] == cov['missing_lines']
    if do_branch:
        assert [(3,4),(3,5)] == cov['executed_branches']
        assert [] == cov['missing_branches']

    foo(1)


def test_deinstrument_seen_upon_d_miss_threshold_doesnt_count_while_deinstrumenting():
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
    assert [2, 3, 5, 6, 7, 8, 9, 10] == [l-base_line for l in cov['executed_lines']]
    assert [4] == [l-base_line for l in cov['missing_lines']]


def test_no_deinstrument_seen_negative_threshold():
    sci = sc.Slipcover(d_miss_threshold=-1)

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


def test_find_functions():
    import class_test as t

    def func_names(funcs):
        return sorted(map(lambda f: f.__name__, funcs))

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


