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

for v in python_versions:
    for c in cases:
        for m in v2r[v][c].values():
            if not isinstance(m, dict): continue    # skip over some old-style entries (e.g., "testme")
            m['median'] = median(m['times'])

fig, ax = plt.subplots(3, 1, figsize=(10, 15))

first = python_versions[0]

for i, c in enumerate(sorted(cases)):
    ax[i].set_title(c)
    for b in benchmarks:
        values = [v2r[v][c][b]['median']/v2r[first]['base'][b]['median'] for v in python_versions]
        ax[i].plot(python_versions, values, label=b)

    ax[i].legend()
    ax[i].set_ylabel('Normalized execution time')

fig.tight_layout()
fig.savefig("benchmarks/versions.png")
