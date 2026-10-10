"""A heading recording WHEN something happened and what its status was is
never edited, moved or merged away by any specialist.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from conftest import run_canned, run_tool

DATED = "2026-09-13 — TRIAGE RULINGS (T112 T113)"
STATUS = "sl-python — DONE (round 6, 2026-05-12)"
PLAIN = "Ordinary Section"

DOC = "\n\n".join([
    "# Handbook",
    f"## {DATED}",
    "- [ ] follow up with owner: Alex, due 2026-09-20",
    f"### {STATUS}",
    "The compactor finished its run without incident, nothing further to do.",
    f"## {PLAIN}",
    "This is a document that is, in point of fact, quite verbose and "
    "contains many words that could be shortened considerably if someone "
    "were to take the time to do it properly and thoroughly.",
]) + "\n"


def _lines():
    return DOC.rstrip("\n").split("\n")


def _heading_line(text):
    body = _lines()
    return next(i for i, ln in enumerate(body, 1) if text in ln)


def test_a_dated_status_heading_is_not_editable(kv):
    prose, headings, tables, quotes = kv.mask(DOC, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)
    assert _heading_line(DATED) not in editable
    assert _heading_line(STATUS) not in editable


def test_an_ordinary_heading_stays_editable(kv):
    """CONTROL. Without it, a rule that froze every heading would pass the
    test above for the wrong reason."""
    prose, headings, tables, quotes = kv.mask(DOC, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)
    assert _heading_line(PLAIN) in editable


def test_a_rename_of_a_dated_status_heading_is_refused(kv):
    body = _lines()
    ln = _heading_line(DATED)
    prose, headings, tables, quotes = kv.mask(DOC, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)

    out, applied, refused, _ = kv.merge(
        body, [{"specialist": "structure", "lo": 1, "hi": len(body),
                "edits": [{"line": ln, "op": "replace", "old": body[ln - 1],
                           "new": "## Renamed heading",
                           "why": "shorten"}]}],
        editable, (), headings)

    assert not applied and out[ln - 1] == body[ln - 1], applied
    assert "dated status" in refused[0][2], refused


def test_a_move_of_a_dated_status_heading_is_refused(kv):
    body = _lines()
    ln = _heading_line(DATED)
    dest = _heading_line(PLAIN)
    prose, headings, tables, quotes = kv.mask(DOC, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)

    out, applied, refused, _ = kv.merge(
        body, [{"specialist": "structure", "lo": 1, "hi": len(body),
                "edits": [{"line": ln, "op": "move", "to": dest,
                           "why": "reorder"}]}],
        editable, (), headings)

    assert not applied, applied
    assert refused and "may not be moved" in refused[0][2], refused


def test_an_ordinary_heading_can_still_be_moved(kv):
    """CONTROL. Without it, a move refusal that fires on every heading would
    pass the test above for the wrong reason."""
    body = _lines()
    ln = _heading_line(PLAIN)
    dest = _heading_line(DATED)
    prose, headings, tables, quotes = kv.mask(DOC, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)

    out, applied, refused, _ = kv.merge(
        body, [{"specialist": "structure", "lo": 1, "hi": len(body),
                "edits": [{"line": ln, "op": "move", "to": dest,
                           "why": "reorder"}]}],
        editable, (), headings)

    assert applied and not refused, (applied, refused)


def test_deleting_the_section_under_a_dated_status_heading_is_refused(kv):
    """`planning`'s `delete-section` is the other way a heading disappears —
    taking its whole body with it. The dated heading's body schedules a task
    (an unchecked box, a due date), which is what lets the section past the
    "nothing to schedule" gate at all; the dated-status freeze is what stops
    it from there.
    """
    body = _lines()
    ln = _heading_line(DATED)
    prose, headings, tables, quotes = kv.mask(DOC, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)

    out, applied, refused, _ = kv.merge(
        body, [{"specialist": "planning", "lo": 1, "hi": len(body),
                "edits": [{"line": ln, "op": "delete-section",
                           "why": "drop old triage"}]}],
        editable, (), headings)

    assert not applied, applied
    assert refused and "protected" in refused[0][2], refused


RULE_DOC = "\n\n".join([
    "# Runbook",
    "## Housekeeping",
    "- [ ] archive the old logs, owner: Alex, due 2026-09-20",
    "## Access Policy",
    "- [ ] rotate the credential, owner: Alex, due 2026-09-20",
    "Never grant an agent write access to production without a named "
    "revoker.",
    "## Notes",
    "Nothing about credentials is repeated here; this section is just "
    "filler prose to round out the document.",
]) + "\n"


def test_a_scheduled_section_stating_a_rule_is_refused_the_bare_one_is_not(
        kv):
    """passing the body-schedules gate is necessary, not sufficient.
    `Housekeeping`'s body is schedule lines and nothing else, so it is CUT.
    `Access Policy`'s body carries the same kind of schedule line but also a
    rule stated nowhere else in the document, so `claims_lost` refuses it —
    a rollout plan lost three appendices of rules this way, past the same
    "nothing to schedule" gate, and `verify` then failed the whole run RULES
    LOST. Both halves in one `merge` call: asserting only the cut is
    satisfied by a gate that never refuses, and asserting only the refusal
    by a gate that refuses everything.
    """
    body = RULE_DOC.rstrip("\n").split("\n")

    def hl(text):
        return next(i for i, ln in enumerate(body, 1) if text in ln)

    ln_house = hl("## Housekeeping")
    ln_access = hl("## Access Policy")
    prose, headings, tables, quotes = kv.mask(RULE_DOC, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)

    out, applied, refused, _ = kv.merge(
        body, [{"specialist": "planning", "lo": 1, "hi": len(body),
                "edits": [
                    {"line": ln_house, "op": "delete-section",
                     "why": "no rule here"},
                    {"line": ln_access, "op": "delete-section",
                     "why": "drop stale policy"},
                ]}],
        editable, (), headings)

    applied_lines = {a[0] for a in applied}
    refused_lines = {r[0] for r in refused}
    assert ln_house in applied_lines, applied
    assert "## Housekeeping" not in "\n".join(out), out

    assert ln_access in refused_lines, refused
    reason = next(r[2] for r in refused if r[0] == ln_access)
    assert "states a rule nothing else in the document keeps" in reason, \
        reason
    assert "Never grant an agent write access" in "\n".join(out), out


def test_a_run_that_would_rewrite_it_leaves_it_untouched(kv, monkeypatch,
                                                         tmp_path):
    """End to end, with the agent stubbed rather than `--no-agents` (which
    sends nothing and so cannot exercise the gate at all): `structure` is
    handed the document job and told to rename the dated-status heading. The
    real pipeline — the real prompt, the real merge, the real report — refuses
    it, and the finished file still carries the original heading text.
    """
    p, out = tmp_path / "d.md", tmp_path / "o.md"
    p.write_text(DOC)
    ln = _heading_line(DATED)

    def reply(who, lo, hi):
        if who != "structure":
            return []
        return [{"line": ln, "op": "replace", "old": DOC.split("\n")[ln - 1],
                 "new": "## Renamed heading", "why": "shorten"}]

    run_canned(kv, monkeypatch, p, out, reply)

    assert out.exists(), "run produced no output"
    assert f"## {DATED}" in out.read_text(), out.read_text()


def test_it_survives_a_run_with_no_agents_too(tmp_path):
    """The cheaper end-to-end check the task also names: with nothing
    dispatched at all, the heading is unchanged by construction — the
    baseline every one of the tests above is measured against.
    """
    p = tmp_path / "d.md"
    p.write_text(DOC)

    r = run_tool("run", p, "--no-agents")
    assert r.returncode in (0, 3), r.stderr + r.stdout
    kv_out = p.parent / (p.stem + ".kv.md")
    assert kv_out.exists(), r.stdout + r.stderr
    assert f"## {DATED}" in kv_out.read_text(), kv_out.read_text()
