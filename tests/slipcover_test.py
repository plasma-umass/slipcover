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


def test_opcode_arg():
    JUMP = bc.op_JUMP_FORWARD
    EXT = bc.op_EXTENDED_ARG

    assert [JUMP, 0x42] == list(bc.opcode_arg(JUMP, 0x42))
    assert [EXT, 0xBA, JUMP, 0xBE] == list(bc.opcode_arg(JUMP, 0xBABE))
    assert [EXT, 0xBA, EXT, 0xBE, JUMP, 0xFA] == \
           list(bc.opcode_arg(JUMP, 0xBABEFA))
    assert [EXT, 0xBA, EXT, 0xBE, EXT, 0xFA, JUMP, 0xCE] == \
           list(bc.opcode_arg(JUMP, 0xBABEFACE))

    assert [EXT, 0, JUMP, 0x42] == list(bc.opcode_arg(JUMP, 0x42, min_ext=1))
    assert [EXT, 0, EXT, 0, JUMP, 0x42] == list(bc.opcode_arg(JUMP, 0x42, min_ext=2))
    assert [EXT, 0, EXT, 0, EXT, 0, JUMP, 0x42] == \
           list(bc.opcode_arg(JUMP, 0x42, min_ext=3))


@pytest.mark.parametrize("EXT", [bc.op_EXTENDED_ARG] +\
                                ([dis._all_opmap["EXTENDED_ARG_QUICK"]] if PYTHON_VERSION >= (3,11) else []))
def test_unpack_opargs(EXT):
    NOP = bc.op_NOP
    JUMP = bc.op_JUMP_FORWARD

    octets = bytearray([NOP, 0,
                        EXT, 1, JUMP, 2,
                        EXT, 1, EXT, 2, JUMP, 3,
                        EXT, 1, EXT, 2, EXT, 3, JUMP, 4
                       ])
    it = iter(bc.unpack_opargs(octets))

    b, l, op, arg = next(it)
    assert 0 == b
    assert 2 == l
    assert NOP == op
    assert 0 == arg

    b, l, op, arg = next(it)
    assert 2 == b
    assert 4 == l
    assert JUMP == op
    assert (1<<8)+2 == arg

    b, l, op, arg = next(it)
    assert 6 == b
    assert 6 == l
    assert JUMP == op
    assert ((1<<8)+2<<8)+3 == arg

    b, l, op, arg = next(it)
    assert 12 == b
    assert 8 == l
    assert JUMP == op
    assert (((1<<8)+2<<8)+3<<8)+4 == arg

    with pytest.raises(StopIteration):
        b, l, op, arg = next(it)


@pytest.mark.parametrize("source", ["foo(1)", "x.foo(*range(10))", "x = sum(*range(10))"])
def test_calc_max_stack(source):
    code = compile(source, "foo", "exec")
    assert code.co_stacksize == bc.calc_max_stack(code.co_code)


def test_branch_from_code():
    def foo(x):
        for _ in range(2):      # FOR_ITER is relative
            if x: print(True)
            else: print(False)

    branches = bc.Branch.from_code(foo.__code__)
    dis.dis(foo)
    assert 4 == len(branches)  # may be brittle

    for i, b in enumerate(branches):
        assert 2 == b.length
        assert foo.__code__.co_code[b.offset+b.length-2] == b.opcode
        assert (b.opcode in dis.hasjabs) or (b.opcode in dis.hasjrel)
        assert (b.opcode in dis.hasjrel) == b.is_relative
        if i > 0: assert branches[i-1].offset < b.offset

    # the tests below are more brittle... they rely on a 'for' loop
    # being created with (pre 3.11)
    #
    #   loop: FOR_ITER done
    #            ...
    #         JUMP_ABSOLUTE loop
    #   done: ...
    #
    # or (3.11+):
    #
    # being created with (3.11+)
    #
    #   loop: FOR_ITER done
    #            ...
    #         JUMP_BACKWARD loop
    #   done: ...

    assert dis.opmap["FOR_ITER"] == branches[0].opcode
    assert branches[0].is_relative

    if PYTHON_VERSION < (3,11):
        assert dis.opmap["JUMP_ABSOLUTE"] == branches[-1].opcode
        assert not branches[-1].is_relative
    else:
        assert dis.opmap["JUMP_BACKWARD"] == branches[-1].opcode
        assert branches[-1].is_relative

    assert branches[0].target == branches[-1].offset+2    # to finish loop
    assert branches[-1].target == branches[0].offset      # to continue loop


