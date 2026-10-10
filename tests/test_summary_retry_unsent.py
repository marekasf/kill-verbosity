"""A summary answer the run refused is not merged when its retry cannot go out."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))

from killverbosity import budget


def _long_document() -> str:
    """Past `summary_needed_from`, so the run schedules a `summary` job."""
    body = ("It is worth noting that the gate is aimed at the request path. "
            "I think the retry should be dropped. This is not the whole "
            "story. We should move the check going forward. One caveat "
            "before we trust a pass: the counter is read once per batch and "
            "the reader has no way to see which batch it came from. ")
    out = ["# The queue rewrite", ""]
    for i in range(12):
        out += [f"## Section {i + 1}", "", body * 2, ""]
    return "\n".join(out)


@pytest.fixture
def doc(tmp_path):
    p = tmp_path / "long.md"
    p.write_text(_long_document())
    return p


def _run(kv, monkeypatch, doc, out, answer):
    """Answer every job, `summary` with `answer`, then spend the budget."""
    now = [0.0]
    real = budget.Budget
    monkeypatch.setattr(kv.budget, "Budget",
                        lambda total: real(total, clock=lambda: now[0]))
    who, real_prompt = {}, kv.job_prompt

    def spy(job, *a, **k):
        p = real_prompt(job, *a, **k)
        who[p] = job["specialist"]
        return p

    def agent(prompt, *_):
        if who.get(prompt) == "summary":
            now[0] = 10_000.0
            return json.dumps(answer), None
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
    return who


def test_the_run_schedules_a_summary_job_at_all(kv, monkeypatch, doc,
                                                tmp_path, capsys):
    """Guards the fixture. Without a summary job the tests below prove
    nothing, and they would still pass."""
    who = _run(kv, monkeypatch, doc, tmp_path / "o.md",
               {"edits": [], "notes": []})
    capsys.readouterr()
    assert "summary" in who.values(), sorted(set(who.values()))


def test_an_over_cap_summary_whose_retry_cannot_go_out_is_not_merged(
        kv, monkeypatch, doc, tmp_path, capsys):
    over = " ".join(["word"] * 900)
    _run(kv, monkeypatch, doc, tmp_path / "o.md",
         {"edits": [{"line": 2, "op": "insert", "old": "", "new": over,
                     "why": "opening summary"}], "notes": []})
    printed = capsys.readouterr().out

    assert "never edited" in printed, printed[-1200:]
    assert "summary answer refused" in printed
    assert "run the same command again" in printed


def _run_retry_failing(kv, monkeypatch, doc, out, answer, second):
    """Answer the summary job with `answer`, then fail its retry with `second`."""
    who, real_prompt, seen = {}, kv.job_prompt, []

    def spy(job, *a, **k):
        p = real_prompt(job, *a, **k)
        who[p] = job["specialist"]
        return p

    def agent(prompt, *_):
        if who.get(prompt) == "summary":
            seen.append(prompt)
            if len(seen) > 1:
                return "", second
            return json.dumps(answer), None
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


def test_a_retry_that_answers_badly_also_drops_the_refused_summary(
        kv, monkeypatch, doc, tmp_path, capsys):
    """The retry was sent and came back broken. Nothing about that makes the
    first answer usable, and it carries no error to file it under."""
    over = " ".join(["word"] * 900)
    out = tmp_path / "o.md"
    _run_retry_failing(kv, monkeypatch, doc, out, {"edits": [
        {"line": 2, "op": "insert", "old": "", "new": over,
         "why": "opening summary"}], "notes": []},
        "the backend closed the connection")
    printed = capsys.readouterr().out

    assert "the backend closed the connection" in printed, printed[-1200:]
    assert not out.exists() or over not in out.read_text()


def test_a_note_survives_the_refused_summary(kv, monkeypatch, doc, tmp_path,
                                             capsys):
    """The gate judged the summary. A note is the reader's decision and was
    never what it refused."""
    over = " ".join(["word"] * 900)
    _run(kv, monkeypatch, doc, tmp_path / "o.md", {"edits": [
        {"line": 2, "op": "insert", "old": "", "new": over,
         "why": "opening summary"}],
        "notes": ["section 3 and section 9 give different counts"]})

    assert ("section 3 and section 9 give different counts"
            in capsys.readouterr().out)


def test_the_refused_summary_does_not_reach_the_file(kv, monkeypatch, doc,
                                                     tmp_path, capsys):
    """The harm the report line only describes. The run judged this answer
    unusable, so writing it anyway is the run overruling itself."""
    over = " ".join(["word"] * 900)
    out = tmp_path / "o.md"
    _run(kv, monkeypatch, doc, out, {"edits": [
        {"line": 2, "op": "insert", "old": "", "new": over,
         "why": "opening summary"}], "notes": []})
    capsys.readouterr()

    assert not out.exists() or over not in out.read_text()
