![pypi](https://img.shields.io/pypi/v/slipcover)
![pyversions](https://img.shields.io/pypi/pyversions/slipcover)
[![license](https://img.shields.io/pypi/l/slipcover)](LICENSE)

# Slipcover: Zero-Overhead Python Code Coverage
by [Juan Altmayer Pizzorno](https://www.linkedin.com/in/juan-altmayer-pizzorno/) and [Emery Berger](https://emeryberger.com).

## About Slipcover
Slipcover is a [code coverage](https://en.wikipedia.org/wiki/Code_coverage) tool.
It keeps tracks of which parts are executing as a Python program runs, and then reports
on them as well as well as on the parts that didn't execute.
You could use that information to guide your testing, debugging, or a
[fuzzing](https://en.wikipedia.org/wiki/Fuzzing) tool.

Tools that gather coverage information often make programs significantly slower;
it is not uncommon for them to take twice as long to execute.
Slipcover aims to provide the information with near-zero overhead, essentially
indistinguishable from measurement noise.

## How it works
Slipcover uses just-in-time instrumentation and de-instrumentation.
When a program is started with slipcover, it modifies the program's Python byte codes,
inserting instructions that allows it to keep track of where the program is.
Then, while the program executes, slipcover gradually removes instrumentation of those
parts that it already saw executing, allowing those to run faster.
Care is taken thoughout slipcover to keep things as efficient as possible.

## Getting started
Slipcover is available from [PyPI](https://pypi.org/project/slipcover).
You can install it like any other Python module with
```console
pip3 install slipcover
```

You could then run your Python script with:
```console
python3 -m slipcover myscript.py
```

## Using it with a test harness
Slipcover can also execute a Python module, as in:
```console
python3 -m slipcover -m pytest -x -v
```
which starts `pytest` passing it any options (`-x -v` in this example)
after the module name.

## Contributing
Slipcover is very young, and under active development.
Please feel free to [create a new issue](https://github.com/jaltmayerpizzorno/slipcover/issues/new)
with any suggestions or issues you may encounter.

# Acknowledgements
This material is based upon work supported by the National Science
Foundation under Grant No. 1955610. Any opinions, findings, and
conclusions or recommendations expressed in this material are those of
the author(s) and do not necessarily reflect the views of the National
Science Foundation.
