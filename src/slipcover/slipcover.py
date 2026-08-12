from __future__ import annotations

import ast
import dis
import re
import sys
import threading
import types
from collections import Counter, defaultdict
from typing import Any, TYPE_CHECKING

if sys.version_info < (3,12):
    from . import bytecode as bc
    from . import probe  # type: ignore[attr-defined]

from pathlib import Path

from . import branch as br
from .version import __version__
from .xmlreport import XmlReporter
from .lcovreport import LcovReporter

# FIXME provide __all__

# Default exclude_lines patterns, matching coverage.py's own zero-config
# defaults (coverage/config.py's DEFAULT_EXCLUDE, copied verbatim for the
# two reused here) so the most common idiom, `# pragma: no cover`, works
# without any configuration. coverage.py's third default -- excluding
# stub-like `def foo(): ...` one-liners -- is intentionally not included;
# that's a distinct feature, not what issue #26 asks for.
DEFAULT_EXCLUDE = [
    r"#\s*(pragma|PRAGMA)[:\s]?\s*(no|NO)\s*(cover|COVER)",
    r"if (typing\.)?TYPE_CHECKING:",
]

# Counter.total() is new in 3.10
if sys.version_info < (3,10):
    def counter_total(self: Counter) -> int:
        return sum([self[n] for n in self])
    setattr(Counter, 'total', counter_total)


# Python 3.13 returns 'None' lines;
# Python 3.11+ generates a line just for RESUME or RETURN_GENERATOR, POP_TOP, RESUME;
# Python 3.11 generates a 0th line
if sys.version_info >= (3,11):
    _op_RESUME = dis.opmap["RESUME"]
    _op_RETURN_GENERATOR = dis.opmap["RETURN_GENERATOR"]

    def findlinestarts(co: types.CodeType):
        for off, line in dis.findlinestarts(co):
            if line and co.co_code[off] not in (_op_RESUME, _op_RETURN_GENERATOR):
                yield off, line

else:
    findlinestarts = dis.findlinestarts


# Opcodes used only for loading type annotations (for function parameter/return annotations)
# Lines that ONLY contain these ops are annotation-only lines and should be excluded from coverage
_ANNOTATION_ONLY_OPS = frozenset({'LOAD_NAME', 'LOAD_GLOBAL', 'LOAD_ATTR', 'BINARY_SUBSCR'})


def _get_annotation_only_lines(co: types.CodeType) -> frozenset:
    """Find lines that only contain annotation-loading bytecode.

    In Python < 3.14, function annotations are evaluated eagerly and their bytecode
    appears in the module code. Lines that ONLY load types (e.g., continuation lines
    of multi-line function signatures) should be excluded from coverage since they're
    just metadata, not actual program logic.

    In Python 3.14+, annotations are deferred (PEP 649), so this returns empty.
    """
    if sys.version_info >= (3, 14):
        return frozenset()

    # Collect opcodes per line
    ops_by_line: dict = {}
    current_line = None
    for instr in dis.get_instructions(co):
        # Python 3.11+ has instr.positions.lineno for every instruction
        # Python < 3.11 has instr.starts_line only for first instruction on each line
        if sys.version_info >= (3, 11):
            if instr.positions and instr.positions.lineno:
                line = instr.positions.lineno
            else:
                continue
        else:
            if instr.starts_line is not None:
                current_line = instr.starts_line
            line = current_line
            if line is None:
                continue

        if line not in ops_by_line:
            ops_by_line[line] = set()
        ops_by_line[line].add(instr.opname)

    # Find lines where ALL ops are annotation-only ops
    annotation_lines = set()
    for line, ops in ops_by_line.items():
        if ops and ops.issubset(_ANNOTATION_ONLY_OPS):
            annotation_lines.add(line)

    return frozenset(annotation_lines)

if TYPE_CHECKING:
    from typing import Dict, Iterable, Iterator, List, Optional, Tuple

    from .schemas import Coverage

class SlipcoverError(Exception):
    pass


class PathSimplifier:
    def __init__(self):
        self.cwd = Path.cwd()

    def simplify(self, path : str) -> str:
        f = Path(path)
        try:
            return str(f.relative_to(self.cwd))
        except ValueError:
            return path 


