all:
	python3 -m pip install -e .

# obtained with e.g. "brew install python@3.10"
HOMEBREW_PYTHON=/opt/homebrew/opt/python@
test:
	- rm -f .coverage
	@ for V in 3.8 3.9 3.10 3.11; do \
	    P=$$(command -v ${HOMEBREW_PYTHON}$$V/bin/python3 || command -v python$$V); \
	    if ! [ -z $$P ]; then \
	      $$P --version; \
	      $$P -m pip -q install -e .; \
	      $$P -m coverage run -a --branch --include 'slipcover/*' -m pytest --no-header --tb=no || break; \
	    fi; \
	done
	- python3 -m coverage report -m

JustUnit/JustUnit.cxx:
	git submodule init
	git submodule update

pyptr_test: tests/pyptr_test.cxx pyptr.h JustUnit/JustUnit.cxx
	clang++ --std=c++17 -I. -IJustUnit $(shell python3-config --cflags) \
		$(shell python3-config --ldflags --embed) -o $@ $< JustUnit/JustUnit.cxx
	./pyptr_test

bench:
	python3 -m pip install -e .
	- find . -iname \*__pycache__\* | xargs rm -rf
	python3 benchmarks/run_benchmarks.py

clean:
	- rm -rf *.so slipcover/*.so
	- rm -rf *.egg-info
	- rm -rf build dist
	- find . -iname __pycache__ -exec rm -r '{}' \+
	- rm -rf .pytest_cache
	- rm -rf pyptr_test *.dSYM
