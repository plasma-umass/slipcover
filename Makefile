all:
	python3 setup.py develop

clean:
	- rm -rf *.so
	- rm -rf *.egg-info
	- rm -rf build
