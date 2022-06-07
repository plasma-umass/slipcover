import setuptools
from setuptools.command.build_ext import build_ext
from os import path, environ
import sys
from pathlib import Path

VERSION = "0.1.7"
REPO_URL = "https://github.com/plasma-umass/slipcover"

def get_description():
#    from pathlib import Path
    import re
    readme_md = Path("README.md")
    text = readme_md.read_text(encoding="utf-8")

    # rewrite any relative paths to version-specific absolute paths
    sub = r'\1' + REPO_URL + "/blob/v" + VERSION + r'/\2'
    text = re.sub(r'(src=")((?!https?://))', sub, text)
    text = re.sub(r'(\[.*?\]\()((?!https?://))', sub, text)

    return text

# If we're testing packaging, build using a ".devN" suffix in the version number,
# so that we can upload new files (as testpypi/pypi don't allow re-uploading files with
# the same name as previously uploaded).
# Numbering scheme: https://www.python.org/dev/peps/pep-0440
#dev_build = ('.dev' + environ['DEV_BUILD']) if 'DEV_BUILD' in environ else ''

dev_build = '.dev' + Path('dev-build.txt').read_text().strip() if Path('dev-build.txt').exists() else ''

def cxx_version(v):
    return [f"-std={v}" if sys.platform != "win32" else f"/std:{v}"]

def platform_compile_args():
    if sys.platform == 'darwin':
        return "-arch x86_64 -arch arm64 -arch arm64e".split()
    if sys.platform == 'win32':
        return ['/MT']  # avoids creating Visual Studio dependencies
    return []

def platform_link_args():
    if sys.platform != 'win32':
        return platform_compile_args() # clang/gcc is used
    return []

def limited_api_args():
    # We would like to use METH_FASTCALL, but that's only available in the
    # Python 3.10+ stable ABI, and we'd like to support Python 3.8+
    #
    # To re-enable, we also need setup.cfg with
    #
    # [bdist_wheel]
    # py-limited-api=cp310
    #
#    return ['-DPy_LIMITED_API=0x030a0000']
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
            extra_compile_args=cxx_version('c++17') + platform_compile_args() + limited_api_args(),
            extra_link_args=platform_link_args(),
            py_limited_api=bool(limited_api_args()),
            language='C++'
)


setuptools.setup(
    name="slipcover",
    version=VERSION + dev_build,
    description="Near Zero-Overhead Python Code Coverage",
    keywords="coverage testing",
    long_description=get_description(),
    long_description_content_type="text/markdown",
    url="https://github.com/plasma-umass/slipcover",
    author="Juan Altmayer Pizzorno, Emery Berger",
    author_email="juan@altmayer.com, emery@cs.umass.edu",
    license="Apache License 2.0",
    packages=['slipcover'],
    ext_modules=([tracker]),
    python_requires=">=3.8,<3.12",
    install_requires=[
        "tabulate"
    ],
    cmdclass={"build_ext": CppExtension},
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows :: Windows 10"
    ]
)
