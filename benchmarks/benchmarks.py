import json
from pathlib import Path
from statistics import median
from datetime import datetime
import subprocess
import sys
import platform

BENCHMARK_JSON = Path(sys.argv[0]).parent / 'benchmarks.json'

def load_cases():
    if sys.version_info[:2] < (3,10):
        from importlib_metadata import version
    else:
        from importlib.metadata import version

    git_head = subprocess.run("git rev-parse --short HEAD", shell=True, check=True,
                              capture_output=True, text=True).stdout.strip()

    class Case:
        def __init__(self, name, label, command, color=None, get_version=None, env=None):
            self.name = name
            self.label = label
            self.command = command
            self.color = color
            # using a version getter allows us to only attempt to get the
            # version when needed (the module may not exist, etc.)
            self.get_version = get_version if get_version else lambda: None
            self.env = env

    return [Case('base', "(no coverage)",
                 sys.executable + " {bench_command}"),
            Case('coveragepy', "coverage.py line",
                 sys.executable + " -m coverage run {coveragepy_opts} {bench_command}",
                 color='orange', get_version=lambda: version('coverage')),
            Case('coveragepy-sysmon', "coverage.py line",
                 sys.executable + " -m coverage run {coveragepy_opts} {bench_command}",
                 color='orange', get_version=lambda: version('coverage'),
                 env={'COVERAGE_CORE':'sysmon'}),
            Case('coveragepy-branch', "coverage.py line+branch, no sysmon",
                 sys.executable + " -m coverage run --branch {coveragepy_opts} {bench_command}",
                 color='tab:orange', get_version=lambda: version('coverage')),
            Case('coveragepy-branch-sysmon', "coverage.py line+branch",
                 sys.executable + " -m coverage run --branch {coveragepy_opts} {bench_command}",
                 color='tab:orange', get_version=lambda: version('coverage'),
                 env={'COVERAGE_CORE':'sysmon'}),
            Case('nulltracer', "null C tracer",
                 sys.executable + " -m nulltracer {nulltracer_opts} {bench_command}",
                 color='tab:red', get_version=lambda: version('nulltracer')),
            Case('slipcover', "SlipCover line",
                 sys.executable + " -m slipcover {slipcover_opts} {bench_command}",
                 color='tab:blue', get_version=lambda: git_head),
            Case('slipcover-branch', "SlipCover line+branch",
                 sys.executable + " -m slipcover --branch {slipcover_opts} {bench_command}",
                 color='blue', get_version=lambda: git_head),
    ] + ([] if platform.python_implementation() == "PyPy" else [
        # immediate de-instrumentation doesn't work with PyPy
            Case('slipcover-imm', "SlipCover line, immediate deinstr.",
                 sys.executable + " -m slipcover --immediate {slipcover_opts} {bench_command}",
                 color='orchid', get_version=lambda: git_head),
            Case('slipcover-branch-imm', "SlipCover l+b, immediate deinstr.",
                 sys.executable + " -m slipcover --branch --immediate {slipcover_opts} {bench_command}",
                 color='purple', get_version=lambda: git_head),
    ]) + [
            Case('slipcover-no-deinstr-1', "SlipCover line, no bytecode deinstr.",
                 sys.executable + " -m slipcover --threshold=-1 {slipcover_opts} {bench_command}",
                 color='silver', get_version=lambda: git_head),
            Case('slipcover-branch-no-deinstr-1', "Slipcover l+b, no bytecode deinstr.",
                 sys.executable + " -m slipcover --branch --threshold=-1 {slipcover_opts} {bench_command}",
                 color='silver', get_version=lambda: git_head),
            Case('slipcover-no-deinstr', "SlipCover line, no deinstr.",
                 sys.executable + " -m slipcover --threshold=-2 {slipcover_opts} {bench_command}",
                 color='lightgreen', get_version=lambda: git_head),
            Case('slipcover-branch-no-deinstr', "SlipCover l+b, no deinstr.",
                 sys.executable + " -m slipcover --branch --threshold=-2 {slipcover_opts} {bench_command}",
                 color='lightgreen', get_version=lambda: git_head),
    ]

cases = load_cases()

