import pytest
from slipcover import slipcover as sc
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

def from_set(s: set):
    return next(iter(s))


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


def test_opcode_arg():
    JUMP = sc.op_JUMP_ABSOLUTE
    EXT = sc.op_EXTENDED_ARG

    assert [JUMP, 0x42] == list(sc.opcode_arg(JUMP, 0x42))
    assert [EXT, 0xBA, JUMP, 0xBE] == list(sc.opcode_arg(JUMP, 0xBABE))
    assert [EXT, 0xBA, EXT, 0xBE, JUMP, 0xFA] == \
           list(sc.opcode_arg(JUMP, 0xBABEFA))
    assert [EXT, 0xBA, EXT, 0xBE, EXT, 0xFA, JUMP, 0xCE] == \
           list(sc.opcode_arg(JUMP, 0xBABEFACE))

    assert [EXT, 0, JUMP, 0x42] == list(sc.opcode_arg(JUMP, 0x42, min_ext=1))
    assert [EXT, 0, EXT, 0, JUMP, 0x42] == list(sc.opcode_arg(JUMP, 0x42, min_ext=2))
    assert [EXT, 0, EXT, 0, EXT, 0, JUMP, 0x42] == \
           list(sc.opcode_arg(JUMP, 0x42, min_ext=3))


def test_calc_max_stack():
    def foo(x):
        def bar(y):
            z = y
            for i in range(3):
                z += i

            return z

        return bar(x) * 2

    assert foo.__code__.co_stacksize == sc.calc_max_stack(foo.__code__.co_code)


def test_calc_max_stack_typical_instrumentation():
    code = list()
    code.extend(sc.opcode_arg(sc.op_NOP, 1234))
    code.extend(sc.opcode_arg(sc.op_LOAD_CONST, 1))
    code.extend(sc.opcode_arg(sc.op_LOAD_CONST, 2))
    code.extend(sc.opcode_arg(sc.op_LOAD_CONST, 3))
    code.extend(sc.opcode_arg(sc.op_LOAD_CONST, 4))
    code.extend(sc.opcode_arg(sc.op_LOAD_CONST, 5))
    code.extend([sc.op_CALL_FUNCTION, 4,
                 sc.op_POP_TOP, 0])

    assert 5 == sc.calc_max_stack(bytes(code))


def test_branch_from_code():
    def foo(x):
        for _ in range(2):      # FOR_ITER is relative
            if x: print(True)
            else: print(False)

    branches = sc.Branch.from_code(foo.__code__)
    dis.dis(foo)
    assert 4 == len(branches)  # may be brittle

    for i, b in enumerate(branches):
        assert 2 == b.length
        assert foo.__code__.co_code[b.offset+b.length-2] == b.opcode
        assert (b.opcode in dis.hasjabs) or (b.opcode in dis.hasjrel)
        assert (b.opcode in dis.hasjrel) == b.is_relative
        if i > 0: assert branches[i-1].offset < b.offset

    # the tests below are more brittle... they rely on a 'for' loop
    # being created with
    #
    #   loop: FOR_ITER done
    #            ...
    #         JUMP_ABSOLUTE loop
    #   done: ...

    assert dis.opmap["FOR_ITER"] == branches[0].opcode
    assert dis.opmap["JUMP_ABSOLUTE"] == branches[-1].opcode

    assert branches[0].is_relative
    assert not branches[-1].is_relative

    assert branches[0].target == branches[-1].offset+2    # to finish loop
    assert branches[-1].target == branches[0].offset      # to continue loop


@pytest.mark.parametrize("length, arg",
                         [(length, arg) for length in range(2, 8+1, 2) \
                                        for arg in [0x02, 0x102, 0x10203, 0x1020304] \
                                        if length >= 2+2*sc.arg_ext_needed(arg)])
def test_branch_init(length, arg):
    abs_opcode = from_set(dis.hasjabs)
    rel_opcode = from_set(dis.hasjrel)

    b = sc.Branch(100, length, abs_opcode, arg)
    assert 100 == b.offset
    assert length == b.length
    assert abs_opcode == b.opcode
    assert not b.is_relative
    assert sc.branch2offset(arg) == b.target
    assert arg == b.arg()

    b = sc.Branch(100, length, rel_opcode, arg)
    assert 100 == b.offset
    assert length == b.length
    assert rel_opcode == b.opcode
    assert b.is_relative
    assert b.offset + b.length + sc.branch2offset(arg) == b.target
    assert arg == b.arg()

