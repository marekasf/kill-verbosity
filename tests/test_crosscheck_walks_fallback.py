"""A crosscheck reviewer that fails falls to the next installed agent outside
the writer's family, and never to one inside it.
"""

from __future__ import annotations

import argparse
import json
import subprocess

import killverbosity.runrecord as runrecord

ALL = {"codex": True, "agy": True, "claude": True}


def _pair(tmp_path, text="# Doc\n\nSome prose here.\n"):
    orig, out = tmp_path / "d.md", tmp_path / "d.kv.md"
    orig.write_text(text)
    out.write_text(text)
    return orig, out


def _ns(orig, out, backend):
    return argparse.Namespace(file=str(out), original=str(orig), context=[],
                              backend=backend, full=False)


def _record(out):
    return json.loads(runrecord.crosscheck_record_path(out).read_text())


def _span(agent, lo, hi, substituted=False):
    return {"lo": lo, "hi": hi, "specialist": "noise", "unit": "chunk",
            "answered_rung": agent, "answered_by": agent,
            "answered_by_state": "read", "substituted": substituted}


def _failed(cmd):
    return subprocess.CompletedProcess(cmd, 1, "", f"{cmd[0]}: not logged in\n")


def test_failed_reviewer_falls_to_next_non_writer_candidate(
        kv, monkeypatch, tmp_path, capsys):
    """Writer agy; codex (the default pick) fails and claude answers."""
    orig, out = _pair(tmp_path)
    kv.write_run_record(out, agent="agy", job_spans=[_span("agy", 1, 3)])
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", dict(ALL))

    def fake(cmd, **kwargs):
        if cmd[0] == "codex":
            return _failed(cmd)
        if cmd[0] == "claude":
            return subprocess.CompletedProcess(cmd, 0, "no findings.", "")
        raise AssertionError(f"unexpected agent dispatched: {cmd[0]}")

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    rc, _ = kv.cmd_crosscheck(_ns(orig, out, None))
    err = capsys.readouterr().err

    assert rc == 0, (rc, err)
    # Nobody named the reviewer, so the walk is silent: no error, no
    # "falling to" line -- the record says who answered.
    assert "exited 1" not in err and "falling to" not in err, err
    rec = _record(out)
    assert rec["checked"] is True, rec
    assert rec["answered_by"] == "claude", rec
    assert rec["dispatched"] == ["codex", "claude"], rec


def test_writer_family_candidate_is_skipped_never_dispatched(
        kv, monkeypatch, tmp_path, capsys):
    """The edits were written by agy and, on fallback, by claude. After codex
    fails there is nothing left: neither writer is called, and the exit-5
    line names them as skipped."""
    orig, out = _pair(tmp_path)
    kv.write_run_record(out, agent="agy", job_spans=[
        _span("agy", 1, 2), _span("claude", 3, 4, substituted=True)])
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", dict(ALL))
    spawned = []

    def fake(cmd, **kwargs):
        spawned.append(cmd[0])
        assert cmd[0] == "codex", f"a writer-family agent was dispatched: {cmd[0]}"
        return _failed(cmd)

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    rc, _ = kv.cmd_crosscheck(_ns(orig, out, "codex"))
    err = capsys.readouterr().err

    assert rc == kv.CROSSCHECK_NOT_CHECKED, (rc, err)
    assert spawned == ["codex"], spawned
    assert "skipped as the writer" in err, err
    assert "claude" in err and "agy" in err, err
    rec = _record(out)
    assert rec["checked"] is False, rec
    assert rec["dispatched"] == ["codex"], rec


def test_every_non_writer_candidate_fails_names_each(
        kv, monkeypatch, tmp_path, capsys):
    """Writer claude; codex and agy both fail. Exit 5, and the reason names
    both."""
    orig, out = _pair(tmp_path)
    kv.write_run_record(out, agent="claude", job_spans=[_span("claude", 1, 3)])
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", dict(ALL))
    spawned = []

    def fake(cmd, **kwargs):
        spawned.append(cmd[0])
        return _failed(cmd)

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    rc, _ = kv.cmd_crosscheck(_ns(orig, out, "codex"))
    err = capsys.readouterr().err

    assert rc == kv.CROSSCHECK_NOT_CHECKED, (rc, err)
    assert spawned == ["codex", "agy"], spawned
    assert "codex exited 1" in err and "agy exited 1" in err, err
    rec = _record(out)
    assert rec["checked"] is False, rec
    assert rec["dispatched"] == ["codex", "agy"], rec
