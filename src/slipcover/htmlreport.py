# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0
# For details: https://github.com/coveragepy/coveragepy/blob/main/NOTICE.txt

"""HTML reporting for slipcover.

The pages, stylesheet and script are slipcover's own.  Adapted from coverage.py
(https://github.com/coveragepy/coveragepy, Apache License 2.0): data_filename,
read_data and write_html below, and the design of the incremental status file
and the report loop.  The NOTICE file at the root of this repository has
details.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import tokenize
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

from .lcovreport import get_branch_info
from .phystokens import source_token_lines
from .version import __url__, __version__

if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional, Set, Tuple

    from .schemas import Coverage, CoverageFile


# Files copied verbatim from htmlfiles/ into the output directory.
STATIC_FILES = ("style.css", "slipcover.js")

# Bump this when the generated markup changes, so an incremental run rebuilds
# pages written by an older slipcover instead of leaving a mix on disk.  The
# assets are hashed directly (see check_global_data); the markup lives in this
# module, where there is nothing to hash but the module itself.
MARKUP_VERSION = "1"

# What tokenizing can raise on a file that no longer parses.  IndentationError
# is a SyntaxError; TokenError is raised on unterminated constructs.
_TOKENIZE_ERRORS = (SyntaxError, tokenize.TokenError, UnicodeDecodeError, ValueError)


def data_filename(fname: str) -> str:
    """Return the path to an "htmlfiles" data file of ours."""
    return os.path.join(os.path.dirname(__file__), "htmlfiles", fname)


def read_data(fname: str) -> str:
    """Return the contents of a data file of ours."""
    with open(data_filename(fname), encoding="utf-8") as data_file:
        return data_file.read()


def write_html(fname: str, html: str) -> None:
    """Write `html` to `fname`, properly encoded."""
    html = re.sub(r"(\A\s+)|(\s+$)", "", html, flags=re.MULTILINE) + "\n"
    with open(fname, "wb") as fout:
        fout.write(html.encode("ascii", "xmlcharrefreplace"))


def flat_rootname(filename: str) -> str:
    """Return a base name for the HTML page describing `filename`.

    Files in a directory get a prefix derived from the directory, so that two
    files with the same base name don't collide.  Separators are normalized
    first so the same source file yields the same page name on every platform.

    """
    normalized = filename.replace("\\", "/")
    dirname, _, basename = normalized.rpartition("/")
    if dirname:
        fp = hashlib.sha3_256(dirname.encode("utf-8")).hexdigest()[:16]
        prefix = f"z_{fp}_"
    else:
        prefix = ""
    return prefix + basename.replace(".", "_")


def pretty_file(filename: str) -> str:
    """Return a prettier version of an already-escaped `filename`.

    The separators are wrapped so a long path can wrap after one.  The result
    is HTML, so what goes in has to be escaped already.

    """
    return re.sub(r"[/\\]", '<span class="sep">\\g<0></span>', filename)


def _percent(nom: int, den: int) -> float:
    """The percentage `nom` is of `den`, matching slipcover's own summaries."""
    return 100.0 if den == 0 else 100 * nom / den


def _percent_str(nom: int, den: int) -> str:
    """`_percent` rounded for display.

    Rounding alone would let a file with missing lines read as "100", so the
    extremes are reserved for genuinely complete/empty coverage.

    """
    pc = _percent(nom, den)
    rounded = int(round(pc))
    if rounded == 100 and nom != den:
        return "99"
    if rounded == 0 and nom != 0:
        return "1"
    return str(rounded)


