import setuptools
import sys
import os
import re
from pathlib import Path

try:
    import tomllib  # available in Python 3.11+
except ImportError:
    import tomli as tomllib


PYTHON_VERSION = sys.version_info[0:2]


def get_version():
    v = re.findall(r"^__version__ *= *\"([^\"]+)\"", Path("src/slipcover/version.py").read_text())[0]
    return v


def get_dev_build():
    # If we're testing packaging, build using a ".devN" suffix in the version number,
    # so that we can upload new files (as testpypi/pypi don't allow re-uploading files with
    # the same name as previously uploaded).
    # Numbering scheme: https://www.python.org/dev/peps/pep-0440
    return '.dev' + Path('dev-build.txt').read_text().strip() if Path('dev-build.txt').exists() else ''


def get_url():
    return tomllib.loads(Path("pyproject.toml").read_text())['project']['urls']['Repository']


def get_description():
    text = Path("README.md").read_text(encoding="utf-8")

    # Rewrite any relative paths to version-specific absolute paths,
    # so that they work from within PyPI
    sub = r'\1' + get_url() + "/blob/v" + get_version() + r'/\2'
    text = re.sub(r'(src=")((?!https?://))', sub, text)
    text = re.sub(r'(\[.*?\]\()((?!https?://))', sub, text)

    return text


def platform_compile_args():
    # If flags are specified as a global env var, use them: this happens in
    # the conda build, and is needed to override build configurations on osx
    if flags := os.environ.get("CXXFLAGS", "").split():
        return flags

    if sys.platform == 'darwin':
        # default to a multi-arch build
        return ['-arch', 'x86_64', '-arch', 'arm64', '-arch', 'arm64e']
    if sys.platform == 'win32':
        # avoids creating Visual Studio dependencies
        return ['/MT']
    return []


def platform_link_args():
    if sys.platform != 'win32':
        return platform_compile_args() # clang/gcc is used
    return []


def limited_api_args():
    # We use METH_FASTCALL, which is only in the Python 3.10+ stable ABI
    if PYTHON_VERSION >= (3,10) and PYTHON_VERSION < (3,12):
        return ['-DPy_LIMITED_API=0x030a0000'] # this needs to match 'cp310' in 'options'

    return []


def ext_modules():
    if PYTHON_VERSION >= (3,12):
        return []

    def cxx_version(v):
        return [f"-std={v}" if sys.platform != "win32" else f"/std:{v}"]

    return [setuptools.extension.Extension(
        'slipcover.probe',
        sources=['src/probe.cxx'],
        extra_compile_args=cxx_version('c++17') + platform_compile_args() + limited_api_args(),
        extra_link_args=platform_link_args(),
        py_limited_api=bool(limited_api_args()),
        language='c++',
    )]


def bdist_wheel_options():
    options = {}

    if limited_api_args():
        options['py_limited_api'] = 'cp310'

    if PYTHON_VERSION >= (3,12):
        # for Python 3.12 onwards, we're a pure Python distribution
        assert not ext_modules()
        options['python_tag'] = 'py312' # this requires 3.12+

    # Build universal wheels on MacOS.
    if sys.platform == 'darwin' and ext_modules() and \
       sum(arg == '-arch' for arg in platform_compile_args()) > 1:
        # On MacOS >= 11, all builds are compatible for a major MacOS version, so Python "floors"
        # all minor versions to 0, leading to tags like like "macosx_11_0_universal2". If you use
        # the actual (non-0) minor name in the build platform, pip doesn't install it.
        import platform
        v = platform.mac_ver()[0]
        major = int(v.split('.')[0])
        if major >= 11:
            v = f"{major}.0"
        options['plat_name'] = f"macosx-{v}-universal2"

    return options


setuptools.setup(
    version=get_version() + get_dev_build(),
    long_description=get_description(),
    long_description_content_type="text/markdown",
    ext_modules=ext_modules(),
    options={'bdist_wheel': bdist_wheel_options()}
)
