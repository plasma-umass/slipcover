# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0
# For details: https://github.com/coveragepy/coveragepy/blob/main/NOTICE.txt

"""Source tokenizing for slipcover's HTML report.

Adapted from coverage.py's phystokens.py
(https://github.com/coveragepy/coveragepy, Apache License 2.0).  The NOTICE
file at the root of this repository has details.
"""

from __future__ import annotations

import ast
import io
import keyword
import re
import sys
import token
import tokenize
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Iterator, List, Optional, Set, Tuple

    TokenInfos = Iterable[tokenize.TokenInfo]

# f-strings are tokenized into FSTRING_START/MIDDLE/END parts starting in 3.12.
_FSTRING_SYNTAX = sys.version_info >= (3, 12)

# match statements, and with them ast.Match, are new in Python 3.10; slipcover
# still supports 3.9, where the name doesn't exist at all.
_MATCH_SYNTAX = sys.version_info >= (3, 10)


def _phys_tokens(toks: TokenInfos) -> Iterator[tokenize.TokenInfo]:
    """Return all physical tokens, even line continuations.

    tokenize.generate_tokens() doesn't return a token for the backslash that
    continues lines.  This wrapper provides those tokens so that we can
    re-create a faithful representation of the original source.

    Returns the same values as generate_tokens()

    """
    last_line: Optional[str] = None
    last_lineno = -1
    last_ttext: str = ""
    for ttype, ttext, (slineno, scol), (elineno, ecol), ltext in toks:
        if last_lineno != elineno:
            if last_line and last_line.endswith("\\\n"):
                # We are at the beginning of a new line, and the last line
                # ended with a backslash.  We probably have to inject a
                # backslash token into the stream. Unfortunately, there's more
                # to figure out.  This code::
                #
                #   usage = """\
                #   HEY THERE
                #   """
                #
                # triggers this condition, but the token text is::
                #
                #   '"""\\\nHEY THERE\n"""'
                #
                # so we need to figure out if the backslash is already in the
                # string token or not.
                inject_backslash = True
                if last_ttext.endswith("\\"):
                    inject_backslash = False
                elif ttype == token.STRING:
                    if (
                        last_line.endswith("\\\n")
                        and last_line.rstrip(" \\\n").endswith(last_ttext)
                    ):
                        # Deal with special cases like such code::
                        #
                        #   a = ["aaa",\ # there may be zero or more blanks here.
                        #        "bbb \
                        #        ccc"]
                        #
                        inject_backslash = True
                    else:
                        # It's a multi-line string and the first line ends with
                        # a backslash, so we don't need to inject another.
                        inject_backslash = False
                elif _FSTRING_SYNTAX and ttype == token.FSTRING_MIDDLE:
                    inject_backslash = False
                if inject_backslash:
                    # Figure out what column the backslash is in.
                    ccol = len(last_line.split("\n")[-2]) - 1
                    # Yield the token, with a fake token type.
                    yield tokenize.TokenInfo(
                        99999,
                        "\\\n",
                        (slineno, ccol),
                        (slineno, ccol + 2),
                        last_line,
                    )
            last_line = ltext
        if ttype not in (tokenize.NEWLINE, tokenize.NL):
            last_ttext = ttext
        yield tokenize.TokenInfo(ttype, ttext, (slineno, scol), (elineno, ecol), ltext)
        last_lineno = elineno


def find_soft_key_lines(source: str) -> Set[int]:
    """Helper for finding lines with soft keywords, like match/case lines."""
    # Do a quick check first, to eliminate files with no possibility of soft
    # keywords.  match/case is only a soft keyword if both words are in the source.
    if "match" not in source or "case" not in source:
        if sys.version_info < (3, 12) or "type" not in source:
            return set()

    soft_key_lines: Set[int] = set()

    for node in ast.walk(ast.parse(source)):
        # Both node types have to be reached through a version guard: naming
        # ast.Match on 3.9, or ast.TypeAlias before 3.12, is an AttributeError.
        if _MATCH_SYNTAX and isinstance(node, ast.Match):
            soft_key_lines.add(node.lineno)
            for case in node.cases:
                soft_key_lines.add(case.pattern.lineno)
        elif sys.version_info >= (3, 12) and isinstance(node, ast.TypeAlias):
            soft_key_lines.add(node.lineno)

    return soft_key_lines


def source_token_lines(source: str) -> Iterator[List[Tuple[str, str]]]:
    """Generate a series of lines, one for each line in `source`.

    Each line is a list of pairs, each pair is a token::

        [('key', 'def'), ('ws', ' '), ('nam', 'hello'), ('op', '('), ... ]

    Each pair has a token class, and the token text.

    If you concatenate all the token texts, and then join them with newlines,
    you should have your original `source` back, with two differences:
    trailing white space is not preserved, and a final line with no newline
    is indistinguishable from a final line with a newline.

    """

    ws_tokens = {token.INDENT, token.DEDENT, token.NEWLINE, tokenize.NL}
    line: List[Tuple[str, str]] = []
    col = 0

    source = source.expandtabs(8).replace("\r\n", "\n")
    tokgen = generate_tokens(source)

    soft_key_lines = find_soft_key_lines(source)

    for ttype, ttext, (sline, scol), (_, ecol), _ in _phys_tokens(tokgen):
        mark_start = True
        for part in re.split("(\n)", ttext):
            if part == "\n":
                yield line
                line = []
                col = 0
                mark_end = False
            elif part == "":
                mark_end = False
            elif ttype in ws_tokens:
                mark_end = False
            else:
                if _FSTRING_SYNTAX and ttype == token.FSTRING_MIDDLE:
                    part = part.replace("{", "{{").replace("}", "}}")
                    ecol = scol + len(part)
                if mark_start and scol > col:
                    line.append(("ws", " " * (scol - col)))
                    mark_start = False
                tok_class = tokenize.tok_name.get(ttype, "xx").lower()[:3]
                if ttype == token.NAME:
                    if keyword.iskeyword(ttext):
                        # Hard keywords are always keywords.
                        tok_class = "key"
                    elif keyword.issoftkeyword(ttext):
                        # Soft keywords appear at the start of their line.
                        if len(line) == 0:
                            is_start_of_line = True
                        elif (len(line) == 1) and line[0][0] == "ws":
                            is_start_of_line = True
                        else:
                            is_start_of_line = False
                        if is_start_of_line and sline in soft_key_lines:
                            tok_class = "key"
                line.append((tok_class, part))
                mark_end = True
            scol = 0
        if mark_end:
            col = ecol

    if line:
        yield line


def generate_tokens(text: str) -> TokenInfos:
    """A helper around `tokenize.generate_tokens`."""
    readline = io.StringIO(text).readline
    return tokenize.generate_tokens(readline)
