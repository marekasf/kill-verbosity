"""`run`'s verify and a standalone `verify` scored the same pair of
files under different rules, and neither report said so.
"""

from __future__ import annotations

import json
import re

import pytest

from conftest import run_tool

pytestmark = pytest.mark.regression

CHECKLIST = "# Release checklist\n\n## Milestones\n\n" + "".join(
    "- [ ] **M%d.** The cleanest available answer closed on 2026-09-05 is\n"
    "  obviously the right one and it was renamed in one place while the\n"
    "  other place kept the old name, which is meant to be read with %d.\n"
    % (i, i) for i in range(1, 41))

TALLY = re.compile(r"shapes \d+ → \d+.*$", re.M)
LONG = re.compile(r"long sentences \d+ → \d+", re.M)


def _pair(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(CHECKLIST)
    r = run_tool("run", doc, "--no-agents")
    assert (tmp_path / "doc.kv.md").is_file(), r.stdout + r.stderr
    return doc, tmp_path / "doc.kv.md", r


def test_the_two_verdicts_agree(tmp_path):
    doc, out, run = _pair(tmp_path)

    standalone = run_tool("verify", doc, out)

    assert TALLY.search(run.stdout), run.stdout
    assert TALLY.search(run.stdout).group(0) \
        == TALLY.search(standalone.stdout).group(0), \
        f"run: {run.stdout[-400:]}\n\nstandalone: {standalone.stdout[-400:]}"


def test_the_long_sentence_threshold_is_the_run_s(tmp_path):
    """The half of the tally that moved furthest, asserted on its own."""
    doc, out, run = _pair(tmp_path)

    standalone = run_tool("verify", doc, out)

    assert LONG.search(standalone.stdout).group(0) == "long sentences 0 → 0", \
        standalone.stdout[-400:]
    assert LONG.search(run.stdout).group(0) \
        == LONG.search(standalone.stdout).group(0)


def test_the_premise_the_document_is_read_as_a_checklist(tmp_path):
    """If the detector stops reading this fixture as a checklist, every test
    above passes while exercising nothing: the two paths agree because both
    scored it as prose."""
    _doc, _out, run = _pair(tmp_path)

    assert "read as checklist" in run.stderr, run.stderr[-400:]


def test_the_run_record_carries_the_genre(tmp_path):
    _doc, out, _run = _pair(tmp_path)

    record = json.loads((out.parent / (out.name + ".kvrun")).read_text())

    assert record["genre"] == "checklist", record


def test_verify_says_where_the_genre_came_from(tmp_path):
    """A silent rescoring is the defect one step along: the numbers would
    agree and nothing would say which document kind produced them."""
    doc, out, _run = _pair(tmp_path)

    standalone = run_tool("verify", doc, out)

    assert "read as checklist, the genre the run scored under" \
        in standalone.stdout, standalone.stdout[:400]


def test_with_no_record_verify_detects_the_genre_itself(tmp_path):
    """The record is the authority, not the only source. A pair whose record
    was never written -- a hand-edited file, a record deleted -- is still
    scored as what it is, and `plan` has always detected this way."""
    doc, out, run = _pair(tmp_path)
    (out.parent / (out.name + ".kvrun")).unlink()

    standalone = run_tool("verify", doc, out)

    assert LONG.search(standalone.stdout).group(0) == "long sentences 0 → 0", \
        standalone.stdout[-400:]
    assert TALLY.search(run.stdout).group(0) \
        == TALLY.search(standalone.stdout).group(0)


def test_a_named_profile_still_wins(tmp_path):
    """`select_genre`'s rule, kept: someone writing the kind down beats both
    the detector and the record. Without this, a project that named a profile
    would have it overwritten by whatever the run happened to detect."""
    doc, out, _run = _pair(tmp_path)
    (tmp_path / ".killverbosity.json").write_text(
        json.dumps({"profile": "clinical"}))

    standalone = run_tool("verify", doc, out)

    assert "read as checklist, the genre the run scored under" \
        not in standalone.stdout, standalone.stdout[:400]


def test_plan_reads_the_document_as_the_same_kind_as_run(tmp_path):
    """The sibling site, found while fixing this one: `run` detected on its
    FOLDED lines and `plan` on the raw ones, so the command a reader runs
    first to decide whether to dispatch read this file as prose while the run
    read it as a checklist -- 40 of 120 raw lines is a third, 40 of 40 folded
    ones is all of it."""
    doc = tmp_path / "doc.md"
    doc.write_text(CHECKLIST)

    plan = run_tool("plan", doc)
    run = run_tool("run", doc, "--no-agents")

    assert "read as checklist" in plan.stdout, plan.stdout[:400]
    assert "read as checklist" in run.stderr, run.stderr[:400]


def test_the_mix_beside_the_verdict_is_what_the_verdict_was_taken_on(tmp_path):
    """The evidence a reader is invited to contest, counted off the same
    lines as the decision. It read `checklist 40 of 120 body lines` beside a
    verdict taken on 40 of 40."""
    doc = tmp_path / "doc.md"
    doc.write_text(CHECKLIST)

    plan = run_tool("plan", doc)

    assert "checklist 40 of 40 body lines" in plan.stdout, plan.stdout[:400]


def test_verify_puts_back_the_profile_it_loaded(kv, tmp_path):
    """Loading a profile mutates tables that live for the whole process, and
    `verify` is the one command called in-process and repeatedly -- by
    `accept`, and by the selftest, which runs some forty pairs through it. The
    first pair the detector read as a reference document switched the
    `summary` specialist off for every pair after it, and the failure surfaced
    three fixtures later as a heading that stopped being reported as renamed.
    """
    import argparse

    doc, out = tmp_path / "doc.md", tmp_path / "doc.kv.md"
    doc.write_text(CHECKLIST)
    out.write_text(CHECKLIST)

    assert kv.PROFILE_NAME == "default"
    kv.cmd_verify(argparse.Namespace(original=str(doc), edited=str(out),
                                     chat=False, content_edit=False,
                                     exempt=[]))

    assert kv.PROFILE_NAME == "default"
    assert "summary" in kv.SPECIALISTS
