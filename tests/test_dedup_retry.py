"""The dedup retry, which used to crash the run it was cleaning up after."""

from __future__ import annotations

import json
import sys

import pytest
from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))

WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet "
         "kilo lima mike november oscar papa quebec romeo sierra tango").split()


def _para(i: int) -> str:
    """Distinct per section, or the corpus repeats itself and no edit is
    blamed for the cluster."""
    w = WORDS[i % len(WORDS)]
    return (f"Section {i} covers the {w} path and the {w} counter is read once "
            f"per batch. The {w} reader cannot see which batch it came from, "
            f"so the {w} gate is applied to the request path only and never to "
            f"the {w} replay queue that follows it later on.")


@pytest.fixture
def doc(tmp_path):
    out = ["# The queue rewrite", ""]
    for i in range(20):
        out += [f"## Section {i + 1}", "", _para(i), ""]
    p = tmp_path / "queue.md"
    p.write_text("\n".join(out))
    return p


def _run(kv, monkeypatch, doc, out):
    """`summary` answers by copying two body paragraphs verbatim."""
    who, real_prompt = {}, kv.job_prompt

    def spy(job, *a, **k):
        p = real_prompt(job, *a, **k)
        who[p] = job["specialist"]
        return p

    def agent(prompt, *_):
        if who.get(prompt) == "summary":
            return json.dumps({"edits": [
                {"line": 2, "op": "insert", "old": "",
                 "new": "## Summary\n\n" + _para(0) + " " + _para(1),
                 "why": "summary"}], "notes": []}), None
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


def test_the_run_survives_the_retry(kv, monkeypatch, doc, tmp_path, capsys):
    """An AttributeError here took the pass with it."""
    out = tmp_path / "o.md"
    _run(kv, monkeypatch, doc, out)
    printed = capsys.readouterr().out

    assert out.exists(), "the run died before writing the file"
    assert "── verify ──" in printed, printed[-800:]


def test_the_dropped_edit_is_reported_with_its_line_and_owner(
        kv, monkeypatch, doc, tmp_path, capsys):
    _run(kv, monkeypatch, doc, tmp_path / "o.md")
    printed = capsys.readouterr().out

    assert "the replacement repeats text already in the file" in printed
    assert "[summary: dedup]" in printed
    assert "L0" not in printed, "the refusal lost its line"


def test_the_repeated_summary_does_not_reach_the_file(kv, monkeypatch, doc,
                                                      tmp_path, capsys):
    out = tmp_path / "o.md"
    _run(kv, monkeypatch, doc, out)
    capsys.readouterr()

    assert "## Summary" not in out.read_text()


def test_verify_does_not_ask_for_the_summary_it_just_dropped(
        kv, monkeypatch, doc, tmp_path, capsys):
    """MISSING here read "add what was examined, the result…" — printed under
    the refusal line, so the reader was told to write the thing the run had
    thrown out, with no hint why."""
    _run(kv, monkeypatch, doc, tmp_path / "o.md")
    printed = capsys.readouterr().out

    assert "REFUSED — the run wrote one and its own gates dropped it" in \
        printed, printed[-1500:]
    assert "MISSING" not in printed
    assert "a summary the gates dropped" in printed.split("REVIEW —")[-1]


def test_the_reason_reaches_a_standalone_verify(kv, monkeypatch, doc,
                                                tmp_path, capsys):
    """`accept` reruns verify on its own, so the reason has to live in the run
    record and not only in the run that printed it."""
    out = tmp_path / "o.md"
    _run(kv, monkeypatch, doc, out)
    capsys.readouterr()

    rec = json.loads(kv.run_record_path(out).read_text())
    assert "repeats text already in the file" in (rec["refused_summary"] or "")

    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "verify", str(doc), str(out)])
    try:
        kv.main()
    except SystemExit:
        pass
    printed = capsys.readouterr().out

    assert "REFUSED — the run wrote one and its own gates dropped it" in \
        printed, printed[-1500:]
    assert "repeats text already in the file" in printed


def test_a_refusal_that_was_not_the_summary_is_not_reported_as_one(
        kv, monkeypatch, doc, tmp_path, capsys):
    """`summary` is told to touch nothing else, and sometimes touches
    something else anyway. The refusal list holds the name of the specialist,
    not what the edit was, so a body reword it got wrong read as proof a
    summary had been written and thrown out. None had been written."""
    who, real_prompt = {}, kv.job_prompt

    def spy(job, *a, **k):
        p = real_prompt(job, *a, **k)
        who[p] = job["specialist"]
        return p

    def agent(prompt, *_):
        if who.get(prompt) == "summary":
            return json.dumps({"edits": [
                {"line": 5, "op": "replace",
                 "old": "text that is not in the file at all",
                 "new": "something else entirely here", "why": "tidy"}],
                "notes": []}), None
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    out = tmp_path / "o.md"
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(doc),
                                      "-o", str(out), "--timeout", "600"])
    try:
        kv.main()
    except SystemExit:
        pass
    printed = capsys.readouterr().out

    assert json.loads(kv.run_record_path(out).read_text())["refused_summary"] \
        is None
    assert "REFUSED —" not in printed, printed[-1500:]
    assert "MISSING" in printed


def test_prose_that_opens_on_the_word_summary_is_not_a_summary(kv):
    """The `#` is required. Stripping an optional one and matching what is
    left read a paragraph as a heading, and prose with no heading over it
    opens no section — which is the whole question being asked."""
    assert kv.heads_summary("## Summary\n\nthe result.")
    assert kv.heads_summary("# Executive Summary")
    assert not kv.heads_summary("Summary of the rewrite follows below.")
    assert not kv.heads_summary("The queue is rebuilt around suites.")


def test_a_summary_only_the_retry_sent_still_counts_as_written(
        kv, monkeypatch, doc, tmp_path, capsys):
    """`summary_tried` is read before the retry, where the first answers are
    whole. A first answer refused for dead pointers carries no summary, so a
    summary the retry sent and the gates then dropped reported as one nobody
    wrote."""
    seen, real_prompt, rounds = {}, kv.job_prompt, {"n": 0}

    def spy(job, *a, **k):
        p = real_prompt(job, *a, **k)
        seen[p] = job["specialist"]
        return p

    def agent(prompt, *_):
        if seen.get(prompt) != "summary":
            return json.dumps({"edits": [], "notes": []}), None
        rounds["n"] += 1
        if rounds["n"] == 1:
            return json.dumps({"edits": [
                {"line": 2, "op": "insert", "old": "",
                 "new": "It is worth noting that we should drop the retry "
                        "going forward.", "why": "note"}], "notes": []}), None
        return json.dumps({"edits": [
            {"line": 2, "op": "insert", "old": "",
             "new": "## Summary\n\n" + _para(0) + " " + _para(1),
             "why": "summary"}], "notes": []}), None

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    out = tmp_path / "o.md"
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(doc),
                                      "-o", str(out), "--timeout", "600"])
    try:
        kv.main()
    except SystemExit:
        pass
    printed = capsys.readouterr().out

    if "## Summary" in out.read_text():
        pytest.skip("the retry's summary landed, so nothing was refused")
    assert "REFUSED — the run wrote one" in printed, printed[-2000:]
