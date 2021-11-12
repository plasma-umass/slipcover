from setuptools import setup, find_packages
from setuptools.extension import Extension
import sys

def extra_compile_args():
    """Returns extra compiler args for platform."""
    if sys.platform == 'win32':
        return ['/std:c++14'] # for Visual Studio C++

    return ['-std=c++14']

setup(
    name="slipcover",
    version='0.1',
    description="XXX add description here",
    keywords="program coverage",
#    long_description=read_file("README.md"),
#    long_description_content_type="text/markdown",
#    url="",
#    author="",
#    author_email="",
#    license="MIT",
    ext_modules=[
        Extension('stackpatch',
            include_dirs=[],
            sources = ['./stackpatch.cxx'],
            extra_compile_args=extra_compile_args(),
            py_limited_api=False,
            language="c++")
    ],
    python_requires=">=3.7" if sys.platform != 'win32' else ">=3.8",
)