class Nums:
    """The counts describing one file, or the totals across files.

    The values come from slipcover's own per-file summaries; only the ratios
    and percentages used by the templates are derived here.

    """

    def __init__(
        self,
        n_statements: int = 0,
        n_executed: int = 0,
        n_branches: int = 0,
        n_executed_branches: int = 0,
        n_partial_branches: int = 0,
    ) -> None:
        self.n_statements = n_statements
        self.n_executed = n_executed
        self.n_branches = n_branches
        self.n_executed_branches = n_executed_branches
        self.n_partial_branches = n_partial_branches

    def __add__(self, other: Nums) -> Nums:
        return Nums(
            n_statements=self.n_statements + other.n_statements,
            n_executed=self.n_executed + other.n_executed,
            n_branches=self.n_branches + other.n_branches,
            n_executed_branches=self.n_executed_branches + other.n_executed_branches,
            n_partial_branches=self.n_partial_branches + other.n_partial_branches,
        )

    def as_dict(self) -> Dict[str, int]:
        return {
            "n_statements": self.n_statements,
            "n_executed": self.n_executed,
            "n_branches": self.n_branches,
            "n_executed_branches": self.n_executed_branches,
            "n_partial_branches": self.n_partial_branches,
        }

    @property
    def n_missing(self) -> int:
        return self.n_statements - self.n_executed

    @property
    def ratio_statements(self) -> Tuple[int, int]:
        return (self.n_executed, self.n_statements)

    @property
    def ratio_branches(self) -> Tuple[int, int]:
        return (self.n_executed_branches, self.n_branches)

    @property
    def ratio_covered(self) -> Tuple[int, int]:
        return (
            self.n_executed + self.n_executed_branches,
            self.n_statements + self.n_branches,
        )

    @property
    def pc_statements_str(self) -> str:
        return _percent_str(*self.ratio_statements)

    @property
    def pc_branches_str(self) -> str:
        return _percent_str(*self.ratio_branches)

    @property
    def pc_covered_str(self) -> str:
        return _percent_str(*self.ratio_covered)


class LineData:
    """The data for one source line of HTML output."""

    def __init__(self, number: int, category: str, tokens: List[Tuple[str, str]]) -> None:
        self.number = number
        self.category = category
        self.tokens = tokens
        self.html = ""
        self.annotate: Optional[str] = None
        self.annotate_long: Optional[str] = None
        self.css_class = ""


class IndexItem:
    """One row of the index page."""

    def __init__(self, url: str = "", file: str = "", nums: Optional[Nums] = None) -> None:
        self.url = url
        # Deliberately unescaped: the index template escapes this once itself.
        self.file = file
        self.nums = nums if nums is not None else Nums()

    def as_dict(self) -> Dict[str, Any]:
        return {"url": self.url, "file": self.file, "nums": self.nums.as_dict()}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> IndexItem:
        return cls(url=d["url"], file=d["file"], nums=Nums(**d["nums"]))


class IncrementalChecker:
    """Tracks what was rendered last time, so unchanged files can be skipped.

    Modeled on coverage.py's IncrementalChecker: a JSON file in the output
    directory records a hash of each file's source and coverage data, plus the
    index row needed to rebuild index.html without re-rendering the page.

    """

    STATUS_FILE = "status.json"
    STATUS_FORMAT = 1
    NOTE = (
        "This file is an internal implementation detail to speed up HTML report"
        " generation. Its format can change at any time."
    )

    def __init__(self, directory: str) -> None:
        self.directory = directory
        self._reset()

    def _reset(self) -> None:
        """Initialize to empty.  Causes all files to be reported."""
        self.globals = ""
        self.files: Dict[str, Dict[str, Any]] = {}

    def read(self) -> None:
        """Read the information we stored last time."""
        try:
            status_file = os.path.join(self.directory, self.STATUS_FILE)
            with open(status_file, encoding="utf-8") as fstatus:
                status = json.load(fstatus)
            usable = (
                status["format"] == self.STATUS_FORMAT
                and status["version"] == __version__
            )
        except (OSError, ValueError, KeyError, TypeError):
            # Status file is missing or malformed; start over rather than fail.
            usable = False

        if usable:
            try:
                self.files = {
                    fname: {
                        "hash": fdict["hash"],
                        "index": IndexItem.from_dict(fdict["index"]),
                    }
                    for fname, fdict in status["files"].items()
                }
                self.globals = status["globals"]
            except (AttributeError, KeyError, TypeError):
                self._reset()
        else:
            self._reset()

    def write(self) -> None:
        """Write the current status.

        Written via a temporary file so a crash mid-write can't leave a
        half-written status.json behind.  A damaged one would be tolerated by
        read() anyway, but this avoids discarding a good cache.

        """
        status_file = os.path.join(self.directory, self.STATUS_FILE)
        status_data = {
            "note": self.NOTE,
            "format": self.STATUS_FORMAT,
            "version": __version__,
            "globals": self.globals,
            "files": {
                fname: {"hash": finfo["hash"], "index": finfo["index"].as_dict()}
                for fname, finfo in self.files.items()
            },
        }
        tmp_file = status_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as fout:
            json.dump(status_data, fout, separators=(",", ":"))
        os.replace(tmp_file, status_file)

    def check_global_data(self, *data: str) -> None:
        """Discard the cache if anything affecting every page has changed."""
        h = hashlib.sha3_256()
        for d in data:
            h.update(d.encode("utf-8"))
            h.update(b"\0")
        these_globals = h.hexdigest()
        if self.globals != these_globals:
            self._reset()
            self.globals = these_globals

    def can_skip_file(
        self, source: str, file_data: CoverageFile, rootname: str, nav: Tuple[str, str]
    ) -> bool:
        """Is the page on disk for `rootname` still correct?"""
        h = hashlib.sha3_256()
        h.update(source.encode("utf-8"))
        h.update(
            json.dumps(file_data, sort_keys=True, default=list).encode("utf-8")
        )
        # The prev/next links are baked into the page, so a file whose
        # neighbours moved has to be re-rendered even though its own source and
        # coverage didn't change.  coverage.py leaves these out of its hash and
        # keeps stale navigation when the set of reported files changes.
        h.update("\0".join(nav).encode("utf-8"))
        this_hash = h.hexdigest()

        file_info = self.files.setdefault(rootname, {"hash": "", "index": IndexItem()})

        # A matching hash isn't enough: the page itself has to still be there.
        # coverage.py skips on the hash alone, so a page deleted by hand stays
        # deleted across runs.
        page_exists = os.path.exists(os.path.join(self.directory, rootname + ".html"))

        if this_hash == file_info["hash"] and page_exists:
            return True

        file_info["hash"] = this_hash
        return False

    def index_info(self, rootname: str) -> IndexItem:
        """Get the index row recorded for `rootname`."""
        return self.files.get(rootname, {}).get("index", IndexItem())

    def set_index_info(self, rootname: str, info: IndexItem) -> None:
        """Record the index row for `rootname`."""
        self.files.setdefault(rootname, {"hash": "", "index": IndexItem()})["index"] = info


