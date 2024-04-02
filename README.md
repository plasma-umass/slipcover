![slipcover](https://github.com/plasma-umass/slipcover/raw/main/docs/slipcover-logo.png)

# SlipCover: Near Zero-Overhead Python Code Coverage
by [Juan Altmayer Pizzorno](https://jaltmayerpizzorno.github.io) and [Emery Berger](https://emeryberger.com)
at UMass Amherst's [PLASMA lab](https://plasma-umass.org/).

[![license](https://img.shields.io/github/license/plasma-umass/slipcover?color=blue)](LICENSE)
[![pypi](https://img.shields.io/pypi/v/slipcover?color=blue)](https://pypi.org/project/slipcover/)
[![Downloads](https://static.pepy.tech/badge/slipcover)](https://pepy.tech/project/slipcover)
![pyversions](https://img.shields.io/pypi/pyversions/slipcover)
![tests](https://github.com/jaltmayerpizzorno/slipcover/workflows/tests/badge.svg)

## About Slipcover
SlipCover is a fast [code coverage](https://en.wikipedia.org/wiki/Code_coverage) tool.
It tracks a Python program as it runs and reports on the parts that executed and
those that didn't.
That can help guide your testing (showing code that isn't being tested), debugging,
[fuzzing](https://en.wikipedia.org/wiki/Fuzzing) or to find "dead" code.

Past code coverage tools can make programs significantly slower;
it is not uncommon for them to take twice as long to execute.
SlipCover aims to provide the same information with **near-zero overhead**, often 
almost as fast as running the original Python program.

### How it works
Previous coverage tools like [Coverage.py](https://github.com/nedbat/coveragepy) rely on 
[Python's tracing facilities](https://docs.python.org/3/library/sys.html?highlight=settrace#sys.settrace),
which add significant overhead.
Instead, SlipCover uses just-in-time instrumentation and de-instrumentation.
When SlipCover gathers coverage information, it modifies the program's Python byte codes,
inserting instructions that let it keep track the lines executed by the program.
As the program executes, SlipCover gradually removes instrumentation that
is no longer needed, allowing those parts to run at full speed.
Care is taken throughout SlipCover to keep things as efficient as possible.
On Python 3.12, rather than rewrite bytecode, SlipCover uses the new
[`sys.monitoring`](https://docs.python.org/3.12/library/sys.monitoring.html) API
to collect coverage information.


### Performance
<img src="benchmarks/cpython.png?raw=True" align="right" width="65%"/>
<img src="benchmarks/pypy.png?raw=True" align="right" width="65%"/>

[//]: # (CPython-range)
The first image on the right shows SlipCover's [speedup](https://en.wikipedia.org/wiki/Speedup),
ranging from 1.1x to 3.4x, in relation to [Coverage.py](https://github.com/nedbat/coveragepy), running on
[CPython 3.10.5](https://github.com/python/cpython).

The first two benchmarks are the test suites for [scikit-learn](https://scikit-learn.org/stable/)
and [Flask](https://flask.palletsprojects.com/);
"sudoku" runs [Peter Norvig's Sudoku solver](http://norvig.com/sudoku.html)
while the others were derived from the 
[Python Benchmark Suite](https://github.com/python/pyperformance).

More "Python-intensive" programs such as sudoku and those from the benchmark
suite (with a larger proportion of execution time spent in Python, rather than in native code)
generate more tracing events, causing more overhead in Coverage.py.
While each program's structure can affect SlipCover's ability to de-instrument,
its running time stays relatively close to the original.

[//]: # (PyPy-range)
On [PyPy 3.9](https://pypy.org), the speedup ranges from 2.1x to 104.9x.
Since it is so high for some of the benchmarks, we plot it on a logarithmic scale (see the second image on the right).

In a proof-of-concept integration with a property-based testing package,
SlipCover sped up coverage-based testing 22x.

### Accuracy
We verified SlipCover's accuracy against [Coverage.py](https://github.com/nedbat/coveragepy)
and against a [simple script](tools/oracle.py) of our own that collects coverage using Python tracing.
We found SlipCover's results to be accurate, in fact, in certain cases [more accurate](https://github.com/nedbat/coveragepy/issues/1358).

## Getting started
SlipCover is available from [PyPI](https://pypi.org/project/slipcover).
You can install it like any other Python module with
```console
pip3 install slipcover
```

You could then run your Python script with:
```console
python3 -m slipcover myscript.py
```

### Using it with a test harness
SlipCover can also execute a Python module, as in:
```console
python3 -m slipcover -m pytest -x -v
```
which starts `pytest`, passing it any options (`-x -v` in this example)
after the module name.
No plug-in is required for pytest.

## Usage example
```console
$ python3 -m slipcover -m pytest
================================================================ test session starts ================================================================
platform darwin -- Python 3.9.12, pytest-7.1.2, pluggy-1.0.0
rootdir: /Users/juan/project/wally/d2k-5, configfile: pytest.ini
plugins: hypothesis-6.39.3, mock-3.7.0, repeat-0.9.1, doctestplus-0.12.0, arraydiff-0.5.0
collected 439 items                                                                                                                                 

tests/box_test.py .........................                                                                                                   [  5%]
tests/image_test.py ...............                                                                                                           [  9%]
tests/network_equivalence_test.py .........................................s................................................................. [ 33%]
..............................................................................                                                                [ 51%]
tests/network_test.py ....................................................................................................................... [ 78%]
...............................................................................................                                               [100%]

=================================================== 438 passed, 1 skipped, 62 warnings in 48.43s ====================================================

File                                 #lines    #miss    Cover%  Lines missing
---------------------------------  --------  -------  --------  ------------------------
d2k/__init__.py                           3        0       100
d2k/box.py                              105       27        74  73, 142-181
d2k/image.py                             38        4        89  70-73
d2k/network.py                          359        1        99  236
tests/box_test.py                       178        0       100
tests/darknet.py                        132       11        91  146, 179-191
tests/image_test.py                      45        0       100
tests/network_equivalence_test.py       304       30        90  63, 68, 191-215, 455-465
tests/network_test.py                   453        0       100
$ 
```
As can be seen in the coverage report, d2k lacks some coverage, especially in
its `box.py` and `image.py` components.

## Platforms
Our GitHub workflows run the automated test suite on Linux, MacOS and Windows, but
really it should work anywhere where CPython/PyPy does.

## Contributing
SlipCover is under active development; contributions are welcome!
Please also feel free to [create a new issue](https://github.com/jaltmayerpizzorno/slipcover/issues/new)
with any suggestions or issues you may encounter.

## Technical Information
For more details about how SlipCover works please see the following paper, published at [ISSTA'23](https://conf.researchr.org/home/issta-2023): [SlipCover: Near Zero-Overhead Code Coverage for Python](https://arxiv.org/pdf/2305.02886).

# Acknowledgements

Logo design by [Sophia Berger](https://www.linkedin.com/in/sophia-berger/).

This material is based upon work supported by the National Science
Foundation under Grant No. 1955610. Any opinions, findings, and
conclusions or recommendations expressed in this material are those of
the author(s) and do not necessarily reflect the views of the National
Science Foundation.
