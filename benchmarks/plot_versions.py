from pathlib import Path
import sys
import re

sys.path += str(Path(sys.argv[0]).parent)
from benchmarks import BENCHMARK_JSON, cases

def parse_args():
    import argparse
    ap = argparse.ArgumentParser()

    ap.add_argument('--os', type=str, default='Linux', help='select OS name')
    ap.add_argument('--case', choices=[c.name for c in cases],
                       action='extend', nargs='+', help='select case(s) to run/plot')
    ap.add_argument('--bench', action='extend', nargs='+', help='select benchmark(s) to plot')
    ap.add_argument('--title', type=str, default='Overhead by Python version', help='set plot title')
    ap.add_argument('--out', type=Path, default=Path("benchmarks/versions.png"), help='set plot output file')
    ap.add_argument('--latex', type=Path, help='also output LaTeX table to given file')
    ap.add_argument('--style', type=str, help='set matplotlib style')
    ap.add_argument('--figure-width', type=float, default=12, help='matplotlib figure width')
    ap.add_argument('--figure-height', type=float, default=8, help='matplotlib figure height')
    ap.add_argument('--bar-labels', action='store_true', help='add labels to bars')
    ap.add_argument('--font-size-delta', type=int, default=0, help='increase or decrease font size')
    ap.add_argument('--rename-slipcover', type=str, help='rename SlipCover in names to given string')
    ap.add_argument('--skip-version', default=[], action='append', help='omit given Python version')
    ap.add_argument('--absolute', action='store_true', help='emit absolute numbers in LaTeX')
    ap.add_argument('--yscale', type=str, default="linear", help='set matplotlib Y scale')

    ap.add_argument('--use-tex', type=str, help='Selects to use (La)TeX fonts and specifies the font family to use')

    args = ap.parse_args()

    if not args.case:
        args.case = ['coveragepy', 'coveragepy-branch', 'slipcover', 'slipcover-branch']

    if not args.bench:
        args.bench = ['raytrace']

    return args

args = parse_args()

def load_data():
    import json
    import packaging.version

    with open(BENCHMARK_JSON, 'r') as f:
        entries = json.load(f)

    entries = [e for e in entries if e['system']['os'][0].casefold() == args.os.casefold()]

    os_versions = set(e['system']['os'][1] for e in entries)
    if len(os_versions) > 1:
        # pick "latest" OS version... FIXME pick by benchmark date, as in benchmarks.py
        latest = max(os_versions)
        entries = [e for e in entries if e['system']['os'][1] == latest]

    systems = set([('/'.join(e['system']['os']), e['system']['cpu']) for e in entries])
    if len(systems) > 1:
        raise RuntimeException(f"Results sets mixes data from different systems: {systems}")

    # Python version -> results
    v2r = {e['system']['python']: e['results'] for e in entries}

    for v in args.skip_version:
        del v2r[v]

    # sort Python versions semantically
    python_versions = sorted(v2r.keys(), key=lambda x: packaging.version.parse(x))
    print("versions: ", python_versions)

    # check data looks ok -- all should have the same cases
    common_cases = set.intersection(*(set(r.keys()) for r in v2r.values()))
    print("common cases: ", common_cases)
    assert common_cases == set(v2r[python_versions[0]].keys())

    if 'all' in args.bench:
        common_benchmarks = set.intersection(*(set(b.keys()) for r in v2r.values() for b in r.values()))
        print("common benchmarks: ", common_benchmarks)
        args.bench.remove('all')
        args.bench.extend(sorted(common_benchmarks))

    # check that requested benchmark(s) are available everywhere
    for v, b in ((v, b) for v in v2r for b in v2r[v].values()):
        for bench in args.bench:
            if bench not in b:
                print(f"Benchmark {bench} not available for {v}")
                sys.exit(1)

    # compute the median
    from statistics import median
    for v in python_versions:
        for c in v2r[v]:
            for b in v2r[v][c]:
                m = v2r[v][c][b]
                m['median'] = median(m['times'])

    return v2r, python_versions

v2r, python_versions = load_data()


def latex_results(args):
    selected_cases = [c for c in cases if c.name in args.case]
    nonbase_cases = [c for c in selected_cases if c.name != 'base']

    assert len(args.bench) == 1, "Only one benchmark at a time supported."

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

    with open(args.latex, "w") as out:
        print("\\begin{tabular}{l " + ("r " * (int(args.absolute)+len(nonbase_cases))) + "}", file=out)
        line = "\\thead[l]{Python\\\\version}"

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

        for version in python_versions:
            line = f"{texttt(latex_escape(version))}"

            base_result = v2r[version]['base'][args.bench[0]]['median']

            if args.absolute:
                line += f" & \\SI{{{base_result:.1f}}}{{s}}"

            for case in nonbase_cases:
                if args.absolute:
                    r = v2r[version][case.name][args.bench[0]]['median']
                    line += f" & \\SI{{{r:.1f}}}{{s}}"
                else:
                    r = v2r[version][case.name][args.bench[0]]['median'] / base_result
                    line += f" & {r:.2f}$\\times$"
            line += " \\\\"
            print(line, file=out)

        print("\\hline", file=out)
        print("\\end{tabular}", file=out)

    print(f"Wrote to {args.latex}.")
    print("")


nonbase_cases = [c for c in cases if c.name != 'base' and c.name in args.case]

import matplotlib.pyplot as plt
import numpy as np

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

x = np.arange(len(python_versions))

fig, ax = plt.subplots()

ax.set_yscale(args.yscale)
if args.yscale == 'log':
    from matplotlib.ticker import ScalarFormatter
    ax.yaxis.set_major_formatter(ScalarFormatter())

if len(args.bench) == 1: # do a bar plot
    n_bars = len(nonbase_cases)
    width = .70 # of all bars
    bars_x = np.arange(width/n_bars/2, width, width/n_bars) - width/2

    for case, bar_x in zip(nonbase_cases, bars_x):
        r = [v2r[v][case.name][args.bench[0]]['median'] / v2r[v]['base'][args.bench[0]]['median'] for v in python_versions]

        case_label = case.label
        if args.rename_slipcover:
            case_label = re.sub('[Ss]lip[Cc]over', args.rename_slipcover, case_label)

        rects = ax.bar(x + bar_x, r, width/n_bars, label=case_label, color=case.color, zorder=2)

        if args.bar_labels:
            ax.bar_label(rects, padding=3, labels=[f'{v:.1f}x' for v in r], fontsize=8+args.font_size_delta)

else: # do a box plot
    for bench, case in ((bench, case) for bench in args.bench for case in nonbase_cases):
        r = [v2r[v][case.name][bench]['median'] / v2r[v]['base'][bench]['median'] for v in python_versions]

        ax.plot(r, label=f"{bench} {case.name}")

ax.set_title(args.title, size=18+args.font_size_delta, weight='bold')
ax.set_ylabel('Normalized execution time', size=15+args.font_size_delta)
ax.set_xticks(x, labels=python_versions, fontsize=15+args.font_size_delta)
if not args.style:
    ax.grid(axis='y', alpha=.3)
ax.axhline(y=1, color='black', linewidth=1, alpha=.5, zorder=1)
ax.legend(fontsize=15+args.font_size_delta)

fig.set_size_inches(args.figure_width, args.figure_height)
fig.tight_layout()
fig.savefig(args.out)
print(f"Plotted to {args.out}.")
print("")

if args.latex:
    latex_results(args)