class FileToReport:
    """A file we're going to report on."""

    def __init__(self, filename: str, relative_filename: str, file_data: CoverageFile) -> None:
        self.filename = filename
        self.relative_filename = relative_filename
        self.file_data = file_data
        self.rootname = flat_rootname(relative_filename)
        self.html_filename = self.rootname + ".html"
        self.prev_html = ""
        self.next_html = ""


# -- rendering --
#
# The pages are built by plain string formatting.  Everything interpolated is
# either a number, one of our own class names, or has been through escape()
# first -- there is no template language here, and nothing is exec'd.

TITLE = "Coverage report"


def _skeleton(title: str, body_class: str, body: str) -> str:
    """Wrap `body` in the page skeleton both kinds of page share.

    `title` is interpolated as-is, so it has to be escaped already.

    """
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="style.css">
<script src="slipcover.js" defer></script>
</head>
<body class="{body_class}">
{body}
</body>
</html>
"""


def _credit(time_stamp: str) -> str:
    """The "slipcover vX, created at ..." line both pages carry."""
    return (
        f'<a class="nav" href="{escape(__url__)}">slipcover v{escape(__version__)}</a>,'
        f" created at {escape(time_stamp)}"
    )


def _index_columns(has_arcs: bool) -> List[Tuple[str, str, str]]:
    """The index table's columns, as (css class, sort kind, heading)."""
    columns = [
        ("name", "text", "File"),
        ("num", "number", "statements"),
        ("num", "number", "missing"),
    ]
    if has_arcs:
        columns += [
            ("num", "number", "branches"),
            ("num", "number", "partial"),
        ]
    columns.append(("pc", "number", "coverage"))
    return columns


def _index_cells(nums: Nums, has_arcs: bool) -> str:
    """The numeric cells of one index row (everything but the file name)."""
    cells = [f"<td>{nums.n_statements}</td>", f"<td>{nums.n_missing}</td>"]
    if has_arcs:
        cells += [f"<td>{nums.n_branches}</td>", f"<td>{nums.n_partial_branches}</td>"]
    cells.append(f'<td class="pc">{nums.pc_covered_str}%</td>')
    return "".join(cells)


