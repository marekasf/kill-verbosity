"""`plan`/`run` reported a file of one-line numbered list items as
"3 paragraphs run over more than one line (25 continuation lines)".
"""

from __future__ import annotations

import sys
from pathlib import Path

from conftest import REPO, run_tool

sys.path.insert(0, str(REPO / "bin"))

from killverbosity import _legacy as kv
from killverbosity import wrapping as _wrapping

ONE_LINE_LIST_DOC = "# Title\n\n" + "\n".join(
    f"{i}. Item number {i} text that is short" for i in range(1, 26)) + "\n"

HARD_WRAPPED_DOC = "# Title\n\n" + (
    "This paragraph is deliberately written long enough that it wraps "
    "across more than one physical line in the source file, the way a "
    "human editor hard-wraps prose at a fixed column width by hand.\n"
    "It continues right here on the very next line with no blank line "
    "in between, which is the shape the warning exists to catch.\n"
) + "\n"


def _prose(doc):
    prose, _h, _t, _q = kv.mask(doc)
    return prose


def test_multiline_paragraphs_does_not_count_one_line_list_items():
    n = _wrapping.multiline_paragraphs(_prose(ONE_LINE_LIST_DOC))
    assert n == 0, f"one-line list items read as {n} wrapped paragraph(s)"


def test_multiline_paragraphs_still_fires_on_hard_wrapped_prose():
    n = _wrapping.multiline_paragraphs(_prose(HARD_WRAPPED_DOC))
    assert n == 1, f"hard-wrapped prose stopped firing: {n}"


def test_continuation_lengths_does_not_count_one_line_list_items():
    lengths = _wrapping._continuation_lengths(_prose(ONE_LINE_LIST_DOC))
    assert lengths == [], (
        f"one-line list items produced continuation-line evidence: {lengths}")


def test_no_margin_notice_is_silent_on_one_line_list_items():
    notice = kv.no_margin_notice(_prose(ONE_LINE_LIST_DOC))
    assert "over more than one line" not in notice, notice


def test_no_margin_notice_still_warns_on_hard_wrapped_prose():
    notice = kv.no_margin_notice(_prose(HARD_WRAPPED_DOC))
    assert "over more than one line" in notice, notice


def test_plan_end_to_end_on_one_line_list_items(tmp_path):
    doc = tmp_path / "list.md"
    doc.write_text(ONE_LINE_LIST_DOC)
    r = run_tool("plan", doc)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "over more than one line" not in r.stderr, r.stderr
