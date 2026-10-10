"""A summary written over an opening the file already had."""

from __future__ import annotations

import json
import sys

import pytest
from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))

LEDE = ("The rewrite is done and the row-per-file queue is gone. Every job now "
        "carries the behaviour it covers, so the population tracks what is "
        "untested rather than how many files the repository holds. Nothing in "
        "the runner changed, and the job table keeps the columns it always "
        "had, so an existing dashboard reads it without a migration. Read the "
        "migration section next if you run this in CI, and the rollback "
        "section before you deploy it anywhere else.")

BODY = ("The queue keeps one row per source file and the population grows "
        "with the repository instead of with uncovered behaviour. Replace it "
        "with reviewed behaviour suites. ")

SECOND = ("## Summary\n\nOne row per file is no longer how the queue is built. "
          "Behaviour suites replace it, so the count reflects gaps in coverage "
          "and not the size of the tree. CI users should read migration; "
          "anyone deploying should read rollback first.")


@pytest.fixture
def doc(tmp_path):
    """Long enough to owe a summary, opening with an unheaded one."""
    out = ["# The queue rewrite", "", LEDE, ""]
    for i in range(20):
        out += [f"## Section {i + 1}", "", BODY * 2, ""]
    p = tmp_path / "queue.md"
    p.write_text("\n".join(out))
    return p


def _run(kv, monkeypatch, doc, out, new):
    """Run with a `summary` specialist that answers `new`, others silent."""
    who, real_prompt = {}, kv.job_prompt

    def spy(job, *a, **k):
        p = real_prompt(job, *a, **k)
        who[p] = job["specialist"]
        return p

    def agent(prompt, *_):
        if who.get(prompt) == "summary" and new is not None:
            return json.dumps({"edits": [
                {"line": 3, "op": "insert", "old": "", "new": new,
                 "why": "opening summary"}], "notes": []}), None
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(doc),
                                      "-o", str(out), "--timeout", "600"])
    try:
        return kv.main()
    except SystemExit as e:
        return e.code


def test_the_reader_is_told_the_file_now_opens_twice(kv, monkeypatch, doc,
                                                     tmp_path, capsys):
    _run(kv, monkeypatch, doc, tmp_path / "o.md", SECOND)
    printed = capsys.readouterr().out

    assert "written over an opening the file already had" in printed, \
        printed[-1500:]
    new_words = len(SECOND.split("\n\n", 1)[1].split())
    assert f"{new_words} new words sit above {len(LEDE.split())} that were " \
        f"there before" in printed, printed[-1500:]


def test_it_reaches_the_verdict_line(kv, monkeypatch, doc, tmp_path, capsys):
    """A line under a PASS is a line nobody reads."""
    code = _run(kv, monkeypatch, doc, tmp_path / "o.md", SECOND)
    printed = capsys.readouterr().out

    assert code == 3, f"expected REVIEW, got {code}"
    assert "REVIEW —" in printed, printed[-900:]
    assert "a summary over an opening the file already had" in \
        printed.split("REVIEW —")[-1]
    assert "\nPASS" not in printed


def test_it_still_fires_when_the_opening_was_also_reworded(
        kv, monkeypatch, doc, tmp_path, capsys):
    """Counted by line, one changed word marks the whole opening as the pass's
    own work, the carried side falls under the floor, and the summary written
    over it goes unreported. Counted by sentence, only the sentence that
    changed is new."""
    who, real_prompt = {}, kv.job_prompt

    def spy(job, *a, **k):
        p = real_prompt(job, *a, **k)
        who[p] = job["specialist"]
        return p

    def agent(prompt, *_):
        if who.get(prompt) == "summary":
            return json.dumps({"edits": [
                {"line": 3, "op": "insert", "old": "", "new": SECOND,
                 "why": "opening summary"},
                {"line": 3, "op": "replace", "old": LEDE,
                 "new": LEDE.replace("rollback section", "rollback notes"),
                 "why": "name it"}], "notes": []}), None
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(doc),
                                      "-o", str(tmp_path / "o.md"),
                                      "--timeout", "600"])
    try:
        kv.main()
    except SystemExit:
        pass
    printed = capsys.readouterr().out

    assert "written over an opening the file already had" in printed, \
        printed[-1500:]


def test_a_run_that_writes_no_summary_says_nothing(kv, monkeypatch, doc,
                                                   tmp_path, capsys):
    """The lede on its own is the `unheaded` verdict's business, not this."""
    _run(kv, monkeypatch, doc, tmp_path / "o.md", None)

    assert ("written over an opening the file already had"
            not in capsys.readouterr().out)


def test_giving_the_lede_a_heading_is_not_the_fault(kv, monkeypatch, doc,
                                                    tmp_path, capsys):
    """It is the right answer to it. The pass wrote a heading and no prose, so
    nothing sits above the opening and the file still opens once."""
    _run(kv, monkeypatch, doc, tmp_path / "o.md", "## Summary")

    assert ("written over an opening the file already had"
            not in capsys.readouterr().out)
