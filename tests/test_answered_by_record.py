"""the run record names who actually answered each job."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import subprocess
import sys
from collections import Counter

import pytest

GOOGLE = "agy"
CODEX = "codex"

DOC = "\n".join(
    ["# Notes", ""]
    + [line for i in range(1, 5) for line in (
        f"## Section {i}", "",
        f"It should be noted that the worker, in point of fact, retries job "
        f"{i} and records the outcome in the store for the purposes of a "
        f"later inspection by whichever operator happens to be on call.", "")])


@pytest.fixture(autouse=True)
def _all_installed(kv, monkeypatch):
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE",
                        {"claude": True, "codex": True, "agy": True})


def test_call_one_hands_back_the_agent_that_answered(kv, monkeypatch):
    monkeypatch.setattr(
        kv.spawn, "run_tree",
        lambda cmd, **k: subprocess.CompletedProcess(
            cmd, 0, '{"edits": [], "notes": []}', ""))
    got = []
    out, err = kv._call_one("p", "codex", 30, answered=got.append)
    assert err is None
    assert got == ["codex"], got


def test_call_one_names_no_one_when_nothing_answered(kv, monkeypatch):
    monkeypatch.setattr(
        kv.spawn, "run_tree",
        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    got = []
    out, err = kv._call_one("p", "codex", 30, answered=got.append)
    assert err and got == [], (err, got)


def test_call_agent_names_the_rung_and_whether_it_looked(kv, monkeypatch):
    def fake(prompt, agent, timeout, say=None, answered=None):
        if agent == "codex":
            return "", "codex exited 1: quota"
        answered(agent)
        return "{}", None

    monkeypatch.setattr(kv, "_call_one", fake)
    seen = []
    kv.call_agent("p", "codex", 60, answered=lambda *a: seen.append(a))
    assert seen == [("claude", "claude", True)], seen


def _run(kv, monkeypatch, tmp_path, capsys, launcher):
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")
    out = tmp_path / "out.md"
    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "--agent", "codex", "-o", str(out)])
    try:
        kv.main()
    except SystemExit:
        pass
    capsys.readouterr()
    return json.loads(kv.run_record_path(out).read_text())


def test_the_record_carries_who_answered_each_job(kv, monkeypatch, tmp_path,
                                                  capsys):
    calls = itertools.count()
    shapes = {0: ("substituted", GOOGLE, True, "read"),
              1: ("as asked", CODEX, True, "read"),
              2: ("as asked", None, True, "unknowable"),
              3: ("as asked", None, False, "not looked at")}

    def launcher(prompt, agent, timeout, say=None, avoid=(), answered=None):
        kind, via, looked, _state = shapes[next(calls) % 4]
        if kind == "substituted":
            say(f"codex failed, answered by {via} instead — quota")
        answered("codex", via, looked)
        return json.dumps({"edits": [], "notes": []}), None

    rec = _run(kv, monkeypatch, tmp_path, capsys, launcher)
    n = next(calls)
    spans = rec["job_spans"]

    assert rec["agent"] == "codex", rec["agent"]
    assert n == len(spans) >= 4, (n, len(spans))
    want = Counter((s == "substituted", v, st)
                   for s, v, _l, st in (shapes[i % 4] for i in range(n)))
    got = Counter((j["substituted"], j["answered_by"], j["answered_by_state"])
                  for j in spans)
    assert got == want, got
    assert rec["substituted_jobs"] == sum(1 for i in range(n) if i % 4 == 0)
    assert rec["substituted_jobs"] >= 1


def test_a_launcher_that_reports_nothing_is_not_looked_at(kv, monkeypatch,
                                                          tmp_path, capsys):
    def launcher(prompt, agent, timeout, say=None, avoid=()):
        return json.dumps({"edits": [], "notes": []}), None

    rec = _run(kv, monkeypatch, tmp_path, capsys, launcher)

    assert rec["job_spans"]
    assert {j["answered_by_state"] for j in rec["job_spans"]} \
        == {"not looked at"}
    assert all(j["answered_by"] is None and j["substituted"] is False
               for j in rec["job_spans"])
    assert rec["substituted_jobs"] == 0


def test_a_retried_summary_does_not_inherit_the_first_answers_reader(
        kv, monkeypatch, tmp_path, capsys):
    """The summary retry hands the first RESULT back in as the job. A second
    answer nobody read must not carry the first answer's reading."""
    body = ("It is worth noting that the gate is aimed at the request path. "
            "I think the retry should be dropped. This is not the whole "
            "story. We should move the check going forward. ") * 2
    doc = ["# The queue rewrite", ""]
    for i in range(12):
        doc += [f"## Section {i + 1}", "", body, ""]
    src, out = tmp_path / "long.md", tmp_path / "o.md"
    src.write_text("\n".join(doc))
    who, real_prompt, seen = {}, kv.job_prompt, []

    def spy(job, *a, **k):
        p = real_prompt(job, *a, **k)
        who[p] = job["specialist"]
        return p

    def launcher(prompt, agent, timeout, say=None, avoid=(), answered=None):
        if who.get(prompt) != "summary":
            answered("codex", CODEX, True)
            return json.dumps({"edits": [], "notes": []}), None
        seen.append(prompt)
        if len(seen) == 1:
            answered("codex", GOOGLE, True)
            over = " ".join(["word"] * 900)
            return json.dumps({"edits": [{"line": 2, "op": "insert",
                                          "old": "", "new": over,
                                          "why": "opening summary"}],
                               "notes": []}), None
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "--agent", "codex", "-o", str(out)])
    try:
        kv.main()
    except SystemExit:
        pass
    capsys.readouterr()
    rec = json.loads(kv.run_record_path(out).read_text())

    assert len(seen) == 2, f"the summary was not retried: {len(seen)} asks"
    summ = [j for j in rec["job_spans"] if j["specialist"] == "summary"]
    assert len(summ) == 1, summ
    assert summ[0]["answered_by_state"] == "not looked at", summ[0]
    assert summ[0]["answered_by"] is None, summ[0]


