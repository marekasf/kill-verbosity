"""A run that completed 20 of 20 jobs in 502 s and then
FAILED verify (RULES LOST) left no journal, so the rerun paid for every job
again. `cmd_run` deleted the journal whenever no job failed, one step before
verify ran, so a verdict `accept` refuses still threw away every answer.
"""

from __future__ import annotations

import json
import sys

DOC = "\n".join(
    ["# Notes", "", "This paragraph wraps across", "two full lines on purpose.",
     ""]
    + [f"It should be noted that the worker, in point of fact, retries job "
       f"{i} and records the outcome in the store for the purposes of a "
       f"later inspection by whichever operator happens to be on call."
       for i in range(1, 8)])


def _run(kv, monkeypatch, src, out, calls, verify_rc):
    def launcher(prompt, agent, timeout, say=None, avoid=()):
        calls.append(prompt)
        return json.dumps({"edits": [], "notes": []}), None

    real = kv.cmd_verify

    def verify(a):
        rc = real(a)
        return rc if verify_rc is None else verify_rc

    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "cmd_verify", verify)
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(src), "-o", str(out)])
    try:
        return kv.main()
    except SystemExit as e:
        return e.code


def test_a_completed_run_that_fails_verify_keeps_its_journal_and_the_rerun_sends_nothing(
        kv, monkeypatch, tmp_path, capsys):
    src, out = tmp_path / "doc.md", tmp_path / "doc.kv.md"
    src.write_text(DOC + "\n")
    first, second = [], []

    rc = _run(kv, monkeypatch, src, out, first, verify_rc=1)
    capsys.readouterr()
    assert rc == 1, rc
    assert first, "the first run dispatched nothing, so there is nothing to bank"
    assert kv.journal_path(out).is_file(), (
        "a run whose every job landed and whose verify FAILED deleted its "
        "journal, so the rerun pays for every job again")

    rc2 = _run(kv, monkeypatch, src, out, second, verify_rc=1)
    capsys.readouterr()
    assert rc2 == 1, rc2
    assert len(second) == 0, (
        f"the rerun after a verify FAIL dispatched {len(second)} of "
        f"{len(first)} jobs; every answer was already paid for")


def test_a_completed_run_that_verify_does_not_fail_still_deletes_its_journal(
        kv, monkeypatch, tmp_path, capsys):
    """Control: REVIEW can be accepted as it is, so the journal has done its
    job and must not linger beside a keepable output."""
    src, out = tmp_path / "doc.md", tmp_path / "doc.kv.md"
    src.write_text(DOC + "\n")

    rc = _run(kv, monkeypatch, src, out, [], verify_rc=None)
    capsys.readouterr()
    assert rc == 3, rc
    assert not kv.journal_path(out).exists(), \
        "a REVIEW run left its journal behind"
