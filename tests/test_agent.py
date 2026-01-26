"""Tests for agent-mode coverage features."""

import pytest
import sys
import tempfile
from pathlib import Path

import slipcover as sc


PYTHON_VERSION = sys.version_info[0:2]


class TestLineMetrics:
    """Tests for LineMetrics dataclass."""

    def test_record_hit_without_timestamp(self):
        metrics = sc.LineMetrics()
        metrics.record_hit(sequence=1)

        assert metrics.hit_count == 1
        assert metrics.last_sequence == 1
        assert metrics.first_hit is None
        assert metrics.last_hit is None

    def test_record_hit_with_timestamp(self):
        metrics = sc.LineMetrics()
        metrics.record_hit(sequence=1, timestamp=1000.0)
        metrics.record_hit(sequence=2, timestamp=2000.0)

        assert metrics.hit_count == 2
        assert metrics.last_sequence == 2
        assert metrics.first_hit == 1000.0
        assert metrics.last_hit == 2000.0

    def test_multiple_hits(self):
        metrics = sc.LineMetrics()
        for i in range(5):
            metrics.record_hit(sequence=i + 1)

        assert metrics.hit_count == 5
        assert metrics.last_sequence == 5


class TestAgentMetrics:
    """Tests for AgentMetrics class."""

    def test_basic_line_recording(self):
        am = sc.AgentMetrics(track_hits=True)
        am.record_line('test.py', 10)
        am.record_line('test.py', 10)
        am.record_line('test.py', 20)

        metrics = am.get_file_metrics('test.py')
        assert metrics is not None
        assert 10 in metrics.lines
        assert 20 in metrics.lines
        assert metrics.lines[10].hit_count == 2
        assert metrics.lines[20].hit_count == 1

    def test_branch_recording(self):
        am = sc.AgentMetrics(track_hits=True)
        am.record_branch('test.py', (10, 15))
        am.record_branch('test.py', (10, 20))

        metrics = am.get_file_metrics('test.py')
        assert metrics is not None
        assert (10, 15) in metrics.branches
        assert (10, 20) in metrics.branches

    def test_execution_trail(self):
        am = sc.AgentMetrics(trace_execution=True, track_hits=True)
        am.record_line('test.py', 1)
        am.record_line('test.py', 2)
        am.record_line('test.py', 3)

        trail = am.get_execution_trail()
        assert len(trail) == 3
        assert trail[0] == ('test.py', 1, 1)
        assert trail[1] == ('test.py', 2, 2)
        assert trail[2] == ('test.py', 3, 3)

    def test_recency_computation(self):
        am = sc.AgentMetrics(trace_execution=True)
        am.record_line('test.py', 1)
        am.record_line('test.py', 2)
        am.record_line('test.py', 3)
        am.record_line('test.py', 4)

        assert am.compute_recency(1) == 0.25
        assert am.compute_recency(4) == 1.0


class TestStructureExtraction:
    """Tests for code structure extraction."""

    def test_extract_class(self):
        source = '''
class MyClass:
    def __init__(self):
        self.x = 1

    def method(self):
        return self.x
'''
        structure = sc.extract_structure('test.py', source)

        assert 'MyClass' in structure.classes
        cls = structure.classes['MyClass']
        assert cls.start_line == 2
        assert '__init__' in cls.methods
        assert 'method' in cls.methods
        assert cls.methods['__init__'].is_method is True
        assert cls.methods['__init__'].class_name == 'MyClass'

    def test_extract_function(self):
        source = '''
def my_function(x, y):
    return x + y

def another_func():
    pass
'''
        structure = sc.extract_structure('test.py', source)

        assert 'my_function' in structure.functions
        assert 'another_func' in structure.functions
        assert structure.functions['my_function'].is_method is False

    def test_methods_not_in_functions(self):
        source = '''
class Foo:
    def bar(self):
        pass

def standalone():
    pass
'''
        structure = sc.extract_structure('test.py', source)

        # bar should only be in class methods, not in top-level functions
        assert 'bar' not in structure.functions
        assert 'standalone' in structure.functions
        assert 'bar' in structure.classes['Foo'].methods


class TestGitUtils:
    """Tests for git utilities."""

    def test_get_git_head(self):
        # Should return a short hash or None
        head = sc.get_git_head()
        if head is not None:
            assert len(head) <= 12  # Short hash

    def test_is_git_dirty(self):
        # Should return a boolean
        dirty = sc.is_git_dirty()
        assert isinstance(dirty, bool)

    def test_git_tracker(self):
        tracker = sc.GitTracker()
        # Properties should be accessible
        _ = tracker.git_head
        _ = tracker.git_dirty


