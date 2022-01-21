import sys
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict
from slipcover import slipcover as sc


from importlib.abc import MetaPathFinder, Loader
from importlib.util import spec_from_loader

class SlipcoverLoader(Loader):
    def __init__(self, orig_loader):
        self.orig_loader = orig_loader

    def create_module(self, spec):
        return self.orig_loader.create_module(spec)

    def exec_module(self, module):
        code = self.orig_loader.get_code(module.__name__)
        code = sc.instrument(code)
        exec(code, module.__dict__)

class SlipcoverMetaPathFinder(MetaPathFinder):
    def __init__(self, script_path, meta_path):
        self.script_path = script_path
        self.meta_path = meta_path

    def find_spec(self, fullname, path, target=None):
#        print(f"Looking for {fullname}")
        for f in self.meta_path:
            found = f.find_spec(fullname, path, target)
            if (found):
                # instrument iff the module's path is related to the original script's
                if self.script_path in Path(found.origin).parents:
                    found.loader = SlipcoverLoader(found.loader)
                return found

        return None


# python 'globals' for the script being executed
script_globals: Dict[str, Any] = defaultdict(None)

def setup_deinstrument():
    import atexit
    import signal
    
    INTERVAL = 0.1

    atexit.register(sc.print_coverage)

    def deinstrument_callback(signum, this_frame):
        """Periodically de-instruments lines that were already reached."""
        nonlocal INTERVAL

        sc.deinstrument_seen(script_globals)

        # Increase the interval geometrically
        INTERVAL *= 2
        signal.setitimer(signal.ITIMER_VIRTUAL, INTERVAL)

    signal.siginterrupt(signal.SIGVTALRM, False)
    signal.signal(signal.SIGVTALRM, deinstrument_callback)
    signal.setitimer(signal.ITIMER_VIRTUAL, INTERVAL)

sys.argv = sys.argv[1:] # delete ourselves so as not to confuse others

import argparse
ap = argparse.ArgumentParser(prog='slipcover')
ap_g = ap.add_mutually_exclusive_group(required=True)
ap_g.add_argument('script', nargs='?', help="run script")
ap_g.add_argument('-m', dest='module', nargs=argparse.REMAINDER, help="run module")
args = ap.parse_args(sys.argv)

base_path = Path(args.script).resolve().parent if args.script \
            else Path('.').resolve()

sys.meta_path = [SlipcoverMetaPathFinder(base_path, sys.meta_path)]

if args.script:
    # needed so that the script being invoked behaves like the main one
    script_globals['__name__'] = '__main__'
    script_globals['__file__'] = args.script

    # the 1st item in sys.path is always the main script's directory
    sys.path.pop(0)
    sys.path.insert(0, str(base_path))

    with open(args.script, "r") as f:
        code = compile(f.read(), args.script, "exec")

    code = sc.instrument(code)

    setup_deinstrument()
    exec(code, script_globals)
else:
    assert args.module
    import runpy
    sys.argv = args.module
    setup_deinstrument()
    runpy.run_module(args.module[0], run_name='__main__', alter_sys=True)
