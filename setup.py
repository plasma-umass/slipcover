from setuptools import setup, find_packages
from os import path, environ

def read_file(name):
    """Returns a file's contents"""
    with open(path.join(path.dirname(__file__), name), encoding="utf-8") as f:
        return f.read()

# If we're testing packaging, build using a ".devN" suffix in the version number,
# so that we can upload new files (as testpypi/pypi don't allow re-uploading files with
# the same name as previously uploaded).
# Numbering scheme: https://www.python.org/dev/peps/pep-0440
dev_build = ('.dev' + environ['DEV_BUILD']) if 'DEV_BUILD' in environ else ''

setup(
    name="slipcover",
    version="0.1" + dev_build,
    description="Zero-Overhead Python Code Coverage",
    keywords="coverage testing",
    long_description=read_file("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/jaltmayerpizzorno/slipcover",
    author="Juan Altmayer Pizzorno, Emery Berger",
    author_email="juan@altmayer.com, emery@cs.umass.edu",
    license="Apache License 2.0",
    python_requires=">=3.8,<3.11"
)