def load_benchmarks():
    TRIES = 5
    # someplace with scikit-learn 1.1.1 sources, built and ready to test
    SCIKIT_LEARN = Path.home() / "tmp" / ("scikit-learn" + ("-pypy" if platform.python_implementation() == "PyPy" else ""))
    FLASK = Path.home() / "tmp" / "flask"
    MATPLOTLIB = Path.home() / "tmp" / "matplotlib"

    class Benchmark:
        def __init__(self, name, command, opts=None, cwd=None, tries=None):
            self.name = name
            self.format = {'bench_command': command}
            for k in ['slipcover_opts', 'coveragepy_opts', 'nulltracer_opts']:
                self.format[k] = opts[k] if opts and k in opts else ''
            self.cwd = cwd 
            self.tries = TRIES if tries is None else tries


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
                    'slipcover_opts': '--source=src', #,*/site-packages',
                    'nulltracer_opts': '--prefix=src'
                  },
                  cwd=FLASK
        )
    )

#    benchmarks.append(
#        Benchmark('matplotlib', "-m pytest -k 'not (test_backends_interactive or test_get_font_names)'", {
#                  },
#                  cwd=MATPLOTLIB
#        )
#    )

    def path2bench(p: Path) -> str:
        import re

        match = re.search('^(bm_)?(.*?)\\.py$', p.name)
        bench_name = match.group(2) if match else p.name

        return Benchmark(bench_name, p, {'coveragepy_opts': f'--include={p}',
#                                         'slipcover_opts': f'--source={p.parent}',
                                         'nulltracer_opts': f'--prefix={p}'
                                         })

    benchmarks.extend([path2bench(p) for p in sorted(BENCHMARK_JSON.parent.glob('bm_*.py'))])
    return benchmarks

benchmarks = load_benchmarks()

def parse_args():
    import argparse
    ap = argparse.ArgumentParser()

    sp = ap.add_subparsers(dest='cmd')

    run = sp.add_parser('run', help='run benchmarks')
    show = sp.add_parser('show', help='show benchmark results')
    plot = sp.add_parser('plot', help='plot graph')
    plot_summary = sp.add_parser('plot-summary', help='plot summary graph')
    latex = sp.add_parser('latex', help='write out LaTeX table')

    for p in [run, show, plot, plot_summary, latex]:
        p.add_argument('--case', choices=[c.name for c in cases] + ['all'],
                       action='extend', nargs='+', help='select case(s) to run/plot')
        p.add_argument('--omit-case', action='extend', nargs='+', help='select case(s) to omit from run/plot')
        p.add_argument('--bench', choices=[b.name for b in benchmarks],
                       action='extend', nargs='+', help='select benchmark(s) to run/plot')
        p.add_argument('--omit-bench', action='extend', nargs='+', help='select benchmark(s) to omit from run/plot')

    plot_summary.add_argument('--boxplot', action='store_true', help='output a boxplot')
    plot_summary.add_argument('--case-name', action='append', help='rename cases')

    latex.add_argument('--absolute', action='store_true', help='emit absolute numbers')

    for p in [show, plot, plot_summary, latex]:
        p.add_argument('--os', type=str, help='select OS name (conflicts with --run)')
        p.add_argument('--python', type=str, help='select python version (conflicts with --run)')

    for p in [plot, plot_summary, latex]:
        p.add_argument('--out', type=Path, help='set output file', required=True)

    for p in [plot, plot_summary]:
        p.add_argument('--title', type=str, default='Line / Line+Branch Coverage Benchmarks', help='set plot title')
        p.add_argument('--style', type=str, help='set matplotlib style')
        p.add_argument('--figure-width', type=float, default=16, help='matplotlib figure width')
        p.add_argument('--figure-height', type=float, default=8, help='matplotlib figure height')
        p.add_argument('--bar-labels', action=argparse.BooleanOptionalAction, help='add labels to bars')
        p.add_argument('--font-size-delta', type=int, default=0, help='increase or decrease font size')
        p.add_argument('--rename-slipcover', type=str, help='rename SlipCover in names to given string')
        p.add_argument('--yscale', type=str, default="linear", help='set matplotlib Y scale')
        p.add_argument('--extra-space', type=float, help='add extra space on Y axis')
        p.add_argument('--use-tex', type=str, help='Selects to use (La)TeX fonts and specifies the font family to use')

    plot.add_argument('--speedup', action='store_true', help='plot speedup graph')
    plot.add_argument('--edit-readme', type=str, help='Update range in given marked paragraph in README.md')

    args = ap.parse_args()

    if not args.case:
        if args.cmd == 'run':
            args.case = ['slipcover', 'slipcover-branch']
        else:
            args.case = ['coveragepy', 'coveragepy-branch', 'slipcover', 'slipcover-branch']

    if 'all' in args.case:
        tmp = set(args.case)
        tmp.remove('all')
        tmp.update([c.name for c in cases])
        args.case = list(tmp)

    if not args.bench:
        args.bench = [b.name for b in benchmarks]

    if args.omit_case:
        for c in args.omit_case:
            args.case.remove(c)

    if args.omit_bench:
        for b in args.omit_bench:
            args.bench.remove(b)

    return args


