from typing import Any
from .slipcover import Slipcover, VERSION
from . import branch as br
from . import bytecode as bc
from pathlib import Path
import sys

from importlib.abc import MetaPathFinder, Loader
from importlib.machinery import SourceFileLoader

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
        if self.sci.branch and isinstance(self.orig_loader, SourceFileLoader) and self.origin.exists():
            t = br.preinstrument(ast.parse(self.origin.read_text()))
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


class SlipcoverMetaPathFinder(MetaPathFinder):
    def __init__(self, sci, file_matcher, debug=False):
        self.debug = debug
        self.sci = sci
        self.file_matcher = file_matcher
        self.meta_path = sys.meta_path.copy()

    def find_spec(self, fullname, path, target=None):
        if self.debug:
            print(f"Looking for {fullname}")
        for f in self.meta_path:
            found = f.find_spec(fullname, path, target) if hasattr(f, 'find_spec') else None
            if found:
                if found.origin and self.file_matcher.matches(found.origin):
                    if self.debug:
                        print(f"adding {fullname} from {found.origin}")
                    found.loader = SlipcoverLoader(self.sci, found.loader, found.origin)
                return found

        return None


class ImportManager:
    """A context manager that enables instrumentation while active."""

    def __init__(self, sci: Slipcover, file_matcher: FileMatcher = None, debug: bool = False):
        self.mpf = SlipcoverMetaPathFinder(sci, file_matcher if file_matcher else FileMatcher(), debug)

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
    def exec_wrapper(obj, g):
        if hasattr(obj, 'co_filename') and file_matcher.matches(obj.co_filename):
            obj = sci.instrument(obj)
        exec(obj, g)

    try:
        import _pytest.assertion.rewrite as pyrewrite
    except ModuleNotFoundError:
        return

    for f in Slipcover.find_functions(pyrewrite.__dict__.values(), set()):
        if 'exec' in f.__code__.co_names:
            ed = bc.Editor(f.__code__)
            wrapper_index = ed.add_const(exec_wrapper)
            ed.replace_global_with_const('exec', wrapper_index)
            f.__code__ = ed.finish()

    if sci.branch:
        from inspect import signature

        expected_sigs = {
            'rewrite_asserts': ['mod', 'source', 'module_path', 'config'],
            '_read_pyc': ['source', 'pyc', 'trace'],
            '_write_pyc': ['state', 'co', 'source_stat', 'pyc']
        }

        for fun, expected in expected_sigs.items():
            sig = signature(pyrewrite.__dict__[fun])
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
