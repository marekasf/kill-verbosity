"""SIGTERM arrived 40 s
into an 800 s budget, and the report named two causes for the same 23 unsent
jobs. L127 said `terminated by SIGTERM before this job was sent`; L129 said
`23 jobs went unsent because the run budget ran out` and told the reader to
raise --timeout. The budget had not run out.
"""

from __future__ import annotations

import json
import sys

import pytest

DOC = "\n".join(
    ["# Notes", "", "This paragraph wraps across", "two full lines on purpose.",
     ""]
    + [f"It should be noted that the worker, in point of fact, retries job "
       f"{i} and records the outcome in the store for the purposes of a "
       f"later inspection by whichever operator happens to be on call."
       for i in range(1, 8)])

ARGS = dict(who="", applied=9, out_name="d.kv.md", journal="d.kvjournal")


def _main(kv, monkeypatch, src, out, extra=()):
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(src), "-o", str(out),
                         *extra])
    try:
        return kv.main()
    except SystemExit as e:
        return e.code


@pytest.mark.skipif(sys.platform == "win32",
                    reason="SIGTERM delivery is POSIX; see test_sigterm_leaves_a_report")
def test_a_sigterm_with_budget_left_names_sigterm_and_never_the_budget(
        kv, monkeypatch, tmp_path, capsys):
    """this used to raise a REAL SIGTERM at the pytest process and then
    `time.sleep(0.3)` to let delivery land before the call returned -- a
    self-timing race that went red 1 of 3 in a loaded full-suite run
    (measured 2026-09-20) despite passing alone in well under a second, and
    a real signal to the runner is a cross-test hazard on top of that.
    """
    src, out = tmp_path / "doc.md", tmp_path / "out.md"
    src.write_text(DOC + "\n")
    monkeypatch.setattr(kv, "JOBS", 1)
    calls = []

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        calls.append(prompt)
        if len(calls) == 1:
            raise kv._Terminated()
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", launcher)
    rc = _main(kv, monkeypatch, src, out)
    said = capsys.readouterr().out

    assert rc == 143, (rc, said)
    assert "went unsent because the run was terminated by SIGTERM" in said, said
    assert "budget ran out" not in said, (
        "a run cut by SIGTERM with its budget left blamed the budget:\n" + said)
    assert "Raise --timeout" not in said, said


def test_a_budget_that_really_expires_still_says_so(
        kv, monkeypatch, tmp_path, capsys):
    """Control: the budget sentence must survive where it is true."""
    src, out = tmp_path / "doc.md", tmp_path / "out.md"
    src.write_text(DOC + "\n")
    monkeypatch.setattr(kv, "JOBS", 1)
    now = [0.0]
    real = kv.budget.Budget
    monkeypatch.setattr(kv.budget, "Budget",
                        lambda total: real(total, clock=lambda: now[0]))

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        now[0] += 10.0
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", launcher)
    rc = _main(kv, monkeypatch, src, out, ["--timeout", "25"])
    said = capsys.readouterr().out

    assert rc == 1, (rc, said)
    assert "went unsent because the run budget ran out" in said, said
    assert "Raise --timeout" in said, said
    assert "SIGTERM" not in said, said


def test_the_advice_splits_a_mixed_count_and_keeps_the_budget_half(kv):
    both = kv.budget.finish_advice(unsent=5, dead=0, terminated=3, **ARGS)
    assert "3 jobs went unsent because the run was terminated by SIGTERM" in both
    assert "2 because the run budget ran out" in both, both
    assert "Raise --timeout" in both, both

    only = kv.budget.finish_advice(unsent=5, dead=0, terminated=5, **ARGS)
    assert "budget" not in only and "Raise --timeout" not in only, only


def test_a_dead_job_beside_sigterm_unsent_jobs_does_not_blame_the_budget(kv):
    said = kv.budget.finish_advice(unsent=3, dead=1, terminated=3, **ARGS)
    assert "3 unsent jobs too" in said, said
    assert "budget" not in said and "Raise --timeout" not in said, said
