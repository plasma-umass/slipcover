"""Session history tracking for trend analysis in slipcover agent mode.

This module provides session-by-session coverage tracking to enable:
- Detection of execution pattern changes (hot -> cold, cold -> hot)
- Trend analysis across runs
- Historical coverage comparison
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class SessionCoverage:
    """Coverage data for a single session."""
    session_id: str
    timestamp: str  # ISO format
    git_head: Optional[str] = None
    # File -> line hits mapping
    line_hits: Dict[str, Dict[str, int]] = field(default_factory=dict)
    # File -> branch hits mapping
    branch_hits: Dict[str, Dict[str, int]] = field(default_factory=dict)


@dataclass
class SessionHistory:
    """History of coverage sessions with rolling window."""
    max_sessions: int = 10
    sessions: List[SessionCoverage] = field(default_factory=list)

    def add_session(self, session: SessionCoverage) -> None:
        """Add a session, maintaining the rolling window."""
        self.sessions.append(session)
        if len(self.sessions) > self.max_sessions:
            self.sessions = self.sessions[-self.max_sessions:]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'max_sessions': self.max_sessions,
            'sessions': [asdict(s) for s in self.sessions],
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'SessionHistory':
        """Create from dictionary (JSON deserialization)."""
        history = cls(max_sessions=data.get('max_sessions', 10))
        for s_data in data.get('sessions', []):
            history.sessions.append(SessionCoverage(**s_data))
        return history


@dataclass
class LineTrend:
    """Trend information for a single line."""
    current_hits: int
    avg_hits_recent: float  # Average over recent sessions
    direction: str  # "heating", "cooling", "stable", "new", "disappeared"
    sessions_since_last_hit: int
    alert: bool = False  # Significant change detected


def _acquire_lock(fd: int) -> None:
    """Acquire exclusive lock on file descriptor (cross-platform)."""
    if sys.platform == 'win32':
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)


def _release_lock(fd: int) -> None:
    """Release lock on file descriptor (cross-platform)."""
    if sys.platform == 'win32':
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def load_history(history_file: str) -> SessionHistory:
    """Load session history from file (process-safe).

    Args:
        history_file: Path to the history file

    Returns:
        SessionHistory, empty if file doesn't exist or is invalid
    """
    path = Path(history_file)
    if not path.exists():
        return SessionHistory()

    try:
        with open(path, 'r') as f:
            _acquire_lock(f.fileno())
            try:
                data = json.load(f)
                return SessionHistory.from_dict(data)
            finally:
                _release_lock(f.fileno())
    except (json.JSONDecodeError, OSError):
        return SessionHistory()


def save_history(history: SessionHistory, history_file: str) -> bool:
    """Save session history to file (process-safe).

    Uses file locking to handle concurrent writes from pytest-xdist workers.

    Args:
        history: SessionHistory to save
        history_file: Path to the history file

    Returns:
        True if save succeeded, False otherwise
    """
    path = Path(history_file)

    try:
        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        # Use open with 'a+' to create file if it doesn't exist
        with open(path, 'a+') as f:
            _acquire_lock(f.fileno())
            try:
                # Read existing data (if any)
                f.seek(0)
                content = f.read()
                if content:
                    existing = SessionHistory.from_dict(json.loads(content))
                    # Merge: keep existing sessions, add new ones
                    existing_ids = {s.session_id for s in existing.sessions}
                    for session in history.sessions:
                        if session.session_id not in existing_ids:
                            existing.add_session(session)
                    history = existing

                # Write updated history
                f.seek(0)
                f.truncate()
                json.dump(history.to_dict(), f, indent=2)
                return True
            finally:
                _release_lock(f.fileno())
    except OSError:
        return False


def compute_trends(
    current_session: SessionCoverage,
    history: SessionHistory,
    threshold: float = 0.5
) -> Dict[str, Dict[str, LineTrend]]:
    """Compute trend information by comparing current session to history.

    Args:
        current_session: The current session's coverage
        history: Historical session data
        threshold: Fraction change to consider "significant" (default 0.5 = 50%)

    Returns:
        Dict mapping filename -> line_number -> LineTrend
    """
    trends: Dict[str, Dict[str, LineTrend]] = {}

    # Build historical averages per line
    # line_averages[file][line] = list of hit counts from history
    line_history: Dict[str, Dict[str, List[int]]] = {}

    for session in history.sessions:
        for filename, hits in session.line_hits.items():
            if filename not in line_history:
                line_history[filename] = {}
            for line, count in hits.items():
                if line not in line_history[filename]:
                    line_history[filename][line] = []
                line_history[filename][line].append(count)

    # Compute trends for current session
    for filename, current_hits in current_session.line_hits.items():
        if filename not in trends:
            trends[filename] = {}

        file_history = line_history.get(filename, {})

        for line, count in current_hits.items():
            hist_counts = file_history.get(line, [])

            if not hist_counts:
                # Line is new (not in any previous session)
                trends[filename][line] = LineTrend(
                    current_hits=count,
                    avg_hits_recent=0.0,
                    direction='new',
                    sessions_since_last_hit=0,
                    alert=False
                )
            else:
                avg = sum(hist_counts) / len(hist_counts)
                sessions_since_hit = 0

                # Calculate sessions since last hit
                for i, session in enumerate(reversed(history.sessions)):
                    session_hits = session.line_hits.get(filename, {})
                    if session_hits.get(line, 0) > 0:
                        break
                    sessions_since_hit = i + 1

                # Determine direction
                if avg == 0:
                    if count > 0:
                        direction = 'heating'
                        alert = True
                    else:
                        direction = 'stable'
                        alert = False
                else:
                    change_ratio = (count - avg) / avg
                    if change_ratio > threshold:
                        direction = 'heating'
                        alert = True
                    elif change_ratio < -threshold:
                        direction = 'cooling'
                        alert = True
                    else:
                        direction = 'stable'
                        alert = False

                trends[filename][line] = LineTrend(
                    current_hits=count,
                    avg_hits_recent=avg,
                    direction=direction,
                    sessions_since_last_hit=sessions_since_hit,
                    alert=alert
                )

        # Check for lines that disappeared (in history but not in current)
        for line in file_history:
            if line not in current_hits:
                hist_counts = file_history[line]
                avg = sum(hist_counts) / len(hist_counts)
                if avg > 0:  # Only track if it was actually hit before
                    trends[filename][line] = LineTrend(
                        current_hits=0,
                        avg_hits_recent=avg,
                        direction='disappeared',
                        sessions_since_last_hit=len(history.sessions),
                        alert=True
                    )

    return trends


def trends_to_dict(trends: Dict[str, Dict[str, LineTrend]]) -> dict:
    """Convert trends to dictionary for JSON output."""
    return {
        filename: {
            line: asdict(trend)
            for line, trend in line_trends.items()
        }
        for filename, line_trends in trends.items()
    }


def create_session_from_coverage(
    coverage: dict,
    session_id: str,
    git_head: Optional[str] = None
) -> SessionCoverage:
    """Create a SessionCoverage from agent coverage output.

    Args:
        coverage: Agent coverage output dictionary
        session_id: Session identifier
        git_head: Optional git commit hash

    Returns:
        SessionCoverage object
    """
    import datetime

    session = SessionCoverage(
        session_id=session_id,
        timestamp=datetime.datetime.now().isoformat(),
        git_head=git_head or coverage.get('meta', {}).get('git_head'),
    )

    for filename, file_data in coverage.get('files', {}).items():
        # Extract line hits from line_details
        if 'line_details' in file_data:
            session.line_hits[filename] = {
                line: detail.get('hit_count', 0)
                for line, detail in file_data['line_details'].items()
                if detail.get('covered', False)
            }
        # Extract branch hits from branch_details
        if 'branch_details' in file_data:
            session.branch_hits[filename] = {
                branch: detail.get('hit_count', 0)
                for branch, detail in file_data['branch_details'].items()
                if detail.get('covered', False)
            }

    return session


class SessionTracker:
    """Tracks sessions and computes trends across runs.

    This class manages the session history file and provides
    trend analysis capabilities.
    """

    def __init__(self, history_file: str = '.slipcover-history.json'):
        """Initialize the session tracker.

        Args:
            history_file: Path to the history file
        """
        self.history_file = history_file
        self._history: Optional[SessionHistory] = None

    @property
    def history(self) -> SessionHistory:
        """Get the session history (lazy-loaded)."""
        if self._history is None:
            self._history = load_history(self.history_file)
        return self._history

    def record_session(self, session: SessionCoverage) -> bool:
        """Record a session and save to history file.

        Args:
            session: The session to record

        Returns:
            True if recording succeeded
        """
        self.history.add_session(session)
        return save_history(self.history, self.history_file)

    def get_trends(
        self,
        current_coverage: dict,
        session_id: str
    ) -> Dict[str, Dict[str, LineTrend]]:
        """Get trend analysis for current coverage.

        Args:
            current_coverage: Agent coverage output dictionary
            session_id: Current session identifier

        Returns:
            Trend information by file and line
        """
        session = create_session_from_coverage(
            current_coverage,
            session_id,
            current_coverage.get('meta', {}).get('git_head')
        )
        return compute_trends(session, self.history)

    def get_cooling_alerts(
        self,
        current_coverage: dict,
        session_id: str
    ) -> List[dict]:
        """Get lines that have "cooled off" (used to be exercised, now aren't).

        Args:
            current_coverage: Agent coverage output dictionary
            session_id: Current session identifier

        Returns:
            List of alert dictionaries with file, line, details
        """
        trends = self.get_trends(current_coverage, session_id)
        alerts = []

        for filename, line_trends in trends.items():
            for line, trend in line_trends.items():
                if trend.direction in ('cooling', 'disappeared') and trend.alert:
                    alerts.append({
                        'file': filename,
                        'line': line,
                        'direction': trend.direction,
                        'current_hits': trend.current_hits,
                        'avg_recent': trend.avg_hits_recent,
                        'sessions_since_hit': trend.sessions_since_last_hit,
                    })

        return alerts