def run_command(command: str, cwd=None, env=None):
    import shlex
    import time
    import os

    if env:
        full_env = os.environ.copy()
        full_env.update(env)
        env = full_env

    print(command)

    begin = time.perf_counter_ns()
    subprocess.run(shlex.split(command), cwd=cwd, check=True, env=env) # capture_output=True)
    end = time.perf_counter_ns()

    elapsed = (end - begin)/1000000000
    print(round(elapsed, 1))

    return elapsed


def load_results(args):
    try:
        with open(BENCHMARK_JSON, 'r') as f:
            saved_results = json.load(f)
    except FileNotFoundError:
        saved_results = []

    def own_sysid():
        import cpuinfo  # pip3 install py-cpuinfo

        return {
            'python': ("pypy" if platform.python_implementation() == "PyPy" else "") + platform.python_version(),
            'os': [platform.system(), platform.release()],
            'cpu': cpuinfo.get_cpu_info()['brand_raw']
        }

    if args.cmd == 'run':
        try:
            results = next(it['results'] for it in saved_results if it['system'] == own_sysid())
            print(f"using {json.dumps(own_sysid())}")
        except StopIteration:
            results = dict()
            saved_results.append({'system': own_sysid(), 'results': results})
    else:
        def e_system_list(e):
            return [e['system']['python'], *e['system']['os'], e['system']['cpu']]

        def show_available_and_exit(entries):
            from tabulate import tabulate

            def get_systems():
                for e in entries:
                    yield e_system_list(e)

            print("Please select results entry to plot using  --python and --os:")
            print(tabulate(get_systems(), headers=["python", "OS", "(release)", "(cpu)"]))
            sys.exit(1)

        entries = saved_results

        if args.os:
            entries = [e for e in entries if e['system']['os'][0].casefold() == args.os.casefold()]
            if len(entries) == 0:
                print(f"No entries found for {args.os}")
                show_available_and_exit(saved_results)

        if args.python:
            entries = [e for e in entries if e['system']['python'] == args.python]
            if len(entries) == 0:
                print(f"No entries found for {args.python}")
                show_available_and_exit(saved_results)

        if len(entries) > 1:
            found = set(f"{e['system']['os'][0]}/{e['system']['python']}" for e in entries)
            if len(found) > 1:
                print("Too many entries match")
                show_available_and_exit(entries)

            def max_datetime(e):
                return max(b['datetime'] for c in e['results'].values() for b in c.values())

            # multiple OS versions or CPU types... pick latest results
            date2entry = {max_datetime(e): e for e in entries}
            picked = date2entry[max(date2entry.keys())]
            print(f"Using results for {'/'.join(e_system_list(picked))}")
            results = picked['results']

        else:
            results = entries[0]['results']

    # 'saved_results' contains the entire JSON; 'results' points into "our" entry within that
    return saved_results, results


def overhead(time, base_time):
    return ((time/base_time)-1)*100


def show_results():
    from tabulate import tabulate

    def get_stats():
        from math import sqrt
        from statistics import mean, stdev

        for bench in benchmarks:
            if bench.name not in results['base']: continue
            base_median = median(results['base'][bench.name]['times'])
            for case in cases:
                if case.name not in results or bench.name not in results[case.name]: continue

                rd = results[case.name][bench.name]
                date = str(datetime.fromisoformat(rd['datetime']).date()) if 'datetime' in rd else None
                r = rd['times']

                oh = round(overhead(median(r), base_median),1) if case.name != 'base' else None
                yield [bench.name, case.name, len(r), round(median(r),2), round(mean(r),2),
                       round(stdev(r),2),
                       round(stdev(r)/sqrt(len(r)),2), oh,
                       date,
                       rd['version'] if 'version' in rd else (rd['git_head'] if 'git_head' in rd else None)
                ]

    print("")
    print(tabulate(get_stats(), headers=["bench", "case", "samples", "median", "mean", "stdev",
                                         "SE", "overhead %", "date", "version"]))
    print("")


