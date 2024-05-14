import pytest
import sys


class IsolateItem(pytest.Item):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def runtest(self):
        assert False, "should never execute"

    def run_forked(self):
        # adapted from pytest-forked
        import marshal
        import pytest_forked as ptf
        import _pytest
        import py

        ihook = self.ihook
        ihook.pytest_runtest_logstart(nodeid=self.nodeid, location=self.location)

        def runforked():
            module = pytest.Module.from_parent(parent=self.parent, path=self.path)
            reports = list()
            for it in module.collect():
                reports.extend(ptf.forked_run_report(it))
            print(reports)
            return marshal.dumps([ptf.serialize_report(x) for x in reports])

        ff = py.process.ForkedFunc(runforked)
        result = ff.waitfinish()

        if result.retval is not None:
            reports = [_pytest.runner.TestReport(**r) for r in marshal.loads(result.retval)]
        else:
            reports = [ptf.report_process_crash(self, result)]

        for r in reports:
            ihook.pytest_runtest_logreport(report=r)

        ihook.pytest_runtest_logfinish(nodeid=self.nodeid, location=self.location)


class IsolateModule(pytest.Module):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def collect(self):
        yield IsolateItem.from_parent(parent=self, name="(module)")


class IsolatePlugin:
    """Pytest plugin to isolate test collection, so that if a test's collection pollutes the in-memory
       state, it doesn't affect the execution of other tests."""

    @pytest.hookimpl(tryfirst=True)
    def pytest_pycollect_makemodule(self, module_path, parent):
         return IsolateModule.from_parent(parent, path=module_path)

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtestloop(self, session):
        for item in session.items:
            item.run_forked()
        return True


if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:], plugins=[IsolatePlugin()]))
