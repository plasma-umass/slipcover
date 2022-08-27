import json
import re
from pathlib import Path
from collections import namedtuple
from statistics import median
from datetime import datetime
import subprocess
import sys

if sys.version_info[:2] < (3,10):
    from importlib_metadata import version, PackageNotFoundError
else:
    from importlib.metadata import version, PackageNotFoundError

BENCHMARK_JSON = Path(sys.argv[0]).parent / 'benchmarks.json'
TRIES = 5
# someplace with scikit-learn 1.1.1 sources, built and ready to test
SCIKIT_LEARN = Path.home() / "tmp" / "scikit-learn"
FLASK = Path.home() / "tmp" / "flask"

git_head = subprocess.run("git rev-parse --short HEAD", shell=True, check=True,
                          capture_output=True, text=True).stdout.strip()

def load_cases():
    Case = namedtuple('Case', ['name', 'label', 'command', 'color', 'version'])

    cases = [Case('base', "(no coverage)",
                  sys.executable + " {bench_command}", None, None),
             Case('coveragepy', "Coverage.py line",
                  sys.executable + " -m coverage run {coveragepy_opts} {bench_command}",
                  'orange', version('coverage')),
             Case('coveragepy-branch', "Coverage.py line+branch",
                  sys.executable + " -m coverage run --branch {coveragepy_opts} {bench_command}",
                  'tab:orange', version('coverage'))
    ]

    try:
        cases += [
             Case('nulltracer', "null C tracer",
                  sys.executable + " -m nulltracer {nulltracer_opts} {bench_command}",
                  'tab:red', version('nulltracer'))
        ]
    except PackageNotFoundError:
        pass

    cases += [
             Case('slipcover', "Slipcover line",
                  sys.executable + " -m slipcover {slipcover_opts} {bench_command}",
                  'tab:blue', git_head),
             Case('slipcover-branch', "Slipcover line+branch",
                  sys.executable + " -m slipcover --branch {slipcover_opts} {bench_command}",
                  'blue', git_head)
    ]
    return cases

cases = load_cases()
base = cases[0]

def load_benchmarks():
    class Benchmark:
        def __init__(self, name, command, opts=None, cwd=None, tries=None):
            self.name = name
            self.format = {'bench_command': command}
            for k in ['slipcover_opts', 'coveragepy_opts', 'nulltracer_opts']:
                self.format[k] = opts[k] if opts and k in opts else ''
            self.cwd = cwd 
            self.tries = TRIES if tries == None else tries


    benchmarks = []
    benchmarks.append(
        # ndcg_score fails with scikit-learn 1.1.1
        Benchmark('sklearn', "-m pytest sklearn -k 'not sklearn.metrics._ranking.ndcg_score'", {
                    # coveragepy options from .coveragerc
                    'slipcover_opts': '--source=sklearn ' +\
                                      '--omit=*/sklearn/externals/*,*/sklearn/_build_utils/*,' +\
                                             '*/benchmarks/*,**/setup.py',
                    'nulltracer_opts': '--prefix=sklearn '
                  },
                  cwd=str(SCIKIT_LEARN)
        )
    )

    benchmarks.append(
        Benchmark('flask', "-m pytest --count 5", {
                    # coveragepy options from setup.cfg
                    'slipcover_opts': '--source=src,*/site-packages',
                    'nulltracer_opts': '--prefix=src'
                  },
                  cwd=FLASK
        )
    )

    def path2bench(p: Path) -> str:
        match = re.search('^(bm_)?(.*?)\.py$', p.name)
        bench_name = match.group(2) if match else p.name

        return Benchmark(bench_name, p, {'coveragepy_opts': f'--include={p}',
                                         'slipcover_opts': f'--source={p.parent}',
                                         'nulltracer_opts': f'--prefix={p}'
                                         })

    benchmarks.extend([path2bench(p) for p in sorted(BENCHMARK_JSON.parent.glob('bm_*.py'))])
    return benchmarks

benchmarks = load_benchmarks()

def parse_args():
    import argparse
    ap = argparse.ArgumentParser()

    ap.add_argument('--run', action='store_true', help='run benchmarks as needed')
    ap.add_argument('--case', choices=[c.name for c in cases],
                       action='append', help='select case(s) to run/plot')

    a_run = ap.add_argument_group('running', 'options for running')
    a_run.add_argument('--rerun-case', choices=['all', 'none', *[c.name for c in cases]],
                       default='slipcover', help='select "case"(s) to re-run')
    a_run.add_argument('--rerun-bench', type=str, default=None, help='select benchmark to re-run')

    a_plot = ap.add_argument_group('plotting', 'options for plotting')
    a_plot.add_argument('--os', type=str, help='select OS name (conflicts with --run)')
    a_plot.add_argument('--python', type=str, help='select python version (conflicts with --run)')
    a_plot.add_argument('--title', type=str, default='Line / Line+Branch Coverage Benchmarks', help='set plot title')
    a_plot.add_argument('--out', type=Path, default=Path("benchmarks/benchmarks.png"), help='set plot output file')
    a_plot.add_argument('--style', type=str, help='set matplotlib style')
    a_plot.add_argument('--figure-width', type=float, default=12, help='matplotlib figure width')
    a_plot.add_argument('--figure-height', type=float, default=8, help='matplotlib figure height')
    a_plot.add_argument('--bar-labels', action='store_true', help='add labels to bars')

    args = ap.parse_args()

    if not args.case:
        if args.run:
            args.case = ['slipcover', 'slipcover-branch']
        else:
            args.case = ['coveragepy', 'coveragepy-branch', 'slipcover', 'slipcover-branch']

    if args.run and args.os: raise Exception("--run and --os can't be used together")
    if args.run and args.python: raise Exception("--run and --python can't be used together")

    return args

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


