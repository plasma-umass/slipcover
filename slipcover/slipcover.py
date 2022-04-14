from __future__ import annotations
import sys
import dis
import types
from typing import Dict, Set, List
from collections import defaultdict, Counter
import threading
from . import tracker
from pathlib import Path

PYTHON_VERSION = sys.version_info[0:2]

# FIXME provide __all__

# Python 3.10a7 changed branch opcodes' argument to mean instruction
# (word) offset, rather than bytecode offset.
if PYTHON_VERSION >= (3,10):
    def offset2branch(offset: int) -> int:
        assert offset % 2 == 0
        return offset//2

    def branch2offset(arg: int) -> int:
        return arg*2
else:
    def offset2branch(offset: int) -> int:
        return offset

    def branch2offset(arg: int) -> int:
        return arg


# Counter.total() is new in 3.10
if PYTHON_VERSION < (3,10):
    def counter_total(self: Counter) -> int:
        return sum([self[n] for n in self])
    setattr(Counter, 'total', counter_total)


op_EXTENDED_ARG = dis.EXTENDED_ARG
op_LOAD_CONST = dis.opmap["LOAD_CONST"]
op_CALL_FUNCTION = dis.opmap["CALL_FUNCTION"]
op_POP_TOP = dis.opmap["POP_TOP"]
op_JUMP_ABSOLUTE = dis.opmap["JUMP_ABSOLUTE"]
op_JUMP_FORWARD = dis.opmap["JUMP_FORWARD"]
op_NOP = dis.opmap["NOP"]


def arg_ext_needed(arg: int) -> int:
    """Returns the number of EXTENDED_ARGs needed for an argument."""
    return (arg.bit_length() - 1) // 8


def opcode_arg(opcode: int, arg: int, min_ext : int = 0) -> List[int]:
    """Emits an opcode and its (variable length) argument."""
    bytecode = []
    ext = max(arg_ext_needed(arg), min_ext)
    assert ext <= 3
    for i in range(ext):
        bytecode.extend(
            [op_EXTENDED_ARG, (arg >> (ext - i) * 8) & 0xFF]
        )
    bytecode.extend([opcode, arg & 0xFF])
    return bytecode


def unpack_opargs(code: bytes) -> List[(int, int, int, int)]:
    """Unpacks opcodes and their arguments, returning:

    - the beginning offset, including that of the first EXTENDED_ARG, if any
    - the length (offset + length is where the next opcode starts)
    - the opcode
    - its argument (decoded)
    """
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


def calc_max_stack(code: bytes) -> int:
    """Calculates the maximum stack size for code to execute.

    Assumes linear execution (i.e., not things like a loop pushing to the stack).
    """
    max_stack = stack = 0
    for (_, _, op, arg) in unpack_opargs(code):
        stack += dis.stack_effect(op, arg if op >= dis.HAVE_ARGUMENT else None)
        max_stack = max(stack, max_stack)

    return max_stack


