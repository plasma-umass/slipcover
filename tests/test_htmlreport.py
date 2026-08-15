import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from slipcover import phystokens
from slipcover.htmlreport import HtmlReporter, LineData, flat_rootname


PARTIAL_SOURCE = """\
def f(x):
    if x > 0:
        return 1
    return 2

f(1)
"""


def run_slipcover(*args, check=True):
    """Runs slipcover as a subprocess, inheriting PYTHONPATH from this process."""
    return subprocess.run([sys.executable, '-m', 'slipcover', *args],
                          check=check, capture_output=True, text=True)


def read(path):
    return Path(path).read_text(encoding='utf-8')


def nav_link(html, which):
    """Returns the href of the page's "prev"/"next" file link."""
    m = re.search(rf'id="{which}FileLink" class="nav" href="([^"]*)"', html)
    assert m, f"{which} file link not found in page"
    return m.group(1)


def line_class(html, lineno):
    """Returns the CSS class of the <p> wrapping source line `lineno`."""
    m = re.search(rf'<p class="([^"]*)"><span class="n"><a id="t{lineno}"', html)
    assert m, f"line {lineno} not found in page"
    return m.group(1)


def test_html_format_writes_report_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")

    run_slipcover('--format=html', 't.py')

    out = tmp_path / "htmlcov"
    assert (out / "index.html").exists()
    assert (out / "t_py.html").exists()
    assert (out / "style.css").exists()
    assert (out / "slipcover.js").exists()
    assert (out / "status.json").exists()
    # The directory starts out ignorable, like coverage.py's.
    assert (out / ".gitignore").exists()


def test_html_pages_reference_the_assets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")

    run_slipcover('--format=html', 't.py')

    out = tmp_path / "htmlcov"
    for page in ("index.html", "t_py.html"):
        html = read(out / page)
        assert '<link rel="stylesheet" href="style.css">' in html, page
        assert '<script src="slipcover.js" defer></script>' in html, page


def test_html_alias_matches_format_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")

    run_slipcover('--html', 't.py')

    assert (tmp_path / "htmlcov" / "index.html").exists()
    assert (tmp_path / "htmlcov" / "t_py.html").exists()


def test_html_out_names_a_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")

    run_slipcover('--format=html', '--out', 'myreport', 't.py')

    assert (tmp_path / "myreport" / "index.html").exists()
    assert not (tmp_path / "htmlcov").exists()
    # --out is a directory here, never a file.
    assert (tmp_path / "myreport").is_dir()


def test_html_out_naming_an_existing_file_is_an_argument_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")
    # A project configured with `out = coverage.json` that ran --json once and
    # then asks for HTML: the directory can't be made where the file already is.
    (tmp_path / "coverage.json").write_text("{}\n")

    p = run_slipcover('--format=html', '--out', 'coverage.json', 't.py', check=False)

    # This has to be caught up front: the report is written from an atexit
    # callback, where the failure would only print an ignored traceback and
    # leave the exit status at 0.
    assert p.returncode != 0
    assert "--out must name a directory" in p.stderr
    assert "Traceback" not in p.stderr
    assert read(tmp_path / "coverage.json") == "{}\n"


def test_html_merge_out_naming_an_existing_file_is_an_argument_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")
    run_slipcover('--json', '--out', 'cov.json', 't.py')

    p = run_slipcover('--merge', 'cov.json', '--format=html', '--out', 'cov.json',
                      check=False)

    assert p.returncode != 0
    assert "--out must name a directory" in p.stderr


