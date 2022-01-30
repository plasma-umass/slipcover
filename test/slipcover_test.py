import pytest
from slipcover import slipcover as sc
import dis
import sys
import struct


PYTHON_VERSION = sys.version_info[0:2]


def current_line():
    import inspect as i
    return i.getframeinfo(i.currentframe().f_back).lineno

def current_file():
    import inspect as i
    return i.getframeinfo(i.currentframe().f_back).filename

def from_set(s: set):
    return next(iter(s))

@pytest.fixture(autouse=True)
def clear_slipcover():
    sc.clear()

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
    return list(struct.unpack("Bb" * (len(lnotab)//2), lnotab))


def test_make_lnotab():
    lines = [sc.LineEntry(0, 6, 1),
             sc.LineEntry(6, 50, 2),
             sc.LineEntry(50, 350, 7),
             sc.LineEntry(350, 361, 207),
             sc.LineEntry(361, 370, 208),
             sc.LineEntry(370, 380, 50)]

    lnotab = sc.make_lnotab(0, lines)

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
             sc.LineEntry(380, 390, 50)]    # XXX this is presumptive, check for accuracy

    linetable = sc.make_linetable(0, lines)

    assert [6, 1,
            44, 1,
            254, 5,
            46, 0,
            10, -128,
            16, 1,
            0, 127,
            4, 73,
            0, -127,
            10, -31] == unpack_lnotab(linetable)


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
        my_linetable = sc.make_linetable(foo.__code__.co_firstlineno,
                                         lines_from_code(foo.__code__))
        assert list(foo.__code__.co_linetable) == list(my_linetable)


    my_lnotab = sc.make_lnotab(foo.__code__.co_firstlineno,
                               lines_from_code(foo.__code__))
    assert list(foo.__code__.co_lnotab) == list(my_lnotab)


def test_instrument():
    first_line = current_line()+1
    def foo(n):
        x = 0
        for i in range(n):
            x += (i+1)
        return x
    last_line = current_line()

    sc.instrument(foo)

    # Are all lines where we expect?
    for (offset, _) in dis.findlinestarts(foo.__code__):
        assert sc.op_NOP == foo.__code__.co_code[offset]

    dis.dis(foo)
    assert 6 == foo(3)

    assert {current_file(): {*range(first_line+1, last_line)}} == sc.get_coverage()
    assert {current_file(): {*range(first_line+1, last_line)}} == sc.get_code_lines()


def test_instrument_threads():
    result = None

    first_line = current_line()+1
    def foo(n):
        nonlocal result
        x = 0
        for i in range(n):
            x += (i+1)
        result = x
    last_line = current_line()

    sc.instrument(foo)

    import threading

    t = threading.Thread(target=foo, args=(3,))
    t.start()
    t.join()

    assert 6 == result

    assert {current_file(): {*range(first_line+2, last_line)}} == sc.get_coverage()
    assert {current_file(): {*range(first_line+2, last_line)}} == sc.get_code_lines()


def test_get_code_lines():
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

    sc.instrument(foo)
    lines = sc.get_code_lines()[current_file()]
    lines = set(map(lambda line: line-first_line, lines))

    assert set([6, 8, 9, 12, 13, 15]) == lines


some_branches_grew = None

@pytest.mark.parametrize("N", [2, 20, 128, 256, 512, 4096, 8192, 65536, 131072])
def test_instrument_long_jump(N):
    # each 'if' adds a branch
    first_line = current_line()+2
    src = "x = 0\n" + \
          "while x == 0:\n" + \
          "  if x >= 0:\n" + \
          "    x += 1\n" * N

    code = compile(src, "foo", "exec")

    orig_branches = sc.Branch.from_code(code)
    assert 2 <= len(orig_branches)

    code = sc.instrument(code)

    # Are all lines where we expect?
    for (offset, _) in dis.findlinestarts(code):
        # This catches any lines not where we expect,
        # such as any not adjusted after adjusting branch lengths
        assert sc.op_NOP == code.co_code[offset]

    exec(code, locals(), globals())
    assert N == x
    assert {"foo": {*range(1, 1+N+3)}} == sc.get_coverage()
    

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


def test_deinstrument():
    first_line = current_line()+2
    def foo(n):
        x = 0
        for i in range(n):
            x += (i+1)
        return x
    last_line = current_line()

    assert not sc.get_coverage()

    sc.instrument(foo)
    sc.deinstrument(foo, {*range(first_line, last_line)})
    assert 6 == foo(3)
    assert not sc.get_coverage()


def test_deinstrument_some():
    first_line = current_line()+2
    def foo(n):
        x = 0
        for i in range(n):
            x += (i+1)
        return x
    last_line = current_line()

    assert not sc.get_coverage()

    sc.instrument(foo)
    sc.deinstrument(foo, {first_line, last_line-1})

    assert 6 == foo(3)
    assert {current_file(): {*range(first_line+1, last_line-1)}} == sc.get_coverage()


# FIXME test deinstrument_seen


def test_auto_deinstrument():
    first_line = current_line()+2
    def foo(n):
        if n > 0:
            return n+1 
        return 0
    last_line = current_line()

    assert not sc.get_coverage()

    sc.instrument(foo)
    old_code = foo.__code__

    sc.auto_deinstrument()
    foo(0)

    max_attempts = 10
    import time
    while (foo.__code__ == old_code and max_attempts > 0):
        max_attempts -= 1
        time.sleep(.05)

    assert max_attempts > 0, "Code never de-instrumented"

    sc.lines_seen[current_file()].clear()   # FIXME breaks interface
    foo(1)

    assert {current_file(): {first_line+1}} == sc.get_coverage()


# FIXME test module loading & instrumentation

