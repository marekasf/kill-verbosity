"""A mostly substituted run prints no `answered by:` line; who answered is
recorded in `.kvrun` (`answered_by`, `substituted_jobs`).
"""

from __future__ import annotations

import json
import sys

GOOGLE = "agy"

DOC = "\n".join(
    ["# Notes", ""]
    + [f"It should be noted that the worker, in point of fact, retries job "
       f"{i} and records the outcome in the store for the purposes of a "
       f"later inspection by whichever operator happens to be on call.\n"
       for i in range(1, 6)])


def _run(kv, monkeypatch, tmp_path, capsys, launcher, *extra_argv):
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")
    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE",
                        {"agy": True, "codex": True})
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "--agent", "codex", "-o",
                                      str(tmp_path / "out.md"), *extra_argv])
    try:
        kv.main()
    except SystemExit:
        pass
    return capsys.readouterr().out


def _launcher(substitute):
    calls = []

    def launcher(prompt, agent, timeout, say=None, avoid=(), answered=None):
        calls.append(prompt)
        if substitute(len(calls)):
            say(f"codex failed, answered by {GOOGLE} instead — quota")
            answered("codex", GOOGLE, True)
        else:
            answered("codex", "codex", True)
        return json.dumps({"edits": [], "notes": []}), None
    return launcher


def test_a_mostly_substituted_run_prints_no_answered_by_line(
        kv, monkeypatch, tmp_path, capsys):
    out = _run(kv, monkeypatch, tmp_path, capsys, _launcher(lambda n: True))
    assert "answered by:" not in out, out[-600:]
    assert "did not run on codex" not in out, out[-600:]
    assert out.rstrip().splitlines()[-1].startswith("exit "), out[-300:]
    rec = json.loads(kv.run_record_path(tmp_path / "out.md").read_text())
    assert rec["substituted_jobs"] >= 1, rec
    assert any(j.get("answered_by") == GOOGLE
               for j in rec["job_spans"]), rec["job_spans"]
