all:
	python3 -m pip install -e .

# obtained with e.g. "brew install python@3.10"
HOMEBREW_PYTHON=/opt/homebrew/opt/python@
test:
	- rm -f .coverage
	@ for V in 3.8 3.9 3.10 3.11 3.12 3.13; do \
	    P=$$(command -v ${HOMEBREW_PYTHON}$$V/bin/python3 || command -v python$$V); \
	    if ! [ -z $$P ]; then \
	      $$P --version; \
	      $$P -O -m pip uninstall -y slipcover; \
	      $$P -m pip -q install -e .; \
	      $$P -m coverage run -a --branch --include 'src/slipcover/*' -m pytest --no-header --tb=no || break; \
	    fi; \
	done
	- python3 -m coverage report -m

JustUnit/JustUnit.cxx:
	git submodule init
	git submodule update

pyptr_test: tests/pyptr_test.cxx src/pyptr.h JustUnit/JustUnit.cxx
	clang++ --std=c++17 -Isrc -IJustUnit $(shell python3-config --cflags) \
		$(shell python3-config --ldflags --embed) -o $@ $< JustUnit/JustUnit.cxx
	./pyptr_test

bench:
	python3 -m pip install -e .
	- find . -iname \*__pycache__\* | xargs rm -rf
	python3 benchmarks/run_benchmarks.py

plot:
	python3 benchmarks/benchmarks.py plot --os=Linux --python=3.10.5 --omit-bench matplotlib --out benchmarks/cpython.png --speedup --title "Slipcover Coverage Speedup on CPython (higher is better)" --bar-labels --edit-readme "CPython-range"
	python3 benchmarks/benchmarks.py plot --os=Linux --python=pypy3.9.16 --out benchmarks/pypy.png --speedup --title "Slipcover Coverage Speedup on PyPy (log scale; higher is better)" --yscale log --bar-labels --edit-readme "PyPy-range"

clean:
	- rm -rf *.so src/slipcover/*.so
	- rm -rf src/*.egg-info
	- rm -rf build dist
	- find . -iname __pycache__ -exec rm -r '{}' \+
	- rm -rf .pytest_cache
	- rm -rf pyptr_test *.dSYM
