# Compares the "missing" attribute of files in a coverage.py
# (or slipcover) JSON output.

import json
import sys

file = (sys.argv[1], sys.argv[2])
data = [None, None]

for i in [0, 1]:
    with open(file[i], "r") as f:
        data[i] = json.load(f)

for (f_name, f0_cover) in data[0]['files'].items():
    if f_name in data[1]['files']:
        f0_miss = set(f0_cover['missing_lines'])
        f1_miss = set(data[1]['files'][f_name]['missing_lines'])
        if f0_miss != f1_miss:
            print(f"{f_name} differs:")
            if f0_miss - f1_miss:
                print(f"    only in {file[0]}: {list(f0_miss - f1_miss)}")
            if f1_miss - f0_miss:
                print(f"    only in {file[1]}: {list(f1_miss - f0_miss)}")
            print("")

for i in [0, 1]:
    other = 1-i
    any = False

    for f_name in sorted(data[i]['files'].keys() - data[other]['files'].keys()):
        if not any:
            print("")
            print(f"only in {file[i]}:")
            any = True

        print(f"    {f_name}")
