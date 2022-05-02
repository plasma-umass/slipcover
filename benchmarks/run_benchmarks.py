import json
import re
from pathlib import Path
from collections import namedtuple
from statistics import median
from datetime import datetime
import subprocess


BENCHMARK_JSON = 'benchmarks/benchmarks.json'
TRIES = 5
PYTHON = 'python3'
# someplace with scikit-learn 1.0.2 sources, built and ready to test
SCIKIT_LEARN = Path.home() / "tmp" / "scikit-learn"
FLASK = Path.home() / "tmp" / "flask"

git_head = subprocess.run("git rev-parse --short HEAD", shell=True, check=True,
                          capture_output=True, text=True).stdout.strip()

Case = namedtuple('Case', ['name', 'label', 'command'])

cases = [Case('base', "(no coverage)", PYTHON + " {bench_command}"),
         Case('coveragepy', "Coverage.py", PYTHON + " -m coverage run {coveragepy_opts} {bench_command}"),
         Case('slipcover', "Slipcover", PYTHON + " -m slipcover {slipcover_opts} {bench_command}")
]
base = cases[0]

class Benchmark:
    def __init__(self, name, command, opts=None, cwd=None, tries=None):
        self.name = name
        self.format = {'bench_command': command}
        for k in ['slipcover_opts', 'coveragepy_opts']:
            self.format[k] = opts[k] if opts and k in opts else ''
        self.cwd = cwd 
        self.tries = TRIES if tries == None else tries


def run_command(command: str, cwd=None):
    import shlex
    import time

    print(command)

    begin = time.perf_counter_ns()
    p = subprocess.run(shlex.split(command), cwd=cwd, check=True) # capture_output=True)
    end = time.perf_counter_ns()

    elapsed = (end - begin)/1000000000
    print(round(elapsed, 1))

    return elapsed


def parse_args():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--rerun-case', choices=['all', 'none', *[c.name for c in cases]],
                    default='slipcover', help='select "case"(s) to re-run')
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


benchmarks = []
if SCIKIT_LEARN.exists():
    benchmarks.append(
        Benchmark('sklearn', "-m pytest sklearn -k 'not test_openmp_parallelism_enabled'", {
                    # coveragepy options from .coveragerc
                    'slipcover_opts': '--source=sklearn ' + \
                                      '--omit=*/sklearn/externals/*,*/sklearn/_build_utils/*,*/benchmarks/*,**/setup.py'
                  },
                  cwd=str(SCIKIT_LEARN)
        )
    )

if FLASK.exists():
    benchmarks.append(
        Benchmark('flask', "-m pytest", {
                    # coveragepy options from setup.cfg
                    'slipcover_opts': '--source=src,*/site-packages'
                  },
                  cwd=FLASK, tries=10
        )
    )

def path2bench(p: Path) -> str:
    match = re.search('^(bm_)?(.*?)\.py$', p.name)
    bench_name = match.group(2) if match else p.name

    return Benchmark(bench_name, p, {'coveragepy_opts': f'--include={p}',
                                     'slipcover_opts': f'--source={p.parent}'})

benchmarks.extend([path2bench(p) for p in sorted(Path('benchmarks').glob('bm_*.py'))])



def overhead(time, base_time):
    return ((time/base_time)-1)*100


for case in cases:
    if case.name not in results:
        if case.label in results:   # they used to be saved by label
            results[case.name] = results[case.label]
            del results[case.label]
        else:
            results[case.name] = dict()

    for bench in benchmarks:
        if bench.name in results[case.name]:
            # 'results' used to be just a list
            if isinstance(results[case.name][bench.name], list):
                results[case.name][bench.name] = {'times': results[case.name][bench.name]}

            if args.rerun_case != 'all' and args.rerun_case != case.name:
                continue

            if args.rerun_bench and args.rerun_bench != bench.name:
                continue

        times = []
        for _ in range(bench.tries):
            times.append(run_command(case.command.format(**bench.format), cwd=bench.cwd))

        results[case.name][bench.name] = {
            'datetime': datetime.now().isoformat(),
            'git_head': git_head,
            'times': times
        }

        m = median(times)
        b_m = median(results[base.name][bench.name]['times'])
        print(f"median: {m:.1f}" + (f" +{overhead(m, b_m):.1f}%" if case.name != "base" else ""))

        # save after each benchmark, in case we abort running others
        with open(BENCHMARK_JSON, 'w') as f:
            json.dump(saved_results, f)


def print_results():
    from tabulate import tabulate

    def get_stats():
        from math import sqrt
        from statistics import mean, stdev

        for bench in benchmarks:
            base_median = median(results[base.name][bench.name]['times'])
            for case in cases:
                rd = results[case.name][bench.name]
                date = str(datetime.fromisoformat(rd['datetime']).date()) if 'datetime' in rd else None
                r = rd['times']

                oh = round(overhead(median(r), base_median),1) if case != base else None
                yield [bench.name, case.name, len(r), round(median(r),2), round(mean(r),2),
                       round(stdev(r),2),
                       round(stdev(r)/sqrt(len(r)),2), oh,
                       date,
                       rd['git_head'] if 'git_head' in rd else None
                ]

    print(tabulate(get_stats(), headers=["bench", "case", "samples", "median", "mean", "stdev",
                                         "SE", "overhead %", "date", "git_head"]))
    print("")

    base_times = [median(results[base.name][b.name]['times']) for b in benchmarks]
    rel_times = dict()
    for case in cases:
        if case == base:
            continue

        times = [median(results[case.name][b.name]['times']) for b in benchmarks]
        rel_times[case.name] = [overhead(t, bt) for t, bt in zip(times, base_times)]

        print(f"Overhead for {case.name}: {min(rel_times[case.name]):.0f}% - " +
                                        f"{max(rel_times[case.name]):.0f}%")

    diff_times = [cover - slip for cover, slip in zip(rel_times['coveragepy'],
                                                      rel_times['slipcover'])]
    print(f"Slipcover savings: {min(diff_times):.0f}% - {max(diff_times):.0f}%")

print_results()


def plot_results():
    import numpy as np
    import matplotlib.pyplot as plt

    nonbase_cases = [c for c in cases if c.name != 'base']

    x = np.arange(len(benchmarks))
    n_bars = len(nonbase_cases)
    width = .70 # of all bars
    bars_x = np.arange(width/n_bars/2, width, width/n_bars) - width/2

    fig, ax = plt.subplots()
    for case, bar_x in zip(nonbase_cases, bars_x):
        r = [median(results[case.name][b.name]['times']) / median(results['base'][b.name]['times']) for b in benchmarks]
        rects = ax.bar(x + bar_x, r, width/n_bars, label=case.label, zorder=2)

        ax.bar_label(rects, padding=3, labels=[f'{"+" if round((v-1)*100)>=0 else ""}{round((v-1)*100)}%' for v in r], fontsize=8)

#    ax.set_title('')
    ax.set_ylabel('Normalized execution time')
    ax.set_xticks(x, labels=[b.name for b in benchmarks], fontsize=8)
    ax.axhline(y=1, color='grey', linewidth=1, alpha=.5, zorder=1)
    ax.legend()

    fig.tight_layout()
    fig.savefig("benchmarks/benchmarks.png")

plot_results()
