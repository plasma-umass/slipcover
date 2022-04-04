import dis
from sys import argv
import argparse

ap = argparse.ArgumentParser(prog=argv[0])
ap.add_argument('--instrument', action='store_true', help="instrument with slipcover")
ap.add_argument('file', help="the script to run")
args = ap.parse_args()

with open(args.file, "r") as f:
    code = compile(f.read(), argv[1], "exec")
    if (args.instrument):
        from slipcover import slipcover as sc
        sci = sc.Slipcover()
        code = sci.instrument(code)
    dis.dis(code)
