import setuptools
from setuptools.command.build_ext import build_ext
from os import path, environ
import sys

def read_file(name):
    """Returns a file's contents"""
    with open(path.join(path.dirname(__file__), name), encoding="utf-8") as f:
        return f.read()

# If we're testing packaging, build using a ".devN" suffix in the version number,
# so that we can upload new files (as testpypi/pypi don't allow re-uploading files with
# the same name as previously uploaded).
# Numbering scheme: https://www.python.org/dev/peps/pep-0440
dev_build = ('.dev' + environ['DEV_BUILD']) if 'DEV_BUILD' in environ else ''

def cxx_version():
    return "-std=c++17" if sys.platform != "win32" else "/std:c++17"

def platform_args():
    if sys.platform == 'darwin':
        return "-arch x86_64 -arch arm64 -arch arm64e".split()
    return []

class CppExtension(build_ext):
    def build_extensions(self):
        if sys.platform == "linux":
            self.compiler.compiler_so[0] = "g++"
            self.compiler.compiler_cxx[0] = "g++"
            self.compiler.linker_so[0] = "g++"
        build_ext.build_extensions(self)

tracker = setuptools.extension.Extension(
            'slipcover.tracker',
            sources=['tracker.cxx'],
            extra_compile_args=[cxx_version()] + platform_args(),
            py_limited_api=True,
            language='C++'
)


setuptools.setup(
    name="slipcover",
    version="0.1" + dev_build,
    description="Near Zero-Overhead Python Code Coverage",
    keywords="coverage testing",
    long_description=read_file("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/plasma-umass/slipcover",
    author="Juan Altmayer Pizzorno, Emery Berger",
    author_email="juan@altmayer.com, emery@cs.umass.edu",
    license="Apache License 2.0",
    packages=['slipcover'],
    ext_modules=([tracker]),
    python_requires=">=3.8,<3.11",
    install_requires=[
        "tabulate"
    ],
    cmdclass={"build_ext": CppExtension}
)
