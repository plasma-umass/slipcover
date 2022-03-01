import sys
from pathlib import Path
from typing import Any, Dict
from slipcover import slipcover as sc
import atexit


from importlib.abc import MetaPathFinder, Loader
from importlib.util import spec_from_loader

class SlipcoverLoader(Loader):
    def __init__(self, sci, orig_loader):
        self.sci = sci
        self.orig_loader = orig_loader

    def create_module(self, spec):
        return self.orig_loader.create_module(spec)

    def exec_module(self, module):
        code = self.orig_loader.get_code(module.__name__)
        sci.register_module(module)
        code = sci.instrument(code)
        exec(code, module.__dict__)

class SlipcoverMetaPathFinder(MetaPathFinder):
    def __init__(self, sci, base_path, meta_path):
        self.sci = sci
        self.base_path = base_path
        self.meta_path = meta_path

        import inspect
        self.pylib_path = Path(inspect.getfile(inspect)).parent

    def find_spec(self, fullname, path, target=None):
#        print(f"Looking for {fullname}")
        for f in self.meta_path:
            found = f.find_spec(fullname, path, target)
            if (found):
                origin = Path(found.origin)
                # Can't instrument built-in or DLL based modules; and
                # probably shouldn't instrument python library modules, either.
                if found.origin != 'built-in' and origin.suffix != '.pyd' and \
                   self.pylib_path not in origin.parents and \
                   self.base_path in origin.parents:
                    global args;
                    if args.debug:
                        print(f"adding {fullname} from {found.origin}; pylib={self.pylib_path}")
                    found.loader = SlipcoverLoader(self.sci, found.loader)
                return found

        return None

#
# The intended usage is:
#
#   slipcover.py [options] (script | -m module [module_args...])
#
# but argparse doesn't seem to support this.  We work around that by only
# showing it what we need.
#
import argparse
ap = argparse.ArgumentParser(prog='slipcover', add_help=False)
ap.add_argument('--stats', action='store_true')
ap.add_argument('--debug', action='store_true')
ap.add_argument('--wrap-exec', action='store_true')
if '-m' in sys.argv:
    ap.add_argument('script', nargs=argparse.SUPPRESS)
    ap.add_argument('-m', dest='module', nargs=1, required=True)
    ap.add_argument('module_args', nargs=argparse.REMAINDER)

    minus_m = sys.argv.index('-m')
    args = ap.parse_args(sys.argv[1:minus_m+2])
    args.module_args = sys.argv[minus_m+2:]
else:
    ap.add_argument('script')
    ap.add_argument('script_args', nargs=argparse.REMAINDER)
    args = ap.parse_args(sys.argv[1:])

base_path = Path(args.script).resolve().parent if args.script \
            else Path('.').resolve()

sci = sc.Slipcover(collect_stats=args.stats)

if args.wrap_exec:
    import types
    import builtins

    orig_exec = builtins.exec
    def exec_wrapper(*p):
        if isinstance(p[0], types.CodeType) and '__slipcover__' not in p[0].co_consts:
            p = (sci.instrument(p[0]), *p[1:])
            # XXX add p[1] globals to those tracked by slipcover, like the modules?
        orig_exec(*p)

    builtins.exec = exec_wrapper

sys.meta_path = [SlipcoverMetaPathFinder(sci, base_path, sys.meta_path)]

atexit.register(lambda: sci.print_coverage())
sci.auto_deinstrument()

if args.script:
    # python 'globals' for the script being executed
    script_globals: Dict[Any, Any] = dict()

    # needed so that the script being invoked behaves like the main one
    script_globals['__name__'] = '__main__'
    script_globals['__file__'] = args.script

    sys.argv = [args.script, *args.script_args]

    # the 1st item in sys.path is always the main script's directory
    sys.path.pop(0)
    sys.path.insert(0, str(base_path))

    with open(args.script, "r") as f:
        code = compile(f.read(), str(Path(args.script).resolve()), "exec")

    code = sci.instrument(code)
    exec(code, script_globals)

else:
    import runpy
    sys.argv = [*args.module, *args.module_args]
    runpy.run_module(*args.module, run_name='__main__', alter_sys=True)