def test_html_marks_run_and_missing_lines(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # f() is never called, so its body is a missing line.
    (tmp_path / "t.py").write_text("def f():\n    return 1\n\ny = 2\n")

    run_slipcover('--format=html', 't.py')

    page = read(tmp_path / "htmlcov" / "t_py.html")
    assert line_class(page, 1) == "run"
    assert "mis" in line_class(page, 2)
    assert line_class(page, 3) == "pln"
    assert line_class(page, 4) == "run"


def test_html_marks_partial_branch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text(PARTIAL_SOURCE)

    run_slipcover('--branch', '--format=html', 't.py')

    page = read(tmp_path / "htmlcov" / "t_py.html")
    # Line 2 ran, but never jumped to line 4.
    assert "par" in line_class(page, 2)
    assert "&#x219B;" in page, "missing the 'didn't jump to' arrow annotation"
    assert "didn&#x27;t jump to line 4" in page or "didn't jump to line 4" in page


def test_html_no_partial_marking_without_branch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text(PARTIAL_SOURCE)

    run_slipcover('--format=html', 't.py')

    page = read(tmp_path / "htmlcov" / "t_py.html")
    assert line_class(page, 2) == "run"
    assert "par" not in page


def test_html_escapes_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text('s = "a<b&c"\nt = "</script>"\n')

    run_slipcover('--format=html', 't.py')

    page = read(tmp_path / "htmlcov" / "t_py.html")
    # The literal characters must never reach the page unescaped, or the
    # source listing would break out of its element.
    assert '"a<b&c"' not in page
    assert '</script>"' not in page
    assert 'a&lt;b&amp;c' in page
    assert '&lt;/script&gt;' in page


def test_html_renders_when_source_is_gone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\ny = 2\n")

    run_slipcover('--json', '--out', 'cov.json', 't.py')
    (tmp_path / "t.py").unlink()

    # Coverage carries no source text, so a merged report often can't read the
    # files it describes.  That degrades the page; it must not fail the report.
    run_slipcover('--merge', 'cov.json', '--format=html')

    out = tmp_path / "htmlcov"
    assert "Source code is not available" in read(out / "t_py.html")
    # The index still carries the file and its counts.
    index = read(out / "index.html")
    assert "t.py" in index
    assert '<td>2</td>' in index


def test_html_merge(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("y = 2\n")

    run_slipcover('--json', '--out', 'a.json', 'a.py')
    run_slipcover('--json', '--out', 'b.json', 'b.py')

    run_slipcover('--merge', 'a.json', 'b.json', '--format=html', '--out', 'merged')

    index = read(tmp_path / "merged" / "index.html")
    assert "a.py" in index
    assert "b.py" in index
    assert (tmp_path / "merged" / "a_py.html").exists()
    assert (tmp_path / "merged" / "b_py.html").exists()


def test_html_incremental_skips_unchanged_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")

    run_slipcover('--format=html', 't.py')
    page = tmp_path / "htmlcov" / "t_py.html"

    # Backdate the page: if the second run rewrites it, the stamp moves.
    os.utime(page, (0, 0))
    run_slipcover('--format=html', 't.py')

    assert page.stat().st_mtime == 0, "unchanged file should have been skipped"
    # The index is still rebuilt from status.json.
    assert "t.py" in read(tmp_path / "htmlcov" / "index.html")


def test_html_incremental_regenerates_changed_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")

    run_slipcover('--format=html', 't.py')
    page = tmp_path / "htmlcov" / "t_py.html"

    os.utime(page, (0, 0))
    (tmp_path / "t.py").write_text("x = 1\ny = 2\n")
    run_slipcover('--format=html', 't.py')

    assert page.stat().st_mtime != 0, "changed file should have been re-rendered"
    assert 'id="t2"' in read(page)


def test_html_incremental_regenerates_deleted_page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")

    run_slipcover('--format=html', 't.py')
    page = tmp_path / "htmlcov" / "t_py.html"
    page.unlink()

    run_slipcover('--format=html', 't.py')

    assert page.exists(), "a deleted page must not stay deleted"


def test_html_incremental_refreshes_stale_prev_next_links(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.py").write_text("x = 1\n")
        run_slipcover('--json', '--out', f"{name}.json", f"{name}.py")

    run_slipcover('--merge', 'b.json', 'c.json', '--format=html', '--out', 'rep')
    b_page = tmp_path / "rep" / "b_py.html"
    c_page = tmp_path / "rep" / "c_py.html"
    assert nav_link(read(b_page), "prev") == "index.html"

    # Backdate both pages: whichever the second run rewrites loses the stamp.
    os.utime(b_page, (0, 0))
    os.utime(c_page, (0, 0))
    run_slipcover('--merge', 'a.json', 'b.json', 'c.json', '--format=html', '--out', 'rep')

    # b.py's own source and coverage are unchanged, but a.py now comes before
    # it, so a skipped page would keep a prev link -- and a `[` shortcut --
    # that jumps straight past the newly added file.
    assert nav_link(read(b_page), "prev") == "a_py.html"
    # c.py's neighbours didn't move, so it must still be skipped: navigation
    # can't cost us the incremental report.
    assert c_page.stat().st_mtime == 0, "unchanged neighbours should still skip"


def test_html_survives_corrupt_status_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")

    run_slipcover('--format=html', 't.py')
    (tmp_path / "htmlcov" / "status.json").write_text("{not json")

    run_slipcover('--format=html', 't.py')

    assert (tmp_path / "htmlcov" / "t_py.html").exists()
    # The status file is rewritten as valid JSON.
    json.loads(read(tmp_path / "htmlcov" / "status.json"))


def test_html_format_from_pyproject(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.slipcover]\nformat = "html"\n'
    )

    run_slipcover('t.py')

    assert (tmp_path / "htmlcov" / "index.html").exists()


def test_html_out_directory_from_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.slipcover]\nformat = "html"\nout = "report_dir"\n'
    )

    run_slipcover('t.py')

    assert (tmp_path / "report_dir" / "index.html").exists()


