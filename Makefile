all:
	python3 -m pip install -e .

# obtained with e.g. "brew install python@3.10"
HOMEBREW_PYTHON=/usr/local/opt/python@
test:
	- rm -f .coverage
	@ for V in 3.8 3.9 3.10; do \
	    P=$$(command -v ${HOMEBREW_PYTHON}$$V/bin/python3 || command -v python$$V); \
	    if ! [ -z $$P ]; then \
	      $$P --version; \
	      $$P -m pip -q install -e .; \
	      $$P -m coverage run -a --include 'slipcover/*' -m pytest --no-header --tb=no; \
	    fi; \
	done
	- python3 -m coverage report -m

bench:
	python3 -m pip install -e .
	python3 benchmarks/run_benchmarks.py

clean:
	- rm -rf *.so slipcover/*.so
	- rm -rf *.egg-info
	- rm -rf build dist
	- find . -iname __pycache__ -exec rm -r {} \;
