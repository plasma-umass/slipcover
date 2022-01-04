import sys
import dis
from pathlib import Path
from types import CodeType
from typing import Any, Dict
from collections import defaultdict


# Python 3.10a7 changed jump opcodes' argument to mean instruction
# (word) offset, rather than bytecode offset.
if sys.version_info[0:2] >= (3,10):
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


def new_CodeType(
    orig: CodeType, code: bytes, stacksize=None, consts=None, names=None
) -> CodeType:
    """Instantiates a new CodeType, modifying it from the original"""
    new = orig.replace(
        co_stacksize=orig.co_stacksize if not stacksize else stacksize,
        co_code=orig.co_code if not code else bytes(code),
        co_consts=(orig.co_consts if not consts else tuple(consts)),
        co_names=(orig.co_names if not names else tuple(names)),
    )
    replace_map[orig] = new
    # print("->", new)
    return new


def instrument(co: CodeType) -> CodeType:
    """Instruments a code object for coverage detection.
    If invoked on a function, instruments its code."""
    import types

    if isinstance(co, types.FunctionType):
        co.__code__ = instrument(co.__code__)
        return co.__code__

    assert isinstance(co, types.CodeType)
    #    print(f"instrumenting {co.co_name}")

    lines = list(dis.findlinestarts(co))
    consts = list(co.co_consts)

    note_coverage_index = len(consts)
    consts.append(note_coverage)

    filename_index = len(consts)
    consts.append(co.co_filename)

    # handle functions-within-functions
    for i in range(len(consts)):
        if isinstance(consts[i], types.CodeType):
            consts[i] = instrument(consts[i])

    def opcode_arg(opcode: str, arg: int):
        """Emits an opcode and its (variable length) argument."""
        bytecode = []
        ext = (arg.bit_length() - 1) // 8
        assert ext <= 3
        for i in range(ext):
            bytecode.extend(
                [dis.opmap["EXTENDED_ARG"], (arg >> (ext - i) * 8) & 0xFF]
            )
        bytecode.extend([dis.opmap[opcode], arg & 0xFF])
        return bytecode

    def mk_trampoline(offset: int, after_jump: int):
        tr = list(co.co_code[offset: offset + after_jump])
        # note_coverage
        tr.extend(opcode_arg("LOAD_CONST", note_coverage_index))
        # filename
        tr.extend(opcode_arg("LOAD_CONST", filename_index))
        # line number (will be added)
        tr.extend(opcode_arg("LOAD_CONST", len(consts)))
        tr.extend([dis.opmap["CALL_FUNCTION"], 2,
                   dis.opmap["POP_TOP"], 0])
        # FIXME do we need to pad to permit jump?
        tr.extend(opcode_arg("JUMP_ABSOLUTE", offset2jump(offset + after_jump)))
        return tr

    patch = bytearray(co.co_code)
    last_offset = None
    last_jump_len = None
    for (offset, lineno) in lines:
        assert(last_offset is None or last_offset + last_jump_len <= offset)

        # FIXME do we need to pad to permit jump?
        j = opcode_arg("JUMP_ABSOLUTE", offset2jump(len(patch)))
        patch.extend(mk_trampoline(offset, len(j)))
        patch[offset: offset + len(j)] = j

        consts.append(lineno)
        last_offset = offset
        last_jump_len = len(j)

    assert(last_offset is None or last_offset + last_jump_len <= len(co.co_code))

    return new_CodeType(
        co,
        patch,
        stacksize=co.co_stacksize + 2,  # use dis.stack_effect?
        consts=consts,
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
        # FIXME this assumes all lines are on the same file
        if lineno in lines:
            ext = 0
            t_offset = co.co_code[offset + 1]
            while co.co_code[offset + ext] == dis.opmap["EXTENDED_ARG"]:
                ext += 2
                t_offset = (t_offset << 8) | co.co_code[offset + ext + 1]

            if co.co_code[offset + ext] == dis.opmap["JUMP_ABSOLUTE"]:
                if not patch:
                    patch = bytearray(co.co_code)

                patch[offset: offset + ext + 2] = patch[
                    jump2offset(t_offset) : jump2offset(t_offset) + ext + 2
                ]

    return (
        co
        if (not patch and not consts)
        else new_CodeType(co, patch, consts=consts)
    )


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
            ### FIXME we're invoking deinstrument with every file's line number set
            deinstrument(f, new_lines_seen[file])

        lines_seen[file].update(new_lines_seen[file])
    new_lines_seen.clear()

    # Replace inner functions and any other function variables
    # XXX this could be better guided
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