@pytest.mark.skipif(PYTHON_VERSION >= (3,11), reason="N/A: no JUMP_ABSOLUTE")
@pytest.mark.parametrize("length, arg",
                         [(length, arg) for length in range(2, 8+1, 2) \
                                        for arg in [0x02, 0x102, 0x10203, 0x1020304] \
                                        if length >= 2+2*bc.arg_ext_needed(arg)])
def test_branch_init_abs(length, arg):
    opcode = dis.opmap["JUMP_ABSOLUTE"]

    b = bc.Branch(100, length, opcode, arg)
    assert 100 == b.offset
    assert length == b.length
    assert opcode == b.opcode
    assert not b.is_relative
    assert bc.branch2offset(arg) == b.target
    assert arg == b.arg()


@pytest.mark.parametrize("length, arg",
                         [(length, arg) for length in range(2, 8+1, 2) \
                                        for arg in [0x02, 0x102, 0x10203, 0x1020304] \
                                        if length >= 2+2*bc.arg_ext_needed(arg)])
def test_branch_init_rel_fw(length, arg):
    opcode = dis.opmap["JUMP_FORWARD"]

    b = bc.Branch(100, length, opcode, arg)
    assert 100 == b.offset
    assert length == b.length
    assert opcode == b.opcode
    assert b.is_relative
    assert b.offset + b.length + bc.branch2offset(arg) == b.target
    assert arg == b.arg()


@pytest.mark.skipif(PYTHON_VERSION < (3,11), reason="N/A: no JUMP_BACKWARD")
@pytest.mark.parametrize("length, arg",
                         [(length, arg) for length in range(2, 8+1, 2) \
                                        for arg in [0x02, 0x102, 0x10203, 0x1020304] \
                                        if length >= 2+2*bc.arg_ext_needed(arg)])
def test_branch_init_rel_bw(length, arg):
    opcode = dis.opmap["JUMP_BACKWARD"]

    b = bc.Branch(100, length, opcode, arg)
    assert 100 == b.offset
    assert length == b.length
    assert opcode == b.opcode
    assert b.is_relative
    assert b.offset + b.length + bc.branch2offset(-arg) == b.target
    assert arg == b.arg()

# Test case building rationale:
#
# All branches have an offset (where the operation is located) and a target
# (where it jumps to).
# 
# On forward branches, an insertion can happen before the offset, at the offset,
# between the offset and the target, at the target, or after the target.
# On backward branches, an insertion can happen before the target, at the target,
# between the target and the offset, at the offset, or after the offset.

if PYTHON_VERSION < (3,11):
    def make_bw_branch(at_offset, to_offset):
        assert to_offset < at_offset
        arg = bc.offset2branch(to_offset)
        return bc.Branch(at_offset, 2 + bc.arg_ext_needed(arg)*2, dis.opmap["JUMP_ABSOLUTE"], arg)
else:
    def make_bw_branch(at_offset, to_offset):
        assert to_offset < at_offset
        ext = 0
        arg = bc.offset2branch(at_offset + 2 - to_offset)
        while ext < bc.arg_ext_needed(arg):
            ext = bc.arg_ext_needed(arg)
            arg = bc.offset2branch(at_offset + 2 + 2*ext - to_offset)

        return bc.Branch(at_offset, 2 + 2*ext, dis.opmap["JUMP_BACKWARD"], arg)


