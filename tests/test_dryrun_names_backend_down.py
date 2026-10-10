"""`run <doc> --dry-run` says on the dispatch line whether the agent is installed.

Only installation is checked: a CLI on PATH can still fail on login or quota,
so a passing check reads "installed, not probed" and never "(up)".
"""

from __future__ import annotations

import argparse
import contextlib
import io

DOC_BODY = "# Doc\n\n" + "\n".join(
    " ".join(f"word{i}x{j}" for j in range(28)) for i in range(60)) + "\n"


def _dry_run(kv, tmp_path, agent="codex"):
    doc = tmp_path / "note.md"
    doc.write_text(DOC_BODY)
    ns = argparse.Namespace(
        file=str(doc), out=None, agent=agent, chat=False, dry_run=True,
        job_timeout=30, no_budget=True, only=None, timeout=60,
        full=False, profile=None)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = kv.cmd_run(ns, launcher=lambda *a, **k: (None, "unused"))
    return rc, out.getvalue(), err.getvalue()


def _dispatch_line(out):
    return next(
        (l for l in out.splitlines() if "dispatches" in l and "against" in l), "")


def test_dry_run_names_a_missing_agent_beside_the_dispatch_line(kv, monkeypatch, tmp_path):
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": False})
    rc, out, err = _dry_run(kv, tmp_path, agent="codex")
    assert rc == 0, (rc, out, err)
    line = _dispatch_line(out)
    assert line, f"no dispatch line at all: {out!r}"
    assert "NOT INSTALLED" in line, line
    assert "(up)" not in line, line


def test_an_installed_agent_reads_installed_not_probed(kv, monkeypatch, tmp_path):
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})
    rc, out, err = _dry_run(kv, tmp_path, agent="codex")
    assert rc == 0, (rc, out, err)
    line = _dispatch_line(out)
    assert "installed, not probed" in line, line
    assert "NOT INSTALLED" not in line, line
    assert "(up)" not in line, line


def test_the_label_follows_the_agent_asked_for(kv, monkeypatch, tmp_path):
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True, "agy": False})
    rc, out, err = _dry_run(kv, tmp_path, agent="agy")
    assert rc == 0, (rc, out, err)
    assert "NOT INSTALLED" in _dispatch_line(out), out