args = parse_args()


def load_results():
    try:
        with open(BENCHMARK_JSON, 'r') as f:
            saved_results = json.load(f)
    except FileNotFoundError:
        saved_results = []

    if args.run:
        def gen_sysid():
            import platform
            import cpuinfo  # pip3 install py-cpuinfo

            return {
                'python': platform.python_version(),
                'os': [platform.system(), platform.release()],
                'cpu': cpuinfo.get_cpu_info()['brand_raw']
            }

        try:
            results = next(it['results'] for it in saved_results if it['system'] == gen_sysid())
            print(f"using {json.dumps(gen_sysid())}")
        except StopIteration:
            results = dict()
            saved_results.append({'system': gen_sysid(), 'results': results})
    else:
        entries = saved_results
        if args.os:
            entries = [e for e in entries if e['system']['os'][0] == args.os]
            if len(entries) == 0:
                raise RuntimeError(f"No entries found for {args.os}")
        if args.python:
            entries = [e for e in entries if e['system']['python'] == args.python]
            if len(entries) == 0:
                raise RuntimeError(f"No entries found for {args.python}")

        if len(entries) > 1:
            found = set(f"{e['system']['os'][0]}/{e['system']['python']}" for e in entries)
            if len(found) > 1:
                raise RuntimeError(f"Too many entries match; found {found}")

            def max_datetime(e):
                return max(b['datetime'] for c in e['results'].values() for b in c.values())

            # multiple OS versions or CPU types... pick latest results
            date2results = {max_datetime(e): e['results'] for e in entries}
            picked = max(date2results.keys())
            print(f"Picking latest of {len(entries)}")
            results = date2results[picked]

        else:
            results = entries[0]['results']

    return saved_results, results

saved_results, results = load_results()





def overhead(time, base_time):
    return ((time/base_time)-1)*100


if args.run:
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
                'version': case.version,
                'times': times
            }

            if case.name == 'coveragepy':
                import coverage
                results[case.name][bench.name]['coveragepy_version'] = coverage.__version__

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
                if case.name not in results or bench.name not in results[case.name]: continue

                rd = results[case.name][bench.name]
                date = str(datetime.fromisoformat(rd['datetime']).date()) if 'datetime' in rd else None
                r = rd['times']

                oh = round(overhead(median(r), base_median),1) if case != base else None
                yield [bench.name, case.name, len(r), round(median(r),2), round(mean(r),2),
                       round(stdev(r),2),
                       round(stdev(r)/sqrt(len(r)),2), oh,
                       date,
                       rd['version'] if 'version' in rd else (rd['git_head'] if 'git_head' in rd else None)
                ]

    print(tabulate(get_stats(), headers=["bench", "case", "samples", "median", "mean", "stdev",
                                         "SE", "overhead %", "date", "version"]))
    print("")

    base_times = [median(results[base.name][b.name]['times']) for b in benchmarks]
    rel_times = dict()
    for case in cases:
        if case == base or case.name not in results:
            continue

        times = [median(results[case.name][b.name]['times']) for b in benchmarks]
        rel_times[case.name] = [overhead(t, bt) for t, bt in zip(times, base_times)]

        print(f"Overhead for {case.name}: {min(rel_times[case.name]):.0f}% - " +
                                        f"{max(rel_times[case.name]):.0f}%")

    if 'slipcover' in rel_times:
        diff_times = [cover - slip for cover, slip in zip(rel_times['coveragepy'],
                                                          rel_times['slipcover'])]
        print(f"Slipcover savings: {min(diff_times):.0f}% - {max(diff_times):.0f}%")

    print("")

print_results()


def plot_results():
    import numpy as np
    import matplotlib.pyplot as plt

    nonbase_cases = [c for c in cases if c.name != 'base' and c.name in args.case]

    x = np.arange(len(benchmarks))
    n_bars = len(nonbase_cases)
    width = .70 # of all bars
    bars_x = np.arange(width/n_bars/2, width, width/n_bars) - width/2

    hide_slipcover = False

    if args.style:
        plt.style.use(args.style)

    fig, ax = plt.subplots()
    for case, bar_x in zip(nonbase_cases, bars_x):
        r = [median(results[case.name][b.name]['times']) / median(results['base'][b.name]['times']) for b in benchmarks]

        showit = not hide_slipcover or (case.name != 'slipcover')

        rects = ax.bar(x + bar_x, r, width/n_bars, label=case.label, zorder=2, alpha=(None if showit else 0),
                       color=case.color)
        if not showit: continue

        if args.bar_labels:
            ax.bar_label(rects, padding=3, labels=[f'{v:.1f}x' for v in r], fontsize=8)

    ax.set_title(args.title, size=18)
    ax.set_ylabel('Normalized execution time', size=15)
    ax.set_xticks(x, labels=[b.name for b in benchmarks], fontsize=15)
    if not args.style:
        ax.grid(axis='y', alpha=.3)
    ax.axhline(y=1, color='black', linewidth=1, alpha=.5, zorder=1)
    if not hide_slipcover:
        ax.legend(fontsize=15)

    fig.set_size_inches(args.figure_width, args.figure_height)
    fig.tight_layout()
    fig.savefig(args.out)
    print(f"Plotting to {args.out}")

if not args.run:
    plot_results()