def test_html_skip_covered_omits_page_but_keeps_totals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # full.py is fully covered; partial.py is not.
    (tmp_path / "full.py").write_text("import partial\nx = 1\n")
    (tmp_path / "partial.py").write_text("def f():\n    return 1\n\ny = 2\n")

    run_slipcover('--format=html', '--skip-covered', 'full.py')

    out = tmp_path / "htmlcov"
    assert not (out / "full_py.html").exists(), "covered file should be skipped"
    assert (out / "partial_py.html").exists()

    index = read(out / "index.html")
    assert "skipped due to complete coverage" in index
    # partial.py contributes 3 statements to the only listed row, but the
    # totals also carry full.py's 2 -- skipping a covered file must not drop
    # it from the overall numbers.
    counts = re.findall(r'<td>(\d+)</td>', index)
    assert counts == ['3', '1', '5', '1']
    assert '<span class="pc_cov">80%</span>' in index
    # The totals are rendered into the footer, not left to the script to work
    # out: a footer summing only the visible rows would say 3 while the heading
    # above it kept saying 80%.
    foot = re.search(r'<tfoot>(.*?)</tfoot>', index, re.S)
    assert foot, "index has no totals row"
    assert re.findall(r'<td>(\d+)</td>', foot.group(1)) == ['5', '1']
    assert '<td class="pc">80%</td>' in foot.group(1)


def test_html_skipped_page_returns_when_no_longer_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")

    run_slipcover('--format=html', '--skip-covered', 't.py')
    assert not (tmp_path / "htmlcov" / "t_py.html").exists()

    run_slipcover('--format=html', 't.py')
    assert (tmp_path / "htmlcov" / "t_py.html").exists()


FORK_SOURCE = """\
import os

pid = os.fork()
if pid:
    os.waitpid(pid, 0)
else:
    import child_only
"""


