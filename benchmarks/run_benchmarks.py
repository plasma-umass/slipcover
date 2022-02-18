import numpy as np
import matplotlib.pyplot as plt
import pickle
import re
from pathlib import Path
from collections import namedtuple

BENCHMARK_FILE = 'benchmarks/benchmarks.pkl'

def run_command(command: str):
    import subprocess

    print(command)
    cmd = "time -p " + command
    p = subprocess.run(("time -p " + command).split(), capture_output=True, check=True)

    user_time = re.search(b'^user *([\\d\\.]+)$', p.stderr, re.M)
    sys_time = re.search(b'^sys *([\\d\\.]+)$', p.stderr, re.M)

    if not (user_time and sys_time):
        raise RuntimeError("Unable to parse " + str(p.stderr))

    results = (float(user_time.group(1)), float(sys_time.group(1)))
    print(results, sum(results))

    return sum(results)


try:
    with open(BENCHMARK_FILE, 'rb') as f:
        results = pickle.load(f)

except FileNotFoundError:
    results = dict()

Case = namedtuple('Case', 'name command')

python = 'python3.9'

cases = [Case("(no coverage)", python + " {bench}"),
         Case("coverage.py", python + " -m coverage run --include={bench} {bench}"),
         Case("Slipcover", python + " -m slipcover {bench}")
]

for case in cases:
    if case.name not in results:
        results[case.name] = dict()  # can't pickle defaultdict(lambda: dict())

Benchmark = namedtuple('Benchmark', 'name file')

def path2name(p: Path) -> str:
    match = re.search('^(bm_)?(.*?)\.py$', p.name)
    return match.group(2) if match else p.name

benchmarks = [Benchmark(path2name(p), p) for p in sorted(Path('benchmarks').glob('bm_*.py'))]

ran_any = False
for case in cases:
    for bench in benchmarks:
        if bench.name in results[case.name] and case.name != 'Slipcover':
            continue

        r = []
        for _ in range(3):
            r.append(run_command(case.command.format(bench=bench.file)))

#        results[case.name][bench.name] = sum(r)/len(r)
        results[case.name][bench.name] = min(r)

        ran_any = True

if ran_any:
    with open(BENCHMARK_FILE, 'wb') as f:
        pickle.dump(results, f, pickle.HIGHEST_PROTOCOL)


base = cases[0]
base_times = [results[base.name][b.name] for b in benchmarks]
rel_times = dict()
for case in cases:
    if case == base:
        continue

    times = [results[case.name][b.name] for b in benchmarks]
    rel_times[case.name] = [((t/bt)-1)*100 for t, bt in zip(times, base_times)]

    print(f"Overhead for {case.name}: {min(rel_times[case.name]):.0f}% - {max(rel_times[case.name]):.0f}%")

diff_times = [cover - slip for cover, slip in zip(rel_times['coverage.py'], rel_times['Slipcover'])]
print(f"Slipcover savings: {min(diff_times):.0f}% - {max(diff_times):.0f}%")

x = np.arange(len(benchmarks))
n_bars = len(cases)
width = .70 # of all bars
bars_x = np.arange(width/n_bars/2, width, width/n_bars) - width/2

fig, ax = plt.subplots()
for case, bar_x in zip(cases, bars_x):
    rects = ax.bar(x + bar_x, [round(results[case.name][b.name], 1) for b in benchmarks],
                   width/n_bars, label=case.name)
    ax.bar_label(rects, padding=3)

#ax.set_title('Execution time')
ax.set_ylabel('CPU seconds')
ax.set_xticks(x, labels=[b.name for b in benchmarks])
ax.legend()

fig.tight_layout()
fig.savefig("benchmarks/benchmarks.png")
