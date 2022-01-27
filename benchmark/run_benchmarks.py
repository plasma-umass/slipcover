import numpy as np
import matplotlib.pyplot as plt
import pickle
import re

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
    with open('benchmark.pkl', 'rb') as f:
        results = pickle.load(f)

except FileNotFoundError:
    from pathlib import Path

    results = dict()

    for bench in [*Path('benchmark').glob('*.py'), Path('test/testme.py')]:
        match = re.search('^(bm_)?(.*?)\.py$', bench.name)
        name = match.group(2) if match else bench.name
        if bench not in results:
            results[name] = dict()

        results[name]['(no coverage)'] = run_command(f"python3 {bench}")
        results[name]['coverage.py'] = \
                run_command(f"python3 -m coverage run --include={bench} {bench}")
        results[name]['Slipcover'] = run_command(f"python3 -m slipcover {bench}")

    with open('benchmark.pkl', 'wb') as f:
        pickle.dump(results, f, pickle.HIGHEST_PROTOCOL)

bars = list(results[next(iter(results))].keys())

benchmarks = list(results.keys())
x = np.arange(len(benchmarks))
n_bars = len(bars)
width = .70 # of all bars
bar_x = np.arange(width/n_bars/2, width, width/n_bars) - width/2

fig, ax = plt.subplots()
for i, bar in enumerate(bars):
    rects = ax.bar(x + bar_x[i], [sum(results[bench][bar]) for bench in benchmarks],
                   width/n_bars, label=bar)
    ax.bar_label(rects, padding=3)

#ax.set_title('Execution time')
ax.set_ylabel('CPU seconds')
ax.set_xticks(x, labels=benchmarks)
ax.legend()

fig.tight_layout()
fig.savefig("benchmark.png")
