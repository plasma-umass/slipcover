"""Agent-oriented coverage tracking for AI coding agents.

This module extends slipcover with recency-aware coverage tracking designed
to help AI coding agents identify relevant code areas. It provides:

- Hit counts and timestamps for each line/branch
- Execution sequence tracking for debugging
- Git integration for change tracking
- Code structure extraction (classes, functions, methods)
- Session history for trend analysis
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union


@dataclass
class LineMetrics:
    """Metrics tracked for each covered line or branch.

    Attributes:
        hit_count: Number of times this line was executed
        first_hit: Unix timestamp of first execution
        last_hit: Unix timestamp of most recent execution
        last_sequence: Sequence number of most recent execution (for recency)
    """
    hit_count: int = 0
    first_hit: Optional[float] = None
    last_hit: Optional[float] = None
    last_sequence: int = 0

    def record_hit(self, sequence: int, timestamp: Optional[float] = None) -> None:
        """Record a hit on this line/branch.

        Args:
            sequence: The global execution sequence number
            timestamp: Optional timestamp (defaults to current time if tracking enabled)
        """
        self.hit_count += 1
        self.last_sequence = sequence
        if timestamp is not None:
            if self.first_hit is None:
                self.first_hit = timestamp
            self.last_hit = timestamp


@dataclass
class BranchMetrics:
    """Metrics for a branch (from_line -> to_line).

    Same as LineMetrics but for branches.
    """
    hit_count: int = 0
    first_hit: Optional[float] = None
    last_hit: Optional[float] = None
    last_sequence: int = 0

    def record_hit(self, sequence: int, timestamp: Optional[float] = None) -> None:
        """Record a hit on this branch."""
        self.hit_count += 1
        self.last_sequence = sequence
        if timestamp is not None:
            if self.first_hit is None:
                self.first_hit = timestamp
            self.last_hit = timestamp


@dataclass
class FileMetrics:
    """All metrics for a single file.

    Tracks both line and branch coverage with detailed metrics.
    """
    # Line number -> metrics
    lines: Dict[int, LineMetrics] = field(default_factory=dict)
    # (from_line, to_line) -> metrics
    branches: Dict[Tuple[int, int], BranchMetrics] = field(default_factory=dict)

    def get_or_create_line(self, line: int) -> LineMetrics:
        """Get or create metrics for a line."""
        if line not in self.lines:
            self.lines[line] = LineMetrics()
        return self.lines[line]

    def get_or_create_branch(self, branch: Tuple[int, int]) -> BranchMetrics:
        """Get or create metrics for a branch."""
        if branch not in self.branches:
            self.branches[branch] = BranchMetrics()
        return self.branches[branch]


@dataclass
class FunctionInfo:
    """Information about a function or method."""
    name: str
    start_line: int
    end_line: int
    is_method: bool = False
    class_name: Optional[str] = None
    # Computed from coverage
    total_lines: int = 0
    covered_lines: int = 0
    hit_count: int = 0  # Sum of all line hits


@dataclass
class ClassInfo:
    """Information about a class."""
    name: str
    start_line: int
    end_line: int
    methods: Dict[str, FunctionInfo] = field(default_factory=dict)
    # Computed from coverage
    total_lines: int = 0
    covered_lines: int = 0


@dataclass
class CodeStructure:
    """Structure of a Python file extracted from AST.

    Contains class and function definitions with their line ranges.
    """
    filename: str
    classes: Dict[str, ClassInfo] = field(default_factory=dict)
    functions: Dict[str, FunctionInfo] = field(default_factory=dict)  # Top-level functions
    total_lines: int = 0


class SequenceCounter:
    """Thread-safe sequence counter for tracking execution order.

    Uses itertools.count() which is thread-safe in CPython.
    """

    def __init__(self):
        self._generator = itertools.count(1)
        self._lock = threading.Lock()
        self._current = 0

    def next(self) -> int:
        """Get the next sequence number (thread-safe)."""
        seq = next(self._generator)
        with self._lock:
            self._current = seq
        return seq

    @property
    def current(self) -> int:
        """Get the current sequence number (thread-safe read)."""
        with self._lock:
            return self._current


class ExecutionTrail:
    """Tracks the most recent N executed lines/branches for debugging.

    Useful for identifying what code was running just before a failure.
    """

    def __init__(self, max_size: int = 50):
        self.max_size = max_size
        self._trail: List[Tuple[str, Union[int, Tuple[int, int]], int]] = []
        self._lock = threading.Lock()

    def record(self, filename: str, line_or_branch: Union[int, Tuple[int, int]],
               sequence: int) -> None:
        """Record an execution event."""
        with self._lock:
            self._trail.append((filename, line_or_branch, sequence))
            if len(self._trail) > self.max_size:
                self._trail.pop(0)

    def get_trail(self) -> List[Tuple[str, Union[int, Tuple[int, int]], int]]:
        """Get a copy of the current trail."""
        with self._lock:
            return list(self._trail)

    def get_last_n(self, n: int) -> List[Tuple[str, Union[int, Tuple[int, int]], int]]:
        """Get the last N events from the trail."""
        with self._lock:
            return list(self._trail[-n:])


class AgentMetrics:
    """Central storage for all agent-mode metrics.

    Thread-safe container for all coverage metrics with support for:
    - Hit counting
    - Timestamp tracking
    - Execution sequence tracking
    - Execution trail for debugging
    """

    def __init__(self,
                 track_hits: bool = True,
                 track_timestamps: bool = False,
                 trace_execution: bool = False,
                 trail_size: int = 50):
        """Initialize agent metrics.

        Args:
            track_hits: Whether to count hits per line/branch
            track_timestamps: Whether to track first/last execution times
            trace_execution: Whether to track full execution sequence
            trail_size: Size of execution trail buffer
        """
        self.track_hits = track_hits
        self.track_timestamps = track_timestamps
        self.trace_execution = trace_execution

        # File -> FileMetrics
        self._files: Dict[str, FileMetrics] = {}
        self._lock = threading.RLock()

        # Sequence counter (always available, but only used in certain modes)
        self._sequence = SequenceCounter()

        # Execution trail (only populated when trace_execution=True)
        self._trail = ExecutionTrail(trail_size) if trace_execution else None

        # Thread-local storage for high-frequency callbacks
        self._thread_local = threading.local()

    def _get_file_metrics(self, filename: str) -> FileMetrics:
        """Get or create metrics for a file (must be called with lock held)."""
        if filename not in self._files:
            self._files[filename] = FileMetrics()
        return self._files[filename]

    def record_line(self, filename: str, line: int) -> None:
        """Record a line execution.

        Thread-safe recording of line coverage with optional metrics.
        """
        sequence = self._sequence.next() if self.trace_execution or self.track_hits else 0
        timestamp = time.time() if self.track_timestamps else None

        with self._lock:
            metrics = self._get_file_metrics(filename).get_or_create_line(line)
            metrics.record_hit(sequence, timestamp)

        if self._trail:
            self._trail.record(filename, line, sequence)

    def record_branch(self, filename: str, branch: Tuple[int, int]) -> None:
        """Record a branch execution.

        Thread-safe recording of branch coverage with optional metrics.
        """
        sequence = self._sequence.next() if self.trace_execution or self.track_hits else 0
        timestamp = time.time() if self.track_timestamps else None

        with self._lock:
            metrics = self._get_file_metrics(filename).get_or_create_branch(branch)
            metrics.record_hit(sequence, timestamp)

        if self._trail:
            self._trail.record(filename, branch, sequence)

    def get_file_metrics(self, filename: str) -> Optional[FileMetrics]:
        """Get metrics for a file (returns None if no coverage)."""
        with self._lock:
            return self._files.get(filename)

    def get_all_files(self) -> Dict[str, FileMetrics]:
        """Get a copy of all file metrics."""
        with self._lock:
            return dict(self._files)

    @property
    def total_executions(self) -> int:
        """Get the total number of executions recorded."""
        return self._sequence.current

    def get_execution_trail(self) -> List[Tuple[str, Union[int, Tuple[int, int]], int]]:
        """Get the execution trail (empty if trace_execution=False)."""
        if self._trail:
            return self._trail.get_trail()
        return []

    def compute_recency(self, sequence: int) -> float:
        """Compute recency score (0.0 = oldest, 1.0 = most recent).

        Args:
            sequence: The sequence number to compute recency for

        Returns:
            Recency score between 0.0 and 1.0
        """
        total = self._sequence.current
        if total == 0:
            return 0.0
        return sequence / total

    def merge_from(self, other: 'AgentMetrics') -> None:
        """Merge metrics from another AgentMetrics instance.

        Used for combining coverage from forked processes or xdist workers.
        """
        with self._lock:
            for filename, other_metrics in other._files.items():
                file_metrics = self._get_file_metrics(filename)

                # Merge line metrics
                for line, line_metrics in other_metrics.lines.items():
                    existing = file_metrics.get_or_create_line(line)
                    existing.hit_count += line_metrics.hit_count
                    # Take earliest first_hit
                    if line_metrics.first_hit is not None:
                        if existing.first_hit is None or line_metrics.first_hit < existing.first_hit:
                            existing.first_hit = line_metrics.first_hit
                    # Take latest last_hit
                    if line_metrics.last_hit is not None:
                        if existing.last_hit is None or line_metrics.last_hit > existing.last_hit:
                            existing.last_hit = line_metrics.last_hit
                    # Take higher sequence (most recent)
                    if line_metrics.last_sequence > existing.last_sequence:
                        existing.last_sequence = line_metrics.last_sequence

                # Merge branch metrics
                for branch, branch_metrics in other_metrics.branches.items():
                    existing = file_metrics.get_or_create_branch(branch)
                    existing.hit_count += branch_metrics.hit_count
                    if branch_metrics.first_hit is not None:
                        if existing.first_hit is None or branch_metrics.first_hit < existing.first_hit:
                            existing.first_hit = branch_metrics.first_hit
                    if branch_metrics.last_hit is not None:
                        if existing.last_hit is None or branch_metrics.last_hit > existing.last_hit:
                            existing.last_hit = branch_metrics.last_hit
                    if branch_metrics.last_sequence > existing.last_sequence:
                        existing.last_sequence = branch_metrics.last_sequence


def extract_structure(filename: str, source: str) -> CodeStructure:
    """Extract code structure (classes, functions) from Python source.

    Args:
        filename: The filename for the code
        source: Python source code string

    Returns:
        CodeStructure containing class and function information
    """
    import ast

    structure = CodeStructure(filename=filename)

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return structure

    class StructureVisitor(ast.NodeVisitor):
        def __init__(self):
            self.in_class: bool = False

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            class_info = ClassInfo(
                name=node.name,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            )

            # Visit methods within the class
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_info = FunctionInfo(
                        name=item.name,
                        start_line=item.lineno,
                        end_line=item.end_lineno or item.lineno,
                        is_method=True,
                        class_name=node.name,
                    )
                    class_info.methods[item.name] = method_info

            structure.classes[node.name] = class_info

            # Continue visiting for nested classes, but mark we're in a class
            old_in_class = self.in_class
            self.in_class = True
            self.generic_visit(node)
            self.in_class = old_in_class

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if not self.in_class:  # Top-level function only
                func_info = FunctionInfo(
                    name=node.name,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    is_method=False,
                )
                structure.functions[node.name] = func_info
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            if not self.in_class:  # Top-level async function only
                func_info = FunctionInfo(
                    name=node.name,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    is_method=False,
                )
                structure.functions[node.name] = func_info
            self.generic_visit(node)

    visitor = StructureVisitor()
    visitor.visit(tree)

    # Count total lines
    structure.total_lines = len(source.splitlines())

    return structure


def compute_structure_coverage(
    structure: CodeStructure,
    code_lines: set,
    covered_lines: set,
    line_hits: Optional[Dict[int, int]] = None
) -> CodeStructure:
    """Compute coverage statistics for a code structure.

    Updates the structure in-place with coverage information.

    Args:
        structure: CodeStructure to update
        code_lines: Set of code lines (from instrumentation)
        covered_lines: Set of covered line numbers
        line_hits: Optional dict of line -> hit count

    Returns:
        The updated CodeStructure
    """
    def compute_range_coverage(start: int, end: int) -> tuple:
        """Compute coverage for a line range."""
        lines_in_range = code_lines & set(range(start, end + 1))
        covered_in_range = covered_lines & lines_in_range
        total = len(lines_in_range)
        covered = len(covered_in_range)
        total_hits = 0
        if line_hits:
            total_hits = sum(line_hits.get(line, 0) for line in covered_in_range)
        return total, covered, total_hits

    # Compute coverage for classes and their methods
    for class_info in structure.classes.values():
        # Compute class-level coverage
        total, covered, hits = compute_range_coverage(
            class_info.start_line, class_info.end_line
        )
        class_info.total_lines = total
        class_info.covered_lines = covered

        # Compute coverage for each method
        for method_info in class_info.methods.values():
            m_total, m_covered, m_hits = compute_range_coverage(
                method_info.start_line, method_info.end_line
            )
            method_info.total_lines = m_total
            method_info.covered_lines = m_covered
            method_info.hit_count = m_hits

    # Compute coverage for top-level functions
    for func_info in structure.functions.values():
        total, covered, hits = compute_range_coverage(
            func_info.start_line, func_info.end_line
        )
        func_info.total_lines = total
        func_info.covered_lines = covered
        func_info.hit_count = hits

    return structure


def structure_to_dict(structure: CodeStructure) -> dict:
    """Convert a CodeStructure to a dictionary for JSON output.

    Args:
        structure: CodeStructure to convert

    Returns:
        Dictionary representation suitable for JSON output
    """
    def func_to_dict(func: FunctionInfo) -> dict:
        percent = 100.0 * func.covered_lines / func.total_lines if func.total_lines > 0 else 100.0
        return {
            'name': func.name,
            'start_line': func.start_line,
            'end_line': func.end_line,
            'total_lines': func.total_lines,
            'covered_lines': func.covered_lines,
            'missing_lines': func.total_lines - func.covered_lines,
            'percent_covered': percent,
            'total_hits': func.hit_count,
            'is_method': func.is_method,
            'class_name': func.class_name,
        }

    def class_to_dict(cls: ClassInfo) -> dict:
        percent = 100.0 * cls.covered_lines / cls.total_lines if cls.total_lines > 0 else 100.0
        return {
            'name': cls.name,
            'start_line': cls.start_line,
            'end_line': cls.end_line,
            'total_lines': cls.total_lines,
            'covered_lines': cls.covered_lines,
            'missing_lines': cls.total_lines - cls.covered_lines,
            'percent_covered': percent,
            'methods': {name: func_to_dict(m) for name, m in cls.methods.items()},
        }

    return {
        'classes': {name: class_to_dict(c) for name, c in structure.classes.items()},
        'functions': {name: func_to_dict(f) for name, f in structure.functions.items()},
    }
