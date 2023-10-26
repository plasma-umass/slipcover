import pytest
import sys

PYTHON_VERSION = sys.version_info[0:2]

if PYTHON_VERSION >= (3,12):
    pytest.skip(allow_module_level=True)

import slipcover.bytecode as bc
import types
import dis
import inspect

def current_line():
    import inspect as i
    return i.getframeinfo(i.currentframe().f_back).lineno

def current_file():
    import inspect as i
    return i.getframeinfo(i.currentframe().f_back).filename

def simple_current_file():
    simp = sc.PathSimplifier()
    return simp.simplify(current_file())

def test_arg_ext_needed():
    assert 0 == bc.arg_ext_needed(0)
    assert 0 == bc.arg_ext_needed(1)
    assert 0 == bc.arg_ext_needed(0xFF)
    assert 1 == bc.arg_ext_needed(0x0100)
    assert 1 == bc.arg_ext_needed(0x0101)
    assert 1 == bc.arg_ext_needed(0x01FF)
    assert 1 == bc.arg_ext_needed(0xFFFF)
    assert 2 == bc.arg_ext_needed(0x010000)
    assert 2 == bc.arg_ext_needed(0x010001)
    assert 2 == bc.arg_ext_needed(0xFFFFFF)
    assert 3 == bc.arg_ext_needed(0x01000000)
    assert 3 == bc.arg_ext_needed(0x01000001)
    assert 3 == bc.arg_ext_needed(0xFFFFFFFF)


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


@pytest.mark.skipif(PYTHON_VERSION < (3,11), reason="N/A: new in 3.11")
def test_opcode_arg_includes_cache():
    for opcode, entries in enumerate(dis._inline_cache_entries):
        if entries:
            b = bc.opcode_arg(opcode, 0)
            assert len(b) >= 4, f"opcode={opcode}"
            assert b[2] == bc.op_CACHE
            assert b[3] == 0


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
        next(it)


@pytest.mark.skipif(PYTHON_VERSION < (3,11), reason="N/A: new in 3.11")
def test_unpack_opargs_skips_cache():
    # check that assumptions haven't changed
    assert dis._inline_cache_entries[bc.op_LOAD_GLOBAL]
    assert dis._inline_cache_entries[bc.op_PRECALL]
    assert dis._inline_cache_entries[bc.op_CALL]

    b = bytearray()
    b.extend(bc.opcode_arg(bc.op_LOAD_GLOBAL, 0))
    b.extend(bc.opcode_arg(bc.op_PRECALL, 1))
    b.extend(bc.opcode_arg(bc.op_CALL, 2))
    b.extend(bc.opcode_arg(bc.op_NOP, 0))

    it = iter(bc.unpack_opargs(b))
    _, _, op, _ = next(it)
    assert op == bc.op_LOAD_GLOBAL

    _, _, op, _ = next(it)
    assert op == bc.op_PRECALL

    _, _, op, _ = next(it)
    assert op == bc.op_CALL

    _, _, op, _ = next(it)
    assert op == bc.op_NOP


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


@pytest.mark.skipif(PYTHON_VERSION != (3,10), reason="N/A: 3.10 specific")
def test_make_linetable_310():
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
    dis_parse_varint = dis.parse_varint if 'parse_varint' in dis.__dict__ else dis._parse_varint
    assert n == dis_parse_varint(iter(bc.write_varint_be(n)))


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
        newcode = code.replace(co_linetable=bc.LineEntry.make_linetable(code.co_firstlineno, lines))
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


def gen_long_jump_code(N):
    return "x = 0\n" + \
           "try:\n" + \
           "  for _ in range(1):\n" + \
           "    " + ("x += 1;" * N) + "pass\n" + \
           "  raise RuntimeError('')\n" + \
           "except RuntimeError:\n" + \
           "  x += 10\n"

def gen_test_sequence():
    code = compile(gen_long_jump_code(64*1024), "foo", "exec")
    branches = bc.Branch.from_code(code)

    b = next(b for b in branches if b.opcode == dis.opmap["FOR_ITER"])

    # we want to generate Ns so that Slipcover's instrumentation forces
    # the "if" branch to grow in length (with an additional extended_arg)
    return [(64*1024*arg)//b.arg() for arg in [0xFF, 0xFFFF]]#, 0xFFFFFF]]


@pytest.mark.skipif(PYTHON_VERSION == (3,11), reason='brittle test')
@pytest.mark.parametrize("N", gen_test_sequence())
def test_adjust_long_jump(N):
    # each 'if' adds a branch
    src = gen_long_jump_code(N)

    orig_code = compile(src, "foo", "exec")
#    dis.dis(orig_code)

    orig_branches = bc.Branch.from_code(orig_code)
    assert len(orig_branches) >= 2

    def foo():
        global x
        x += 42

    lines = bc.LineEntry.from_code(orig_code)

    ed = bc.Editor(orig_code)
    foo_index = ed.add_const(foo)
    # instrument the line inside the "for" loop, making the loop grow
    ed.insert_function_call(lines[3].start, foo_index, ())
    inserts = ed.get_inserts()
    code = ed.finish()
#    dis.dis(code)

    assert len(inserts) > 0
    for offset in inserts:
        assert code.co_code[offset] == bc.op_NOP

    exec(orig_code, locals(), globals())
    assert N+10 == x

    exec(code, locals(), globals())
    assert N+10+42 == x

    # we want at least one branch to have grown in length
    print([b.arg() for b in orig_branches])
    print([b.arg() for b in bc.Branch.from_code(code)])
    assert any(b.length > orig_branches[i].length for i, b in enumerate(bc.Branch.from_code(code)))


def test_find_const_assignments():
    code = compile(inspect.cleandoc("""
            if x == 0:
                foo = True
                _slipcover_branch = (42, 666)
                ...
            bar = 1.234
        """), "foo", "exec")

    ed = bc.Editor(code)
    it = iter(ed.find_const_assignments('_slipcover_branch'))
    found = next(it)
    assert code.co_consts[found[2]] == (42, 666)

    with pytest.raises(StopIteration):
        next(it)


def test_find_const_assignment_not_found():
    code = compile(inspect.cleandoc("""
            if x == 0:
                foo = True
                _slipcover_branch = (42, 666)
                ...
            bar = 1.234
        """), "foo", "exec")

    ed = bc.Editor(code)
    with pytest.raises(StopIteration):
        next(ed.find_const_assignments('foobar'))


def test_replace_const_assignments_with_function_call():
    code = compile(inspect.cleandoc("""
            if x == 0:
                _slipcover_branch = (1, 2)
                x += 1
                ...

            else:
                _slipcover_branch = (1, 7)

            x += 2
        """), "foo", "exec")

#    dis.dis(code)
#    print("----")

    branches = set()
    def record_branch(b):
        branches.add(b)

    ed = bc.Editor(code)
    fn = ed.add_const(record_branch)

    delta = 0
    for found in ed.find_const_assignments('_slipcover_branch'):
        begin, end, arg = found
        delta += ed.insert_function_call(begin+delta, fn, [arg], repl_length=end-begin)

    inserts = ed.get_inserts()
    code = ed.finish()
#    dis.dis(code)

    assert len(inserts) > 0
    for offset in inserts:
        assert code.co_code[offset] == bc.op_NOP

    g = {'x':0}
    exec(code, g, g)
    assert {(1,2)} == branches

    branches = set()
    g = {'x':1}
    exec(code, g, g)
    assert {(1,7)} == branches
