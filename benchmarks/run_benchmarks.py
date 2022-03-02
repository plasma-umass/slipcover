import pickle
import re
from pathlib import Path
from collections import namedtuple
from statistics import median

# XXX change to saving/restoring from json
# XXX save/restore on a per-system basis

BENCHMARK_FILE = 'benchmarks/benchmarks.pkl'
TRIES = 5

Case = namedtuple('Case', 'name command')

python = 'python3'

cases = [Case("(no coverage)", python + " {bench}"),
         Case("coverage.py", python + " -m coverage run --include={bench} {bench}"),
         Case("Slipcover", python + " -m slipcover {bench}")
]
base = cases[0]


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
    print(results, round(sum(results), 1))

    return sum(results)


def parse_args():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--rerun-case', choices=['all', 'none', *[c.name for c in cases]],
                    default='Slipcover', help='select "case"(s) to re-run')
    ap.add_argument('--rerun-bench', type=str, default=None, help='select benchmark to re-run')
    return ap.parse_args()

args = parse_args()


try:
    with open(BENCHMARK_FILE, 'rb') as f:
        results = pickle.load(f)

except FileNotFoundError:
    results = dict()


for case in cases:
    if case.name not in results:
        results[case.name] = dict()  # can't pickle defaultdict(lambda: dict())

Benchmark = namedtuple('Benchmark', 'name file')

def path2name(p: Path) -> str:
    match = re.search('^(bm_)?(.*?)\.py$', p.name)
    return match.group(2) if match else p.name

benchmarks = [Benchmark(path2name(p), p) for p in sorted(Path('benchmarks').glob('bm_*.py'))]


def overhead(time, base_time):
    return ((time/base_time)-1)*100


ran_any = False
for case in cases:
    for bench in benchmarks:
        if bench.name in results[case.name]:
            if args.rerun_case != 'all' and args.rerun_case != case.name:
                continue

            if args.rerun_bench and args.rerun_bench != bench.name:
                continue

        r = []
        for _ in range(TRIES):
            r.append(run_command(case.command.format(bench=bench.file)))

        results[case.name][bench.name] = r

        m = median(r)
        b_m = median(results[base.name][bench.name])
        print(f"median: {m:.1f}  +{overhead(m, b_m):.1f}%")

        ran_any = True

if ran_any:
    with open(BENCHMARK_FILE, 'wb') as f:
        pickle.dump(results, f, pickle.HIGHEST_PROTOCOL)

def print_results():
    from tabulate import tabulate

    def get_stats():
        from math import sqrt
        from statistics import mean, stdev

        for bench in benchmarks:
            for case in cases:
                r = results[case.name][bench.name]
                oh = round(overhead(median(r), median(results[base.name][bench.name])),1) \
                        if case != base else None
                yield [bench.name, case.name, round(median(r),2), round(mean(r),2),
                       round(stdev(r),2),
                       round(stdev(r)/sqrt(len(r)),2), oh]

    print(tabulate(get_stats(), headers=["bench", "case", "median", "mean", "stdev",
                                         "SE", "overhead %"]))
    print("")

    base_times = [median(results[base.name][b.name]) for b in benchmarks]
    rel_times = dict()
    for case in cases:
        if case == base:
            continue

        times = [median(results[case.name][b.name]) for b in benchmarks]
        rel_times[case.name] = [overhead(t, bt) for t, bt in zip(times, base_times)]

        print(f"Overhead for {case.name}: {min(rel_times[case.name]):.0f}% - " +
                                        f"{max(rel_times[case.name]):.0f}%")

    diff_times = [cover - slip for cover, slip in zip(rel_times['coverage.py'],
                                                      rel_times['Slipcover'])]
    print(f"Slipcover savings: {min(diff_times):.0f}% - {max(diff_times):.0f}%")

print_results()

def plot_results():
    import numpy as np
    import matplotlib.pyplot as plt

    x = np.arange(len(benchmarks))
    n_bars = len(cases)
    width = .70 # of all bars
    bars_x = np.arange(width/n_bars/2, width, width/n_bars) - width/2

    fig, ax = plt.subplots()
    for case, bar_x in zip(cases, bars_x):
        rects = ax.bar(x + bar_x, [round(median(results[case.name][b.name]),1) for b in benchmarks],
                       width/n_bars, label=case.name)
#        ax.boxplot([results[case.name][b.name] for b in benchmarks],
#                   positions=x+bar_x, widths=width/n_bars, showfliers=False,
#                   medianprops={'color': 'black'},
#                   labels=[case.name] * len(benchmarks),
#        )
        ax.bar_label(rects, padding=3)

    #ax.set_title('Execution time')
    ax.set_ylabel('CPU seconds')
    ax.set_xticks(x, labels=[b.name for b in benchmarks])
    ax.legend()

    fig.tight_layout()
    fig.savefig("benchmarks/benchmarks.png")

plot_results()