class Branch:
    """Describes a branch instruction."""

    def __init__(self, offset : int, length : int, opcode : int, arg : int):
        """Initializes a new Branch.

        offset - offset in code where the instruction starts; if EXTENDED_ARGs are
            used, it should be the offset of the first EXTENDED_ARG
        length - instruction length, including that of any EXTENDED_ARGs
        opcode - the instruction's opcode
        arg - the instruction's argument (decoded if using EXTENDED_ARGs)
        """
        self.offset = offset
        self.length = length
        self.opcode = opcode
        self.is_relative = (opcode in dis.hasjrel)
        self.target = branch2offset(arg) if not self.is_relative \
                      else offset + length + branch2offset(arg)

    def arg(self) -> int:
        """Returns this branch's opcode argument."""
        if self.is_relative:
            return offset2branch(self.target - (self.offset + self.length))
        return offset2branch(self.target)

    def adjust(self, insert_offset : int, insert_length : int) -> None:
        """Adjusts this branch after a code insertion."""
        assert insert_length > 0
        if self.offset >= insert_offset:
            self.offset += insert_length
        if self.target > insert_offset:
            self.target += insert_length

    def adjust_length(self) -> int:
        """Adjusts this branch's opcode length, if needed.

        Returns the number of bytes by which the length increased.
        """
        length_needed = 2 + 2*arg_ext_needed(self.arg())
        change = max(0, length_needed - self.length)
        if change:
            if self.target > self.offset:
                self.target += change
            self.length = length_needed

        return change

    def code(self) -> bytes:
        """Emits this branch's code."""
        assert self.length >= 2 + 2*arg_ext_needed(self.arg())
        return opcode_arg(self.opcode, self.arg(), (self.length-2)//2)

    @staticmethod
    def from_code(code : types.CodeType) -> List[Branch]:
        """Finds all Branches in code."""
        branches = []

        branch_opcodes = set(dis.hasjrel).union(dis.hasjabs)

        for (off, length, op, arg) in unpack_opargs(code.co_code):
            if op in branch_opcodes:
                branches.append(Branch(off, length, op, arg))

        return branches


class LineEntry:
    def __init__(self, start : int, end : int, number : int):
        """Initializes a new line entry.

        start, end: start and end offsets in the code
        number: line number
        """
        self.start = start
        self.end = end
        self.number = number

    # FIXME tests missing
    def adjust(self, insert_offset : int, insert_length : int) -> None:
        """Adjusts this line after a code insertion."""
        assert insert_length > 0
        if self.start > insert_offset:
            self.start += insert_length
        if self.end > insert_offset:
            self.end += insert_length


    @staticmethod
    def make_lnotab(firstlineno : int, lines : List[LineEntry]) -> bytes:
        """Generates the line number table used by Python 3.9- to map offsets to line numbers."""

        lnotab = []

        prev_start = 0
        prev_number = firstlineno

        for l in lines:
            delta_start = l.start - prev_start
            delta_number = l.number - prev_number

            while delta_start > 255:
                lnotab.extend([255, 0])
                delta_start -= 255

            while delta_number > 127:
                lnotab.extend([delta_start, 127])
                delta_start = 0
                delta_number -= 127

            while delta_number < -128:
                lnotab.extend([delta_start, -128 & 0xFF])
                delta_start = 0
                delta_number += 128

            lnotab.extend([delta_start, delta_number & 0xFF])

            prev_start = l.start
            prev_number = l.number

        return bytes(lnotab)


    @staticmethod
    def make_linetable(firstlineno : int, lines : List[LineEntry]) -> bytes:
        """Generates the line number table used by Python 3.10+ to map offsets to line numbers."""

        linetable = []

        prev_end = 0
        prev_number = firstlineno

        for l in lines:
            delta_end = l.end - prev_end

            if l.number is None:
                while delta_end > 254:
                    linetable.extend([254, -128 & 0xFF])
                    delta_end -= 254

                linetable.extend([delta_end, -128 & 0xFF])
            else:
                delta_number = l.number - prev_number

                while delta_number > 127:
                    linetable.extend([0, 127])
                    delta_number -= 127

                while delta_number < -127:
                    linetable.extend([0, -127 & 0xFF])
                    delta_number += 127

                while delta_end > 254:
                    linetable.extend([254, delta_number & 0xFF])
                    delta_number = 0
                    delta_end -= 254

                linetable.extend([delta_end, delta_number & 0xFF])
                prev_number = l.number

            prev_end = l.end

        return bytes(linetable)


class PathSimplifier:
    def __init__(self):
        self.cwd = Path.cwd()

    def simplify(self, path : str) -> str:
        f = Path(path)
        try:
            return str(f.relative_to(self.cwd))
        except ValueError:
            return path 


class FileMatcher:
    def __init__(self):
        import inspect
        pylib_path = Path(inspect.getfile(inspect)).parent

        self.cwd = Path.cwd()
        self.sources = []
        self.omit = [pylib_path]

    def addSource(self, source : Path):
        if isinstance(source, str):
            source = Path(source)
        if not source.is_absolute():
            source = self.cwd / source
        self.sources.append(source)

    def addOmit(self, omit):
        if not omit.startswith('*'):
            omit = self.cwd / omit

        self.omit.append(omit)
        pass

    def matches(self, filename : Path):
        if isinstance(filename, str):
            if filename == 'built-in': return False     # can't instrument
            filename = Path(filename)

        if filename.suffix in ('.pyd', '.so'): return False  # can't instrument DLLs

        if not filename.is_absolute():
            filename = self.cwd / filename

        if self.omit:
            from fnmatch import fnmatch
            if any(fnmatch(filename, o) for o in self.omit):
                return False

        if self.sources:
            return any(s in filename.parents for s in self.sources)

        return self.cwd in filename.parents


class Slipcover:
    def __init__(self, collect_stats : bool = False, d_threshold = 50):
        if not ((3,8) <= PYTHON_VERSION <= (3,10)):
            raise RuntimeError("Unsupported Python version; please use 3.8 to 3.10")

        self.collect_stats = collect_stats
        self.d_threshold = d_threshold

        # mutex protecting this state
        self.lock = threading.RLock()

        # maps to guide CodeType replacements
        self.replace_map: Dict[types.CodeType, types.CodeType] = dict()
        self.instrumented: Dict[str, set] = defaultdict(set)

        # notes which code lines have been instrumented
        self.code_lines: Dict[str, set] = defaultdict(set)

        # notes which lines have been seen.
        self.lines_seen: Dict[str, Set[int]] = defaultdict(set)

        # notes lines seen since last de-instrumentation
        self._get_new_lines()

        # stats
        self.u_misses: Dict[str, Counter[int]] = defaultdict(Counter)
        self.reported: Dict[str, Counter[int]] = defaultdict(Counter)
        self.deinstrumented: Dict[str, Counter[int]] = defaultdict(Counter)

        self.modules = []

    def _get_new_lines(self):
        """Returns the current set of ``new'' lines, leaving a new container in place."""

        # We trust that assigning to self.new_lines_seen is atomic, as it is triggered
        # by a STORE_NAME or similar opcode and Python synchronizes those.  We rely on
        # C extensions' atomicity for updates within self.new_lines_seen.  The lock here
        # is just to protect callers of this method (so that the exchange is atomic).

        with self.lock:
            new_lines = self.new_lines_seen if hasattr(self, "new_lines_seen") else None

            if not self.collect_stats:
                self.new_lines_seen: Dict[str, Set[int]] = defaultdict(set)
            else:
                self.new_lines_seen: Dict[str, Counter[int]] = defaultdict(Counter)

        return new_lines


    def instrument(self, co: types.CodeType, parent: types.CodeType = 0) -> types.CodeType:
        """Instruments a code object for coverage detection.

        If invoked on a function, instruments its code.
        """

        if isinstance(co, types.FunctionType):
            co.__code__ = self.instrument(co.__code__)
            return co.__code__

        assert isinstance(co, types.CodeType)
        # print(f"instrumenting {co.co_name}")

        consts = list(co.co_consts)

        tracker_signal_index = len(consts)
        consts.append(tracker.signal)

        # handle functions-within-functions
        for i, c in enumerate(consts):
            if isinstance(c, types.CodeType):
                consts[i] = self.instrument(c, co)

        branches = Branch.from_code(co)
        patch = bytearray()
        lines = []

        max_addtl_stack = 0

        prev_offset = 0
        prev_lineno = None
        patch_offset = 0
        for (offset, lineno) in dis.findlinestarts(co):
            patch.extend(co.co_code[prev_offset:offset])
            if offset > prev_offset:
                lines.append(LineEntry(patch_offset, len(patch), prev_lineno))
            prev_offset = offset
            prev_lineno = lineno

            while (prev_offset >= 2 and co.co_code[prev_offset-2] == op_EXTENDED_ARG):
                patch.extend(co.co_code[prev_offset:prev_offset+2])
                prev_offset += 2

            # FIXME test out if prev_offset is larger than the next offset

            patch_offset = len(patch)
            patch.extend([op_NOP, 0])       # for deinstrument jump
            patch.extend(opcode_arg(op_LOAD_CONST, tracker_signal_index))
            patch.extend(opcode_arg(op_LOAD_CONST, len(consts)))
            consts.append(tracker.register(self, co.co_filename, lineno))
            patch.extend([op_CALL_FUNCTION, 1,
                          op_POP_TOP, 0])    # ignore return
            inserted = len(patch) - patch_offset
            assert inserted <= 255
            patch[patch_offset+1] = offset2branch(inserted-2)

            max_addtl_stack = max(max_addtl_stack, calc_max_stack(patch[patch_offset:]))

            for b in branches:
                b.adjust(patch_offset, inserted)

        if prev_offset != None:
            patch.extend(co.co_code[prev_offset:])
            lines.append(LineEntry(patch_offset, len(patch), prev_lineno))

        # A branch's new target may now require more EXTENDED_ARG opcodes to be expressed.
        # Inserting space for those may in turn trigger needing more space for others...
        # FIXME missing test for length adjustment triggering other length adjustments
        any_adjusted = True
        while any_adjusted:
            any_adjusted = False

            for b in branches:
                change = b.adjust_length()
                if change:
#                    print(f"adjusted branch {b.offset} to {b.target} by {change} to {b.length}")
                    patch[b.offset:b.offset] = [0] * change
                    for c in branches:
                        if b != c:
                            c.adjust(b.offset, change)

                    for l in lines:
                        l.adjust(b.offset, change)

                    any_adjusted = True

        for b in branches:
            assert patch[b.offset+b.length-2] == b.opcode
            patch[b.offset:b.offset+b.length] = b.code()

        kwargs = {}
        if PYTHON_VERSION < (3,10):
            kwargs["co_lnotab"] = LineEntry.make_lnotab(co.co_firstlineno, lines)
        else:
            kwargs["co_linetable"] = LineEntry.make_linetable(co.co_firstlineno, lines)

        consts.append('__slipcover__')  # mark instrumented

        new_code = co.replace(
            co_code=bytes(patch),
            co_stacksize=co.co_stacksize + max_addtl_stack,
            co_consts=tuple(consts),
            **kwargs
        )

        with self.lock:
            self.code_lines[co.co_filename].update(
                        map(lambda line: line[1], dis.findlinestarts(co)))

            self.replace_map[co] = new_code

            if not parent:
                self.instrumented[co.co_filename].add(new_code)

        return new_code


    def deinstrument(self, co, lines: set) -> types.CodeType:
        """De-instruments a code object previously instrumented for coverage detection.

        If invoked on a function, de-instruments its code.
        """

        if isinstance(co, types.FunctionType):
            co.__code__ = self.deinstrument(co.__code__, lines)
            return co.__code__

        assert isinstance(co, types.CodeType)
        # print(f"de-instrumenting {co.co_name}")

        patch = None
        consts = None

        co_code = co.co_code
        co_consts = co.co_consts

        for i in range(len(co_consts)):
            if isinstance(co_consts[i], types.CodeType):
                nc = self.deinstrument(co_consts[i], lines)
                if nc != co_consts[i]:
                    if not consts:
                        consts = list(co_consts)
                    consts[i] = nc

        for (offset, lineno) in dis.findlinestarts(co):
            if lineno in lines and co_code[offset] == op_NOP:
                it = iter(unpack_opargs(co.co_code[offset:]))
                next(it) # NOP
                next(it) # LOAD_CONST tracker_signal_index
                _, _, _, tracker_index = next(it)

                stats_deinstr_tracker = tracker.deinstrument(co_consts[tracker_index])

                if not self.collect_stats:
                    if not patch:
                        patch = bytearray(co_code)
                    patch[offset] = op_JUMP_FORWARD
                elif stats_deinstr_tracker:
                    if not consts:
                        consts = list(co_consts)
                    consts[tracker_index] = stats_deinstr_tracker

        if not patch and not consts:
            return co

        changed = {}
        if patch: changed["co_code"] = bytes(patch)
        if consts: changed["co_consts"] = tuple(consts)

        new_code = co.replace(**changed)

        with self.lock:
            self.replace_map[co] = new_code

            if co in self.instrumented[co.co_filename]:
                self.instrumented[co.co_filename].remove(co)
                self.instrumented[co.co_filename].add(new_code)

        return new_code


    def _update_stats(self, new_lines) -> None:
        # XXX assert self.lock owned
        if self.collect_stats:
            for file, lines in new_lines.items():
                pos_lines = Counter({line:count for line, count in lines.items() if line >= 0})
                neg_lines = Counter({-line:count for line, count in lines.items() if line < 0})

                self.deinstrumented[file] += neg_lines

                self.reported[file].update(pos_lines)
                self.u_misses[file].update({l: pos_lines[l] for l in pos_lines \
                                       if l in self.lines_seen[file]})

                # hide negative lines from normal processing
                new_lines[file] = pos_lines


    def get_coverage(self):
        """Returns coverage information collected."""

        with self.lock:
            # FIXME calling _get_new_lines will prevent de-instrumentation if still running!
            new_lines = self._get_new_lines()
            self._update_stats(new_lines)

            for file, lines in new_lines.items():
                self.lines_seen[file].update(lines)

            simp = PathSimplifier()

            files = dict()
            for f, f_code_lines in self.code_lines.items():
                seen = self.lines_seen[f] if f in self.lines_seen else set()

                f_files = {
                    'executed_lines': sorted(seen),
                    'missing_lines': sorted(f_code_lines - seen)
                }

                if self.collect_stats:
                    # Once a line reports in, it's available for deinstrumentation.
                    # Each time it reports in after that, we consider it a miss (like a cache miss).
                    # We differentiate between (de-instrument) "D misses", where a line
                    # reports in after it _could_ have been de-instrumented and (use) "U misses"
                    # and where a line reports in after it _has_ been de-instrumented, but
                    # didn't use the code object where it's deinstrumented.
                    u_misses = self.u_misses[f]
                    d_misses = self.reported[f] - u_misses
                    d_misses.subtract(self.reported[f].keys())  # 1st time is normal, not a d miss
                    d_misses = +d_misses    # drop any 0 counts
                    all_for_file = self.reported[f] + self.deinstrumented[f]
                    f_files['stats'] = {
                        'd_misses_pct': round(d_misses.total()/all_for_file.total()*100, 1),
                        'u_misses_pct': round(u_misses.total()/all_for_file.total()*100, 1),
                        'top_d_misses': [f"{it[0]}:{it[1]}" for it in d_misses.most_common(5)],
                        'top_u_misses': [f"{it[0]}:{it[1]}" for it in u_misses.most_common(5)],
                        'top_lines': [f"{it[0]}:{it[1]}" for it in all_for_file.most_common(5)]
                    }

                files[simp.simplify(f)] = f_files

            return {'files': files}


    def print_coverage(self, outfile=sys.stdout) -> None:
        cov = self.get_coverage()

        def merge_consecutives(L):
            # Neat little trick due to John La Rooy: the difference between the numbers
            # on a list and a counter is constant for consecutive items :)
            from itertools import groupby, count

            groups = groupby(sorted(L), key=lambda item, c=count(): item - next(c))
            return [
                str(g[0]) if g[0] == g[-1] else f"{g[0]}-{g[-1]}"
                for g in [list(g) for _, g in groups]
            ]

        from tabulate import tabulate

        def table(files):
            for f, f_info in files.items():
                seen = len(f_info['executed_lines'])
                miss = len(f_info['missing_lines'])
                total = seen+miss
                yield [f, total, miss, round(100*seen/total),
                       ', '.join(merge_consecutives(f_info['missing_lines']))]

        print("", file=outfile)
        print(tabulate(table(cov['files']),
              headers=["File", "#lines", "#missed", "Cover%", "Lines missing"]), file=outfile)

        def stats_table(files):
            for f, f_info in files.items():
                stats = f_info['stats']

                yield (f, stats['d_misses_pct'], stats['u_misses_pct'],
                       " ".join(stats['top_d_misses'][:4]),
                       " ".join(stats['top_u_misses'][:4]),
                       " ".join(stats['top_lines'][:4])
                )

        if self.collect_stats:
            print("\n", file=outfile)
            print(tabulate(stats_table(cov['files']),
                           headers=["File", "D miss%", "U miss%", "Top D", "Top U", "Top lines"]),
                  file=outfile)


    @staticmethod
    def find_functions(items, visited : set):
        import inspect

        def find_funcs(root):
            if inspect.isfunction(root):
                if root not in visited:
                    visited.add(root)
                    yield root

            # Prefer isinstance(x,type) over isclass(x) because many many
            # things, such as str(), are classes
            elif isinstance(root, type):
                if root not in visited:
                    visited.add(root)

                    # Don't use inspect.getmembers(root) since that invokes getattr(),
                    # which causes any descriptors to be invoked, which results in either
                    # additional (unintended) coverage and/or errors because __get__ is
                    # invoked in an unexpected way.
                    obj_names = dir(root)
                    for obj_key in obj_names:
                        mro = (root,) # FIXME should be "+ obj.__mro__" to look in all bases, but add tests first
                        for base in mro:
                            if obj_key in base.__dict__:
                                yield from find_funcs(base.__dict__[obj_key])
                                break

        # FIXME this may yield "dictionary changed size during iteration"
        return [f for it in items for f in find_funcs(it)]


    def register_module(self, m):
        self.modules.append(m)


    def deinstrument_seen(self) -> None:
        with self.lock:
            new_lines = self._get_new_lines()
            self._update_stats(new_lines)

            for file, new_set in new_lines.items():
                if self.collect_stats: new_set = set(new_set)    # Counter -> set

                for co in self.instrumented[file]:
                    self.deinstrument(co, new_set)

                self.lines_seen[file].update(new_set)

            # Replace references to code
            if self.replace_map:
                visited = set()

                # XXX the set of function objects could be pre-computed at register_module;
                # also, the same could be done for functions objects in globals()
                for m in self.modules:
                    for f in Slipcover.find_functions(m.__dict__.values(), visited):
                        if f.__code__ in self.replace_map:
                            f.__code__ = self.replace_map[f.__code__]

                globals_seen = []
                for frame in sys._current_frames().values():
                    while frame:
                        if not frame.f_globals in globals_seen:
                            globals_seen.append(frame.f_globals)
                            for f in Slipcover.find_functions(frame.f_globals.values(), visited):
                                if f.__code__ in self.replace_map:
                                    f.__code__ = self.replace_map[f.__code__]

                        for f in Slipcover.find_functions(frame.f_locals.values(), visited):
                            if f.__code__ in self.replace_map:
                                f.__code__ = self.replace_map[f.__code__]

                        frame = frame.f_back

                # all references should have been replaced now... right?
                self.replace_map.clear()