# Test case building rationale:
#
# There are relative and absolute branches; both kinds have an offset (where
# the operation is located) and a target (absolute offset for the branch,
# resolved from the argument).
# 
# On forward branches, an insertion can happen before the offset, at the offset,
# between the offset and the target, at the target, or after the target.
# On backward branches, an insertion can happen before the target, between the
# target and the offset, at the offset, or after the offset.
#
# Branches have an offset (op address) and a target (absolute branch address).
# There are relative and absolute branches; absolute branches may branch forward
# or backward.  In absolute forward branches, the offset (op address) precedes
# the target and in backwards

def test_branch_adjust_abs_fw_before_offset():
    b = sc.Branch(100, 2, from_set(dis.hasjabs), arg=sc.offset2branch(108))
    b.adjust(90, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 110 == b.target
    assert sc.offset2branch(108) != b.arg()

def test_branch_adjust_abs_fw_at_offset():
    b = sc.Branch(100, 2, from_set(dis.hasjabs), arg=sc.offset2branch(108))
    b.adjust(100, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 110 == b.target
    assert sc.offset2branch(108) != b.arg()

def test_branch_adjust_abs_fw_after_offset_before_target():
    b = sc.Branch(100, 2, from_set(dis.hasjabs), arg=sc.offset2branch(108))
    b.adjust(105, 2)

    assert 100 == b.offset
    assert 2 == b.length
    assert 110 == b.target
    assert sc.offset2branch(108) != b.arg()

def test_branch_adjust_abs_fw_at_target():
    b = sc.Branch(100, 2, from_set(dis.hasjabs), arg=sc.offset2branch(108))
    b.adjust(108, 2)

    assert 100 == b.offset
    assert 2 == b.length
    assert 108 == b.target
    assert sc.offset2branch(108) == b.arg()

def test_branch_adjust_abs_fw_after_target():
    b = sc.Branch(100, 2, from_set(dis.hasjabs), arg=sc.offset2branch(108))
    b.adjust(110, 2)

    assert 100 == b.offset
    assert 2 == b.length
    assert 108 == b.target
    assert sc.offset2branch(108) == b.arg()

def test_branch_adjust_abs_bw_before_target():
    b = sc.Branch(100, 2, from_set(dis.hasjabs), arg=sc.offset2branch(90))
    b.adjust(50, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 92 == b.target
    assert sc.offset2branch(90) != b.arg()

def test_branch_adjust_abs_bw_at_target():
    b = sc.Branch(100, 2, from_set(dis.hasjabs), arg=sc.offset2branch(90))
    b.adjust(90, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 90 == b.target
    assert sc.offset2branch(90) == b.arg()

def test_branch_adjust_abs_bw_after_target_before_offset():
    b = sc.Branch(100, 2, from_set(dis.hasjabs), arg=sc.offset2branch(90))
    b.adjust(96, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 90 == b.target
    assert sc.offset2branch(90) == b.arg()

def test_branch_adjust_abs_bw_at_offset():
    b = sc.Branch(100, 2, from_set(dis.hasjabs), arg=sc.offset2branch(90))
    b.adjust(100, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 90 == b.target
    assert sc.offset2branch(90) == b.arg()

def test_branch_adjust_abs_bw_after_offset():
    b = sc.Branch(100, 2, from_set(dis.hasjabs), arg=sc.offset2branch(90))
    b.adjust(110, 2)

    assert 100 == b.offset
    assert 2 == b.length
    assert 90 == b.target
    assert sc.offset2branch(90) == b.arg()

def test_branch_adjust_rel_fw_before_offset():
    b = sc.Branch(100, 2, from_set(dis.hasjrel), arg=sc.offset2branch(30))
    b.adjust(90, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 134 == b.target
    assert sc.offset2branch(30) == b.arg()

def test_branch_adjust_rel_fw_at_offset():
    b = sc.Branch(100, 2, from_set(dis.hasjrel), arg=sc.offset2branch(30))
    b.adjust(100, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 134 == b.target
    assert sc.offset2branch(30) == b.arg()

def test_branch_adjust_rel_fw_after_offset_before_target():
    b = sc.Branch(100, 2, from_set(dis.hasjrel), arg=sc.offset2branch(30))
    b.adjust(105, 2)

    assert 100 == b.offset
    assert 2 == b.length
    assert 134 == b.target
    assert sc.offset2branch(30) != b.arg()

def test_branch_adjust_rel_fw_at_target():
    b = sc.Branch(100, 2, from_set(dis.hasjrel), arg=sc.offset2branch(30))
    b.adjust(132, 2)

    assert 100 == b.offset
    assert 2 == b.length
    assert 132 == b.target
    assert sc.offset2branch(30) == b.arg()

def test_branch_adjust_rel_fw_after_target():
    b = sc.Branch(100, 2, from_set(dis.hasjrel), arg=sc.offset2branch(30))
    b.adjust(140, 2)

    assert 100 == b.offset
    assert 2 == b.length
    assert 132 == b.target
    assert sc.offset2branch(30) == b.arg()


def test_branch_adjust_length_no_change():
    b = sc.Branch(100, 2, from_set(dis.hasjrel), arg=sc.offset2branch(30))
    b.adjust(10, 50)

    change = b.adjust_length()
    assert 0 == change
    assert 2 == b.length


@pytest.mark.parametrize("prev_size, shift, increase_by", [
                            (2, 0x100, 2), (2, 0x10000, 4), (2, 0x1000000, 6),
                            (4, 0x100, 0), (4, 0x10000, 2), (4, 0x1000000, 4),
                            (6, 0x100, 0), (6, 0x10000, 0), (6, 0x1000000, 2),
                            (8, 0x100, 0), (8, 0x10000, 0), (8, 0x1000000, 0)
                         ])
def test_branch_adjust_length_increases(prev_size, shift, increase_by):
    b = sc.Branch(100, prev_size, from_set(dis.hasjrel), arg=sc.offset2branch(30))
    b.adjust(b.offset+prev_size, sc.branch2offset(shift))

    change = b.adjust_length()
    assert increase_by == change
    assert prev_size+change == b.length


def test_branch_adjust_length_decreases():
    b = sc.Branch(100, 4, from_set(dis.hasjrel), arg=sc.offset2branch(30))

    change = b.adjust_length()
    assert 0 == change
    assert 4 == b.length



@pytest.mark.parametrize("length, arg",
                         [(length, arg) for length in range(2, 8+1, 2) \
                                        for arg in [0x02, 0x102, 0x10203, 0x1020304] \
                                        if length >= 2+2*sc.arg_ext_needed(arg)])
def test_branch_code_unchanged(length, arg):
    opcode = from_set(dis.hasjrel)

    b = sc.Branch(100, length, opcode, arg=arg)
    assert sc.opcode_arg(opcode, arg, (length-2)//2) == b.code()


@pytest.mark.parametrize("length, arg",
                         [(length, arg) for length in range(2, 8+1, 2) \
                                        for arg in [0x02, 0x102, 0x10203, 0x1020304] \
                                        if length >= 2+2*sc.arg_ext_needed(arg)])
def test_branch_code_adjusted(length, arg):
    opcode = from_set(dis.hasjrel)

    b = sc.Branch(100, length, opcode, arg=arg)
    b.adjust(b.offset+b.length, sc.branch2offset(arg))
    b.adjust_length()

    assert sc.opcode_arg(opcode, 2*arg, (length-2)//2) == b.code()


def unpack_lnotab(lnotab: bytes) -> list:
    import struct
    return list(struct.unpack("Bb" * (len(lnotab)//2), lnotab))


def test_make_lnotab():
    lines = [sc.LineEntry(0, 6, 1),
             sc.LineEntry(6, 50, 2),
             sc.LineEntry(50, 350, 7),
             sc.LineEntry(350, 361, 207),
             sc.LineEntry(361, 370, 208),
             sc.LineEntry(370, 380, 50)]

    lnotab = sc.LineEntry.make_lnotab(0, lines)

    assert [0, 1,
            6, 1,
            44, 5,
            255, 0,
            45, 127,
            0, 73,
            11, 1,
            9, -128,
            0, -30] == unpack_lnotab(lnotab)


def test_make_linetable():
    lines = [sc.LineEntry(0, 6, 1),
             sc.LineEntry(6, 50, 2),
             sc.LineEntry(50, 350, 7),
             sc.LineEntry(350, 360, None),
             sc.LineEntry(360, 376, 8),
             sc.LineEntry(376, 380, 208),
             # XXX the lines below are presumptive, check for accuracy
             sc.LineEntry(380, 390, 50),
             sc.LineEntry(390, 690, None)]

    linetable = sc.LineEntry.make_linetable(0, lines)

    assert [6, 1,
            44, 1,
            254, 5,
            46, 0,
            10, -128,
            16, 1,
            0, 127,
            4, 73,
            0, -127,
            10, -31,
            254, -128,
            46, -128] == unpack_lnotab(linetable)


def lines_from_code(code):
    if PYTHON_VERSION >= (3,10):
        # XXX might co_lines() return the same line multiple times?
        return [sc.LineEntry(*l) for l in code.co_lines()]

    lines = [sc.LineEntry(start, 0, number) \
            for start, number in dis.findlinestarts(code)]
    for i in range(len(lines)-1):
        lines[i].end = lines[i+1].start
    lines[-1].end = len(code.co_code)
    return lines


def test_make_lines_and_compare():
    # XXX test with more code!
    def foo(n):
        x = 0

        for i in range(n):
            x += (i+1)

        return x

    if PYTHON_VERSION >= (3,10):
        my_linetable = sc.LineEntry.make_linetable(foo.__code__.co_firstlineno,
                                                   lines_from_code(foo.__code__))
        assert list(foo.__code__.co_linetable) == list(my_linetable)


    my_lnotab = sc.LineEntry.make_lnotab(foo.__code__.co_firstlineno,
                                         lines_from_code(foo.__code__))
    assert list(foo.__code__.co_lnotab) == list(my_lnotab)


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

# FIXME what about patterns starting with '?'


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

    first_line = current_line()+2
    def foo(n):
        if n == 42:
            return 666
        x = 0
        for i in range(n):
            x += (i+1)
        return x
    last_line = current_line()

    sci.instrument(foo)

    assert foo.__code__.co_stacksize >= sc.calc_max_stack(foo.__code__.co_code)
    assert '__slipcover__' in foo.__code__.co_consts

    # Are all lines where we expect?
    for (offset, _) in dis.findlinestarts(foo.__code__):
        assert sc.op_NOP == foo.__code__.co_code[offset]

    dis.dis(foo)
    assert 6 == foo(3)

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    assert [first_line, *range(first_line+2, last_line)] == cov['executed_lines']
    assert [first_line+1] == cov['missing_lines']


def test_instrument_code_before_first_line():
    sci = sc.Slipcover()

    first_line = current_line()+1
    def foo(n):
        for i in range(n+1):
            yield i
    last_line = current_line()

    # Generators in 3.10 start with a GEN_START that's not assigned to any lines;
    # that's what we're trying to test here
    first_line_offset, _ = next(dis.findlinestarts(foo.__code__))
    assert PYTHON_VERSION < (3,10) or 0 != first_line_offset

    sci.instrument(foo)
    dis.dis(foo)

    # Are all lines where we expect?
    for (offset, _) in dis.findlinestarts(foo.__code__):
        assert sc.op_NOP == foo.__code__.co_code[offset]

    assert 6 == sum(foo(3))

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    assert [*range(first_line+1, last_line)] == cov['executed_lines']
    assert [] == cov['missing_lines']


def test_instrument_threads():
    sci = sc.Slipcover()
    result = None

    first_line = current_line()+1
    def foo(n):
        nonlocal result
        x = 0
        for i in range(n):
            x += (i+1)
        result = x
    last_line = current_line()

    sci.instrument(foo)

    import threading

    t = threading.Thread(target=foo, args=(3,))
    t.start()
    t.join()

    assert 6 == result

    cov = sci.get_coverage()
    assert {simple_current_file()} == cov['files'].keys()

    cov = cov['files'][simple_current_file()]
    assert [*range(first_line+2, last_line)] == cov['executed_lines']
    assert [] == cov['missing_lines']


@pytest.mark.parametrize("N", [260, 65600])
def test_instrument_doesnt_interrupt_ext_sequence(N):
    EXT = sc.op_EXTENDED_ARG

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
    lines = lines_from_code(code)
    for i in range(len(lines)):
        if lines[i].number > 257:
            assert EXT == code.co_code[lines[i].start]
            lines[i].start = lines[i-1].end = lines[i-1].end + 2

    if PYTHON_VERSION >= (3,10):
        code = code.replace(co_linetable=sc.LineEntry.make_linetable(1, lines))
    else:
        code = code.replace(co_lnotab=sc.LineEntry.make_lnotab(1, lines))

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
    first_line = current_line()
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
    lines = list(map(lambda line: line-first_line, cov['missing_lines']))
    assert [6, 8, 9, 12, 13, 15] == lines


some_branches_grew = None

@pytest.mark.parametrize("N", [2, 20, 128, 256, 512, 4096, 8192, 65536, 131072])
def test_instrument_long_jump(N):
    sci = sc.Slipcover()

    # each 'if' adds a branch
    src = "x = 0\n" + \
          "while x == 0:\n" + \
          "  if x >= 0:\n" + \
          "    x += 1\n" * N

    code = compile(src, "foo", "exec")

    orig_branches = sc.Branch.from_code(code)
    assert 2 <= len(orig_branches)

    sci = sc.Slipcover()
    code = sci.instrument(code)

    # Are all lines where we expect?
    for (offset, _) in dis.findlinestarts(code):
        # This catches any lines not where we expect,
        # such as any not adjusted after adjusting branch lengths
        assert sc.op_NOP == code.co_code[offset]

    exec(code, locals(), globals())
    assert N == x

    cov = sci.get_coverage()['files']['foo']
    assert [*range(1, 1+N+3)] == cov['executed_lines']
    assert [] == cov['missing_lines']
    

    global some_branches_grew
    if some_branches_grew == None:
        some_branches_grew = False

    for i, b in enumerate(sc.Branch.from_code(code)):
        assert b.opcode == orig_branches[i].opcode
        if b.length > orig_branches[i].length:
            some_branches_grew = True


def test_some_branches_grew():
    # if the above test ran, check that we're getting some
    # branches to grow in size
    assert some_branches_grew == None or some_branches_grew


@pytest.mark.parametrize("stats", [False, True])
def test_deinstrument(stats):
    sci = sc.Slipcover(collect_stats=stats)

    first_line = current_line()+2
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
    sci.deinstrument(foo, {*range(first_line, last_line)})
    assert 6 == foo(3)
    assert not sci.get_coverage()['files'][simple_current_file()]['executed_lines']


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

    exec(code, locals(), globals())
    assert N-1 == x

    cov = sci.get_coverage()['files']['foo']
    assert [N] == cov['executed_lines']
    assert [*range(1,N)] == cov['missing_lines']


@pytest.mark.parametrize("stats", [False, True])
def test_deinstrument_some(stats):
    sci = sc.Slipcover(collect_stats=stats)

    first_line = current_line()+2
    def foo(n):
        x = 0
        for i in range(n):
            x += (i+1)
        return x
    last_line = current_line()

    assert not sci.get_coverage()['files'].keys()

    sci.instrument(foo)
    sci.deinstrument(foo, {first_line, last_line-1})

    assert 6 == foo(3)
    cov = sci.get_coverage()['files'][simple_current_file()]
    assert [*range(first_line+1, last_line-1)] == cov['executed_lines']
    assert [first_line, last_line-1] == cov['missing_lines']


def test_deinstrument_seen_d_threshold():
    sci = sc.Slipcover()

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

    assert old_code != foo.__code__, "Code never de-instrumented"

    foo(1)

    cov = sci.get_coverage()['files'][simple_current_file()]
    assert [*range(first_line, last_line)] == cov['executed_lines']
    assert [] == cov['missing_lines']


def test_deinstrument_seen_d_threshold_doesnt_count_while_deinstrumenting():
    sci = sc.Slipcover()

    def seq(start, stop):
        return list(range(start, stop))


    first_line = current_line()+2
    def foo(n):
        class Desc:  # https://docs.python.org/3/howto/descriptor.html
            def __get__(self, obj, objtype=None):
                return 10   # first_line+2 <-- shouldn't be seen
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
    assert seq(first_line, first_line+2) + seq(first_line+3, last_line) == cov['executed_lines']
    assert [first_line+2] == cov['missing_lines']


def test_deinstrument_seen_descriptor_not_invoked():
    sci = sc.Slipcover()

    def seq(start, stop):
        return list(range(start, stop))

    first_line = current_line()+2
    def foo(n):
        class Desc:  # https://docs.python.org/3/howto/descriptor.html
            def __get__(self, obj, objtype=None):
                raise TypeError("just testing!")
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
    assert seq(first_line, first_line+2) + seq(first_line+3, last_line) == cov['executed_lines']
    assert [first_line+2] == cov['missing_lines']


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


@pytest.mark.parametrize("stats", [False, True])
def test_print_coverage(stats, capsys):
    sci = sc.Slipcover(collect_stats=stats)

    first_line = current_line()+2
    def foo(n):
        if n == 42:
            return 666
        x = 0
        for i in range(n):
            x += (i+1)
        return x
    last_line = current_line()

    sci.instrument(foo)
    foo(3)
    sci.print_coverage(sys.stdout)

    import re

    # FIXME test more cases (multiple files, etc.)
    output = capsys.readouterr()[0].splitlines()
    print(output)
    assert re.match('^tests[/\\\\]slipcover_test\\.py + 6 + 1 +83 +' + str(first_line+1), output[3])

    if stats:
        assert re.match('^tests[/\\\\]slipcover_test\\.py +28.6 +0', output[8])


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
    # FIXME include in coverage info
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
    # FIXME include in coverage info
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


def test_pytest_plugins_visible(tmp_path):
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
