import setuptools
import sys
import os
from pathlib import Path

def get_version():
    import re
    v = re.findall(r"\nVERSION *= *\"([^\"]+)\"", Path("src/slipcover/slipcover.py").read_text())[0]
    return v

VERSION = get_version()
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

dev_build = '.dev' + Path('dev-build.txt').read_text().strip() if Path('dev-build.txt').exists() else ''

def cxx_version(v):
    return [f"-std={v}" if sys.platform != "win32" else f"/std:{v}"]

def platform_compile_args():
    # If flags are specified as a global env var use them,
    # this happens during conda build,
    # and is needed to override build configurations on osx
    if flags := os.environ.get("CXXFLAGS", "").split():
        return flags

    # Otherwise default to a multi-arch build
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


probe = setuptools.extension.Extension(
    'slipcover.probe',
    sources=['src/probe.cxx'],
    extra_compile_args=cxx_version('c++17') + platform_compile_args() + limited_api_args(),
    extra_link_args=platform_link_args(),
    py_limited_api=bool(limited_api_args()),
    language='c++',
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
    package_dir={'': 'src'},
    ext_modules=([probe]),
    python_requires=">=3.8,<3.12",
    install_requires=[
        "tabulate"
    ],
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows :: Windows 10"
    ]
)
