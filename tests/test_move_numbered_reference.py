"""A numbered
section moved to a new position broke every "item N" / "row N" reference to
it elsewhere in the document -- no gate in the move chain read the section's
own number or looked for who cites it, so the run reported success and only
a later crosscheck round caught the stale reading order.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))

DOC = "\n\n".join([
    "# Rollout Report",
    "## 1. Overview",
    "Filler text about the overview section, nothing special here at all.",
    "## 2. Baseline",
    "More filler text describing the baseline measurement in detail here.",
    "## 3. Findings",
    "See item 2 for the baseline this compares against, and note the delta.",
    "## 4. Appendix",
    "Nothing references numbers here, just closing remarks to wrap this up.",
]) + "\n"


def _lines():
    return DOC.rstrip("\n").split("\n")


def _heading_line(text):
    body = _lines()
    return next(i for i, ln in enumerate(body, 1) if text in ln)


def test_moving_a_cited_numbered_section_is_refused(kv):
    body = _lines()
    ln = _heading_line("## 2. Baseline")
    dest = _heading_line("## 4. Appendix")
    prose, headings, tables, quotes = kv.mask(DOC, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)

    out, applied, refused, _ = kv.merge(
        body, [{"specialist": "structure", "lo": 1, "hi": len(body),
                "edits": [{"line": ln, "op": "move", "to": dest,
                           "why": "reorder for readability"}]}],
        editable, (), headings)

    assert not applied, applied
    assert refused, refused
    reason = refused[0][2]
    assert "item 2" in reason, reason
    assert "referenced by number" in reason, reason
    assert out == body, out


def test_row_reference_is_also_caught(kv):
    """CONTROL on the second word the report named: "row N" refuses too, not
    only "item N" -- the refusal message always names the number, not which
    word matched it."""
    doc = DOC.replace("See item 2 for the baseline", "See row 2 for the baseline")
    body = doc.rstrip("\n").split("\n")
    ln = next(i for i, l in enumerate(body, 1) if "## 2. Baseline" in l)
    dest = next(i for i, l in enumerate(body, 1) if "## 4. Appendix" in l)
    prose, headings, tables, quotes = kv.mask(doc, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)

    out, applied, refused, _ = kv.merge(
        body, [{"specialist": "structure", "lo": 1, "hi": len(body),
                "edits": [{"line": ln, "op": "move", "to": dest,
                           "why": "reorder"}]}],
        editable, (), headings)

    assert not applied, applied
    assert refused and "item 2" in refused[0][2], refused


def test_moving_an_uncited_numbered_section_still_works(kv):
    """CONTROL. Without it, the refusal above could be firing on every
    numbered-heading move rather than only a cited one."""
    body = _lines()
    ln = _heading_line("## 4. Appendix")
    dest = _heading_line("## 1. Overview")
    prose, headings, tables, quotes = kv.mask(DOC, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)

    out, applied, refused, _ = kv.merge(
        body, [{"specialist": "structure", "lo": 1, "hi": len(body),
                "edits": [{"line": ln, "op": "move", "to": dest,
                           "why": "reorder"}]}],
        editable, (), headings)

    assert applied and not refused, (applied, refused)


def test_a_self_reference_inside_the_moving_span_does_not_refuse(kv):
    """CONTROL. A section that cites its OWN number inside its own body is
    not a stale reference -- the citation moves along with the section, so
    the gate must look only OUTSIDE the span."""
    doc = "\n\n".join([
        "# Rollout Report",
        "## 1. Overview",
        "Filler text about the overview section, nothing special at all.",
        "## 2. Baseline",
        "As covered in item 2, the baseline measurement stays as recorded.",
        "## 3. Findings",
        "Nothing here cites another section by number, just plain prose.",
        "## 4. Appendix",
        "Nothing references numbers here, just closing remarks to close.",
    ]) + "\n"
    body = doc.rstrip("\n").split("\n")
    ln = next(i for i, l in enumerate(body, 1) if "## 2. Baseline" in l)
    dest = next(i for i, l in enumerate(body, 1) if "## 4. Appendix" in l)
    prose, headings, tables, quotes = kv.mask(doc, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)

    out, applied, refused, _ = kv.merge(
        body, [{"specialist": "structure", "lo": 1, "hi": len(body),
                "edits": [{"line": ln, "op": "move", "to": dest,
                           "why": "reorder"}]}],
        editable, (), headings)

    assert applied and not refused, (applied, refused)
