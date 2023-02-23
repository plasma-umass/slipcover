import dis
import sys
import argparse

ap = argparse.ArgumentParser(prog=sys.argv[0])
ap.add_argument('--instrument', action='store_true', help="instrument with slipcover")
ap.add_argument('--branch', action='store_true', help="pre-instrument for branch coverage")
ap.add_argument('file', help="the script to run")
args = ap.parse_args()

def decode_linetable(co):
    def read_varint(it):
        v = 0
        while (b := next(it)) & 0x40:
            assert b & 0b10000000 == 0;
            v = (v | (b & 0x3F)) << 6
        v = v | b
        return v

    def read_svarint(it):
        v = read_varint(it)
        return -(v >> 1) if v & 1 else v >> 1

    print("")

    off = 0
    line = co.co_firstlineno
    it = iter(co.co_linetable)
    while (b := next(it, None)) != None:
        assert b & 0b10000000;
        code = (b & 0b1111000)>>3
        length = (b & 0b111) + 1
        if code <= 9:
            b = next(it)
            col_start = (code*8) + ((b>>4)&7)
            col_end = col_start + (b&15)
            print(f"{off:-6} line={line} col={col_start}-{col_end} code={code}")
        elif code <= 12:
            line += (code - 10)
            col_start = next(it)
            col_end = next(it)
            print(f"{off:-6} line={line} col={col_start}-{col_end} code={code}")
        elif code == 13:
            line += read_svarint(it)
            print(f"{off:-6} line={line} code={code}")
        elif code == 14:
            line_start = line + read_svarint(it)
            line = line_start + read_varint(it)
            col_start = read_varint(it)
            col_end = read_varint(it)
            print(f"{off:-6} line={line_start}-{line} col={col_start}-{col_end} code={code}")
        else:
            print(f"{off:-6} line=None code={code}")
        off += 2*length


import ast

with open(args.file, "r") as f:
    t = ast.parse(f.read())

if args.branch:
    import slipcover.branch as br
    t = br.preinstrument(t)

code = compile(t, args.file, "exec")

if args.instrument:
    import slipcover as sc
    sci = sc.Slipcover(branch=args.branch)
    code = sci.instrument(code)

dis.dis(code)

if sys.version_info[0:2] >= (3,11):
    decode_linetable(code)

