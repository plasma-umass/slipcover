from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, List, NotRequired, Optional, Tuple, TypedDict

    class CoverageMeta(TypedDict):
        software: str
        version: str
        timestamp: str
        branch_coverage: bool
        show_contexts: bool

    class CoverageSummary(TypedDict):
        covered_lines: int
        missing_lines: int
        covered_branches: NotRequired[int]
        missing_branches: NotRequired[int]
        percent_covered: float

    class CoverageFile(TypedDict):
        executed_lines: List[int]
        missing_lines: List[int]
        executed_branches: NotRequired[List[Tuple[int, int]]]
        missing_branches: NotRequired[List[Tuple[int, int]]]
        summary: CoverageSummary

    class Coverage(TypedDict):
        meta: CoverageMeta
        files: Dict[str, CoverageFile]
        summary: CoverageSummary

    # Agent mode schemas - extended coverage with metrics

    class AgentMeta(TypedDict):
        """Extended metadata for agent mode coverage."""
        software: str
        version: str
        timestamp: str
        branch_coverage: bool
        show_contexts: bool
        # Agent-specific fields
        session_id: NotRequired[str]
        git_head: NotRequired[Optional[str]]
        git_dirty: NotRequired[bool]
        track_hits: NotRequired[bool]
        track_timestamps: NotRequired[bool]
        trace_execution: NotRequired[bool]
        total_executions: NotRequired[int]

    class LineDetail(TypedDict, total=False):
        """Detailed metrics for a single line."""
        covered: bool
        hit_count: int
        first_hit: Optional[str]  # ISO timestamp
        last_hit: Optional[str]   # ISO timestamp
        sequence: int             # Last execution sequence
        recency: float            # 0.0-1.0 recency score
        # Git integration fields
        git_commit: Optional[str]
        git_author: Optional[str]
        covered_since_modification: bool

    class BranchDetail(TypedDict, total=False):
        """Detailed metrics for a single branch."""
        from_line: int
        to_line: int
        covered: bool
        hit_count: int
        first_hit: Optional[str]
        last_hit: Optional[str]
        sequence: int
        recency: float

    class FunctionDetail(TypedDict, total=False):
        """Coverage summary for a function or method."""
        name: str
        start_line: int
        end_line: int
        total_lines: int
        covered_lines: int
        missing_lines: int
        percent_covered: float
        total_hits: int
        is_method: bool
        class_name: Optional[str]

    class ClassDetail(TypedDict, total=False):
        """Coverage summary for a class."""
        name: str
        start_line: int
        end_line: int
        total_lines: int
        covered_lines: int
        missing_lines: int
        percent_covered: float
        methods: Dict[str, FunctionDetail]

    class ExecutionEvent(TypedDict):
        """Single event in the execution trail."""
        file: str
        line: int
        branch: NotRequired[Tuple[int, int]]
        sequence: int
        recency: float

    class AgentFileSummary(TypedDict, total=False):
        """Extended file summary for agent mode."""
        # Standard fields
        total_lines: int
        covered_lines: int
        missing_lines: int
        percent_covered: float
        # Branch fields
        total_branches: NotRequired[int]
        covered_branches: NotRequired[int]
        missing_branches: NotRequired[int]
        # Agent-specific fields
        total_hits: int
        hottest_line: NotRequired[int]
        hottest_hits: NotRequired[int]
        # Git integration
        modified_since_baseline: NotRequired[int]
        modified_covered: NotRequired[int]
        modified_uncovered: NotRequired[int]

    class AgentCoverageFile(TypedDict, total=False):
        """Extended coverage data for a file in agent mode."""
        # Standard coverage
        executed_lines: List[int]
        missing_lines: List[int]
        executed_branches: NotRequired[List[Tuple[int, int]]]
        missing_branches: NotRequired[List[Tuple[int, int]]]
        summary: AgentFileSummary
        # Structure
        classes: NotRequired[Dict[str, ClassDetail]]
        functions: NotRequired[Dict[str, FunctionDetail]]
        # Detailed line/branch metrics (optional, controlled by --detail)
        line_details: NotRequired[Dict[str, LineDetail]]
        branch_details: NotRequired[Dict[str, BranchDetail]]
        # Git integration
        git_blame_available: NotRequired[bool]

    class TrendInfo(TypedDict, total=False):
        """Trend information from session history."""
        direction: str  # "heating", "cooling", "stable", "new"
        avg_recent: float
        current: int
        sessions_since_last_hit: int
        alert: bool

    class AgentCoverage(TypedDict):
        """Full agent-mode coverage output."""
        meta: AgentMeta
        files: Dict[str, AgentCoverageFile]
        summary: AgentFileSummary
        # Execution trail (for debugging, when --trace-execution enabled)
        execution_trail: NotRequired[List[ExecutionEvent]]
        # Trend data (when --show-trends enabled)
        trends: NotRequired[Dict[str, Dict[str, TrendInfo]]]