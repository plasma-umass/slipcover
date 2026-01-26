from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, List, NotRequired, Tuple, TypedDict

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