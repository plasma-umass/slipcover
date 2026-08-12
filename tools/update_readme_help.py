#!/usr/bin/env python3
"""Refreshes the '--help' transcript in README.md's "Command-line options"
section from the actual current output, so it can't silently go stale.
Run after changing any argparse option in __main__.py.
"""
import re
import subprocess
import sys
from pathlib import Path

readme_path = Path(__file__).resolve().parent.parent / "README.md"

help_text = subprocess.run(
    [sys.executable, "-m", "slipcover", "--help"],
    check=True, capture_output=True, text=True
).stdout

readme = readme_path.read_text()

readme, n = re.subn(
    r'(\[//\]: # \(help-output\)\n```console\n\$ python3 -m slipcover --help\n).*?(\n```)',
    lambda m: m.group(1) + help_text.rstrip('\n') + m.group(2),
    readme, flags=re.S
)
if n != 1:
    sys.exit("update_readme_help.py: expected exactly one help-output marker in README.md")

readme_path.write_text(readme)
print("README.md's --help transcript updated.")
