"""crosscheck's same-family guard falls back to `.kvcross` once `.kvrun` is gone.

`accept` unlinks the run record by design. If a `.kvcross` from an earlier
crosscheck still names the writer, the guard must use it rather than calling
the writer unknowable.
"""

from __future__ import annotations

import argparse
import subprocess

import killverbosity.runrecord as runrecord

def _pair(tmp_path, text="# Doc\n\nSome prose here.\n"):
    orig, out = tmp_path / "d.md", tmp_path / "d.kv.md"
    orig.write_text(text)
    out.write_text(text)
    return orig, out


def _ns(orig, out, backend):
    return argparse.Namespace(file=str(out), original=str(orig), context=[],
                              backend=backend, full=False)


def _spawn_tracker(kv, monkeypatch):
    spawned = []

    def fake(cmd, **kwargs):
        spawned.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "no findings.", "")

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE",
                        {"codex": True, "agy": True, "claude": True})
    return spawned


def test_deleted_kvrun_surviving_kvcross_names_the_writer_and_refuses(
        kv, monkeypatch, tmp_path, capsys):
    """The real reachable trigger: `accept` has already unlinked the .kvrun
    (by design), but an earlier `crosscheck` left a `.kvcross` naming codex
    as the writer. A second `crosscheck --backend codex` must refuse exactly
    as it would have with the .kvrun still present, and must say the writer
    came from the .kvcross.
    """
    orig, out = _pair(tmp_path)
    spawned = _spawn_tracker(kv, monkeypatch)
    assert not runrecord.run_record_path(out).is_file(), \
        "fixture error: a .kvrun exists, which is the case this is NOT about"
    runrecord.write_crosscheck_record(
        out, backend="agy", answered_by="agy",
        answered_by_state="read", wrote=["codex"], same_family=False,
        same_family_reason=None, checked=True, not_checked_reason=None,
        dispatched=["agy"])

    rc, _ = kv.cmd_crosscheck(_ns(orig, out, "codex"))
    err = capsys.readouterr().err
    assert rc == 2 and not spawned, (rc, err, spawned)
    assert "codex" in err, err
    assert ".kvcross" in err, err


def test_deleted_kvrun_and_no_kvcross_writer_is_still_unknowable(
        kv, monkeypatch, tmp_path, capsys):
    """CONTROL: neither file names a writer, so the guard still says
    unknowable and does not refuse.
    """
    orig, out = _pair(tmp_path)
    spawned = _spawn_tracker(kv, monkeypatch)
    assert not runrecord.run_record_path(out).is_file()
    assert not runrecord.crosscheck_record_path(out).is_file()

    rc, _ = kv.cmd_crosscheck(_ns(orig, out, "codex"))
    err = capsys.readouterr().err
    assert rc == 0, (rc, err)
    assert spawned, "the review should have been dispatched -- unknown, not refused"
    assert "did not run" in err, err


def test_a_live_kvrun_still_wins_over_a_stale_kvcross(
        kv, monkeypatch, tmp_path, capsys):
    """CONTROL: a live `.kvrun` is never shadowed by a `.kvcross` fallback --
    the fallback is read only when the run record itself has nothing to say.
    A `.kvrun` naming a DIFFERENT vendor than the `.kvcross` must win.
    """
    orig, out = _pair(tmp_path)
    spawned = _spawn_tracker(kv, monkeypatch)
    kv.write_run_record(
        out, agent="agy",
        job_spans=[{"lo": 1, "hi": 3, "specialist": "noise", "unit": "chunk",
                    "answered_rung": "agy", "answered_by": "gemini-3.7-flash",
                    "answered_by_state": "read", "substituted": False}])
    runrecord.write_crosscheck_record(
        out, backend="codex", answered_by="codex", wrote=["codex"],
        same_family=False, same_family_reason=None, checked=True,
        not_checked_reason=None, dispatched=["codex"])

    rc, _ = kv.cmd_crosscheck(_ns(orig, out, "codex"))
    err = capsys.readouterr().err
    assert rc == 0, (rc, err)
    assert spawned, "a live .kvrun's own answer must not be shadowed by .kvcross"
