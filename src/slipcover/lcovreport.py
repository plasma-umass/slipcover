"""LCOV reporting for slipcover"""

from __future__ import annotations

import sys
from collections import defaultdict
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from typing import IO

    from .schemas import Coverage, CoverageFile


def get_missing_branch_arcs(file_data: CoverageFile) -> Dict[int, List[int]]:
    """Return arcs that weren't executed from branch lines.

    Returns {l1:[l2a,l2b,...], ...}

    """
    mba: Dict[int, List[int]] = {}
    for branch in file_data.get("missing_branches", []):
        mba.setdefault(branch[0], []).append(branch[1])

    return mba


def get_branch_info(
    file_data: CoverageFile, missing_arcs: Dict[int, List[int]]
) -> Dict[int, List[Tuple[int, bool]]]:
    """Get information about branches for LCOV format.

    Returns a dict mapping line numbers to a list of (branch_dest, was_taken) tuples.

    """
    all_branches = sorted(file_data.get("executed_branches", []) + file_data.get("missing_branches", []))

    # Group branches by their source line
    branches_by_line: Dict[int, List[Tuple[int, bool]]] = defaultdict(list)

    for branch in all_branches:
        src_line, dest_line = branch
        is_taken = branch not in file_data.get("missing_branches", [])
        branches_by_line[src_line].append((dest_line, is_taken))

    return branches_by_line


class LcovReporter:
    """A reporter for writing LCOV-style coverage results."""

    def __init__(
        self,
        coverage: Coverage,
        with_branches: bool,
        test_name: Optional[str] = None,
        comments: Optional[List[str]] = None,
    ) -> None:
        self.coverage = coverage
        self.with_branches = with_branches
        self.test_name = test_name
        self.comments = comments or []

    def report(self, outfile: IO[str] | None = None) -> None:
        """Generate an LCOV-compatible coverage report.

        `outfile` is a file object to write the LCOV data to.

        """
        outfile = outfile or sys.stdout

        for comment in self.comments:
            outfile.write(f"# {comment}\n")

        for file_path, file_data in sorted(self.coverage["files"].items()):
            self._write_file_coverage(outfile, file_path, file_data)

    def _write_file_coverage(
        self, outfile: IO[str], file_path: str, file_data: CoverageFile
    ) -> None:
        """Write LCOV coverage data for a single file."""

        # TN: Test Name (optional)
        if self.test_name is not None:
            outfile.write(f"TN:{self.test_name}\n")

        # SF: Source File
        outfile.write(f"SF:{file_path}\n")

        # Get all lines (both executed and missing)
        all_lines = sorted(file_data["executed_lines"] + file_data["missing_lines"])

        # Write branch coverage data if enabled
        if self.with_branches and (file_data.get("executed_branches") or file_data.get("missing_branches")):
            missing_arcs = get_missing_branch_arcs(file_data)
            branch_info = get_branch_info(file_data, missing_arcs)

            # BRDA: Branch data
            # Format: BRDA:<line number>,<block number>,<branch number>,<taken count or '-'>
            for line_num in sorted(branch_info.keys()):
                branches = branch_info[line_num]
                # Use line number as block number for simplicity
                block_num = 0
                for branch_num, (dest, is_taken) in enumerate(branches):
                    taken_str = "1" if is_taken else "-"
                    outfile.write(f"BRDA:{line_num},{block_num},{branch_num},{taken_str}\n")

            # BRF: Branches Found
            total_branches = len(file_data.get("executed_branches", [])) + len(file_data.get("missing_branches", []))
            outfile.write(f"BRF:{total_branches}\n")

            # BRH: Branches Hit
            branches_hit = len(file_data.get("executed_branches", []))
            outfile.write(f"BRH:{branches_hit}\n")

        # DA: Line coverage data
        # Format: DA:<line number>,<execution count>
        for line in all_lines:
            hit_count = 1 if line in file_data["executed_lines"] else 0
            outfile.write(f"DA:{line},{hit_count}\n")

        # LF: Lines Found (total instrumented lines)
        total_lines = len(all_lines)
        outfile.write(f"LF:{total_lines}\n")

        # LH: Lines Hit (covered lines)
        lines_hit = len(file_data["executed_lines"])
        outfile.write(f"LH:{lines_hit}\n")

        # end_of_record: End of record marker
        outfile.write("end_of_record\n")
