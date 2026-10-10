"""Crosscheck refuses a reviewer from the family that answered."""

from __future__ import annotations

import json
import sys

GOOGLE = "agy"

DOC = "\n".join(
    ["# Notes", ""]
    + [line for i in range(1, 5) for line in (
        f"## Section {i}", "",
        f"It should be noted that the worker, in point of fact, retries job "
        f"{i} and records the outcome in the store for the purposes of a "
        f"later inspection by whichever operator happens to be on call.", "")])


def _main(kv, monkeypatch, src, out, launcher):
    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "--agent", "codex", "-o", str(out)])
    try:
        kv.main()
    except SystemExit:
        pass


def test_a_resumed_run_still_names_the_vendor_that_wrote_the_banked_jobs(
        kv, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE",
                        {"agy": True, "codex": True})
    src, out = tmp_path / "doc.md", tmp_path / "out.md"
    src.write_text(DOC + "\n")
    first = []

    def substituted(prompt, agent, timeout, say=None, avoid=(), answered=None):
        first.append(first[0] if first else prompt)
        if prompt == first[0]:
            return "", "codex exited 1: usage limit reached"
        say(f"codex failed, answered by {GOOGLE} instead — quota")
        answered("codex", GOOGLE, True)
        return json.dumps({"edits": [], "notes": []}), None

    _main(kv, monkeypatch, src, out, substituted)
    assert kv.journal_path(out).is_file(), capsys.readouterr().out[-800:]

    def codex(prompt, agent, timeout, say=None, avoid=(), answered=None):
        answered("codex", "codex", True)
        return json.dumps({"edits": [], "notes": []}), None

    _main(kv, monkeypatch, src, out, codex)
    said = capsys.readouterr()
    assert "resuming:" in said.err, said.err[-800:]
    record = json.loads(kv.run_record_path(out).read_text())
    assert GOOGLE in kv.answering_backends(record), record["job_spans"]

    called = []
    monkeypatch.setattr(kv.spawn, "run_tree",
                        lambda *a, **k: called.append(a) or None)
    args = kv.build_parser().parse_args(
        ["crosscheck", str(out), str(src), "--backend", "agy"])
    rc, _kinds = kv.cmd_crosscheck(args)
    assert rc == 2 and not called, capsys.readouterr().err
    assert "is the model that wrote these edits" in capsys.readouterr().err
