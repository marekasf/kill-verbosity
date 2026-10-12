"""A run that completed 20 of 20 jobs in 502 s and then
FAILED verify (RULES LOST) left no journal, so the rerun paid for every job
again. `cmd_run` deleted the journal whenever no job failed, one step before
verify ran, so a verdict `accept` refuses still threw away every answer.
"""

from __future__ import annotations

import builtins
import io
import json
import sys
import threading

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
    src.write_text(DOC + "\n", encoding="utf-8")
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
    src.write_text(DOC + "\n", encoding="utf-8")

    rc = _run(kv, monkeypatch, src, out, [], verify_rc=None)
    capsys.readouterr()
    assert rc == 3, rc
    assert not kv.journal_path(out).exists(), \
        "a REVIEW run left its journal behind"


class _SeekThenWrite:
    """A journal handle that appends the way the Windows C runtime does.

    There, append mode is emulated: every write seeks to the end and then
    writes, two steps another handle can land between. POSIX `O_APPEND` makes
    them one, which is why this never fails on a POSIX host. The barrier holds
    two writers between their seek and their write, so the race is certain
    rather than a matter of timing; a writer the tool keeps alone times out of
    the barrier and writes where the last one stopped.
    """

    def __init__(self, path, barrier):
        self._path, self._barrier, self._text = path, barrier, []

    def write(self, text):
        self._text.append(text)
        return len(text)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        data = "".join(self._text).encode("utf-8")
        self._real_open(self._path, "ab").close()
        with self._real_open(self._path, "r+b") as f:
            f.seek(0, 2)
            at = f.tell()
            try:
                self._barrier.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass
            f.seek(at)
            f.write(data)
        return False


def test_two_answers_banked_at_once_both_survive_a_seek_then_write_append(
        kv, monkeypatch, tmp_path, capsys):
    """The four jobs land on a thread pool and each appends its own row.
    Where append is seek-then-write, two rows written together share one
    offset and one is lost, so the rerun after a verify FAIL paid for that job
    again: 1 of 4 on a Windows host, never on a POSIX one."""
    src, out = tmp_path / "doc.md", tmp_path / "doc.kv.md"
    src.write_text(DOC + "\n", encoding="utf-8")
    journal = str(kv.journal_path(out))
    real_open = builtins.open
    _SeekThenWrite._real_open = staticmethod(real_open)
    barrier = threading.Barrier(2)

    def opener(file, mode="r", *a, **k):
        if mode == "a" and str(file) == journal:
            return _SeekThenWrite(file, barrier)
        return real_open(file, mode, *a, **k)

    first, second = [], []
    monkeypatch.setattr(builtins, "open", opener)
    monkeypatch.setattr(io, "open", opener)
    rc = _run(kv, monkeypatch, src, out, first, verify_rc=1)
    monkeypatch.setattr(builtins, "open", real_open)
    monkeypatch.setattr(io, "open", real_open)
    capsys.readouterr()
    assert rc == 1, rc
    assert len(first) > 1, "one job cannot race itself; the case measures nothing"

    rc2 = _run(kv, monkeypatch, src, out, second, verify_rc=1)
    capsys.readouterr()
    assert rc2 == 1, rc2
    assert len(second) == 0, (
        f"the rerun dispatched {len(second)} of {len(first)} jobs: rows the "
        f"workers banked together overwrote each other in the journal")
