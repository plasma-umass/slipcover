[![license](https://img.shields.io/github/license/plasma-umass/slipcover?color=blue)](LICENSE)
[![pypi](https://img.shields.io/pypi/v/slipcover?color=blue)](https://pypi.org/project/slipcover/)
![pyversions](https://img.shields.io/pypi/pyversions/slipcover)
![tests](https://github.com/jaltmayerpizzorno/slipcover/workflows/tests/badge.svg)

# Slipcover: Near Zero-Overhead Python Code Coverage
by [Juan Altmayer Pizzorno](https://www.linkedin.com/in/juan-altmayer-pizzorno/) and [Emery Berger](https://emeryberger.com)
at UMass Amherst's [PLASMA lab](https://plasma-umass.org/).

## About Slipcover
Slipcover is a fast [code coverage](https://en.wikipedia.org/wiki/Code_coverage) tool.
It tracks a Python program as it runs and reports on the parts that executed and
those that didn't.
That can help guide your testing (showing code that isn't being tested), debugging,
[fuzzing](https://en.wikipedia.org/wiki/Fuzzing) or to find "dead" code.

Past code coverage tools can make programs significantly slower;
it is not uncommon for them to take twice as long to execute.
Slipcover aims to provide the same information with **near-zero overhead**, often 
almost as fast as running the original Python program.

### How it works
Previous coverage tools like [Coverage.py](https://github.com/nedbat/coveragepy) rely on 
[Python's tracing facilities](https://docs.python.org/3/library/sys.html?highlight=settrace#sys.settrace),
which add significant overhead.
Instead, Slipcover uses just-in-time instrumentation and de-instrumentation.
When Slipcover gathers coverage information, it modifies the program's Python byte codes,
inserting instructions that let it keep track the lines executed by the program.
As the program executes, Slipcover gradually removes instrumentation that
is no longer needed, allowing those parts to run at full speed.
Care is taken throughout Slipcover to keep things as efficient as possible.

### Performance
<img src="benchmarks/benchmarks.png?raw=True" align="right" width="50%"/>

The image on the right shows the execution time of a few benchmarks.
It compares how long they take to run while tracking coverage using [Coverage.py](https://github.com/nedbat/coveragepy)
and tracking coverage using Slipcover, relative to their normal running times.

The first two benchmarks are the test suites for [scikit-learn](https://scikit-learn.org/stable/)
and [Flask](https://flask.palletsprojects.com/);
"sudoku" runs [Peter Norvig's Sudoku solver](http://norvig.com/sudoku.html)
while the others were derived from the 
[Python Benchmark Suite](https://github.com/python/pyperformance).

More "Python-intensive" programs such as sudoku and those from the benchmark
suite (with a larger proportion of execution time spent in Python, rather than in native code)
generate more tracing events, causing more overhead in Coverage.py.
While each program's structure can affect Slipcover's ability to de-instrument,
its running time stays relatively close to the original, mostly at 5% or less overhead.

### Accuracy
We verified Slipcover's accuracy against [Coverage.py](https://github.com/nedbat/coveragepy)
and against a [simple script](tools/oracle.py) of our own that collects coverage using Python tracing.
We found Slipcover's results to be accurate, in fact, in certain cases [more accurate](https://github.com/nedbat/coveragepy/issues/1358).

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

### Using it with a test harness
Slipcover can also execute a Python module, as in:
```console
python3 -m slipcover -m pytest -x -v
```
which starts `pytest`, passing it any options (`-x -v` in this example)
after the module name.
No plug-in is required for pytest.

## Usage example
```console
$ python3 -m slipcover -m pytest --disable-warnings
============================================================================= test session starts ==============================================================================
platform darwin -- Python 3.9.9, pytest-6.2.5, py-1.11.0, pluggy-1.0.0
rootdir: /Users/juan/project/wally/d2k-5
collected 439 items                                                                                                                                                            

tests/box_test.py .........................                                                                                                                              [  5%]
tests/image_test.py ...............                                                                                                                                      [  9%]
tests/network_equivalence_test.py .........................................s............................................................................................ [ 39%]
...................................................                                                                                                                      [ 51%]
tests/network_test.py .................................................................................................................................................. [ 84%]
....................................................................                                                                                                     [100%]

================================================================= 438 passed, 1 skipped, 53 warnings in 55.31s =================================================================

File                #lines    #missed    Cover%  Lines missing
----------------  --------  ---------  --------  ---------------------------------------------------------------------------------------------------
d2k/__init__.py          3          0       100
d2k/network.py         359          1       100  236
d2k/box.py             105         27        74  73, 142, 144-146, 148-149, 151, 154, 156-159, 161, 163-166, 168, 170-171, 173-174, 176-177, 180-181
d2k/image.py            38          4        89  70-73
tests/darknet.py       132         11        92  146, 179-181, 183-187, 189, 191
$
```
As can be seen in the coverage report, d2k lacks some coverage, especially in
its `box.py` and `image.py` components.

## Platforms
Our GitHub workflows run the automated test suite on Linux, MacOS and Windows, but
really it should work anywhere where CPython does.

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
