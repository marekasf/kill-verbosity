"""Who may name a section "Summary", and what may sit above one."""
from __future__ import annotations

import json
import sys

from conftest import run_canned

SHORT = """# Retry budget review

## Background

The retry budget is four attempts and the queue drains in eight seconds under
the current load of 400 requests per second on the search path today.

## Findings

It is worth noting that we should utilize the ranking service in order to
facilitate a reduction in the p99, which sits at 240 ms today.

## What to do

Move the ranking call off the request path before the next release ships.
"""

BODY = SHORT.rstrip("\n").split("\n")


def _rename(kv, monkeypatch, tmp_path, who, line, new_heading, name):
    """Let one specialist propose a heading rename, straight through `run`."""
    src = tmp_path / f"{name}.md"
    src.write_text(SHORT)
    out = tmp_path / f"{name}.kv.md"

    real_prompt = kv.job_prompt

    def spy(job, *a, **k):
        real_prompt(job, *a, **k)
        return f"@@{job['specialist']}|{job['unit']}@@"

    def agent(prompt, *_):
        spec, _unit = prompt.split("@@")[1].split("|")
        edits = ([{"line": line, "old": BODY[line - 1], "new": new_heading}]
                 if spec == who else [])
        return json.dumps({"edits": edits, "notes": []}), None

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(
        sys, "argv", ["kill-verbosity", "run", str(src), "-o", str(out)])
    kv.main()
    return out.read_text()


def test_the_summary_specialist_does_not_run_on_a_short_file(kv, monkeypatch,
                                                             tmp_path):
    """The fixture check. If `summary` ran, the gate tests prove nothing."""
    assert len(SHORT.split()) < kv.SUMMARY_NEEDED_FROM
    src = tmp_path / "f.md"
    src.write_text(SHORT)
    seen = run_canned(kv, monkeypatch, src, tmp_path / "f.kv.md",
                      lambda *_: [])
    assert "summary" not in {who for who, _unit in seen}, seen


def test_structure_may_not_rename_a_section_into_the_summary_vocabulary(
        kv, monkeypatch, tmp_path):
    """The gate. Only `summary` reads the prose, so only it may apply the label."""
    assert BODY[2] == "## Background", BODY[2]
    assert not kv.SUMMARY_HEADING.match("Background"), (
        "the fixture heading has to sit outside the vocabulary or the gate "
        "is not the thing under test")

    text = _rename(kv, monkeypatch, tmp_path, "structure", 3, "## Summary", "a")

    assert "## Summary" not in text, (
        "`structure` labelled a section it cannot read as the summary\n" + text)
    assert "## Background" in text, "the heading should be left as it was\n" + text


def test_a_rename_inside_the_summary_vocabulary_is_allowed(kv, monkeypatch,
                                                           tmp_path):
    """The deliberate gap, pinned so a later gate cannot close it by accident."""
    assert BODY[7] == "## Findings", BODY[7]
    assert kv.SUMMARY_HEADING.match("Findings"), "fixture"
    assert kv.SUMMARY_HEADING.match("Results"), "fixture"

    text = _rename(kv, monkeypatch, tmp_path, "structure", 8, "## Results", "b")

    assert "## Results" in text, (
        "a rename inside the summary vocabulary was refused. That blocks "
        "`## Findings` -> `## What to do`, which is what `structure` is "
        "for\n" + text)


def test_an_ordinary_rename_by_structure_still_works(kv, monkeypatch, tmp_path):
    """The boundary. The gate is about the summary words, not about renaming."""
    text = _rename(kv, monkeypatch, tmp_path, "structure", 3,
                   "## Where we are", "c")

    assert "## Where we are" in text, "an ordinary rename was refused\n" + text


def test_the_words_that_count_as_a_summary_heading(kv):
    """What the gates read. Named here so a change to the list is deliberate."""
    for word in ("Summary", "Executive Summary", "1. Summary", "Overview",
                 "Findings", "What to do"):
        assert kv.SUMMARY_HEADING.match(word), (
            f"{word!r} should read as a summary heading")

    for word in ("Background", "Introduction", "Triage"):
        assert not kv.SUMMARY_HEADING.match(word), (
            f"{word!r} should not read as a summary heading")


HELD = [
    "# Rollout review",
    "",
    "## Summary",
    "",
    "The retry budget is four attempts and the queue drains in eight "
    "seconds.",
    "",
    "## Background",
    "",
    "The load is 400 requests per second today.",
    "",
    "## What to do",
    "",
    "Move the ranking call off the request path.",
]
HELD_H = [(0, 1, "Rollout review"), (2, 2, "Summary"),
          (6, 2, "Background"), (10, 2, "What to do")]
HELD_SUMMARY_LINE = 3


def _move(kv, doc, heads, src, dest, summary_line):
    """One `structure` move, straight at `merge`, which is where the gate is."""
    results = [{"specialist": "structure",
                "edits": [{"line": src, "op": "move", "to": dest,
                           "why": "result first"}]}]
    out, applied, refused, _ = kv.merge(
        list(doc), results, set(range(1, len(doc) + 1)),
        headings=heads, summary_line=summary_line)
    return [l for l in out if l.lstrip().startswith("#")], applied, refused


def test_a_move_may_not_land_a_section_above_the_summary(kv):
    """The fault. `result first` lifted the actions over the summary."""
    assert HELD[HELD_SUMMARY_LINE - 1] == "## Summary", "fixture"

    heads, applied, refused = _move(
        kv, HELD, HELD_H, 11, HELD_SUMMARY_LINE, HELD_SUMMARY_LINE)

    assert heads[1] == "## Summary", (
        "a section was moved above the summary, so the document opens on "
        f"something else\n  {heads}")
    assert not any(a[2] == "move" for a in applied), applied
    assert refused, "the move should be refused and reported, not dropped"


def test_a_move_below_the_summary_still_works(kv):
    """The boundary. Reordering the body is what the specialist is for."""
    heads, applied, refused = _move(kv, HELD, HELD_H, 11, 7,
                                    HELD_SUMMARY_LINE)

    assert [a[2] for a in applied] == ["move"], (applied, refused)
    assert heads == ["# Rollout review", "## Summary", "## What to do",
                     "## Background"], heads


def test_a_summary_this_run_inserts_cannot_be_jumped(kv):
    """The other half, pinned. Nothing to fix here, and that is worth holding."""
    doc = [
        "# Rollout review",
        "",
        "## Background",
        "",
        "The load is 400 requests per second today.",
        "",
        "## Next steps",
        "",
        "Move the ranking call off the request path.",
    ]
    heads_in = [(0, 1, "Rollout review"), (2, 2, "Background"),
                (6, 2, "Next steps")]
    for _h in heads_in:
        assert not kv.SUMMARY_HEADING.match(_h[2]), _h
    results = [
        {"specialist": "structure",
         "edits": [{"line": 7, "op": "move", "to": 3, "why": "result first"}]},
        {"specialist": "summary",
         "edits": [{"line": 3, "op": "insert",
                    "new": "## Summary\n\nThe load is 400 requests per second "
                           "and the ranking call moves off the request "
                           "path.\n",
                    "why": "one page"}]},
    ]
    out, applied, _refused = kv.merge(
        list(doc), results, set(range(1, len(doc) + 1)), headings=heads_in)[:3]
    heads = [l for l in out if l.lstrip().startswith("#")]

    assert {a[2] for a in applied} == {"move", "insert"}, applied
    assert heads[1] == "## Summary", (
        "an inserted summary lost the top to a moved section\n"
        f"  {heads}")
