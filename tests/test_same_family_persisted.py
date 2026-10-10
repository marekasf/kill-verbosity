"""`.kvcross` records `same_family` on every path, never a silent null.

A missing sidecar reads the same as "checked, and fine", so `crosscheck`
writes one whether it refuses or passes.
"""

from __future__ import annotations

import argparse
import json
import subprocess

import killverbosity.runrecord as runrecord

CODEX = "codex"


def _pair(tmp_path, text="# Doc\n\nSome prose here.\n"):
    orig, out = tmp_path / "d.md", tmp_path / "d.kv.md"
    orig.write_text(text)
    out.write_text(text)
    return orig, out


def _stub_ok(kv, monkeypatch, stdout="no findings.", stderr=""):
    def fake(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout, stderr)

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE",
                        {"codex": True, "agy": True, "claude": True})


def _ns(orig, out, backend):
    return argparse.Namespace(file=str(out), original=str(orig), context=[],
                              backend=backend, full=False)


def _record(out):
    return json.loads(runrecord.crosscheck_record_path(out).read_text())


def test_unknown_writer_gets_an_explicit_unknown_not_a_silent_null(
        kv, monkeypatch, tmp_path, capsys):
    """No `.kvrun` beside the file at all -- the ordinary shape of a
    standalone `crosscheck` on a document nobody ran through `run` first. Before the fix `cmd_crosscheck` wrote
    no `.kvcross` sidecar on this path, so `same_family` was not merely
    `null` inside a record -- there was no record, which reads the same way
    to anything that checks it.
    """
    orig, out = _pair(tmp_path)
    _stub_ok(kv, monkeypatch)
    rc, _ = kv.cmd_crosscheck(_ns(orig, out, "codex"))
    assert rc == 0, capsys.readouterr()

    record_path = runrecord.crosscheck_record_path(out)
    assert record_path.is_file(), (
        "no .kvcross sidecar was written -- same_family is absent, which a "
        "reader can only read as null")
    rec = _record(out)
    assert rec.get("same_family") is not None, rec
    assert rec["same_family"] == "unknown", rec
    assert isinstance(rec.get("same_family_reason"), str) and \
        rec["same_family_reason"], rec

    err = capsys.readouterr().err
    assert "self-review check (same-family) did not run" in err, err


def test_known_family_writes_a_real_boolean_not_unknown(
        kv, monkeypatch, tmp_path, capsys):
    """Negative control: the writer IS known and the families genuinely
    differ, so `same_family` must land as the boolean `False` -- not the
    `"unknown"` the null used to blur every case into by writing nothing.
    """
    orig, out = _pair(tmp_path)
    kv.write_run_record(
        out, agent="codex",
        job_spans=[{"lo": 1, "hi": 3, "specialist": "noise", "unit": "chunk",
                    "answered_rung": "codex", "answered_by": CODEX,
                    "answered_by_state": "read", "substituted": False}])
    _stub_ok(kv, monkeypatch)
    rc, _ = kv.cmd_crosscheck(_ns(orig, out, "agy"))
    assert rc == 0, capsys.readouterr()

    rec = _record(out)
    assert rec["same_family"] is False, rec
    assert rec["same_family_reason"] is None, rec


def test_self_review_refusal_is_persisted_too(kv, monkeypatch, tmp_path,
                                               capsys):
    """The pre-dispatch refusal (the vendor that wrote the edits reviewing
    them) is a real observation, not only a printed line that scrolls away:
    `.kvcross` must carry `same_family: true` even though no reviewer ever
    ran, so a reader who was not watching the terminal can still see why.
    """
    orig, out = _pair(tmp_path)
    kv.write_run_record(
        out, agent="codex",
        job_spans=[{"lo": 1, "hi": 3, "specialist": "noise", "unit": "chunk",
                    "answered_rung": "codex", "answered_by": CODEX,
                    "answered_by_state": "read", "substituted": False}])
    spawned = []

    def fake(cmd, **kwargs):
        spawned.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "no findings.", "")

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})
    rc, _ = kv.cmd_crosscheck(_ns(orig, out, "codex"))
    assert rc == 2 and not spawned, (rc, capsys.readouterr().err)

    rec = _record(out)
    assert rec["same_family"] is True, rec
    assert rec["answered_by"] is None, rec
