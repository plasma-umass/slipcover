"""Git integration utilities for slipcover agent mode.

This module provides git blame parsing and change tracking to enable:
- Tracking which lines were modified since a baseline commit
- Identifying lines that are covered/uncovered since modification
- Detecting uncommitted changes
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class GitLineInfo:
    """Git blame information for a single line."""
    commit: str  # Short commit hash, or "uncommitted" for working changes
    author: Optional[str] = None
    timestamp: Optional[str] = None  # ISO format
    is_uncommitted: bool = False


@dataclass
class GitFileInfo:
    """Git information for a file."""
    lines: Dict[int, GitLineInfo]  # Line number -> GitLineInfo
    modified_lines: List[int]  # Lines modified since baseline
    has_uncommitted: bool  # Whether file has uncommitted changes


def get_git_head() -> Optional[str]:
    """Get the current HEAD commit hash.

    Returns:
        Short commit hash, or None if not in a git repository
    """
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def is_git_dirty() -> bool:
    """Check if there are uncommitted changes.

    Returns:
        True if there are uncommitted changes, False otherwise
    """
    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True,
            text=True,
            check=True
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_git_blame(filepath: str) -> Optional[Dict[int, GitLineInfo]]:
    """Get git blame information for a file.

    Args:
        filepath: Path to the file

    Returns:
        Dictionary mapping line numbers to GitLineInfo, or None if git blame fails
    """
    try:
        # Use git blame with porcelain format for easy parsing
        # Include uncommitted changes with --contents
        result = subprocess.run(
            ['git', 'blame', '--line-porcelain', filepath],
            capture_output=True,
            text=True,
            check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    lines: Dict[int, GitLineInfo] = {}
    current_commit = ""
    current_author = ""
    current_line = 0

    for line in result.stdout.splitlines():
        # Line format: <commit> <orig-line> <final-line> [<num-lines>]
        if line and line[0] not in '\t ':
            parts = line.split()
            if len(parts) >= 3 and len(parts[0]) >= 40:
                current_commit = parts[0][:7]  # Short hash
                current_line = int(parts[2])
        elif line.startswith('author '):
            current_author = line[7:]
        elif line.startswith('\t'):
            # This is the actual line content, record the blame info
            is_uncommitted = current_commit.startswith('0000000')
            lines[current_line] = GitLineInfo(
                commit='uncommitted' if is_uncommitted else current_commit,
                author=current_author if current_author else None,
                is_uncommitted=is_uncommitted
            )

    return lines


def get_modified_lines_since(filepath: str, baseline: str = 'HEAD~1') -> Optional[List[int]]:
    """Get line numbers modified since a baseline commit.

    Args:
        filepath: Path to the file
        baseline: Git ref to compare against (default: HEAD~1)

    Returns:
        List of line numbers that have been modified, or None if diff fails
    """
    try:
        # Use git diff with line numbers
        result = subprocess.run(
            ['git', 'diff', '-U0', baseline, '--', filepath],
            capture_output=True,
            text=True,
            check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    modified_lines: List[int] = []

    for line in result.stdout.splitlines():
        # Parse unified diff format: @@ -old_start,old_count +new_start,new_count @@
        if line.startswith('@@'):
            # Extract the new file range
            parts = line.split()
            for part in parts:
                if part.startswith('+') and ',' in part:
                    # Format: +start,count
                    range_part = part[1:]  # Remove +
                    start, count = map(int, range_part.split(','))
                    modified_lines.extend(range(start, start + count))
                elif part.startswith('+') and part[1:].isdigit():
                    # Format: +line (single line)
                    modified_lines.append(int(part[1:]))

    return modified_lines


def get_uncommitted_lines(filepath: str) -> Optional[List[int]]:
    """Get line numbers with uncommitted changes.

    Args:
        filepath: Path to the file

    Returns:
        List of line numbers with uncommitted changes, or None if check fails
    """
    return get_modified_lines_since(filepath, 'HEAD')


def get_git_file_info(filepath: str, baseline: str = 'HEAD~1') -> Optional[GitFileInfo]:
    """Get comprehensive git information for a file.

    Args:
        filepath: Path to the file
        baseline: Git ref to compare against for modified lines

    Returns:
        GitFileInfo with blame data and modified lines, or None if git operations fail
    """
    blame = get_git_blame(filepath)
    if blame is None:
        return None

    modified = get_modified_lines_since(filepath, baseline) or []
    has_uncommitted = any(info.is_uncommitted for info in blame.values())

    return GitFileInfo(
        lines=blame,
        modified_lines=modified,
        has_uncommitted=has_uncommitted
    )


class GitTracker:
    """Tracks git information for multiple files.

    Caches git blame and modification data to avoid repeated git calls.
    """

    def __init__(self, baseline: str = 'HEAD~1'):
        """Initialize the git tracker.

        Args:
            baseline: Git ref to compare against for modified lines
        """
        self.baseline = baseline
        self._cache: Dict[str, Optional[GitFileInfo]] = {}
        self._git_head: Optional[str] = None
        self._git_dirty: Optional[bool] = None

    @property
    def git_head(self) -> Optional[str]:
        """Get the current HEAD commit (cached)."""
        if self._git_head is None:
            self._git_head = get_git_head()
        return self._git_head

    @property
    def git_dirty(self) -> bool:
        """Check if repo has uncommitted changes (cached)."""
        if self._git_dirty is None:
            self._git_dirty = is_git_dirty()
        return self._git_dirty

    def get_file_info(self, filepath: str) -> Optional[GitFileInfo]:
        """Get git info for a file (cached).

        Args:
            filepath: Path to the file

        Returns:
            GitFileInfo or None if not available
        """
        # Resolve to absolute path for consistent caching
        abs_path = str(Path(filepath).resolve())

        if abs_path not in self._cache:
            self._cache[abs_path] = get_git_file_info(abs_path, self.baseline)

        return self._cache.get(abs_path)

    def get_modified_lines(self, filepath: str) -> List[int]:
        """Get modified lines for a file.

        Args:
            filepath: Path to the file

        Returns:
            List of modified line numbers, empty if git info not available
        """
        info = self.get_file_info(filepath)
        return info.modified_lines if info else []

    def get_line_commit(self, filepath: str, line: int) -> Optional[str]:
        """Get the commit hash for a specific line.

        Args:
            filepath: Path to the file
            line: Line number

        Returns:
            Short commit hash or 'uncommitted', None if not available
        """
        info = self.get_file_info(filepath)
        if info and line in info.lines:
            return info.lines[line].commit
        return None

    def is_line_modified_since_baseline(self, filepath: str, line: int) -> bool:
        """Check if a line was modified since the baseline.

        Args:
            filepath: Path to the file
            line: Line number

        Returns:
            True if line was modified since baseline
        """
        info = self.get_file_info(filepath)
        return info is not None and line in info.modified_lines

    def is_covered_since_modification(
        self,
        filepath: str,
        line: int,
        coverage_timestamp: Optional[float]
    ) -> bool:
        """Check if a line was covered since it was last modified.

        This is a key signal for AI agents: modified but uncovered lines
        are high-priority targets for investigation.

        Args:
            filepath: Path to the file
            line: Line number
            coverage_timestamp: When the line was last covered (Unix timestamp)

        Returns:
            True if line was covered after its last modification
        """
        info = self.get_file_info(filepath)
        if info is None:
            return False

        # If line has uncommitted changes, it needs coverage
        if line in info.lines and info.lines[line].is_uncommitted:
            return coverage_timestamp is not None

        # If line is in modified set but not uncommitted, it was modified
        # in a commit since baseline - check if covered
        if line in info.modified_lines:
            return coverage_timestamp is not None

        # Line wasn't modified, so any historical coverage counts
        return True

    def clear_cache(self) -> None:
        """Clear the git info cache."""
        self._cache.clear()
        self._git_head = None
        self._git_dirty = None
