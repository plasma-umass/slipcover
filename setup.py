from setuptools import setup, find_packages
from os import path

def read_file(name):
    """Returns a file's contents"""
    with open(path.join(path.dirname(__file__), name), encoding="utf-8") as f:
        return f.read()

setup(
    name="slipcover",
    version='0.1',
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