def format_missing(missing_lines: List[int], executed_lines: List[int],
                   missing_branches: List[tuple]) -> str:
    """Formats ranges of missing lines, including non-code (e.g., comments) ones that fall
       between missed ones"""

    missing_set = set(missing_lines)
    missing_branches = [(a,b) for a,b in missing_branches if a not in missing_set and b not in missing_set]

    def format_branch(br):
        return f"{br[0]}->exit" if br[1] == 0 else f"{br[0]}->{br[1]}"

    def find_ranges():
        executed = set(executed_lines)
        it = iter(missing_lines)    # assumed sorted
        a = next(it, None)
        while a is not None:
            while missing_branches and missing_branches[0][0] < a:
                yield format_branch(missing_branches.pop(0))

            b = a
            n = next(it, None)
            while n is not None:
                if any(l in executed for l in range(b+1, n+1)):
                    break

                b = n
                n = next(it, None)

            yield str(a) if a == b else f"{a}-{b}"

            a = n

        while missing_branches:
            yield format_branch(missing_branches.pop(0))

    return ", ".join(find_ranges())

def print_xml(
    coverage: Coverage,
    source_paths: Iterable[str],
    *,
    with_branches: bool = False,
    xml_package_depth: int = 99,
    outfile=sys.stdout
) -> None:
    XmlReporter(
        coverage=coverage,
        source=source_paths,
        with_branches=with_branches,
        xml_package_depth=xml_package_depth,
    ).report(outfile=outfile)


def print_lcov(
    coverage: Coverage,
    *,
    with_branches: bool = False,
    test_name: Optional[str] = None,
    comments: Optional[List[str]] = None,
    outfile=sys.stdout
) -> None:
    LcovReporter(
        coverage=coverage,
        with_branches=with_branches,
        test_name=test_name,
        comments=comments,
    ).report(outfile=outfile)


def print_coverage(coverage, *, outfile=sys.stdout, missing_width=None, skip_covered=False) -> None:
    """Prints coverage information for human consumption."""
    from tabulate import tabulate

    if not coverage.get('files', None): # includes empty coverage['files']
        return

    branch_coverage = coverage.get('meta', {}).get('branch_coverage', False)

    def table():
        for f, f_info in sorted(coverage['files'].items()):
            exec_l = len(f_info['executed_lines'])
            miss_l = len(f_info['missing_lines'])

            extra_b = []
            if branch_coverage:
                exec_b = len(f_info['executed_branches'])
                miss_b = len(f_info['missing_branches'])
                pct_b = 100*exec_b/(exec_b+miss_b) if (exec_b+miss_b) else 0
                extra_b = [exec_b+miss_b, miss_b, round(pct_b)]

            pct = f_info['summary']['percent_covered']

            if skip_covered and pct == 100.0:
                continue

            yield [f, exec_l+miss_l, miss_l, *extra_b,
                   round(pct),
                   format_missing(f_info['missing_lines'], f_info['executed_lines'],
                                  f_info['missing_branches'] if 'missing_branches' in f_info else [])]

        if len(coverage['files']) > 1:
            yield ['---'] + [''] * (6 if branch_coverage else 4)

            s = coverage['summary']

            extra_b = []
            if branch_coverage:
                exec_b = s['covered_branches']
                miss_b = s['missing_branches']
                pct_b = 100*exec_b/(exec_b+miss_b) if (exec_b+miss_b) else 0
                extra_b = [exec_b+miss_b, miss_b, round(pct_b)]

            yield ['(summary)', s['covered_lines']+s['missing_lines'], s['missing_lines'], *extra_b,
                   round(s['percent_covered']), '']



    print("", file=outfile)
    headers = ["File", "#lines", "#l.miss",
               *(["#br.", "#br.miss", "brCov%", "totCov%"] if branch_coverage else ["Cover%"]),
               "Missing"]
    maxcolwidths = [None] * (len(headers)-1) + [missing_width]
    print(tabulate(table(), headers=headers, maxcolwidths=maxcolwidths), file=outfile)


def add_summaries(cov: dict) -> None:
    """Adds (or updates) 'summary' entries in coverage information."""
    # global summary
    g_summary : dict[str, Any] = defaultdict(int)
    g_nom = g_den = 0

    if 'files' in cov:
        for f_cov in cov['files'].values():
            summary : dict = { # per-file summary
                'covered_lines': len(f_cov['executed_lines']),
                'missing_lines': len(f_cov['missing_lines']),
            }

            nom = summary['covered_lines']
            den = nom + summary['missing_lines']

            if 'executed_branches' in f_cov:
                summary.update({
                    'covered_branches': len(f_cov['executed_branches']),
                    'missing_branches': len(f_cov['missing_branches'])
                })

                nom += summary['covered_branches']
                den += summary['covered_branches'] + summary['missing_branches']

            summary['percent_covered'] = 100.0 if den == 0 else 100*nom/den
            f_cov['summary'] = summary

            for k in summary:
                g_summary[k] += summary[k]
            g_nom += nom
            g_den += den

    g_summary['percent_covered'] = 100.0 if g_den == 0 else 100*g_nom/g_den
    g_summary['percent_covered_display'] = str(int(round(g_summary['percent_covered'], 0)))
    cov['summary'] = g_summary


