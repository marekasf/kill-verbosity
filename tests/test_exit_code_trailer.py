"""`run`, `verify` and `crosscheck` print what their exit code means.

All three can exit 3, and an exit code alone says nothing. An agent
reading the log alone -- the usual case, over a wire or a pipe -- had no way
to tell accept from rerun from stop without already knowing this tool's exit
vocabulary by heart.
"""

from __future__ import annotations

import argparse

from conftest import run_tool

ORIG = "# Runbook\n\nThe importer reads from the staging bucket.\n\n" \
       "You must never run this against production.\n\n" \
       "The warehouse is rebuilt nightly by the scheduler.\n"

BROKEN_EDIT = (
    "# Runbook\n\nThe importer reads from the staging bucket.\n\n"
    "The warehouse is rebuilt nightly by the scheduler.\n")

REVIEW_ORIG = """# Rust Usage

## Context

Before we get to the actual problem, some background is helpful. In the visual
team, our core consists of a diffing engine that takes two images and compares
them pixel-wise. It should be noted that image sizes range up to 100
megapixels, which is quite large.
"""

REVIEW_EDIT = """# Rust Usage

## Context

Our core is a diffing engine comparing two images pixel-wise, with image sizes
ranging up to 100 megapixels.
"""


def _pair(tmp_path, orig, edit):
    o, n = tmp_path / "orig.md", tmp_path / "new.md"
    o.write_text(orig)
    n.write_text(edit)
    return o, n


def test_verify_pass_names_its_own_exit_code(tmp_path):
    o, n = _pair(tmp_path, ORIG, ORIG)
    r = run_tool("verify", o, n)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "exit 0:" in r.stdout, r.stdout


def test_verify_review_names_its_own_exit_code(tmp_path):
    o, n = _pair(tmp_path, REVIEW_ORIG, REVIEW_EDIT)
    r = run_tool("verify", o, n)
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert "exit 3:" in r.stdout, r.stdout


def test_verify_broken_names_its_own_exit_code(tmp_path):
    o, n = _pair(tmp_path, ORIG, BROKEN_EDIT)
    r = run_tool("verify", o, n)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "exit 1:" in r.stdout, r.stdout


def test_verify_bad_input_names_its_own_exit_code(tmp_path):
    o = tmp_path / "orig.md"
    o.write_text(ORIG)
    r = run_tool("verify", o, o)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "exit 2:" in r.stdout, r.stdout


def test_run_names_its_own_exit_code(tmp_path):
    src = tmp_path / "note.md"
    src.write_text(ORIG)
    r = run_tool("run", src, "--no-agents")
    assert r.returncode in (0, 3), (r.returncode, r.stdout, r.stderr)
    assert f"exit {r.returncode}:" in r.stdout, r.stdout


def test_run_bad_input_names_its_own_exit_code(tmp_path):
    src = tmp_path / "note.py"
    src.write_text("print(1)\n")
    r = run_tool("run", src, "--no-agents")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "exit 2:" in r.stdout, r.stdout


def _crosscheck(kv, monkeypatch, tmp_path, stdout):
    """`cmd_crosscheck_cli` with the agent call stubbed."""
    import subprocess

    target = tmp_path / "doc.md"
    target.write_text("# Doc\n\nSome prose here.\n")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(kv.spawn, "run_tree", fake_run)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})
    monkeypatch.setattr(kv, "crosscheck_prompt", lambda *a, **k: "PROMPT")
    monkeypatch.setattr(kv, "run_notes_prompt", lambda *a, **k: "")

    return kv.cmd_crosscheck_cli(argparse.Namespace(
        file=str(target), original=None, context=[], dropped=[],
        backend="codex", mode="review", timeout=60))


def test_crosscheck_clean_answer_names_its_own_exit_code(kv, monkeypatch,
                                                          tmp_path, capsys):
    rc = _crosscheck(kv, monkeypatch, tmp_path, "no findings.")
    assert rc == 0, rc
    out = capsys.readouterr().out
    assert "exit 0:" in out, out


def test_crosscheck_meaning_finding_names_its_own_exit_code(kv, monkeypatch,
                                                             tmp_path, capsys):
    answer = ("- problem: the rule was inverted\n"
              "  kind: reversed_rule\n"
              "  file: /doc.md:3\n"
              "  fix: restore the original wording\n"
              "  solves: the reader is no longer told the opposite\n")
    rc = _crosscheck(kv, monkeypatch, tmp_path, answer)
    assert rc == 3, rc
    out = capsys.readouterr().out
    assert "exit 3:" in out, out