def plot_results(args):
    import numpy as np
    import matplotlib.pyplot as plt
    import re

    def getBase(caseName):
        if not args.speedup: return 'base'
        if caseName.startswith('slipcover-branch'): return 'coveragepy-branch'
        if caseName.startswith('slipcover'): return 'coveragepy'
        return None

    bases = set([getBase(c) for c in args.case if getBase(c)])
    relevant_cases = set.union(set(args.case), bases)

    all_benchmarks = set.union(*(set(results[c].keys()) for c in relevant_cases))
    common_benchmarks = set.intersection(*(set(results[c].keys()) for c in relevant_cases))
    all_benchmarks = all_benchmarks.intersection(args.bench)
    common_benchmarks = common_benchmarks.intersection(args.bench)

    for c in relevant_cases:
        if not all_benchmarks.issubset(results[c].keys()):
            print(f"WARNING: \"{c}\" is missing benchmarks {all_benchmarks - set(results[c].keys())}")

    # note 'cases' and 'benchmarks' are global
    nonbase_cases = [c for c in cases if c.name in args.case and c.name not in bases]

    x = np.arange(len(common_benchmarks))
    n_bars = len(nonbase_cases)
    width = .70 # of all bars
    bars_x = np.arange(width/n_bars/2, width, width/n_bars) - width/2

    hide_slipcover = False

    plt.rcParams.update({
        'font.weight': 'bold',
        'pdf.fonttype': 42  # output TrueType; bigger but scalable
    })
    if args.use_tex:
        plt.rcParams.update({
            "text.usetex": True,
            "font.family": args.use_tex
        })
    plt.rc('ytick', labelsize=12+args.font_size_delta)

    if args.style:
        plt.style.use(args.style)

    def getValue(caseName, benchName):
        if args.speedup:
            return median(results[getBase(caseName)][benchName]['times']) / median(results[caseName][benchName]['times'])

        return median(results[caseName][benchName]['times']) / median(results['base'][benchName]['times'])

    min_range, max_range = None, None
    times = 'x' if args.speedup else ''

    fig, ax = plt.subplots()
    for case, bar_x in zip(nonbase_cases, bars_x):
        r = [getValue(case.name, b.name) for b in benchmarks if b.name in common_benchmarks]

        min_range = min(r + ([] if min_range is None else [min_range]))
        max_range = max(r + ([] if max_range is None else [max_range]))

        showit = not hide_slipcover or (case.name != 'slipcover')

        case_label = case.label
        if args.rename_slipcover:
            case_label = re.sub('[Ss]lip[Cc]over', args.rename_slipcover, case_label)

        rects = ax.bar(x + bar_x, r, width/n_bars, label=case_label, color=case.color, zorder=2,
                       alpha=(None if showit else 0))
        if not showit: continue

        if args.bar_labels:
            ax.bar_label(rects, padding=3, labels=[f'{v:.1f}{times}' for v in r], fontsize=11+args.font_size_delta)

    ax.set_title(args.title, size=18+args.font_size_delta, weight='bold')
    if args.speedup:
        ax.set_ylabel('Speedup over coverage.py', size=15+args.font_size_delta)
    else:
        ax.set_ylabel('Normalized execution time', size=15+args.font_size_delta)
    ax.set_yscale(args.yscale)
    if args.yscale == 'log':
        from matplotlib.ticker import ScalarFormatter
        ax.yaxis.set_major_formatter(ScalarFormatter())

    if args.extra_space:
        ax.set_ylim(0, max_range*args.extra_space)

    ax.set_xticks(x, labels=[b.name for b in benchmarks if b.name in common_benchmarks], fontsize=15+args.font_size_delta)
    if not args.style:
        ax.grid(axis='y', alpha=.3)
    ax.axhline(y=1, color='black', linewidth=1, alpha=.5, zorder=1) # 1x line
    if not hide_slipcover:
        ax.legend(fontsize=15+args.font_size_delta)

    fig.set_size_inches(args.figure_width, args.figure_height)
    fig.tight_layout()

    fig.savefig(args.out)
    print(f"Plotted to {args.out}.")
    print(f"Results range from {min_range:.1f}{times} to {max_range:.1f}{times}.")
    print("")

    if args.edit_readme:
        with open("README.MD", "r") as f:
            readme = f.read()

        readme = re.sub(r'(\n\n\[//\]: # \(' + args.edit_readme + r'\)\s*\n.*?from )[\d\.]+x? to [\d\.]+x?(.*?\n\n)',
                        r'\g<1>' + f'{min_range:.1f}{times} to {max_range:.1f}{times}' + r'\g<2>', readme, flags=re.S)

        with open("README.MD", "w") as f:
            f.write(readme)

