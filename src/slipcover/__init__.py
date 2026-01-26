from .version import __version__
from .slipcover import Slipcover, merge_coverage, print_coverage, print_xml
from .importer import FileMatcher, ImportManager, wrap_pytest
from .fuzz import wrap_function
from .agent import (
    LineMetrics, BranchMetrics, FileMetrics, AgentMetrics,
    FunctionInfo, ClassInfo, CodeStructure,
    SequenceCounter, ExecutionTrail, extract_structure,
    compute_structure_coverage, structure_to_dict
)
from .git_utils import (
    GitLineInfo, GitFileInfo, GitTracker,
    get_git_head, is_git_dirty, get_git_blame,
    get_modified_lines_since, get_uncommitted_lines
)
from .session_history import (
    SessionCoverage, SessionHistory, SessionTracker,
    LineTrend, load_history, save_history,
    compute_trends, create_session_from_coverage
)