class TestSessionHistory:
    """Tests for session history tracking."""

    def test_session_coverage_creation(self):
        session = sc.SessionCoverage(
            session_id='test-001',
            timestamp='2024-01-15T10:00:00',
            git_head='abc123',
            line_hits={'file.py': {'1': 5, '2': 10}},
            branch_hits={}
        )

        assert session.session_id == 'test-001'
        assert session.line_hits['file.py']['1'] == 5

    def test_session_history_rolling_window(self):
        history = sc.SessionHistory(max_sessions=3)

        for i in range(5):
            history.add_session(sc.SessionCoverage(
                session_id=f'session-{i}',
                timestamp=f'2024-01-1{i}T10:00:00'
            ))

        # Should only keep last 3
        assert len(history.sessions) == 3
        assert history.sessions[0].session_id == 'session-2'

    def test_save_and_load_history(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            history_file = f.name

        try:
            # Create and save history
            history = sc.SessionHistory()
            history.add_session(sc.SessionCoverage(
                session_id='test-001',
                timestamp='2024-01-15T10:00:00',
                line_hits={'file.py': {'1': 5}}
            ))
            sc.save_history(history, history_file)

            # Load and verify
            loaded = sc.load_history(history_file)
            assert len(loaded.sessions) == 1
            assert loaded.sessions[0].session_id == 'test-001'
        finally:
            Path(history_file).unlink(missing_ok=True)

    def test_compute_trends(self):
        history = sc.SessionHistory()
        history.add_session(sc.SessionCoverage(
            session_id='session-1',
            timestamp='2024-01-14T10:00:00',
            line_hits={'file.py': {'1': 10, '2': 5}}
        ))

        current = sc.SessionCoverage(
            session_id='session-2',
            timestamp='2024-01-15T10:00:00',
            line_hits={'file.py': {'1': 2, '2': 10}}  # Line 1 cooling, line 2 heating
        )

        trends = sc.compute_trends(current, history)

        assert 'file.py' in trends
        # Line 1 dropped from 10 to 2 - should be cooling
        assert trends['file.py']['1'].direction == 'cooling'
        # Line 2 increased from 5 to 10 - should be heating
        assert trends['file.py']['2'].direction == 'heating'


class TestSlipcoverAgentMode:
    """Integration tests for agent mode in Slipcover."""

    def test_agent_mode_initialization(self):
        sci = sc.Slipcover(agent_mode=True)
        assert sci.agent_mode is True
        assert sci.track_hits is True
        assert sci.agent_metrics is not None

    def test_track_hits_without_agent_mode(self):
        sci = sc.Slipcover(track_hits=True)
        assert sci.track_hits is True
        assert sci.agent_metrics is not None

    @pytest.mark.skipif(PYTHON_VERSION < (3, 12),
                        reason="sys.monitoring not available before 3.12")
    def test_agent_coverage_output(self):
        sci = sc.Slipcover(agent_mode=True)

        def test_func(x):
            if x > 0:
                return x * 2
            return 0

        sci.instrument(test_func)
        test_func(5)
        test_func(-1)

        cov = sci.get_agent_coverage()

        assert 'meta' in cov
        assert cov['meta']['track_hits'] is True
        assert 'session_id' in cov['meta']
        assert 'total_executions' in cov['meta']

    @pytest.mark.skipif(PYTHON_VERSION < (3, 12),
                        reason="sys.monitoring not available before 3.12")
    def test_trace_execution_mode(self):
        sci = sc.Slipcover(trace_execution=True)

        def test_func():
            x = 1
            y = 2
            return x + y

        sci.instrument(test_func)
        test_func()

        cov = sci.get_agent_coverage()

        assert 'execution_trail' in cov
        assert len(cov['execution_trail']) > 0

        # Check trail format
        event = cov['execution_trail'][0]
        assert 'file' in event
        assert 'line' in event
        assert 'sequence' in event
        assert 'recency' in event

    @pytest.mark.skipif(PYTHON_VERSION < (3, 12),
                        reason="sys.monitoring not available before 3.12")
    def test_line_details_in_output(self):
        sci = sc.Slipcover(agent_mode=True)

        def test_func():
            return 42

        sci.instrument(test_func)
        test_func()

        cov = sci.get_agent_coverage(detail='full')

        for file_data in cov['files'].values():
            if 'line_details' in file_data:
                for detail in file_data['line_details'].values():
                    assert 'covered' in detail
                    assert 'hit_count' in detail


class TestCliFlags:
    """Test CLI argument parsing for agent mode."""

    def test_help_includes_agent_flags(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, '-m', 'slipcover', '--help'],
            capture_output=True,
            text=True
        )

        assert '--agent-mode' in result.stdout
        assert '--track-hits' in result.stdout
        assert '--track-timestamps' in result.stdout
        assert '--trace-execution' in result.stdout
        assert '--detail' in result.stdout
        assert '--git-baseline' in result.stdout
        assert '--history-file' in result.stdout
        assert '--show-trends' in result.stdout
