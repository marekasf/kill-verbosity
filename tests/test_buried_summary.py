"""Unburying a summary: the one job `summary` stands down for."""

from __future__ import annotations

import json
import sys

import pytest
from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))

WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet "
         "kilo lima mike november oscar papa quebec romeo sierra tango").split()


def _para(i: int) -> str:
    w = WORDS[i % len(WORDS)]
    return (f"Section {i} covers the {w} path and the {w} counter is read once "
            f"per batch. The {w} reader cannot see which batch it came from, "
            f"so the {w} gate is applied to the request path only and never to "
            f"the {w} replay queue that follows it later on.")


PRE1 = ("This document was put together from a meeting transcript and a long "
        "chat thread, and it went through several rounds of review before it "
        "reached the shape it has now.")
PRE2 = ("The people who worked on it are listed at the end, and the raw notes "
        "are kept in the working log next to this file for anyone who wants "
        "to trace a claim back to where it came from.")
SUM = ("The queue is rebuilt around behaviour suites. The count now tracks "
       "uncovered behaviour rather than repository size, the runner is "
       "unchanged, and the job table keeps every column it had, so an "
       "existing dashboard reads it without a migration. Read migration if "
       "you run this in CI and rollback before you deploy it anywhere.")

SECTION_1 = 11


@pytest.fixture
def doc(tmp_path):
    out = ["# The queue rewrite", "", PRE1, "", PRE2, "",
           "## Summary", "", SUM, ""]
    for i in range(20):
        out += [f"## Section {i + 1}", "", _para(i), ""]
    p = tmp_path / "queue.md"
    p.write_text("\n".join(out))
    return p


def _run(kv, monkeypatch, doc, out, edits):
    """`structure`'s document job answers with `edits`, everyone else silent."""
    seen, real_prompt = {}, kv.job_prompt

    def spy(job, *a, **k):
        p = real_prompt(job, *a, **k)
        seen[p] = (job["specialist"], job["unit"])
        return p

    def agent(prompt, *_):
        if seen.get(prompt) == ("structure", "document"):
            return json.dumps({"edits": edits, "notes": []}), None
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(doc),
                                      "-o", str(out), "--timeout", "600"])
    try:
        kv.main()
    except SystemExit:
        pass


def _unbury(into):
    return [{"line": 3, "op": "move-block", "thru": 3, "into": into,
             "why": "unbury"},
            {"line": 5, "op": "move-block", "thru": 5, "into": into,
             "why": "unbury"}]


def test_structure_can_unbury_the_summary(kv, monkeypatch, doc, tmp_path,
                                          capsys):
    out = tmp_path / "o.md"
    _run(kv, monkeypatch, doc, out, _unbury(SECTION_1))
    printed = capsys.readouterr().out
    head = out.read_text().split("\n")

    assert "2 of 2 edits applied" in printed, printed[-1500:]
    assert head[2] == "## Summary", head[:6]
    assert "BURIED" not in printed.split("── verify ──")[-1]


def test_summary_stands_down_and_says_who_has_it(kv, monkeypatch, doc,
                                                 tmp_path, capsys):
    """Standing `summary` down is only safe while somebody else is on it."""
    _run(kv, monkeypatch, doc, tmp_path / "o.md", _unbury(SECTION_1))
    printed = capsys.readouterr().out

    assert "summary     skipped — BURIED" in printed, printed[:1500]
    assert "`structure` has it" in printed


def test_naming_the_section_says_the_field_takes_a_line(kv, monkeypatch, doc,
                                                        tmp_path, capsys):
    """Two of the three refusals on this field say "name the section". Sending
    a name got "`into` is not a line in the file", which says what the field
    is not and never what it is."""
    _run(kv, monkeypatch, doc, tmp_path / "o.md", _unbury("Section 1"))
    printed = capsys.readouterr().out

    assert "`into` takes a line number, not a name" \
        in printed, printed[-1500:]


def test_a_line_that_is_not_a_heading_names_the_line(kv, monkeypatch, doc,
                                                     tmp_path, capsys):
    """L12 is the blank under `## Section 1`. The old message repeated the
    field name back; the number is the part the reader has to change."""
    _run(kv, monkeypatch, doc, tmp_path / "o.md", _unbury(SECTION_1 + 1))
    printed = capsys.readouterr().out

    assert "line 12 is not a heading — give the line of the heading it goes " \
        "into" in printed, printed[-1500:]