def plot_summary_results(args):
    import numpy as np
    import matplotlib.pyplot as plt
    import matplotlib.ticker

    relevant_cases = set(args.case)

    all_benchmarks = set.union(*(set(results[c].keys()) for c in relevant_cases))
    common_benchmarks = set.intersection(*(set(results[c].keys()) for c in relevant_cases))
    all_benchmarks = all_benchmarks.intersection(args.bench)
    common_benchmarks = common_benchmarks.intersection(args.bench)

    for c in relevant_cases:
        if not all_benchmarks.issubset(results[c].keys()):
            print(f"WARNING: \"{c}\" is missing benchmarks {all_benchmarks - set(results[c].keys())}")

    # note 'cases' and 'benchmarks' are global
    hide_slipcover = False

    plt.rcParams.update({
        'font.weight': 'bold',
        'pdf.fonttype': 42  # output TrueType; bigger but scalable
    })
    if args.use_tex:
        plt.rcParams.update({
            "text.usetex": True,
            "font.family": args.use_tex
        })
    plt.rc('ytick', labelsize=12+args.font_size_delta)

    if args.style:
        plt.style.use(args.style)

    def getValue(caseName, benchName):
        exectime = median(results[caseName][benchName]['times'])
        base = median(results['base'][benchName]['times'])
#        return 100*(exectime - base) / base
        return overhead(exectime, base)

    fig, ax = plt.subplots()
#    ax.yaxis.set_major_formatter(matplotlib.ticker.FormatStrFormatter('%.0f%%'))

    if args.boxplot:
        data = [[getValue(c, b.name) for b in benchmarks if b.name in common_benchmarks] for c in args.case]
        bp = ax.boxplot(data)#, showmeans=True)

        for m in bp['medians']:
            (xleft, y), (xright, _) = m.get_xydata()
            plt.text((xleft+xright)/2, y, f'{y:,.1f}', ha='center', va='center',
                    fontsize=14+args.font_size_delta,
                    bbox={'facecolor':'white', 'edgecolor':'none', 'pad':0})

        ax.set_xticklabels(args.case)

        if args.extra_space:
            ax.set_ylim(0, max([max(d) for d in data])*args.extra_space)
    else:
        data = [median([getValue(c, b.name) for b in benchmarks if b.name in common_benchmarks]) for c in args.case]
        x = args.case_name if args.case_name else args.case
        bp = ax.bar(x, data, color=[c.color for cn in args.case for c in cases if c.name == cn])
        if args.bar_labels:
            ax.bar_label(bp, labels=[f'{v:,.0f} %' for v in data])
#        ax.set_xticklabels(args.case)

        if args.extra_space:
            ax.set_ylim(0, max(data)*args.extra_space)

    ax.set_title(args.title, size=18+args.font_size_delta, weight='bold')
    ax.set_ylabel('Execution time overhead' + (" (log scale)" if args.yscale=='log' else ""),
                  size=15+args.font_size_delta)
    ax.set_yscale(args.yscale)
    ax.yaxis.set_major_formatter('{x:,.0f}%')

    ax.tick_params(labelsize=15+args.font_size_delta)
    #if not args.style:
    #    ax.grid(axis='y', alpha=.3)
    #ax.axhline(y=1, color='black', linewidth=1, alpha=.5, zorder=1) # 1x line
    #if not hide_slipcover:
    #    ax.legend(fontsize=15+args.font_size_delta)

    fig.set_size_inches(args.figure_width, args.figure_height)
    fig.tight_layout()

    fig.savefig(args.out)
    print(f"Plotted to {args.out}.")