def _canonical_path(p: str) -> str:
    """Resolve a path key to a canonical form for cross-step equivalence.

    The same physical file can be recorded under different path spellings
    across steps of a workload — most commonly a cwd-relative form when one
    step runs a script directly and an absolute editable-install form when
    another step imports it as a package. Without canonicalization the merge
    treats them as separate files and the headline percentage is halved.
    """
    try:
        return str(Path(p).resolve())
    except OSError:
        return p


def merge_coverage(a: dict, b: dict) -> dict:
    """Merges coverage result 'b' into 'a'.

    File entries are grouped by canonical path so that aliases of the same
    physical file (relative vs absolute, symlinked, etc.) collapse into a
    single merged entry. The shortest original spelling is used as the
    display key for each group.
    """

    if a.get('meta', {}).get('software', None) != 'slipcover':
        raise SlipcoverError('Cannot merge coverage: only SlipCover format supported.')

    if a.get('meta', {}).get('show_contexts', False) or \
       b.get('meta', {}).get('show_contexts', False):
        raise SlipcoverError('Merging coverage with show_contexts=True unsupported')

    branch_coverage = a.get('meta', {}).get('branch_coverage', False)
    if branch_coverage and not b.get('meta', {}).get('branch_coverage', False):
        raise SlipcoverError('Cannot merge coverage: branch coverage missing')

    a_files = a['files']
    b_files = b['files']

    # Group aliases by canonical path.
    groups: dict = defaultdict(lambda: {'a': [], 'b': []})
    for k in a_files:
        groups[_canonical_path(k)]['a'].append(k)
    for k in b_files:
        groups[_canonical_path(k)]['b'].append(k)

    new_files: dict = {}
    for aliases in groups.values():
        executed_lines: set = set()
        missing_lines: set = set()
        executed_branches: set = set()
        missing_branches: set = set()

        for k in aliases['a']:
            entry = a_files[k]
            executed_lines.update(entry.get('executed_lines', ()))
            missing_lines.update(entry.get('missing_lines', ()))
            if branch_coverage:
                executed_branches.update(tuple(br) for br in entry.get('executed_branches', ()))
                missing_branches.update(tuple(br) for br in entry.get('missing_branches', ()))
        for k in aliases['b']:
            entry = b_files[k]
            executed_lines.update(entry.get('executed_lines', ()))
            missing_lines.update(entry.get('missing_lines', ()))
            if branch_coverage:
                executed_branches.update(tuple(br) for br in entry.get('executed_branches', ()))
                missing_branches.update(tuple(br) for br in entry.get('missing_branches', ()))

        missing_lines -= executed_lines
        missing_branches -= executed_branches

        # Prefer the shortest original spelling as the display key (typically
        # the cwd-relative form when both relative and absolute are present).
        display = min(aliases['a'] + aliases['b'], key=lambda s: (len(s), s))

        update: dict = {
            'executed_lines': sorted(executed_lines),
            'missing_lines': sorted(missing_lines),
        }
        if branch_coverage:
            update['executed_branches'] = sorted(list(br) for br in executed_branches)
            update['missing_branches'] = sorted(list(br) for br in missing_branches)
        new_files[display] = update

    a_files.clear()
    a_files.update(new_files)

    add_summaries(a)
    return a


