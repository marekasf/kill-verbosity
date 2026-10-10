"""`.kvcross` records who reviewed as an observation, on every agent.

Each agent CLI is spawned directly, so the reviewer that answered is the
process this tool ran: `answered_by_state` is "observed", and the record holds
no `tried` key that a reader could take for a second claim.
"""

from __future__ import annotations

import argparse
import json
import subprocess

import pytest

import killverbosity.runrecord as runrecord

WRITER = {"codex": "agy", "agy": "claude", "claude": "codex"}


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


@pytest.mark.parametrize("reviewer", ["codex", "agy", "claude"])
def test_the_reviewer_is_recorded_as_observed(kv, monkeypatch, tmp_path,
                                              capsys, reviewer):
    orig, out = _pair(tmp_path)
    w = WRITER[reviewer]
    kv.write_run_record(
        out, agent=w,
        job_spans=[{"lo": 1, "hi": 3, "specialist": "noise", "unit": "chunk",
                    "answered_rung": w, "answered_by": w,
                    "answered_by_state": "read", "substituted": False}])
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {reviewer: True})
    monkeypatch.setattr(kv, "_cli_argv", lambda name: ([name], None))

    def fake(cmd, **kwargs):
        assert cmd[0] == reviewer, cmd
        return subprocess.CompletedProcess(cmd, 0, "no findings.", "")

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    rc, _ = kv.cmd_crosscheck(_ns(orig, out, reviewer))
    err = capsys.readouterr().err

    assert rc == 0, (rc, err)
    assert "ASSUMED" not in err, err
    rec = _record(out)
    assert rec["answered_by"] == reviewer, rec
    assert rec["answered_by_state"] == kv.CROSSCHECK_OBSERVED == "observed", rec
    assert "tried" not in rec, rec
    assert rec["dispatched"] == [reviewer], rec
