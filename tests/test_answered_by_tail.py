"""A run whose jobs were mostly substituted names, on its last
lines, the model that really answered.
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


def test_the_last_lines_name_the_model_that_answered(kv, monkeypatch,
                                                     tmp_path, capsys):
    out = _run(kv, monkeypatch, tmp_path, capsys, _launcher(lambda n: True),
              "--any-agent")
    lines = out.rstrip().splitlines()
    assert lines[-1].startswith("exit "), lines[-3:]
    assert lines[-2].startswith(f"answered by: {GOOGLE} ("), lines[-3:]
    assert "did not run on codex" in lines[-2], lines[-2]


def test_a_mostly_unsubstituted_run_prints_no_such_line(kv, monkeypatch,
                                                       tmp_path, capsys):
    out = _run(kv, monkeypatch, tmp_path, capsys, _launcher(lambda n: n == 1))
    assert "answered by:" not in out, out[-600:]
    assert "answered by a substituted backend" in out, out[-600:]


def test_the_counts_are_per_model(kv):
    read = kv.ANSWERED_READ
    answered = ([{"substituted": True, "answered_by": GOOGLE,
                  "answered_by_state": read}] * 3
                + [{"substituted": True, "answered_by": "claude",
                    "answered_by_state": read}]
                + [{"substituted": False, "answered_by": "codex",
                    "answered_by_state": read}])
    line = kv.answered_tail(answered, "codex")
    assert line.startswith(f"answered by: {GOOGLE} (3), claude (1)"), line
    assert "4 of 5 jobs" in line, line
    assert kv.answered_tail(answered[3:], "codex") is None