class Slipcover:
    def __init__(self, immediate: bool = False,
                 d_miss_threshold: int = 50, branch: bool = False,
                 disassemble: bool = False, source: Optional[List[str]] = None,
                 omit: Optional[List[str]] = None,
                 exclude_lines: Optional[List[str]] = None,
                 exclude_also: Optional[List[str]] = None):
        self.immediate = immediate
        self.d_miss_threshold = d_miss_threshold
        self.branch = branch
        self.disassemble = disassemble
        self.source = source
        self.omit = omit
        # Matching coverage.py's exclude_lines: user-supplied patterns
        # replace DEFAULT_EXCLUDE, they don't add to it. None (not given at
        # all) means "use the defaults"; an explicit [] disables exclusion
        # entirely, including the defaults -- the natural way to express
        # "no exclusion" via [tool.slipcover] exclude-lines = [] in config.
        # exclude_also, matching coverage.py's own separate setting, is
        # always additive to whatever that resolves to.
        base = DEFAULT_EXCLUDE if exclude_lines is None else exclude_lines
        self._exclude_patterns = [re.compile(p) for p in list(base) + list(exclude_also or [])]

        # mutex protecting this state
        self.lock = threading.RLock()

        # notes which code lines have been instrumented
        self.code_lines: Dict[str, set] = defaultdict(set)
        self.code_branches: Dict[str, set] = defaultdict(set)

        # notes which lines and branches have been seen.
        self.all_seen: Dict[str, set] = defaultdict(set)

        # notes lines/branches seen since last de-instrumentation
        self._get_newly_seen()

        if sys.version_info >= (3,12):
            def handle_line(code, line):
                if br.is_branch(line):
                    self.newly_seen[code.co_filename].add(br.decode_branch(line))
                elif line:
                    self.newly_seen[code.co_filename].add(line)
                return sys.monitoring.DISABLE

            if sys.monitoring.get_tool(sys.monitoring.COVERAGE_ID) != "SlipCover":
                sys.monitoring.use_tool_id(sys.monitoring.COVERAGE_ID, "SlipCover") # FIXME add free_tool_id

            sys.monitoring.register_callback(sys.monitoring.COVERAGE_ID,
                                             sys.monitoring.events.LINE, handle_line)
        else:
            # maps to guide CodeType replacements
            self.replace_map: Dict[types.CodeType, types.CodeType] = dict()
            self.instrumented: Dict[str, set] = defaultdict(set)

            # provides an index (line_or_branch -> offset) for each code object
            self.code2index: Dict[types.CodeType, list] = dict()

        self.modules : list = []

    def _get_newly_seen(self):
        """Returns the current set of ``new'' lines, leaving a new container in place."""

        # We trust that assigning to self.newly_seen is atomic, as it is triggered
        # by a STORE_NAME or similar opcode and Python synchronizes those.  We rely on
        # C extensions' atomicity for updates within self.newly_seen.  The lock here
        # is just to protect callers of this method (so that the exchange is atomic).

        with self.lock:
            newly_seen = self.newly_seen if hasattr(self, "newly_seen") else defaultdict(set)
            self.newly_seen: Dict[str, set] = defaultdict(set)

        return newly_seen


    if sys.version_info >= (3,12):
        @staticmethod
        def lines_from_code(co: types.CodeType) -> Iterator[int]:
            for c in co.co_consts:
                if isinstance(c, types.CodeType):
                    # Skip __annotate__ functions (PEP 649, Python 3.14+) - they're only
                    # called when annotations are explicitly accessed, not during normal execution
                    if c.co_name == '__annotate__':
                        continue
                    yield from Slipcover.lines_from_code(c)

            # Exclude annotation-only lines (Python < 3.14 evaluates annotations eagerly)
            annotation_only = _get_annotation_only_lines(co)
            yield from (line for _, line in findlinestarts(co)
                        if not br.is_branch(line) and line not in annotation_only)


        @staticmethod
        def branches_from_code(co: types.CodeType) -> Iterator[Tuple[int, int]]:
            for c in co.co_consts:
                if isinstance(c, types.CodeType):
                    # Skip __annotate__ functions (PEP 649, Python 3.14+)
                    if c.co_name == '__annotate__':
                        continue
                    yield from Slipcover.branches_from_code(c)

            yield from (br.decode_branch(line) for _, line in findlinestarts(co) if br.is_branch(line))

    else:
        @staticmethod
        def lines_from_code(co: types.CodeType) -> Iterator[int]:
            for c in co.co_consts:
                if isinstance(c, types.CodeType):
                    yield from Slipcover.lines_from_code(c)

            # Python 3.11 generates a 0th line; 3.11+ generates a line just for RESUME
            # Exclude annotation-only lines (Python < 3.14 evaluates annotations eagerly)
            annotation_only = _get_annotation_only_lines(co)
            yield from (line for _, line in findlinestarts(co) if line not in annotation_only)


        @staticmethod
        def branches_from_code(co: types.CodeType) -> Iterator[Tuple[int, int]]:
            for c in co.co_consts:
                if isinstance(c, types.CodeType):
                    yield from Slipcover.branches_from_code(c)

            ed = bc.Editor(co)
            for _, _, br_index in ed.find_const_assignments(br.BRANCH_NAME):
                yield co.co_consts[br_index]


    if sys.version_info >= (3,12):
        def instrument(self, co: types.CodeType, parent: Optional[types.CodeType] = None) -> types.CodeType:
            """Instruments a code object for coverage detection.

            If invoked on a function, instruments its code.
            """

            if isinstance(co, types.FunctionType):
                co = co.__code__

            assert isinstance(co, types.CodeType)
            # print(f"instrumenting {co.co_name}")

            sys.monitoring.set_local_events(sys.monitoring.COVERAGE_ID, co, sys.monitoring.events.LINE)

            # handle functions-within-functions
            for c in co.co_consts:
                if isinstance(c, types.CodeType):
                    # Skip __annotate__ functions (PEP 649, Python 3.14+)
                    if c.co_name == '__annotate__':
                        continue
                    self.instrument(c, co)

            if not parent:
                with self.lock:
                    self.code_lines[co.co_filename].update(Slipcover.lines_from_code(co))
                    self.code_branches[co.co_filename].update(Slipcover.branches_from_code(co))

            return co

    else:
        def instrument(self, co: types.CodeType, parent: Optional[types.CodeType] = None) -> types.CodeType:
            """Instruments a code object for coverage detection.

            If invoked on a function, instruments its code.
            """

            if isinstance(co, types.FunctionType):
                co.__code__ = self.instrument(co.__code__)
                return co.__code__

            assert isinstance(co, types.CodeType)
            # print(f"instrumenting {co.co_name}")

            ed = bc.Editor(co)

            # handle functions-within-functions
            for i, c in enumerate(co.co_consts):
                if isinstance(c, types.CodeType):
                    ed.set_const(i, self.instrument(c, co))

            probe_signal_index = ed.add_const(probe.signal)

            off_list = list(findlinestarts(co))
            if self.branch:
                off_list.extend(list(ed.find_const_assignments(br.BRANCH_NAME)))
                # sort line probes (2-tuples) before branch probes (3-tuples) because
                # line probes don't overwrite bytecode like branch probes do, so if there
                # are two being inserted at the same offset, the accumulated offset 'delta' applies
                off_list.sort(key = lambda x: (x[0], len(x)))

            insert_labels = []
            probes = []

            delta = 0
            for off_item in off_list:
                if len(off_item) == 2: # from findlinestarts
                    offset, lineno = off_item

                    # Can't insert between an EXTENDED_ARG and the final opcode
                    if (offset >= 2 and co.co_code[offset-2] == bc.op_EXTENDED_ARG):
                        while (offset < len(co.co_code) and co.co_code[offset-2] == bc.op_EXTENDED_ARG):
                            offset += 2 # TODO will we overtake the next offset from findlinestarts?

                    insert_labels.append(lineno)

                    tr = probe.new(self, co.co_filename, lineno, self.d_miss_threshold)
                    probes.append(tr)
                    tr_index = ed.add_const(tr)

                    delta += ed.insert_function_call(offset+delta, probe_signal_index, (tr_index,))

                else: # from find_const_assignments
                    begin_off, end_off, branch_index = off_item
                    branch = co.co_consts[branch_index]

                    insert_labels.append(branch)

                    tr = probe.new(self, co.co_filename, branch, self.d_miss_threshold)
                    probes.append(tr)
                    ed.set_const(branch_index, tr)

                    delta += ed.insert_function_call(begin_off+delta, probe_signal_index, (branch_index,),
                                                     repl_length = end_off-begin_off)

            ed.add_const('__slipcover__')  # mark instrumented
            new_code = ed.finish()

            if self.disassemble:
                print()
                print(f'---- {co.co_name} before ----')
                dis.dis(co)
                print(f'---- {co.co_name} after ----')
                dis.dis(new_code)

            if self.immediate:
                for tr, off in zip(probes, ed.get_inserts()):
                    probe.set_immediate(tr, new_code.co_code, off)
            else:
                index = list(zip(ed.get_inserts(), insert_labels))

            with self.lock:
                if not parent:
                    self.code_lines[co.co_filename].update(Slipcover.lines_from_code(co))
                    self.code_branches[co.co_filename].update(Slipcover.branches_from_code(co))

                    self.instrumented[co.co_filename].add(new_code)

                if not self.immediate:
                    self.code2index[new_code] = index

            return new_code


    if sys.version_info < (3,12):
        def deinstrument(self, co, lines: set) -> types.CodeType:
            """De-instruments a code object previously instrumented for coverage detection.

            If invoked on a function, de-instruments its code.
            """

            assert not self.immediate

            if isinstance(co, types.FunctionType):
                co.__code__ = self.deinstrument(co.__code__, lines)
                return co.__code__

            assert isinstance(co, types.CodeType)
            # print(f"de-instrumenting {co.co_name}")

            ed = bc.Editor(co)

            co_consts = co.co_consts
            for i, c in enumerate(co_consts):
                if isinstance(c, types.CodeType):
                    nc = self.deinstrument(c, lines)
                    if nc is not c:
                        ed.set_const(i, nc)

            index = self.code2index[co]

            for (offset, lineno) in index:
                if lineno in lines and (func := ed.get_inserted_function(offset)):
                    func_index, func_arg_index, *_ = func
                    if co_consts[func_index] == probe.signal:
                        probe.mark_removed(co_consts[func_arg_index])
                        ed.disable_inserted_function(offset)

            new_code = ed.finish()
            if new_code is co:
                return co

            # no offsets changed, so the old code's index is still usable
            self.code2index[new_code] = index

            with self.lock:
                self.replace_map[co] = new_code

                if co in self.instrumented[co.co_filename]:
                    self.instrumented[co.co_filename].remove(co)
                    self.instrumented[co.co_filename].add(new_code)

            return new_code


    def _add_unseen_source_files(self, source: List[str]):
        import ast
        from fnmatch import fnmatch

        # Prepare omit patterns (same logic as FileMatcher._resolve_omit)
        omit_patterns = []
        if self.omit:
            cwd = Path.cwd().resolve()
            for o in self.omit:
                if o.startswith('*'):
                    omit_patterns.append(o)
                else:
                    omit_patterns.append(str(cwd / o))

        def is_omitted(filepath: Path) -> bool:
            if not omit_patterns:
                return False
            filepath_str = str(filepath)
            return any(fnmatch(filepath_str, p) for p in omit_patterns)

        dirs = [Path(d).resolve() for d in source]

        while dirs:
            p = dirs.pop()
            for file in p.iterdir():
                if file.is_dir():
                    dirs.append(file)   # walk this directory, too

                elif file.is_file() and file.suffix.lower() == '.py':
                    file = file.absolute()
                    if is_omitted(file):
                        continue
                    filename = str(file)
                    try:
                        if filename not in self.code_lines:
                            t = ast.parse(file.read_text())
                            if self.branch:
                                t = br.preinstrument(t)
                            code = compile(t, filename, "exec")
                            self.code_lines[filename] = set(Slipcover.lines_from_code(code))
                            if self.branch:
                                self.code_branches[filename] = set(Slipcover.branches_from_code(code))

                    except Exception as e: # for SyntaxError and such... FIXME curate list and catch only those
                        print(f"Warning: unable to include {filename}: {e}")


    # Statement types whose primary clause (`body`) must be bounded
    # separately from a trailing elif/else/except/finally clause: ast.If/
    # For/While/Try's own end_lineno reaches through ALL of those, so using
    # it directly for the "if"/"for"/"while"/"try" line's own span would
    # incorrectly sweep a sibling clause the pattern never matched. `elif`
    # needs no special handling: it's just a nested If inside orelse,
    # walked (and correctly bounded) like any other If. Built via getattr
    # since TryStar (3.11+) doesn't exist on every Python version
    # slipcover supports.
    _MULTI_CLAUSE_TYPES = tuple(t for t in (
        ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, getattr(ast, 'TryStar', None),
    ) if t is not None)

    def _compute_excluded_lines(self, source: str) -> set:
        """Computes the set of 1-based line numbers excluded by self._exclude_patterns.

        A match on a block's own header line excludes the whole block; a
        match on a decorator, or the decorated def/class line itself,
        excludes from the *first* decorator onward (matching coverage.py:
        verified against coverage/parser.py, which computes
        first_line = min(d.lineno for d in decorator_list) regardless of
        which decorator actually matched, and confirmed by running
        coverage.py against this exact scenario); any other match excludes
        just that line/statement.

        Each candidate gets a (full_start, full_end, trigger_start,
        trigger_end): a match anywhere in [trigger_start, trigger_end]
        excludes the whole [full_start, full_end]. For a plain statement
        these coincide -- a match anywhere in a multi-line statement
        excludes that whole statement. For a block/decorator/clause header,
        the trigger is bounded to just the header (not the body), matching
        coverage.py's own check (which only looks through the header's
        closing colon, never into the body) -- so a match buried inside a
        block's body is never mistakenly attributed to the enclosing block;
        only its own, smaller, more specific statement claims it. Spans are
        tried smallest-full-range first, so the most specific match always
        wins.

        A bare `else:`/`finally:` line has no dedicated AST node of its own
        to anchor on (`elif` doesn't need special handling: it's just a
        nested If, with its own real `lineno`). But the *gap* between where
        the preceding clause's body ends and the next clause's body begins
        -- both real AST positions -- can only ever contain that keyword
        itself, plus blank lines or comments, so it's used directly as the
        trigger region with no need to locate the keyword's exact line via
        source-text scanning. A match with no statement of its own and no
        such gap to claim it (e.g. a standalone comment) excludes just that
        single physical line, never whatever larger span happens to
        numerically contain it.
        """
        lines = source.splitlines()
        matched = {
            i + 1 for i, text in enumerate(lines)
            if any(p.search(text) for p in self._exclude_patterns)
        }
        if not matched:
            return set()

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return matched  # best-effort: at least exclude the matched lines themselves

        def _end(n) -> int:
            # end_lineno is Optional per the ast stubs, but always set for
            # any node coming from a real ast.parse() of source text (as
            # opposed to a synthetically-constructed node with no position
            # info) -- lineno is a reasonable, always-safe fallback.
            return n.end_lineno or n.lineno

        spans = []  # (full_start, full_end, trigger_start, trigger_end)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                first = node.decorator_list[0].lineno if node.decorator_list else node.lineno
                spans.append((first, _end(node), first, node.lineno))
                continue  # handled fully here -- skip the generic stmt case below

            if isinstance(node, ast.ExceptHandler):
                spans.append((node.lineno, _end(node), node.lineno, node.body[0].lineno - 1))

            elif hasattr(ast, 'Match') and isinstance(node, ast.Match):
                for case in node.cases:
                    spans.append((case.pattern.lineno, _end(case.body[-1]),
                                  case.pattern.lineno, case.body[0].lineno - 1))

            orelse = getattr(node, 'orelse', None)
            if isinstance(node, Slipcover._MULTI_CLAUSE_TYPES) and orelse:
                clause_body = getattr(node, 'body')
                gap_start = _end(clause_body[-1]) + 1
                gap_end = orelse[0].lineno - 1
                if gap_start <= gap_end:
                    spans.append((gap_start, _end(orelse[-1]), gap_start, gap_end))

            finalbody = getattr(node, 'finalbody', None)
            if finalbody:
                handlers = getattr(node, 'handlers', None)
                prev_end = (_end(orelse[-1]) if orelse
                            else _end(handlers[-1]) if handlers
                            else _end(getattr(node, 'body')[-1]))
                gap_start = prev_end + 1
                gap_end = finalbody[0].lineno - 1
                if gap_start <= gap_end:
                    spans.append((gap_start, _end(finalbody[-1]), gap_start, gap_end))

            if isinstance(node, ast.stmt):
                body = getattr(node, 'body', None)
                if body:
                    header_end = max(body[0].lineno - 1, node.lineno)
                    if isinstance(node, Slipcover._MULTI_CLAUSE_TYPES):
                        full_end = _end(body[-1])
                    else:
                        full_end = _end(node)
                    spans.append((node.lineno, full_end, node.lineno, header_end))
                else:
                    end = _end(node)
                    spans.append((node.lineno, end, node.lineno, end))

        # Smallest full-range first, so a matched line is always attributed
        # to its most specific enclosing construct.
        spans.sort(key=lambda s: s[1] - s[0])

        excluded: set = set()
        claimed: set = set()
        for full_start, full_end, trig_start, trig_end in spans:
            trigger_lines = set(range(trig_start, trig_end + 1))
            if (matched & trigger_lines) - claimed:
                span_lines = set(range(full_start, full_end + 1))
                excluded.update(span_lines)
                claimed.update(matched & span_lines)

        # any matched line nothing above accounts for (e.g. a standalone
        # comment line) is still excluded on its own.
        excluded.update(matched - claimed)
        return excluded

    def _filter_excluded_lines(self, files: dict) -> None:
        """Removes excluded lines, and any branch tuple originating from one,
        from the coverage data -- a decision point on an excluded line
        shouldn't leave stray executed/missing branch entries behind even
        though the line itself is gone."""
        source_cache: Dict[str, str] = {}

        for fname, fdata in files.items():
            if fname not in source_cache:
                path = Path(fname)
                if not path.is_absolute():
                    path = Path.cwd() / path
                try:
                    source_cache[fname] = path.read_text()
                except OSError:
                    source_cache[fname] = ""

            source = source_cache[fname]
            if not source:
                continue

            excluded = self._compute_excluded_lines(source)
            if not excluded:
                continue

            fdata['executed_lines'] = [l for l in fdata['executed_lines'] if l not in excluded]
            fdata['missing_lines'] = [l for l in fdata['missing_lines'] if l not in excluded]

            if 'executed_branches' in fdata:
                fdata['executed_branches'] = [b for b in fdata['executed_branches'] if b[0] not in excluded]
            if 'missing_branches' in fdata:
                fdata['missing_branches'] = [b for b in fdata['missing_branches'] if b[0] not in excluded]


    @staticmethod
    def _make_meta(branch_coverage: bool) -> dict:
        import datetime

        return {
            'software': 'slipcover',
            'version': __version__,
            'timestamp': datetime.datetime.now().isoformat(),
            'branch_coverage': branch_coverage,
            'show_contexts': False
        }


    def signal_child_process(self):
        self.source = None  # only the parent process needs to run _add_unseen_source_files
        with self.lock:
            self._get_newly_seen()
            self.all_seen.clear()


    def get_coverage(self):
        """Returns coverage information collected."""

        with self.lock:
            # FIXME calling _get_newly_seen will prevent de-instrumentation if still running!
            newly_seen = self._get_newly_seen()

            for file, lines in newly_seen.items():
                self.all_seen[file].update(lines)

            if self.source:
                self._add_unseen_source_files(self.source)

            simp = PathSimplifier()

            files = dict()
            for f, f_code_lines in self.code_lines.items():
                if f in self.all_seen:
                    branches_seen = {x for x in self.all_seen[f] if isinstance(x, tuple)}
                    # Only count lines that are in code_lines (excludes annotation-only lines)
                    lines_seen = (self.all_seen[f] - branches_seen) & f_code_lines
                else:
                    lines_seen = branches_seen = set()

                f_files = {
                    'executed_lines': sorted(lines_seen),
                    'missing_lines': sorted(f_code_lines - lines_seen),
                }

                if self.branch:
                    f_files['executed_branches'] = sorted(branches_seen)
                    f_files['missing_branches'] = sorted(self.code_branches[f] - branches_seen)

                files[simp.simplify(f)] = f_files

            self._filter_excluded_lines(files)

            cov = {
                'meta': Slipcover._make_meta(self.branch),
                'files': files
            }

            add_summaries(cov)
            return cov


    # @deprecated
    def print_coverage(self, outfile=sys.stdout, *, missing_width=None) -> None:
        """Prints the coveage collected by this Slipcover."""
        print_coverage(self.get_coverage(), outfile=outfile, missing_width=missing_width)


    @staticmethod
    def find_functions(items, visited : set):
        # Don't use isinstance() or inspect.isfunction, as isinstance as may call __class__,
        # which may have side effects (e.g., using Celery https://github.com/celery/celery).
        def is_patchable_function(func):
            # PyPy has no "builtin functions" like CPython. instead, it uses
            # regular functions, with a special type of code object.
            # the second condition is always True on CPython
            return issubclass(type(func), types.FunctionType) and type(func.__code__) is types.CodeType

        def find_funcs(root):
            if is_patchable_function(root):
                if root not in visited:
                    visited.add(root)
                    yield root

            # Prefer isinstance(x,type) over isclass(x) because many many
            # things, such as str(), are classes
            elif issubclass(type(root), type):
                if root not in visited:
                    visited.add(root)

                    # Don't use inspect.getmembers(root) since that invokes getattr(),
                    # which causes any descriptors to be invoked, which results in either
                    # additional (unintended) coverage and/or errors because __get__ is
                    # invoked in an unexpected way.
                    obj_names = dir(root)
                    for obj_key in obj_names:
                        mro = (root,) + root.__mro__
                        for base in mro:
                            if (base == root or base not in visited) and obj_key in base.__dict__:
                                yield from find_funcs(base.__dict__[obj_key])
                                break

            elif (issubclass(type(root), classmethod) or issubclass(type(root), staticmethod)) and \
                 is_patchable_function(root.__func__):
                if root.__func__ not in visited:
                    visited.add(root.__func__)
                    yield root.__func__

        # FIXME this may yield "dictionary changed size during iteration"
        return [f for it in items for f in find_funcs(it)]


    def register_module(self, m):
        self.modules.append(m)


    if sys.version_info < (3,12):
        def deinstrument_seen(self) -> None:
            with self.lock:
                newly_seen = self._get_newly_seen()

                for file, new_set in newly_seen.items():
                    for co in self.instrumented[file]:
                        self.deinstrument(co, new_set)

                    self.all_seen[file].update(new_set)

                # Replace references to code
                if self.replace_map:
                    visited : set = set()

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

                            frame = frame.f_back # type: ignore[assignment]

                    # all references should have been replaced now... right?
                    self.replace_map.clear()