@pytest.mark.skipif(sys.platform == 'win32', reason='fork() is Unix-specific')
def test_html_forked_child_writes_no_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text(FORK_SOURCE)
    # Imported only in the child, so a page for it can only come from a report
    # the child wrote.  The parent waits, so the child's atexit runs first and
    # any report of its own is on disk before the parent writes.
    (tmp_path / "child_only.py").write_text("x = 1\n")

    run_slipcover('--format=html', 't.py')

    out = tmp_path / "htmlcov"
    # The parent's report is whole...
    assert (out / "index.html").exists()
    assert (out / "t_py.html").exists()
    assert (out / "status.json").exists()
    assert "t.py" in read(out / "index.html")
    # ...and nothing of the child's interleaved with it.  The child reaches
    # normal interpreter shutdown, so without the guard in sci_atexit it would
    # write a second, partial report over the same directory.
    assert not (out / "child_only_py.html").exists()
    assert "child_only.py" not in read(out / "index.html")


def test_html_rejects_unknown_format(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.py").write_text("x = 1\n")

    p = run_slipcover('--format=htm', 't.py', check=False)

    assert p.returncode != 0
    assert 'html' in p.stderr


def test_tokenizes_where_ast_has_no_Match(monkeypatch):
    # Python 3.9 has no ast.Match, so naming it there is an AttributeError --
    # which isn't a tokenizing error, so it would escape all the way out of the
    # report.  Any file mentioning both "match" and "case", a comment included,
    # gets past find_soft_key_lines' quick check and reaches that name.
    monkeypatch.setattr(phystokens, "_MATCH_SYNTAX", False)
    monkeypatch.delattr(ast, "Match", raising=False)

    source = "import re\n# match a lowercase name\nm = re.match('a', 'a')\n"
    lines = list(phystokens.source_token_lines(source))

    assert len(lines) == 3
    assert ("key", "import") in lines[0]
    assert ("nam", "m") in lines[2]


def annotate(missing_dests, all_dests, lineno=7):
    """Runs _annotate over one line and returns its (short, long) annotations."""
    reporter = HtmlReporter({"files": {}}, directory="unused", with_branches=True)
    ldata = LineData(lineno, "par", [])
    reporter._annotate(ldata, missing_dests, all_dests)
    return ldata.annotate, ldata.annotate_long


def test_annotate_line_that_never_jumped_anywhere():
    # Every destination missing on a line that ran: the line was reached and
    # then raised, so naming the destinations it "didn't jump to" would be
    # misleading.
    short, long = annotate([8, 9], [8, 9])

    assert short == "7&#x202F;&#x219B;&#x202F;anywhere"
    assert "always raised an exception" in long
    assert "jump to line" not in long


def test_annotate_line_that_missed_only_some_destinations():
    short, long = annotate([9], [8, 9])

    assert short == "7&#x202F;&#x219B;&#x202F;9"
    assert "didn&#x27;t jump to line 9." in long
    assert "always raised an exception" not in long


def test_annotate_keeps_every_missing_destination():
    # slipcover can record more than two destinations for a line, which is why
    # coverage.py's `assert len(longs) == 1` had to go: all of them must be
    # described, not just the first.
    short, long = annotate([4, 5, 6], [4, 5, 6, 8], lineno=3)

    assert short == ("3&#x202F;&#x219B;&#x202F;4,&nbsp;&nbsp; "
                     "3&#x202F;&#x219B;&#x202F;5,&nbsp;&nbsp; "
                     "3&#x202F;&#x219B;&#x202F;6")
    for dest in (4, 5, 6):
        assert f"didn&#x27;t jump to line {dest}." in long


@pytest.mark.parametrize("filename,expected", [
    ("t.py", "t_py"),
    ("pkg/t.py", None),          # hashed prefix, checked below
])
def test_flat_rootname_basics(filename, expected):
    got = flat_rootname(filename)
    if expected is not None:
        assert got == expected
    else:
        assert got.startswith("z_") and got.endswith("_t_py")


def test_flat_rootname_is_separator_independent():
    # The same file must get the same page name regardless of the separator
    # the platform handed us.
    assert flat_rootname("pkg/sub/t.py") == flat_rootname("pkg\\sub\\t.py")


def test_flat_rootname_distinguishes_directories():
    assert flat_rootname("a/t.py") != flat_rootname("b/t.py")
