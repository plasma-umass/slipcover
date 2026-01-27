from .version import __version__
from .slipcover import Slipcover, merge_coverage, print_coverage, print_xml
from .importer import FileMatcher, ImportManager, wrap_pytest, wrap_spec_from_file_location
from .fuzz import wrap_function