def _render_index(
    rows: List[IndexItem],
    totals: Nums,
    has_arcs: bool,
    skip_covered: bool,
    skipped_covered_msg: str,
    time_stamp: str,
) -> str:
    """Build index.html."""
    columns = _index_columns(has_arcs)

    head = "".join(
        f'<th scope="col" class="{cls}" data-sort="{kind}" aria-sort="none">'
        f'<button type="button">{heading}</button></th>'
        for cls, kind, heading in columns
    )

    # The raw counts ride along on each row so the script can subtotal a
    # filtered view by summing integers, rather than re-deriving anything from
    # the rounded percentages in the cells.
    body = "\n".join(
        f'<tr data-st="{row.nums.n_statements}" data-ex="{row.nums.n_executed}"'
        f' data-br="{row.nums.n_branches}" data-exbr="{row.nums.n_executed_branches}"'
        f' data-pa="{row.nums.n_partial_branches}">'
        f'<td class="name"><a href="{escape(row.url)}">'
        f"{pretty_file(escape(row.file))}</a></td>{_index_cells(row.nums, has_arcs)}</tr>"
        for row in rows
    )

    # The footer is what the report computed over every measured file, whatever
    # --skip-covered left out of the table above, and that is what shows while
    # nothing is filtered.  The script only replaces it once a filter is
    # actually active, and relabels it when it does -- coverage.py's version
    # recomputed unconditionally on load, so with --skip-covered the footer
    # silently disagreed with the heading.
    foot = (
        f'<tr class="total"><td class="name"><span class="total-label">Total</span></td>'
        f"{_index_cells(totals, has_arcs)}</tr>"
    )

    # --skip-covered already left the covered files out server-side, so the box
    # is checked and disabled: the control still says what the table shows.
    checked = " checked disabled" if skip_covered else ""

    skipped = ""
    if skipped_covered_msg:
        skipped = f'<p class="skipped">{escape(skipped_covered_msg)}</p>\n'

    return _skeleton(
        escape(TITLE),
        "indexfile",
        f"""\
<header>
<div class="bar">
<h1><span class="brand">{escape(TITLE)}</span></h1>
<span class="pc_cov">{totals.pc_covered_str}%</span>
</div>
<div class="controls">
<label for="filter">filter</label>
<input id="filter" type="search" autocomplete="off" placeholder="file name">
<label for="hide_covered"><input id="hide_covered" type="checkbox"{checked}> hide covered</label>
</div>
</header>
<main>
<table class="index">
<thead><tr>{head}</tr></thead>
<tbody class="rows">
{body}
</tbody>
<tbody class="empty" hidden><tr><td colspan="{len(columns)}">No files match.</td></tr></tbody>
<tfoot>{foot}</tfoot>
</table>
{skipped}</main>
<footer>
<p class="keys"><kbd>f</kbd> filter</p>
<p class="meta">{_credit(time_stamp)}</p>
</footer>""",
    )


def _render_line(line: LineData) -> str:
    """One source line.  Whitespace-free: the tests read these back by regex,
    and a stray newline inside the line would show up in the listing."""
    annotation = ""
    if line.annotate:
        annotation = (
            f'<span class="r"><span class="annotate short">{line.annotate}</span>'
            f'<span class="annotate long">{line.annotate_long}</span></span>'
        )
    return (
        f'<p class="{line.css_class}">'
        f'<span class="n"><a id="t{line.number}" href="#t{line.number}">{line.number}</a></span>'
        f'<span class="t">{line.html}&nbsp;</span>'
        f"{annotation}</p>"
    )


