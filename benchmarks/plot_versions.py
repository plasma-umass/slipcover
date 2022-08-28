from pathlib import Path
import sys

sys.path += str(Path(sys.argv[0]).parent)
from benchmarks import BENCHMARK_JSON, cases

def parse_args():
    import argparse
    ap = argparse.ArgumentParser()

    ap.add_argument('--os', type=str, default='Linux', help='select OS name')
    ap.add_argument('--case', choices=[c.name for c in cases],
                       action='append', help='select case(s) to run/plot')
    ap.add_argument('--bench', type=str, default='raytrace', help='select benchmark to plot')
    ap.add_argument('--title', type=str, default='Overhead by Python version', help='set plot title')
    ap.add_argument('--out', type=Path, default=Path("benchmarks/versions.png"), help='set plot output file')
    ap.add_argument('--style', type=str, help='set matplotlib style')
    ap.add_argument('--figure-width', type=float, default=12, help='matplotlib figure width')
    ap.add_argument('--figure-height', type=float, default=8, help='matplotlib figure height')
    ap.add_argument('--bar-labels', action='store_true', help='add labels to bars')

    args = ap.parse_args()

    if not args.case:
        args.case = ['coveragepy', 'coveragepy-branch', 'slipcover', 'slipcover-branch']

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

    # sort Python versions semantically
    python_versions = sorted(v2r.keys(), key=lambda x: packaging.version.parse(x))
    print("versions: ", python_versions)

    # check data looks ok -- all should have the same cases
    common_cases = set.intersection(*(set(r.keys()) for r in v2r.values()))
    print("common cases: ", common_cases)
    assert common_cases == set(v2r[python_versions[0]].keys())

    # check that requested benchmark is available everywhere
    benchmarks = set.intersection(*(set(b.keys()) for r in v2r.values() for b in r.values()))
    if args.bench not in benchmarks:
        print(f"Benchmark {args.bench} not in common benchmarks {benchmarks}")
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

nonbase_cases = [c for c in cases if c.name != 'base' and c.name in args.case]

import matplotlib.pyplot as plt
import numpy as np

x = np.arange(len(python_versions))
n_bars = len(nonbase_cases)
width = .70 # of all bars
bars_x = np.arange(width/n_bars/2, width, width/n_bars) - width/2

if args.style:
    plt.style.use(args.style)

fig, ax = plt.subplots()
for case, bar_x in zip(nonbase_cases, bars_x):
    r = [v2r[v][case.name][args.bench]['median'] / v2r[v]['base'][args.bench]['median'] for v in python_versions]

    rects = ax.bar(x + bar_x, r, width/n_bars, label=case.label, color=case.color, zorder=2)

    if args.bar_labels:
        ax.bar_label(rects, padding=3, labels=[f'{v:.1f}x' for v in r], fontsize=8)

ax.set_title(args.title, size=18)
ax.set_ylabel('Normalized execution time', size=15)
ax.set_xticks(x, labels=python_versions, fontsize=15)
if not args.style:
    ax.grid(axis='y', alpha=.3)
ax.axhline(y=1, color='black', linewidth=1, alpha=.5, zorder=1)
ax.legend(fontsize=15)

fig.set_size_inches(args.figure_width, args.figure_height)
fig.tight_layout()
fig.savefig(args.out)
print(f"Plotted to {args.out}.")
print("")
