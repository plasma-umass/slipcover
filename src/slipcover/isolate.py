import os
import pytest
import sys
from pathlib import Path


class IsolatePlugin:
    """Pytest plugin to isolate test collection, so that if a test's collection pollutes the in-memory
       state, it doesn't affect the execution of other tests."""

    def __init__(self):
        self._is_child = False
        self._test_failed = False

    def pytest_ignore_collect(self, path, config):
        if self._is_child:
            return True

        if (pid := os.fork()):
            pid, status = os.waitpid(pid, 0)
            if status:
                if os.WIFSIGNALED(status):
                    exitstatus = os.WTERMSIG(status) + 128
                else:
                    exitstatus = os.WEXITSTATUS(status)
            else:
                exitstatus = 0

            if exitstatus not in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED):
                self._test_failed = True

            return True
        else:
            self._is_child = True
            return False

    def pytest_collectreport(self, report):
        if self._is_child and report.failed and report.nodeid.endswith('.py'):
            self._test_failed = True

    def pytest_runtest_logreport(self, report):
        if self._is_child and report.failed:
            self._test_failed = True

    def pytest_unconfigure(self, config):
        if self._is_child:
            os._exit(self.get_exit_code())

    def get_exit_code(self):
        # FIXME this error handling is very simplistic, extend to other cases
        return pytest.ExitCode.TESTS_FAILED if self._test_failed else pytest.ExitCode.OK


def preload_pytest_plugins():
    """Preloads pytest plugins, in an attempt to speed things up."""
    import pkg_resources
    import importlib
    import warnings

    for ep in pkg_resources.iter_entry_points(group='pytest11'):
        try:
            importlib.import_module(ep.module_name)
        except ImportError as e:
            warnings.warn(e)


if __name__ == "__main__":
    preload_pytest_plugins()

    plugin = IsolatePlugin()
    exitcode = pytest.main(sys.argv[1:] + ['--forked'], plugins=[plugin])
    if exitcode in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED):
        exitcode = plugin.get_exit_code()

    sys.exit(exitcode)