def _render_page(
    relative_filename: str,
    nums: Nums,
    lines: List[LineData],
    no_source: bool,
    prev_html: str,
    next_html: str,
    has_arcs: bool,
    time_stamp: str,
) -> str:
    """Build the page for one source file."""
    escaped_name = escape(relative_filename)

    counts = [
        f'<span class="count">{nums.n_statements} statements</span>',
        f'<span class="count run">{nums.n_executed} run</span>',
        f'<span class="count mis">{nums.n_missing} missing</span>',
    ]
    legend = [
        '<span class="swatch run">run</span>',
        '<span class="swatch mis">missing</span>',
    ]
    if has_arcs:
        counts.append(f'<span class="count par">{nums.n_partial_branches} partial</span>')
        legend.append('<span class="swatch par">partial</span>')

    if no_source:
        # The source is read at report time and may be gone -- see read_source.
        main = (
            '<main id="source"><p class="no-source">Source code is not available for'
            f" this file. It was measured at a path that cannot be read now:"
            f" {escaped_name}</p></main>"
        )
    else:
        main = '<main id="source">\n' + "\n".join(_render_line(ld) for ld in lines) + "\n</main>"

    def nav(with_ids: bool) -> str:
        """The prev/index/next links.  Only the header copy carries the ids the
        script navigates by; a second set would be duplicate ids."""
        prev_id = ' id="prevFileLink"' if with_ids else ""
        index_id = ' id="indexLink"' if with_ids else ""
        next_id = ' id="nextFileLink"' if with_ids else ""
        return (
            f'<a{prev_id} class="nav" href="{escape(prev_html)}">&#xab; prev</a>'
            f' <a{index_id} class="nav" href="index.html">&Hat; index</a>'
            f' <a{next_id} class="nav" href="{escape(next_html)}">&#xbb; next</a>'
        )

    return _skeleton(
        f"Coverage for {escaped_name}: {nums.pc_covered_str}%",
        "pyfile",
        f"""\
<header>
<div class="bar">
<h1><span class="brand">Coverage for</span> <b>{pretty_file(escaped_name)}</b></h1>
<span class="pc_cov">{nums.pc_covered_str}%</span>
</div>
<p class="counts">{"".join(counts)}</p>
<p class="meta">{nav(True)} {_credit(time_stamp)}</p>
</header>
{main}
<footer>
<div class="legend-bar">
<p class="legend">{"".join(legend)}</p>
<p class="keys"><kbd>[</kbd> prev <kbd>]</kbd> next <kbd>u</kbd> index</p>
</div>
<p class="meta">{nav(False)} {_credit(time_stamp)}</p>
</footer>""",
    )


