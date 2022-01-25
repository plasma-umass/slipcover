![pypi](https://img.shields.io/pypi/v/slipcover)
![pyversions](https://img.shields.io/pypi/pyversions/slipcover)
[![license](https://img.shields.io/pypi/l/slipcover)](LICENSE)

# Slipcover: Zero-Overhead Python Code Coverage
by [Juan Altmayer Pizzorno](https://www.linkedin.com/in/juan-altmayer-pizzorno/) and [Emery Berger](https://emeryberger.com)
at UMass Amherst's [PLASMA lab](https://plasma-umass.org/).

## About Slipcover
Slipcover is a fast [code coverage](https://en.wikipedia.org/wiki/Code_coverage) tool.
It tracks a Python program as it runs and reports on the parts that executed and
those that didn't.
That can help guide your testing (showing code that isn't being tested), debugging,
or [fuzzing](https://en.wikipedia.org/wiki/Fuzzing).

Past code coverage tools can make programs significantly slower;
it is not uncommon for them to take twice as long to execute.
Slipcover aims to provide the same information with **near-zero overhead**, that is, 
just as fast as running the original Python program.

## How it works
Slipcover uses just-in-time instrumentation and de-instrumentation.
When Slipcover is used to gather coverage information, it modifies the program's Python byte codes,
inserting instructions that let it keep track the lines executed by the program.
As the program executes, Slipcover gradually removes instrumentation that
is no longer needed, allowing those parts to run at full speed.
Care is taken thoughout Slipcover to keep things as efficient as possible.

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
which starts `pytest`, passing it any options (`-x -v` in this example)
after the module name.

## Contributing
Slipcover is alpha software, and under active development.
Please feel free to [create a new issue](https://github.com/jaltmayerpizzorno/slipcover/issues/new)
with any suggestions or issues you may encounter.

# Acknowledgements
This material is based upon work supported by the National Science
Foundation under Grant No. 1955610. Any opinions, findings, and
conclusions or recommendations expressed in this material are those of
the author(s) and do not necessarily reflect the views of the National
Science Foundation.
