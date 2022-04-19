import json
import re
from pathlib import Path
from collections import namedtuple
from statistics import median


BENCHMARK_JSON = 'benchmarks/benchmarks.json'
TRIES = 5
PYTHON = 'python3'

Case = namedtuple('Case', ['name', 'label', 'command'])

cases = [Case('base', "(no coverage)", PYTHON + " {bench_command}"),
         Case('coveragepy', "coveragepy", PYTHON + " -m coverage run {coveragepy_opts} {bench_command}"),
         Case('slipcover', "Slipcover", PYTHON + " -m slipcover {slipcover_opts} {bench_command}")
]
base = cases[0]

class Benchmark:
    def __init__(self, name, command, opts=None, cwd=None):
        self.name = name
        self.format = {'bench_command': command}
        for k in ['slipcover_opts', 'coveragepy_opts']:
            self.format[k] = opts[k] if opts and k in opts else ''
        self.cwd = cwd 


def run_command(command: str, cwd=None):
    import subprocess
    import resource

    print(command)

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    p = subprocess.run(command.split(), cwd=cwd, check=True) # capture_output=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)

    user_time = round(after.ru_utime - before.ru_utime, 2)
    sys_time = round(after.ru_stime - before.ru_stime, 2)
    results = (user_time, sys_time)

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


def load_results():
    def gen_sysid():
        import platform
        import cpuinfo  # pip3 install py-cpuinfo

        return {'python': platform.python_version(),
                'os': [platform.system(), platform.release()],
                'cpu': cpuinfo.get_cpu_info()['brand_raw']}


    try:
        with open(BENCHMARK_JSON, 'r') as f:
            saved_results = json.load(f)

    except FileNotFoundError:
        saved_results = []

    try:
        results = next(it['results'] for it in saved_results if it['system'] == gen_sysid())
        print(f"using {json.dumps(gen_sysid())}")
    except StopIteration:
        results = dict()
        saved_results.append({'system': gen_sysid(), 'results': results})

    return saved_results, results

saved_results, results = load_results()


def path2bench(p: Path) -> str:
    match = re.search('^(bm_)?(.*?)\.py$', p.name)
    bench_name = match.group(2) if match else p.name

    return Benchmark(bench_name, p, {'coveragepy_opts': f'--include={p}',
                                     'slipcover_opts': f'--source={p.parent}'})

benchmarks = [path2bench(p) for p in sorted(Path('benchmarks').glob('bm_*.py'))]
benchmarks.append(
    Benchmark('sklearn', '-m pytest sklearn', {
                # coveragepy options from .coveragerc
                'slipcover_opts': '--source=sklearn --omit=*/sklearn/externals/* --omit=*/sklearn/_build_utils/* --omit=*/benchmarks/* --omit=**/setup.py'
              },
              cwd='/home/juan/tmp/scikit-learn'
    )
)



def overhead(time, base_time):
    return ((time/base_time)-1)*100


ran_any = False
for case in cases:
    if case.name not in results:
        if case.label in results:   # they used to be saved by label
            results[case.name] = results[case.label]
            del results[case.label]
        else:
            results[case.name] = dict()

    for bench in benchmarks:
        if bench.name in results[case.name]:
            if args.rerun_case != 'all' and args.rerun_case != case.name:
                continue

            if args.rerun_bench and args.rerun_bench != bench.name:
                continue

        r = []
        for _ in range(TRIES):
            r.append(run_command(case.command.format(**bench.format)))

        results[case.name][bench.name] = r

        m = median(r)
        b_m = median(results[base.name][bench.name])
        print(f"median: {m:.1f}  +{overhead(m, b_m):.1f}%")

        ran_any = True

if ran_any:
    with open(BENCHMARK_JSON, 'w') as f:
        json.dump(saved_results, f)

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
                       width/n_bars, label=case.label)
#        ax.boxplot([results[case.name][b.name] for b in benchmarks],
#                   positions=x+bar_x, widths=width/n_bars, showfliers=False,
#                   medianprops={'color': 'black'},
#                   labels=[case.name] * len(benchmarks),
#        )
        ax.bar_label(rects, padding=3)

    #ax.set_title('Execution time')
    ax.set_ylabel('CPU seconds')
    ax.set_xticks(x, labels=[b.label for b in benchmarks])
    ax.legend()

    fig.tight_layout()
    fig.savefig("benchmarks/benchmarks.png")

plot_results()
