from typing import Any
from .slipcover import Slipcover, VERSION
from . import branch as br
from pathlib import Path
import sys

from importlib.abc import MetaPathFinder, Loader
from importlib import machinery

class SlipcoverLoader(Loader):
    def __init__(self, sci: Slipcover, orig_loader: Loader, origin: str):
        self.sci = sci                  # Slipcover object measuring coverage
        self.orig_loader = orig_loader  # original loader we're wrapping
        self.origin = Path(origin)      # module origin (source file for a source loader)

        # loadlib checks for this attribute to see if we support it... keep in sync with orig_loader
        if not getattr(self.orig_loader, "get_resource_reader", None):
            delattr(self, "get_resource_reader")

    # for compability with loaders supporting resources, used e.g. by sklearn
    def get_resource_reader(self, fullname: str):
        return self.orig_loader.get_resource_reader(fullname)

    def create_module(self, spec):
        return self.orig_loader.create_module(spec)

    def get_code(self, name):   # expected by pyrun
        return self.orig_loader.get_code(name)

    def exec_module(self, module):
        import ast
        # branch coverage requires pre-instrumentation from source
        if self.sci.branch and isinstance(self.orig_loader, machinery.SourceFileLoader) and self.origin.exists():
            t = br.preinstrument(ast.parse(self.origin.read_bytes()))
            code = compile(t, str(self.origin), "exec")
        else:
            code = self.orig_loader.get_code(module.__name__)

        self.sci.register_module(module)
        code = self.sci.instrument(code)
        exec(code, module.__dict__)


class FileMatcher:
    def __init__(self):
        self.cwd = Path.cwd()
        self.sources = []
        self.omit = []

        import inspect  # usually in Python lib
        # pip is usually in site-packages; importing it causes warnings

        self.pylib_paths = [Path(inspect.__file__).parent] + \
                           [Path(p) for p in sys.path if (Path(p) / "pip").exists()]

    def addSource(self, source : Path):
        if isinstance(source, str):
            source = Path(source)
        if not source.is_absolute():
            source = self.cwd / source
        self.sources.append(source)

    def addOmit(self, omit):
        if not omit.startswith('*'):
            omit = self.cwd / omit

        self.omit.append(omit)

    def matches(self, filename : Path):
        if filename is None:
            return False

        if isinstance(filename, str):
            if filename == 'built-in': return False     # can't instrument
            filename = Path(filename)

        if filename.suffix in ('.pyd', '.so'): return False  # can't instrument DLLs

        if not filename.is_absolute():
            filename = self.cwd / filename

        if self.omit:
            from fnmatch import fnmatch
            if any(fnmatch(filename, o) for o in self.omit):
                return False

        if self.sources:
            return any(s in filename.parents for s in self.sources)

        if any(p in self.pylib_paths for p in filename.parents):
            return False

        return self.cwd in filename.parents


class MatchEverything:
    def __init__(self):
        pass

    def matches(self, filename : Path):
        return True


class SlipcoverMetaPathFinder(MetaPathFinder):
    def __init__(self, sci, file_matcher, debug=False):
        self.debug = debug
        self.sci = sci
        self.file_matcher = file_matcher

    def find_spec(self, fullname, path, target=None):
        if self.debug:
            print(f"Looking for {fullname}")

        for f in sys.meta_path:
            # skip ourselves
            if isinstance(f, SlipcoverMetaPathFinder):
                continue

            if not hasattr(f, "find_spec"):
                continue

            spec = f.find_spec(fullname, path, target)
            if spec is None or spec.loader is None:
                continue

            # can't instrument extension files
            if isinstance(spec.loader, machinery.ExtensionFileLoader):
                return None

            if self.file_matcher.matches(spec.origin):
                if self.debug:
                    print(f"instrumenting {fullname} from {spec.origin}")
                spec.loader = SlipcoverLoader(self.sci, spec.loader, spec.origin)

            return spec

        return None


