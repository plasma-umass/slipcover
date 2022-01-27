import numpy as np
import matplotlib.pyplot as plt
import pickle
import re
from pathlib import Path
from collections import namedtuple

BENCHMARK_FILE = 'benchmark/benchmark.pkl'

def run_command(command: str):
    import subprocess

    print(command)
    cmd = "time -p " + command
    p = subprocess.run(("time -p " + command).split(), capture_output=True)

    user_time = re.search(b'^user *([\\d\\.]+)$', p.stderr, re.M)
    sys_time = re.search(b'^sys *([\\d\\.]+)$', p.stderr, re.M)

    if not (user_time and sys_time):
        raise RuntimeError("Unable to parse " + str(p.stderr))

    results = (float(user_time.group(1)), float(sys_time.group(1)))
    print(results)

    return results


try:
    with open(BENCHMARK_FILE, 'rb') as f:
        results = pickle.load(f)

except FileNotFoundError:
    results = dict()

Case = namedtuple('Case', 'name command')

cases = [Case("(no coverage)", "python3 {bench}"),
         Case("coverage.py", "python3 -m coverage run --include={bench} {bench}"),
         Case("Slipcover", "python3 -m slipcover {bench}")
]

for case in cases:
    if case.name not in results:
        results[case.name] = dict()  # can't pickle defaultdict(lambda: dict())

Benchmark = namedtuple('Benchmark', 'name file')

def path2name(p: Path) -> str:
    match = re.search('^(bm_)?(.*?)\.py$', p.name)
    return match.group(2) if match else p.name

benchmarks = [Benchmark(path2name(p), p) for p in [
                *Path('benchmark').glob('bm_*.py'), Path('test/testme.py')]]

ran_any = False
for case in cases:
    for bench in benchmarks:
        if bench.name in results[case.name] and case.name != 'Slipcover':
            continue

        results[case.name][bench.name] = run_command(case.command.format(bench=bench.file))
        ran_any = True

if ran_any:
    with open(BENCHMARK_FILE, 'wb') as f:
        pickle.dump(results, f, pickle.HIGHEST_PROTOCOL)


base = cases[0]
base_times = [sum(results[base.name][b.name]) for b in benchmarks]
for case in cases:
    if case == base:
        continue

    times = [sum(results[case.name][b.name]) for b in benchmarks]
    rel_times = [((t/bt)-1)*100 for t, bt in zip(times, base_times)]

    print(f"Overhead for {case.name}: {min(rel_times):.0f}% - {max(rel_times):.0f}%")

x = np.arange(len(benchmarks))
n_bars = len(cases)
width = .70 # of all bars
bars_x = np.arange(width/n_bars/2, width, width/n_bars) - width/2

fig, ax = plt.subplots()
for case, bar_x in zip(cases, bars_x):
    rects = ax.bar(x + bar_x, [sum(results[case.name][b.name]) for b in benchmarks],
                   width/n_bars, label=case.name)
    ax.bar_label(rects, padding=3)

#ax.set_title('Execution time')
ax.set_ylabel('CPU seconds')
ax.set_xticks(x, labels=[b.name for b in benchmarks])
ax.legend()

fig.tight_layout()
fig.savefig("benchmark.png")