class HtmlReporter:
    """A reporter for writing an HTML coverage report."""

    def __init__(
        self,
        coverage: Coverage,
        directory: str = "htmlcov",
        with_branches: bool = False,
        skip_covered: bool = False,
    ) -> None:
        self.coverage = coverage
        self.directory = str(directory)
        self.with_branches = with_branches
        self.skip_covered = skip_covered

        self.incr = IncrementalChecker(self.directory)
        self.skipped_covered_count = 0
        self.directory_was_empty = False

        self.time_stamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")

    # -- source reading and per-line categorization --

    def read_source(self, filename: str) -> Optional[str]:
        """Return the text of `filename`, or None if it can't be read.

        Coverage data carries no source text, so the source is read at report
        time and may legitimately be gone -- notably after merging coverage
        produced on another machine.  That degrades the page, it doesn't fail
        the report.

        """
        try:
            return Path(filename).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def tokenized_lines(self, source: str) -> List[List[Tuple[str, str]]]:
        """Tokenize `source` for highlighting, falling back to plain text.

        The file on disk can have changed since it was measured, so it may no
        longer tokenize.  An unhighlighted page beats no page at all.

        """
        try:
            return list(source_token_lines(source))
        except _TOKENIZE_ERRORS:
            return [[("txt", line)] for line in source.expandtabs(8).splitlines()]

    def branch_arcs(
        self, file_data: CoverageFile
    ) -> Tuple[Dict[int, List[int]], Dict[int, List[int]], Set[int]]:
        """Group this file's branches by source line.

        Returns every destination per line, the untaken destinations per line,
        and the lines counted as partial: a line that ran but has at least one
        branch that never did.

        """
        all_arcs: Dict[int, List[int]] = {}
        missing_arcs: Dict[int, List[int]] = {}
        partial_lines: Set[int] = set()

        if self.with_branches:
            executed = set(file_data.get("executed_lines", []))
            for src_line, dests in get_branch_info(file_data).items():
                all_arcs[src_line] = [dest for dest, _ in dests]
                untaken = [dest for dest, taken in dests if not taken]
                if untaken and src_line in executed:
                    missing_arcs[src_line] = untaken
                    partial_lines.add(src_line)

        return all_arcs, missing_arcs, partial_lines

    def line_categories(
        self, file_data: CoverageFile, n_lines: int
    ) -> Tuple[Dict[int, str], Dict[int, List[int]], Set[int], Dict[int, List[int]]]:
        """Work out how to mark each line.

        Returns the category per line, the missing branch destinations per
        line, the set of lines counted as partial branches, and every branch
        destination per line (needed to tell a partial line from one that
        never jumped anywhere).

        """
        executed = set(file_data.get("executed_lines", []))
        missing = set(file_data.get("missing_lines", []))

        all_arcs, missing_arcs, partial_lines = self.branch_arcs(file_data)

        categories: Dict[int, str] = {}
        for lineno in range(1, n_lines + 1):
            if lineno in missing:
                categories[lineno] = "mis"
            elif lineno in missing_arcs:
                categories[lineno] = "par"
            elif lineno in executed:
                categories[lineno] = "run"
            else:
                categories[lineno] = ""

        return categories, missing_arcs, partial_lines, all_arcs

    def nums_for(self, file_data: CoverageFile, partial_lines: Set[int]) -> Nums:
        """Build the counts for one file from slipcover's own summary."""
        summary = file_data.get("summary", {})
        n_executed = summary.get("covered_lines", len(file_data.get("executed_lines", [])))
        n_missing = summary.get("missing_lines", len(file_data.get("missing_lines", [])))

        n_executed_branches = 0
        n_branches = 0
        if self.with_branches:
            n_executed_branches = summary.get(
                "covered_branches", len(file_data.get("executed_branches", []))
            )
            n_missing_branches = summary.get(
                "missing_branches", len(file_data.get("missing_branches", []))
            )
            n_branches = n_executed_branches + n_missing_branches

        return Nums(
            n_statements=n_executed + n_missing,
            n_executed=n_executed,
            n_branches=n_branches,
            n_executed_branches=n_executed_branches,
            n_partial_branches=len(partial_lines),
        )

    # -- writing --

    def report(self) -> None:
        """Generate the HTML report into the output directory."""
        self.incr.read()
        self.incr.check_global_data(
            f"branch={self.with_branches}",
            f"markup={MARKUP_VERSION}",
            # coverage.py leaves the assets out of this hash, so editing the
            # stylesheet silently leaves stale pages behind.  Include them.
            *(read_data(static) for static in STATIC_FILES),
        )

        simplify = _path_simplifier()
        files_to_report = []
        totals = Nums()
        for filename, file_data in sorted(self.coverage.get("files", {}).items()):
            ftr = FileToReport(filename, simplify(filename), file_data)
            # Totals cover every measured file, including any that --skip-covered
            # keeps off the index -- otherwise skipping fully covered files
            # would drag the reported total down.
            _, _, partial_lines = self.branch_arcs(file_data)
            totals = totals + self.nums_for(file_data, partial_lines)
            if self.should_report(file_data):
                files_to_report.append(ftr)
            else:
                _remove_if_present(os.path.join(self.directory, ftr.html_filename))

        self.make_directory()
        self.make_local_static_report_files()

        if files_to_report:
            for ftr1, ftr2 in zip(files_to_report[:-1], files_to_report[1:]):
                ftr1.next_html = ftr2.html_filename
                ftr2.prev_html = ftr1.html_filename
            files_to_report[0].prev_html = "index.html"
            files_to_report[-1].next_html = "index.html"

        summaries = []
        for ftr in files_to_report:
            summaries.append(self.write_html_page(ftr))

        self.write_index_page(summaries, totals)
        self.incr.write()

    def should_report(self, file_data: CoverageFile) -> bool:
        """Determine if we'll report this file."""
        if not self.skip_covered:
            return True

        summary = file_data.get("summary", {})
        no_missing_lines = summary.get("missing_lines", 0) == 0
        no_missing_branches = (
            not self.with_branches or summary.get("missing_branches", 0) == 0
        )
        if no_missing_lines and no_missing_branches:
            self.skipped_covered_count += 1
            return False
        return True

    def make_directory(self) -> None:
        """Make sure the output directory exists."""
        os.makedirs(self.directory, exist_ok=True)
        if not os.listdir(self.directory):
            self.directory_was_empty = True

    def make_local_static_report_files(self) -> None:
        """Copy the static files into the output directory."""
        for static in STATIC_FILES:
            shutil.copyfile(data_filename(static), os.path.join(self.directory, static))

        # Only write .gitignore if the directory was originally empty, so we
        # never clobber one the user put there.
        if self.directory_was_empty:
            gitignore = os.path.join(self.directory, ".gitignore")
            with open(gitignore, "w", encoding="utf-8") as fgi:
                fgi.write("# Created by slipcover\n*\n")

    def write_html_page(self, ftr: FileToReport) -> IndexItem:
        """Write the page for one source file, and return its index row."""
        source = self.read_source(ftr.filename)

        if self.incr.can_skip_file(
            source or "", ftr.file_data, ftr.rootname, (ftr.prev_html, ftr.next_html)
        ):
            return self.incr.index_info(ftr.rootname)

        if source is None:
            token_lines: List[List[Tuple[str, str]]] = []
        else:
            token_lines = self.tokenized_lines(source)

        categories, missing_arcs, partial_lines, all_arcs = self.line_categories(
            ftr.file_data, len(token_lines)
        )
        nums = self.nums_for(ftr.file_data, partial_lines)

        lines = []
        for lineno, tokens in enumerate(token_lines, start=1):
            ldata = LineData(lineno, categories.get(lineno, ""), tokens)

            html_parts = []
            for tok_type, tok_text in ldata.tokens:
                if tok_type == "ws":
                    html_parts.append(escape(tok_text))
                else:
                    tok_html = escape(tok_text) or "&nbsp;"
                    html_parts.append(f'<span class="{tok_type}">{tok_html}</span>')
            ldata.html = "".join(html_parts)

            if lineno in missing_arcs:
                self._annotate(ldata, missing_arcs[lineno], all_arcs.get(lineno, []))

            # slipcover has no notion of excluded lines (there is no
            # `pragma: no cover`), so a line is run, missing, partial, or plain.
            ldata.css_class = ldata.category or "pln"
            lines.append(ldata)

        html = _render_page(
            ftr.relative_filename,
            nums,
            lines,
            no_source=source is None,
            prev_html=ftr.prev_html,
            next_html=ftr.next_html,
            has_arcs=self.with_branches,
            time_stamp=self.time_stamp,
        )
        write_html(os.path.join(self.directory, ftr.html_filename), html)

        index_info = IndexItem(url=ftr.html_filename, file=ftr.relative_filename, nums=nums)
        self.incr.set_index_info(ftr.rootname, index_info)
        return index_info

    def _annotate(
        self, ldata: LineData, missing_dests: List[int], all_dests: List[int]
    ) -> None:
        """Attach the "didn't jump to" annotations for a partial line."""
        if all_dests and len(missing_dests) == len(all_dests):
            shorts = ["anywhere"]
            longs = [
                f"line {ldata.number} didn't jump anywhere: "
                "it always raised an exception."
            ]
        else:
            shorts = []
            longs = []
            for dest in missing_dests:
                if dest == 0:
                    shorts.append("exit")
                    longs.append(
                        f"line {ldata.number} didn't finish the block it is in, "
                        "because it never exited."
                    )
                else:
                    shorts.append(str(dest))
                    longs.append(f"line {ldata.number} didn't jump to line {dest}.")

        # 202F is NARROW NO-BREAK SPACE, 219B is RIGHTWARDS ARROW WITH STROKE.
        ldata.annotate = ",&nbsp;&nbsp; ".join(
            f"{ldata.number}&#x202F;&#x219B;&#x202F;{d}" for d in shorts
        )
        # slipcover can record more than two destinations for a line, so every
        # description is kept -- coverage.py asserts there is exactly one.
        ldata.annotate_long = " ".join(escape(text) for text in longs)

    def write_index_page(self, summaries: List[IndexItem], totals: Nums) -> None:
        """Write index.html."""
        skipped_covered_msg = ""
        if self.skipped_covered_count:
            n = self.skipped_covered_count
            things = "1 file" if n == 1 else f"{n} files"
            skipped_covered_msg = f"{things} skipped due to complete coverage."

        html = _render_index(
            summaries,
            totals,
            has_arcs=self.with_branches,
            skip_covered=self.skip_covered,
            skipped_covered_msg=skipped_covered_msg,
            time_stamp=self.time_stamp,
        )
        write_html(os.path.join(self.directory, "index.html"), html)


def _path_simplifier():
    """Return slipcover's cwd-relative path simplifier."""
    from .slipcover import PathSimplifier

    return PathSimplifier().simplify


def _remove_if_present(path: str) -> None:
    """Delete `path` if it exists, ignoring errors."""
    try:
        os.remove(path)
    except OSError:
        pass