def test_branch_adjust_bw_before_target():
    b = make_bw_branch(100, 90)
    b.adjust(50, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 92 == b.target
    assert bc.offset2branch(b.offset+b.length-b.target if b.is_relative else b.target) == b.arg()

def test_branch_adjust_bw_at_target():
    b = make_bw_branch(100, 90)
    b.adjust(90, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 90 == b.target
    assert bc.offset2branch(b.offset+b.length-b.target if b.is_relative else b.target) == b.arg()

def test_branch_adjust_bw_after_target_before_offset():
    b = make_bw_branch(100, 90)
    b.adjust(96, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 90 == b.target
    assert bc.offset2branch(b.offset+b.length-b.target if b.is_relative else b.target) == b.arg()

def test_branch_adjust_bw_at_offset():
    b = make_bw_branch(100, 90)
    b.adjust(100, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 90 == b.target
    assert bc.offset2branch(b.offset+b.length-b.target if b.is_relative else b.target) == b.arg()

def test_branch_adjust_bw_after_offset():
    b = make_bw_branch(100, 90)
    b.adjust(110, 2)

    assert 100 == b.offset
    assert 2 == b.length
    assert 90 == b.target
    assert bc.offset2branch(b.offset+b.length-b.target if b.is_relative else b.target) == b.arg()

def test_branch_adjust_fw_before_offset():
    b = bc.Branch(100, 2, dis.opmap["JUMP_FORWARD"], arg=bc.offset2branch(30))
    b.adjust(90, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 134 == b.target
    assert bc.offset2branch(30) == b.arg()

def test_branch_adjust_fw_at_offset():
    b = bc.Branch(100, 2, dis.opmap["JUMP_FORWARD"], arg=bc.offset2branch(30))
    b.adjust(100, 2)

    assert 102 == b.offset
    assert 2 == b.length
    assert 134 == b.target
    assert bc.offset2branch(30) == b.arg()

def test_branch_adjust_fw_after_offset_before_target():
    b = bc.Branch(100, 2, dis.opmap["JUMP_FORWARD"], arg=bc.offset2branch(30))
    b.adjust(105, 2)

    assert 100 == b.offset
    assert 2 == b.length
    assert 134 == b.target
    assert bc.offset2branch(30) != b.arg()

def test_branch_adjust_fw_at_target():
    b = bc.Branch(100, 2, dis.opmap["JUMP_FORWARD"], arg=bc.offset2branch(30))
    b.adjust(132, 2)

    assert 100 == b.offset
    assert 2 == b.length
    assert 132 == b.target
    assert bc.offset2branch(30) == b.arg()

def test_branch_adjust_fw_after_target():
    b = bc.Branch(100, 2, dis.opmap["JUMP_FORWARD"], arg=bc.offset2branch(30))
    b.adjust(140, 2)

    assert 100 == b.offset
    assert 2 == b.length
    assert 132 == b.target
    assert bc.offset2branch(30) == b.arg()


def test_branch_adjust_length_no_change():
    b = bc.Branch(100, 2, dis.opmap["JUMP_FORWARD"], arg=bc.offset2branch(30))
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
    b = bc.Branch(100, prev_size, dis.opmap["JUMP_FORWARD"], arg=bc.offset2branch(30))
    b.adjust(b.offset+prev_size, bc.branch2offset(shift))

    change = b.adjust_length()
    assert increase_by == change
    assert prev_size+change == b.length


def test_branch_adjust_length_decreases():
    b = bc.Branch(100, 4, dis.opmap["JUMP_FORWARD"], arg=bc.offset2branch(30))

    change = b.adjust_length()
    assert 0 == change
    assert 4 == b.length



@pytest.mark.parametrize("length, arg",
                         [(length, arg) for length in range(2, 8+1, 2) \
                                        for arg in [0x02, 0x102, 0x10203, 0x1020304] \
                                        if length >= 2+2*bc.arg_ext_needed(arg)])
def test_branch_code_unchanged(length, arg):
    opcode = dis.opmap["JUMP_FORWARD"]

    b = bc.Branch(100, length, opcode, arg=arg)
    assert bc.opcode_arg(opcode, arg, (length-2)//2) == b.code()


@pytest.mark.parametrize("length, arg",
                         [(length, arg) for length in range(2, 8+1, 2) \
                                        for arg in [0x02, 0x102, 0x10203, 0x1020304] \
                                        if length >= 2+2*bc.arg_ext_needed(arg)])
def test_branch_code_adjusted(length, arg):
    opcode = dis.opmap["JUMP_FORWARD"]

    b = bc.Branch(100, length, opcode, arg=arg)
    b.adjust(b.offset+b.length, bc.branch2offset(arg))
    b.adjust_length()

    assert bc.opcode_arg(opcode, 2*arg, (length-2)//2) == b.code()


def unpack_bytes(b: bytes) -> list:
    import struct
    return list(struct.unpack("Bb" * (len(b)//2), b))


def test_make_lnotab():
    lines = [bc.LineEntry(0, 6, 1),
             bc.LineEntry(6, 50, 2),
             bc.LineEntry(50, 350, 7),
             bc.LineEntry(350, 361, 207),
             bc.LineEntry(361, 370, 208),
             bc.LineEntry(370, 380, 50)]

    lnotab = bc.LineEntry.make_lnotab(0, lines)

    assert [0, 1,
            6, 1,
            44, 5,
            255, 0,
            45, 127,
            0, 73,
            11, 1,
            9, -128,
            0, -30] == unpack_bytes(lnotab)


def test_make_linetable():
    lines = [bc.LineEntry(0, 6, 1),
             bc.LineEntry(6, 50, 2),
             bc.LineEntry(50, 350, 7),
             bc.LineEntry(350, 360, None),
             bc.LineEntry(360, 376, 8),
             bc.LineEntry(376, 380, 208),
             # XXX the lines below are presumptive, check for accuracy
             bc.LineEntry(380, 390, 50),
             bc.LineEntry(390, 690, None)]

    linetable = bc.LineEntry.make_linetable(0, lines)

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
            46, -128] == unpack_bytes(linetable)


@pytest.mark.skipif(PYTHON_VERSION < (3,11), reason="N/A: new in 3.11")
def test_append_varint():
    assert [42] == bc.append_varint([], 42)
    assert [0x3f] == bc.append_varint([], 63)
    assert [0x48, 0x03] == bc.append_varint([], 200)


@pytest.mark.skipif(PYTHON_VERSION < (3,11), reason="N/A: new in 3.11")
def test_append_svarint():
    assert [0x20] == bc.append_svarint([], 0x10)
    assert [0x21] == bc.append_svarint([], -0x10)

    assert [0x3e] == bc.append_svarint([], 31)
    assert [0x3f] == bc.append_svarint([], -31)

    assert bc.append_varint([], 200<<1) == bc.append_svarint([], 200)
    assert bc.append_varint([], (200<<1)|1) == bc.append_svarint([], -200)


@pytest.mark.skipif(PYTHON_VERSION < (3,11), reason="N/A: new in 3.11")
@pytest.mark.parametrize("n", [0, 42, 63, 200, 65539])
def test_write_varint_be(n):
    assert n == dis.parse_varint(iter(bc.write_varint_be(n)))


@pytest.mark.skipif(PYTHON_VERSION < (3,11), reason="N/A: new in 3.11")
@pytest.mark.parametrize("n", [0, 42, 63, 200, 65539])
def test_read_varint_be(n):
    assert n == bc.read_varint_be(iter(bc.write_varint_be(n)))


@pytest.mark.parametrize("code", [
        (lambda x: x).__code__,
        (x \
         for x in range(10)).gi_code,
        compile("x=0;\ny=x;\n", "foo", "exec"),
        compile("""
def foo(n):
    x = 0

    for i in range(n):
        x += (i+1)

    return x
        """, "foo", "exec").co_consts[0], # should contain "foo" code
        # in 3.10, this yields byte codes without any lines
        compile("""
def foo(n):
    for i in range(n+1):
        yield i
        """, "foo", "exec").co_consts[0], # should contain "foo" code
    ])
def test_make_lines_and_compare(code):
    assert isinstance(code, types.CodeType)
    lines = bc.LineEntry.from_code(code)

    dis.dis(code)
    print(code.co_firstlineno)
    print([str(l) for l in lines])

    if PYTHON_VERSION < (3,10):
        my_lnotab = bc.LineEntry.make_lnotab(code.co_firstlineno, lines)
        assert list(code.co_lnotab) == list(my_lnotab)
    elif PYTHON_VERSION == (3,10):
        my_linetable = bc.LineEntry.make_linetable(code.co_firstlineno, lines)
        assert list(code.co_linetable) == list(my_linetable)
    else:
        newcode = code.replace(co_linetable=bc.LineEntry.make_positions(code.co_firstlineno, lines))
        assert list(dis.findlinestarts(newcode)) == list(dis.findlinestarts(code))

        # co_lines() repeats the same lines several times  FIXME -- do we care?
        #assert list(newcode.co_lines()) == list(code.co_lines())

        # Slipcover doesn't currently retain column information  FIXME
        #assert list(newcode.co_positions()) == list(code.co_positions())


@pytest.mark.skipif(PYTHON_VERSION < (3,11), reason="N/A: new in 3.11")
def test_make_exceptions_and_compare():
    # XXX test with more code!
    def foo(n):
        x = 0

        try:
            for i in range(n):
                try:
                    x += (i+1)
                finally:
                    pass
        finally:
            x += 42

        return x

    code = foo.__code__
    table = bc.ExceptionTableEntry.from_code(code)
    assert list(code.co_exceptiontable) == list(bc.ExceptionTableEntry.make_exceptiontable(table))


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


@pytest.mark.xfail(PYTHON_VERSION >= (3,11), reason="FIXME -- is this still applicable to Python 3.10+?", run=False)
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

    if PYTHON_VERSION >= (3,10):
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

    # FIXME test more cases (multiple files, etc.)
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


@pytest.mark.xfail(PYTHON_VERSION >= (3,11), reason="FIXME -- pytest interposition broken", run=False)
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


@pytest.mark.xfail(PYTHON_VERSION >= (3,11), reason="FIXME -- pytest interposition broken", run=False)
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


@pytest.mark.xfail(PYTHON_VERSION >= (3,11), reason="FIXME -- pytest interposition broken", run=False)
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