def latex_results(args):
    import re

    selected_cases = [c for c in cases if c.name in args.case]
    nonbase_cases = [c for c in selected_cases if c.name != 'base']

    all_benchmarks = set.union(*(set(results[c.name].keys()) for c in selected_cases))
    common_benchmarks = set.intersection(*(set(results[c.name].keys()) for c in selected_cases))
    all_benchmarks = all_benchmarks.intersection(args.bench)
    common_benchmarks = common_benchmarks.intersection(args.bench)

    if common_benchmarks != all_benchmarks:
        print(f"WARNING: some benchmarks are missing: {all_benchmarks - common_benchmarks}")

    def latex_escape(s):
        repl = {
            '&':  r'\&',
            '%':  r'\%', 
            '$':  r'\$', 
            '#':  r'\#', 
            '_':  r'\_', 
            '{':  r'\{', 
            '}':  r'\}',
            '~':  r'\textasciitilde{}', 
            '^':  r'\^{}', 
            '\\': r'\textbackslash',
        }

        return "".join([repl.get(c, c) for c in s])

    def texttt(s):
        return f"\\texttt{{{s}}}"

    with open(args.out, "w") as out:
        print("\\begin{tabular}{l " + ("r " * (int(args.absolute)+len(nonbase_cases))) + "}", file=out)
        line = "\\thead[l]{Benchmark}"

        if args.absolute:
            line += " & \\thead[r]{no coverage}"

        for case in nonbase_cases:
            case_name = re.sub('[Ss]lip[Cc]over', '\\\\systemname{}', latex_escape(case.label))
            case_name = re.sub('coverage\\.py', '\\\\texttt{coverage.py}', case_name)

            import textwrap
            case_name = "\\\\ ".join(textwrap.wrap(case_name, 10, break_long_words=False))

            line += " & \\thead[r]{" + case_name + "}"
        line += " \\\\"
        print(line, file=out)
        print("\\hline", file=out)

        for bench in [b for b in benchmarks if b.name in common_benchmarks]:
            line = f"{texttt(latex_escape(bench.name))}"

            base_result = median(results['base'][bench.name]['times'])

            if args.absolute:
                line += f" & \\SI{{{base_result:.1f}}}{{s}}"

            for case in nonbase_cases:
                if args.absolute:
                    r = median(results[case.name][bench.name]['times'])
                    line += f" & \\SI{{{r:.1f}}}{{s}}"
                else:
                    r = median(results[case.name][bench.name]['times']) / base_result
                    line += f" & {r:.2f}$\\times$"
            line += " \\\\"
            print(line, file=out)

        print("\\hline", file=out)

        if not args.absolute:
            line = "median"
            for case in nonbase_cases:
                r = []
                for bench in [b for b in benchmarks if b.name in common_benchmarks]:
                    base_result = median(results['base'][bench.name]['times'])
                    r.append(median(results[case.name][bench.name]['times']) / base_result)

                line += f" & {median(r):.2f}$\\times$"
            line += " \\\\"

            print(line, file=out)

        print("\\end{tabular}", file=out)

    print(f"Wrote to {args.out}.")
    print("")


if __name__ == "__main__":
    args = parse_args()
    saved_results, results = load_results(args)

    if args.cmd == 'run':
        print(f"Selected cases:      {args.case}")
        print(f"Selected benchmarks: {args.bench}")

        for case in [c for c in cases if c.name in args.case]:
            if case.name not in results:
                if case.label in results:   # they used to be saved by label
                    results[case.name] = results[case.label]
                    del results[case.label]
                else:
                    results[case.name] = dict()

            for bench in [b for b in benchmarks if b.name in args.bench]:
                if bench.name in results[case.name]:
                    # 'results' used to be just a list
                    if isinstance(results[case.name][bench.name], list):
                        results[case.name][bench.name] = {'times': results[case.name][bench.name]}

                times = []
                for t in range(bench.tries):
                    print(f"--- {case.name} {bench.name} #{t+1}/{bench.tries} ---")
                    times.append(run_command(case.command.format(**bench.format), cwd=bench.cwd, env=case.env))

                results[case.name][bench.name] = {
                    'datetime': datetime.now().isoformat(),
                    'version': case.get_version(),
                    'times': times
                }

                if case.name == 'coveragepy':
                    import coverage
                    results[case.name][bench.name]['coveragepy_version'] = coverage.__version__

                m = median(times)
                b_m = median(results['base'][bench.name]['times'])
                print(f"median: {m:.1f}" + (f" +{overhead(m, b_m):.1f}%" if case.name != "base" else ""))

                # save after each benchmark, in case we abort running others
                with open(BENCHMARK_JSON, 'w') as f:
                    json.dump(saved_results, f, indent=4)

    elif args.cmd == 'show':
        show_results()

    elif args.cmd == 'latex':
        latex_results(args)

    elif args.cmd == 'plot':
        plot_results(args)

    elif args.cmd == 'plot-summary':
        plot_summary_results(args)
