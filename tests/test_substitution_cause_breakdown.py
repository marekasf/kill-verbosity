"""A backend fallback is normal behaviour. No per-agent cause count and no
all-substituted banner are printed; `.kvrun` keeps the substitution.
"""

from __future__ import annotations

import json
import re
import sys

DOC = "\n".join(
    ["# Notes", "", "This paragraph wraps across", "two full lines on purpose.",
     ""]
    + [f"It should be noted that the worker, in point of fact, retries job "
       f"{i} and records the outcome in the store for the purposes of a "
       f"later inspection by whichever operator happens to be on call."
       for i in range(1, 8)])

_SUBST_NOTE = ("codex failed, answered by agy instead — "
               "codex exited 1: not authenticated, run codex login")


def _run(kv, monkeypatch, tmp_path, capsys, launcher, *extra_argv):
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n", encoding="utf-8")
    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(src),
                         "--agent", "codex", "-o", str(tmp_path / "out.md"),
                         *extra_argv])
    try:
        kv.main()
    except SystemExit:
        pass
    said = capsys.readouterr()
    return said.out, said.err


def test_a_substituted_run_prints_no_cause_count_and_no_banner(
        kv, monkeypatch, tmp_path, capsys):
    def launcher(prompt, agent, timeout, say=None, avoid=()):
        if say:
            say(_SUBST_NOTE)
        return json.dumps({"edits": [], "notes": []}), None

    out, err = _run(kv, monkeypatch, tmp_path, capsys, launcher)

    for text in (out, err):
        assert "substituted backend" not in text, text
        assert "fail (" not in text, text
        assert "JOBS SUBSTITUTED" not in text, text
    rec = json.loads(kv.run_record_path(tmp_path / "out.md").read_text(encoding="utf-8"))
    assert rec["substituted_jobs"] >= 1, rec