class ImportManager:
    """A context manager that enables instrumentation while active."""

    def __init__(self, sci: Slipcover, file_matcher: FileMatcher = None, debug: bool = False):
        self.mpf = SlipcoverMetaPathFinder(sci, file_matcher if file_matcher else MatchEverything(), debug)

    def __enter__(self) -> "ImportManager":
        sys.meta_path.insert(0, self.mpf)
        return self

    def __exit__(self, *args: Any) -> None:
        i = 0
        while i < len(sys.meta_path):
            if sys.meta_path[i] is self.mpf:
                sys.meta_path.pop(i)
                break
            i += 1


def wrap_pytest(sci: Slipcover, file_matcher: FileMatcher):
    def redirect_calls(module, funcName, funcWrapperName):
        """Redirects calls to the given function to a wrapper function in the same module."""
        import ast
        import types

        assert funcWrapperName not in module.__dict__, f"function {funcWrapperName} already defined"

        with open(module.__file__) as f:
            t = ast.parse(f.read())

        funcNames = set() # names of the functions we modified
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for s in ast.walk(n):
                    if isinstance(s, ast.Call) and isinstance(s.func, ast.Name) and s.func.id == funcName:
                        s.func.id = funcWrapperName
                        funcNames.add(n.name)

        code = compile(t, module.__file__, "exec")

        # It's tempting to just exec(code, module.__dict__) here, but the code often times has side effects...
        # So instead of we find the new code object(s) and replace them in the loaded module.

        replacement = dict() # replacement code objects
        def find_replacements(co):
            for c in co.co_consts:
                if isinstance(c, types.CodeType):
                    if c.co_name in funcNames:
                        replacement[c.co_name] = c
                    find_replacements(c)

        find_replacements(code)

        visited = set()
        for f in Slipcover.find_functions(module.__dict__.values(), visited):
            if (repl := replacement.get(f.__code__.co_name, None)):
                assert f.__code__.co_firstlineno == repl.co_firstlineno # sanity check
                f.__code__ = repl


    try:
        import _pytest.assertion.rewrite as pyrewrite
    except ModuleNotFoundError:
        return

    redirect_calls(pyrewrite, "exec", "_Slipcover_exec_wrapper")

    def exec_wrapper(obj, g):
        if hasattr(obj, 'co_filename') and file_matcher.matches(obj.co_filename):
            obj = sci.instrument(obj)
        exec(obj, g)

    pyrewrite._Slipcover_exec_wrapper = exec_wrapper

    if sci.branch:
        import inspect

        expected_sigs = {
            'rewrite_asserts': ['mod', 'source', 'module_path', 'config'],
            '_read_pyc': ['source', 'pyc', 'trace'],
            '_write_pyc': ['state', 'co', 'source_stat', 'pyc']
        }

        for fun, expected in expected_sigs.items():
            sig = inspect.signature(pyrewrite.__dict__[fun])
            if list(sig.parameters) != expected:
                import warnings
                warnings.warn(f"Unable to activate pytest branch coverage: unexpected {fun} signature {str(sig)}"
                              +"; please open an issue at https://github.com/plasma-umass/slipcover .",
                              RuntimeWarning)
                return

        orig_rewrite_asserts = pyrewrite.rewrite_asserts
        def rewrite_asserts_wrapper(*args):
            # FIXME we should normally subject pre-instrumentation to file_matcher matching...
            # but the filename isn't clearly available. So here we instead always pre-instrument
            # (pytest instrumented) files. Our pre-instrumentation adds global assignments that
            # *should* be innocuous if not followed by sci.instrument.
            args = (br.preinstrument(args[0]), *args[1:])
            return orig_rewrite_asserts(*args)

        def adjust_name(fn : Path) -> Path:
            return fn.parent / (fn.stem + "-slipcover-" + VERSION + fn.suffix)

        orig_read_pyc = pyrewrite._read_pyc
        def read_pyc(*args, **kwargs):
            return orig_read_pyc(*args[:1], adjust_name(args[1]), *args[2:], **kwargs)

        orig_write_pyc = pyrewrite._write_pyc
        def write_pyc(*args, **kwargs):
            return orig_write_pyc(*args[:3], adjust_name(args[3]), *args[4:], **kwargs)

        pyrewrite._read_pyc = read_pyc
        pyrewrite._write_pyc = write_pyc
        pyrewrite.rewrite_asserts = rewrite_asserts_wrapper
