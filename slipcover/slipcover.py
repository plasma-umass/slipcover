import sys
import dis
from types import CodeType
from typing import Dict
from collections import defaultdict

PYTHON_VERSION = sys.version_info[0:2]

# FIXME provide __all__

# Python 3.10a7 changed jump opcodes' argument to mean instruction
# (word) offset, rather than bytecode offset.
if PYTHON_VERSION >= (3,10):
    def offset2jump(offset: int):
        assert offset % 2 == 0
        return offset//2

    def jump2offset(jump: int):
        return jump*2
else:
    def offset2jump(offset: int):
        return offset

    def jump2offset(jump: int):
        return jump


# map to guide CodeType replacements
replace_map = dict()


def new_CodeType(orig: CodeType, **kwargs) -> CodeType:
    """Instantiates a new CodeType, modifying it from the original"""
    new = orig.replace(**kwargs)
    replace_map[orig] = new
    # print("->", new)
    return new


op_EXTENDED_ARG = dis.EXTENDED_ARG
op_LOAD_CONST = dis.opmap["LOAD_CONST"]
op_CALL_FUNCTION = dis.opmap["CALL_FUNCTION"]
op_POP_TOP = dis.opmap["POP_TOP"]
op_JUMP_ABSOLUTE = dis.opmap["JUMP_ABSOLUTE"]
op_JUMP_FORWARD = dis.opmap["JUMP_FORWARD"]
op_NOP = dis.opmap["NOP"]


def arg_ext_needed(arg: int):
    """Returns the number of EXTENDED_ARGs needed for an argument."""
    return (arg.bit_length() - 1) // 8


def opcode_arg(opcode: int, arg: int):
    """Emits an opcode and its (variable length) argument."""
    bytecode = []
    ext = arg_ext_needed(arg)
    assert ext <= 3
    for i in range(ext):
        bytecode.extend(
            [op_EXTENDED_ARG, (arg >> (ext - i) * 8) & 0xFF]
        )
    bytecode.extend([opcode, arg & 0xFF])
    return bytecode


class JumpOp:
    def __init__(self, offset : int, length : int, opcode : int, arg : int):
        self.offset = offset
        self.length = length
        self.opcode = opcode
        self.is_relative = (opcode in dis.hasjrel)
        self.target = jump2offset(arg) if not self.is_relative \
                      else offset + 2 + jump2offset(arg)

    def adjust(self, insert_offset : int, insert_length : int) -> None:
        """Adjusts this jump after a code insertion."""
        assert insert_length > 0
        if self.offset >= insert_offset:
            self.offset += insert_length
        if self.target > insert_offset:
            self.target += insert_length

    def arg(self) -> int:
        """Returns this jump's opcode argument."""
        if self.is_relative:
            return offset2jump(self.target - 2 - self.offset)
        return offset2jump(self.target)

    # FIXME tests missing
    def adjust_length(self) -> int:
        """Adjusts this jump's length, if needed, assuming the returned number of
           bytes will be inserted (or deleted) at this jump's offset.
           Returns the number of bytes by which the length changed."""
        length_needed = 2 + 2*arg_ext_needed(self.arg())
        change = length_needed - self.length
        if change:
            if self.target > self.offset:
                self.target += change
            self.length = length_needed

        return change

    # FIXME tests missing
    def code(self) -> bytes:
        """Emits this jump's code."""
        assert self.length == 2 + 2*arg_ext_needed(self.arg())
        return opcode_arg(self.opcode, self.arg())


def get_jumps(code):
    """Extracts all the JumpOps in code."""
    jumps = []

    def unpack_opargs(code):
        ext_arg = 0
        next_off = 0
        for off in range(0, len(code), 2):
            op = code[off]
            if op == op_EXTENDED_ARG:
                ext_arg = (ext_arg | code[off+1]) << 8
            else:
                arg = (ext_arg | code[off+1])
                yield (next_off, off+2-next_off, op, arg)
                ext_arg = 0
                next_off = off+2

    jump_opcodes = set(dis.hasjrel).union(dis.hasjabs)

    for (off, length, op, arg) in unpack_opargs(code):
        if op in jump_opcodes:
            jumps.append(JumpOp(off, length, op, arg))

    return jumps


