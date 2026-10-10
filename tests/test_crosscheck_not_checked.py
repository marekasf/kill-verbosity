"""A crosscheck no reviewer could run exits 5 ("not checked"), never 1.

Exit 1 is this tool's own "broken" verdict. A reviewer that is not installed,
or that fails without answering, judged nothing, so the result must say the
document was not checked rather than that it is broken.
"""

from __future__ import annotations

import argparse
import json
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


def _record(out):
    return json.loads(runrecord.crosscheck_record_path(out).read_text())


def _write_claude_run(kv, out):
    """A run record naming `claude` as the writer, so `codex` and `agy` are
    the only reviewers outside the writer's family."""
    kv.write_run_record(
        out, agent="claude",
        job_spans=[{"lo": 1, "hi": 3, "specialist": "noise", "unit": "chunk",
                    "answered_rung": "claude", "answered_by": "claude",
                    "answered_by_state": "read", "substituted": False}])


def test_nothing_installed_refuses_without_dispatch(kv, monkeypatch, tmp_path,
                                                    capsys):
    orig, out = _pair(tmp_path)
    _write_claude_run(kv, out)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE",
                        {"codex": False, "agy": False, "claude": True})
    spawned = []

    def fake(cmd, **kwargs):
        spawned.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "no findings.", "")

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    rc, _ = kv.cmd_crosscheck(_ns(orig, out, "codex"))
    err = capsys.readouterr().err

    assert rc == kv.CROSSCHECK_NOT_CHECKED, (rc, err)
    assert not spawned, spawned
    assert "not checked" in err, err
    assert "broken" not in err, err
    rec = _record(out)
    assert rec["checked"] is False, rec
    assert rec.get("not_checked_reason"), rec
    assert rec["answered_by"] is None, rec


def test_a_failed_reviewer_is_not_checked_not_broken(kv, monkeypatch,
                                                     tmp_path, capsys):
    orig, out = _pair(tmp_path)
    _write_claude_run(kv, out)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE",
                        {"codex": True, "agy": False, "claude": True})

    def fake(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "error: not logged in\n")

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    rc, _ = kv.cmd_crosscheck(_ns(orig, out, "codex"))
    err = capsys.readouterr().err

    assert rc == kv.CROSSCHECK_NOT_CHECKED, (rc, err)
    assert "not checked" in err, err
    assert "codex" in err and "not logged in" in err, err
    rec = _record(out)
    assert rec["checked"] is False, rec
    assert rec.get("not_checked_reason"), rec


def test_exit_line_covers_the_new_code(kv):
    assert kv._exit_line(kv.CROSSCHECK_NOT_CHECKED) == (
        "exit 5: not checked -- the reviewer could not run; the document "
        "was not judged")


def test_missing_target_refuses_before_dispatch_and_writes_no_kvcross(
        kv, monkeypatch, tmp_path, capsys):
    """A path that does not exist is refused cleanly, with no traceback and
    no `.kvcross`."""
    missing = tmp_path / "never-written.kv.md"
    spawned = []

    def fake(cmd, **kwargs):
        spawned.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "no findings.", "")

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})
    rc, _ = kv.cmd_crosscheck(argparse.Namespace(
        file=str(missing), original=None, context=[], backend="codex",
        full=False))
    err = capsys.readouterr().err

    assert rc == 2, (rc, err)
    assert not spawned, spawned
    assert "does not exist" in err, err
    assert not runrecord.crosscheck_record_path(missing).exists()


def test_accept_does_not_read_5_as_a_pass(kv):
    """`accept` lets through only `rc not in (0, 3)`, an explicit allow-list,
    so a new code is refused by construction."""
    import inspect
    src = inspect.getsource(kv.cmd_accept)
    assert "rc not in (0, 3)" in src, (
        "cmd_accept's verdict allow-list changed shape -- confirm a new "
        "crosscheck-only code (5) still cannot read as accepted")
