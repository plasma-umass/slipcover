all:
	python3 -m pip install -e .

# obtained with e.g. "brew install python@3.10"
HOMEBREW_PYTHON=/usr/local/opt/python@
test:
	- rm -f .coverage
	@ for p in 3.8 3.9 3.10; do \
	  ${HOMEBREW_PYTHON}$$p/bin/python3 --version; \
	  ${HOMEBREW_PYTHON}$$p/bin/python3 -m pip install -e .; \
	  ${HOMEBREW_PYTHON}$$p/bin/python3 -m coverage run -a --include 'slipcover/*' \
	                                    -m pytest --no-header --tb=no; \
	done
	python3 -m coverage report -m

bench:
	python3 -m pip install -e .
	python3 benchmarks/run_benchmarks.py

clean:
	- rm -rf *.so slipcover/*.so
	- rm -rf *.egg-info
	- rm -rf build dist
	- find . -iname __pycache__ -exec rm -r {} \;