def make_lnotab(firstlineno, lines):
    """Generates the line number table used by Python to map offsets to line numbers."""
    assert (3,8) <= PYTHON_VERSION <= (3,9) # 3.10+ has a new format
    # FIXME add python 3.10 support

    lnotab = []

    prev_offset = 0
    prev_line = firstlineno

    for (offset, line) in lines:
        delta_offset = offset - prev_offset
        delta_line = line - prev_line

        while delta_offset > 255:
            lnotab.extend([255, 0])
            delta_offset -= 255

        if delta_line >= 0:
            while delta_line > 127:
                lnotab.extend([delta_offset, 127])
                delta_line -= 127
                delta_offset = 0
        else:
            while delta_line < -128:
                lnotab.extend([delta_offset, -128])
                delta_line += 128
                delta_offset = 0

        lnotab.extend([delta_offset, delta_line])

        prev_offset = offset
        prev_line = line

    return lnotab


def instrument(co: CodeType) -> CodeType:
    """Instruments a code object for coverage detection.
    If invoked on a function, instruments its code."""
    import types

    if not ((3,8) <= PYTHON_VERSION <= (3,10)):
        raise RuntimeError("Unsupported Python version; please use 3.8 to 3.10")

    if isinstance(co, types.FunctionType):
        co.__code__ = instrument(co.__code__)
        return co.__code__

    assert isinstance(co, types.CodeType)
    #    print(f"instrumenting {co.co_name}")

    consts = list(co.co_consts)

    note_coverage_index = len(consts)
    consts.append(note_coverage)

    filename_index = len(consts)
    consts.append(co.co_filename)

    # handle functions-within-functions
    for i in range(len(consts)):
        if isinstance(consts[i], types.CodeType):
            consts[i] = instrument(consts[i])

    jumps = get_jumps(co.co_code)
    patch = bytearray()
    lines = []

    prev_offset = None
    for (offset, lineno) in dis.findlinestarts(co):
        if prev_offset != None:
            patch.extend(co.co_code[prev_offset:offset])
        prev_offset = offset

        patch_offset = len(patch)
        patch.extend([op_NOP, 0])       # for deinstrument jump
        patch.extend(opcode_arg(op_LOAD_CONST, note_coverage_index))
        patch.extend(opcode_arg(op_LOAD_CONST, filename_index))
        patch.extend(opcode_arg(op_LOAD_CONST, len(consts)))
        consts.append(lineno)
        patch.extend([op_CALL_FUNCTION, 2,
                      op_POP_TOP, 0])    # ignore return
        inserted = len(patch) - patch_offset
        assert inserted <= 255
        patch[patch_offset+1] = inserted-2

        lines.append([patch_offset, lineno])

        for j in jumps:
            j.adjust(patch_offset, inserted)

    if prev_offset != None:
        patch.extend(co.co_code[prev_offset:])

    # A jump's new target may now require more EXTENDED_ARG opcodes to be expressed.
    # Inserting space for those may in turn trigger needing more space for others...
    # FIXME missing test for length adjustment triggering other length adjustments
    any_adjusted = True
    while any_adjusted:
        any_adjusted = False

        for j in jumps:
            change = j.adjust_length()
            if change:
#                print(f"adjusted jump {j.offset} to {j.target} by {change} to {j.length}")
                # FIXME what if change < 0?
                patch[j.offset:j.offset] = [0] * change
                for k in jumps:
                    if j != k:
                        k.adjust(j.offset, change)

                for i in range(len(lines)):
                    if lines[i][0] > j.offset:
                        lines[i][0] += change

                any_adjusted = True

    for j in jumps:
        assert patch[j.offset+j.length-2] == j.opcode
        patch[j.offset:j.offset+j.length] = j.code()

    lnotab = make_lnotab(co.co_firstlineno, lines)

    return new_CodeType(
        co,
        co_code=bytes(patch),
        co_stacksize=co.co_stacksize + 2,  # FIXME use dis.stack_effect
        co_consts=tuple(consts),
        co_lnotab=bytes(lnotab)
    )


