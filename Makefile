all:
	python3 setup.py bdist_wheel

# obtained with e.g. "brew install python@3.10"
HOMEBREW_PYTHON=/usr/local/opt/python@
test-all:
	@ for p in 3.8 3.9 3.10; do \
	  ${HOMEBREW_PYTHON}$$p/bin/python3 --version; \
	  ${HOMEBREW_PYTHON}$$p/bin/python3 -m pytest --no-header --tb=no; \
	done

clean:
	- rm -rf *.so
	- rm -rf *.egg-info
	- rm -rf build