def _span(via, state="read", rung="codex", sub=True):
    return {"lo": 1, "hi": 3, "specialist": "noise", "unit": "chunk",
            "answered_rung": rung, "answered_by": via,
            "answered_by_state": state, "substituted": sub}


def test_answering_backends_reads_old_and_new_records(kv):
    assert kv.answering_backends({"agent": "codex"}) == ["codex"]
    assert kv.answering_backends(
        {"agent": "codex", "job_spans": [{"lo": 1, "hi": 2,
                                          "specialist": "noise"}]}) \
        == ["codex"]
    assert kv.answering_backends({}) == []
    assert kv.answering_backends(
        {"agent": "codex", "job_spans": [_span(GOOGLE)] * 3}) == [GOOGLE]
    assert kv.answering_backends(
        {"agent": "codex",
         "job_spans": [_span(GOOGLE), _span(CODEX, sub=False),
                       _span(None, "unknowable", rung="claude"),
                       _span(None, "not looked at", rung=None)]}) \
        == [GOOGLE, CODEX, "claude"]


def _crosscheck(kv, monkeypatch, tmp_path, backend, spans, stderr=""):
    orig, out = tmp_path / "d.md", tmp_path / "d.kv.md"
    orig.write_text("# a\n\ntext\n")
    out.write_text("# a\n\ntext\n")
    fields = {"agent": "codex", "chat": False, "inserted": False,
              "summary_added": False, "swaps": [], "exempt": [],
              "incomplete": [],
              "source": hashlib.sha256(b"# a\n\ntext\n").hexdigest()}
    if spans is not None:
        fields["job_spans"] = spans
    kv.write_run_record(out, **fields)
    spawned = []

    def run(*a, **k):
        spawned.append(a)
        return subprocess.CompletedProcess(a, 0, "", stderr)

    monkeypatch.setattr(kv.spawn, "run_tree", run)
    ns = argparse.Namespace(file=str(out), original=str(orig), context=[],
                            backend=backend, full=False)
    rc, _ = kv.cmd_crosscheck(ns)
    return rc, spawned


def test_the_guard_refuses_the_vendor_that_really_answered(
        kv, monkeypatch, tmp_path, capsys):
    rc, spawned = _crosscheck(kv, monkeypatch, tmp_path, "agy",
                              [_span(GOOGLE)] * 3)
    assert rc == 2 and not spawned, (rc, capsys.readouterr().err)
    assert "is the model that wrote these edits" in capsys.readouterr().err


def test_the_guard_lets_the_requested_vendor_review_when_it_wrote_nothing(
        kv, monkeypatch, tmp_path, capsys):
    rc, spawned = _crosscheck(kv, monkeypatch, tmp_path, "codex",
                              [_span(GOOGLE)] * 3)
    err = capsys.readouterr().err
    assert "is the model that wrote these edits" not in err, err
    assert spawned, err


def test_a_mixed_run_refuses_both_vendors(kv, monkeypatch, tmp_path, capsys):
    spans = [_span(GOOGLE), _span(CODEX, sub=False)]
    for backend in ("agy", "codex"):
        rc, spawned = _crosscheck(kv, monkeypatch, tmp_path, backend, spans)
        assert rc == 2 and not spawned, (backend, rc)


def test_an_old_record_still_guards_on_the_requested_agent(
        kv, monkeypatch, tmp_path, capsys):
    rc, spawned = _crosscheck(kv, monkeypatch, tmp_path, "codex", None)
    assert rc == 2 and not spawned, rc
    rc, spawned = _crosscheck(kv, monkeypatch, tmp_path, "agy", None)
    assert spawned, capsys.readouterr().err