def deinstrument(co, lines: set):
    """De-instruments a code object previously instrumented for coverage detection.
    If invoked on a function, de-instruments its code."""
    import types

    if isinstance(co, types.FunctionType):
        co.__code__ = deinstrument(co.__code__, lines)
        return

    assert isinstance(co, types.CodeType)
    # print(f"de-instrumenting {co.co_name}")

    patch = None
    consts = None

    for i in range(len(co.co_consts)):
        if isinstance(co.co_consts[i], types.CodeType):
            nc = deinstrument(co.co_consts[i], lines)
            if nc != co.co_consts[i]:
                if not consts:
                    consts = list(co.co_consts)
                consts[i] = nc

    for (offset, lineno) in dis.findlinestarts(co):
        if lineno in lines and co.co_code[offset] == op_NOP:
            if not patch:
                patch = bytearray(co.co_code)
            patch[offset] = op_JUMP_FORWARD

    if not patch and not consts:
        return co

    changed = {}
    if patch: changed["co_code"] = bytes(patch)
    if consts: changed["co_consts"] = tuple(consts)
    return new_CodeType(co, **changed)


# Notes which lines have been seen.
lines_seen: Dict[str, set] = defaultdict(lambda: set())

# Notes lines seen since last de-instrumentation
new_lines_seen: Dict[str, set] = defaultdict(lambda: set())


def note_coverage(filename: str, lineno: int):
    """Invoked to mark a line as having executed."""
    new_lines_seen[filename].add(lineno)


def get_coverage() -> Dict[str, set]:
    # in case any haven't been merged in yet
    for file in new_lines_seen:
        lines_seen[file].update(new_lines_seen[file])

    return lines_seen


def clear():
    """Clears accumulated coverage information."""
    lines_seen.clear()
    new_lines_seen.clear()
    replace_map.clear()


def print_coverage():
    import signal
    signal.setitimer(signal.ITIMER_VIRTUAL, 0)

    lines_seen = get_coverage()

    print("printing coverage")

    def merge_consecutives(L):
        # Neat little trick due to John La Rooy: the difference between the numbers
        # on a list and a counter is constant for consecutive items :)
        from itertools import groupby, count

        groups = groupby(sorted(L), key=lambda item, c=count(): item - next(c))
        return [
            str(g[0]) if g[0] == g[-1] else f"{g[0]}-{g[-1]}"
            for g in [list(g) for _, g in groups]
        ]

    def get_nonempty_lines(filename):
        import ast
        nonempty_lines = set()

        with open(filename, "r") as f:
            tree = ast.parse(f.read(), mode="exec")

        for f in ast.walk(tree):
            if (hasattr(f, 'lineno')):
                nonempty_lines.add(f.lineno)

        return nonempty_lines

    print("not covered:")
    for file in lines_seen:
        print(" " * 5, file, merge_consecutives(get_nonempty_lines(file) - lines_seen[file]))


def deinstrument_seen(script_globals: dict):
    import inspect
    import types

    def all_functions():
        """Introspects, returning all functions (that may be pointing to
           instrumented code) to deinstrument"""
        classes = [
            c
            for c in script_globals.values()
            if isinstance(c, type) or isinstance(c, types.ModuleType)
        ]
        methods = [
            f[1]
            for c in classes
            for f in inspect.getmembers(c, inspect.isfunction)
        ]
        funcs = [
            o
            for o in script_globals.values()
            if isinstance(o, types.FunctionType)
        ]
        return methods + funcs


    for file in new_lines_seen:
        for f in all_functions():
            # FIXME we're invoking deinstrument with every file's line number set
            deinstrument(f, new_lines_seen[file])

        lines_seen[file].update(new_lines_seen[file])
    new_lines_seen.clear()

    # Replace inner functions and any other function variables
    if replace_map:
        frame = inspect.currentframe()
        while frame:
            # list() avoids 'dictionary changed size during iter.'
            for var in list(frame.f_locals.keys()):
                if isinstance(frame.f_locals[var], types.FunctionType):
                    f = frame.f_locals[var]
                    if f.__code__ in replace_map:
                        f.__code__ = replace_map[f.__code__]

            frame = frame.f_back

        # all references should have been replaced now... right?
        replace_map.clear()

    # stackpatch.patch(replace_map)
