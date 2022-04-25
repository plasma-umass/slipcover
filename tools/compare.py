# Compares the "missing" attribute of files in a coverage.py
# (or slipcover) JSON output.

import json
import sys

file = (sys.argv[1], sys.argv[2])
data = [None, None]

for i in [0, 1]:
    with open(file[i], "r") as f:
        data[i] = json.load(f)

def merge_consecutives(L):
    # Neat little trick due to John La Rooy: the difference between the numbers
    # on a list and a counter is constant for consecutive items :)
    from itertools import groupby, count

    groups = groupby(sorted(L), key=lambda item, c=count(): item - next(c))
    return [
        str(g[0]) if g[0] == g[-1] else f"{g[0]}-{g[-1]}"
        for g in [list(g) for _, g in groups]
    ]

for (f_name, f0_cover) in data[0]['files'].items():
    if f_name in data[1]['files']:
        for item in ('executed_lines', 'missing_lines'):
            f0_item = set(f0_cover[item])
            f1_item = set(data[1]['files'][f_name][item])
            if f0_item != f1_item:
                print(f"{f_name}  {item}  differs:")
                if f0_item - f1_item:
                    print(f"    only in {file[0]}: {merge_consecutives(f0_item - f1_item)}")
                if f1_item - f0_item:
                    print(f"    only in {file[1]}: {merge_consecutives(f1_item - f0_item)}")
                print("")

def is_pytest(filename):
    from pathlib import Path
    import re

    p = Path(filename)
    # pytest file conventions
    if p.name == 'conftest.py' or re.match(r"test_.*\.py$", p.name) or re.match(r".*_test\.py$", p.name):
           return True

#    with open(filename, "r") as f:
#        if re.search(r"^(import pytest|from pytest )", f.read(), re.M):
#            return True

    return False

for is_test in [False, True]:
    for i in [0, 1]:
        other = 1-i
        any = False

        for f_name in sorted(data[i]['files'].keys() - data[other]['files'].keys()):
            if is_pytest(f_name) != is_test:
                continue

            if not any:
                print(("tests " if is_test else "") + f"only in {file[i]}:")
                any = True

            print(f"    {f_name}")

        if any:
            print("")
