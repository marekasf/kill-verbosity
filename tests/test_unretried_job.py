"""A job whose retry the budget refused has not died twice."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))

from killverbosity import budget

DOC = REPO / "tests" / "fixtures" / "review-findings.md"



@pytest.fixture
def doc(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(DOC.read_text())
    return p


def _run_out_of_budget_after_one_failure(kv, monkeypatch, path, out):
    """One job fails, then the clock jumps past the budget."""
    now = [0.0]
    real = budget.Budget
    monkeypatch.setattr(kv.budget, "Budget",
                        lambda total: real(total, clock=lambda: now[0]))
    calls = []

    def agent(prompt, *_):
        calls.append(prompt)
        if len(calls) == 1:
            now[0] = 10_000.0
            return "", "the backend closed the connection"
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(path),
                                      "-o", str(out), "--timeout", "600"])
    try:
        kv.main()
    except SystemExit:
        pass
    return calls


def test_a_job_asked_once_is_not_reported_as_dead(kv, monkeypatch, doc,
                                                  tmp_path, capsys):
    out = tmp_path / "doc.kv.md"
    calls = _run_out_of_budget_after_one_failure(kv, monkeypatch, doc, out)
    printed = capsys.readouterr()

    assert len(calls) == 1, "the budget did not stop the run"
    assert "died twice" not in printed.out, printed.out[-900:]
    assert "rerun with a different --agent" not in printed.out


def test_it_is_told_to_run_the_same_command_again(kv, monkeypatch, doc,
                                                  tmp_path, capsys):
    """Nothing died, so the whole answer is the resume."""
    out = tmp_path / "doc.kv.md"
    _run_out_of_budget_after_one_failure(kv, monkeypatch, doc, out)

    assert "run the same command again" in capsys.readouterr().out


def test_a_retry_that_was_sent_keeps_its_own_reason(kv, monkeypatch, doc,
                                                    tmp_path, capsys):
    """Not every unsent retry was refused before dispatch. One sent with a
    clock the run had already cut says exactly that, and rewriting it as
    "never sent" is the same wrong label pointing the other way."""
    now = [0.0]
    real = budget.Budget
    monkeypatch.setattr(kv.budget, "Budget",
                        lambda total: real(total, clock=lambda: now[0]))
    first = []

    def agent(prompt, *_):
        if not first:
            first.append(prompt)
            now[0] = 500.0
            return "", "the backend closed the connection"
        if prompt == first[0]:
            return "", "timed out"
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(doc),
                                      "-o", str(tmp_path / "doc.kv.md"),
                                      "--timeout", "600"])
    try:
        kv.main()
    except SystemExit:
        pass
    printed = capsys.readouterr().out

    assert "left only 100s of the 240s a job gets" in printed, printed[-900:]
    assert "failed once" not in printed
    assert "died twice" not in printed


def test_the_cause_line_says_it_failed_once_and_was_not_re_asked():
    """Not the plain unsent reason: this job did fail, and hiding that would
    lose the backend error the reader needs if it keeps happening."""
    said = budget.unretried_reason(600, "the backend closed the connection")
    assert "failed once" in said
    assert "the backend closed the connection" in said
    assert "600s run budget ran out before the retry was sent" in said
