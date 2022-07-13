import json
from statistics import median
import packaging.version
import matplotlib.pyplot as plt
import sys

BENCHMARK_JSON = 'benchmarks/benchmarks.json'

with open(BENCHMARK_JSON, 'r') as f:
    entries = json.load(f)

entries = [e for e in entries if e['system']['os'][0] == 'Linux']

systems = set([(' '.join(e['system']['os']), e['system']['cpu']) for e in entries])
assert len(systems) == 1    # don't mix results across different systems
print("system: ", systems)

v2r = {e['system']['python']: e['results'] for e in entries}

python_versions = sorted(v2r.keys(), key=lambda x: packaging.version.parse(x))
print("versions: ", python_versions)

case_sets = [set(r.keys()) for r in v2r.values()]
cases = list(case_sets[0].intersection(*case_sets[1:]))
print("cases: ", cases)

# all should have the same cases
assert sorted(cases) == sorted(v2r[python_versions[0]].keys())

bench_sets = [set(b.keys()) for r in v2r.values() for b in r.values()]
benchmarks = list(bench_sets[0].intersection(*bench_sets[1:]))
print("common benchmarks: ", benchmarks)

all_benchmarks = bench_sets[0].union(*bench_sets[1:])
for v in python_versions:
    for c in cases:
        missing = all_benchmarks - set(v2r[v][c].keys())
        if len(missing):
            print(f"  missing from {v} {c}: ", missing)

for v in python_versions:
    for c in cases:
        for b in benchmarks:
            m = v2r[v][c][b]
            m['median'] = median(m['times'])

fig, ax = plt.subplots(3, 1, figsize=(10, 15))

max_v = None
min_v = None

first = python_versions[0]

for i, c in enumerate(sorted(cases)):
    ax[i].set_title(c)
    for b in benchmarks:
        values = [v2r[v][c][b]['median']/v2r[first]['base'][b]['median'] for v in python_versions]
        ax[i].plot(python_versions, values, label=b)

        if max_v is None or max_v < max(values):
            max_v = max(values)
        if min_v is None or min_v > min(values):
            min_v = min(values)

    ax[i].legend()
    ax[i].set_ylabel('Normalized execution time')

for i in range(len(cases)):
    ax[i].set_ylim([min_v, max_v])

fig.tight_layout()
fig.savefig("benchmarks/versions.png")

from tabulate import tabulate

def get_comparison():
    for b in benchmarks:
        yield [b, round(v2r[python_versions[-2]]['base'][b]['median'], 2),
               round(v2r[python_versions[-1]]['slipcover'][b]['median'], 2)]

print(tabulate(get_comparison(), headers=["bench", python_versions[-2],
                                          f"{python_versions[-1]} + slipcover"]))
