"""Who really wrote each job when the requested agent was substituted.

`.kvrun`'s `job_spans` carries `answered_by` on every entry, substituted or
not, so there is no second, top-level tally to drift from it.
"""

from __future__ import annotations

import json
import sys

OTHER = "agy"

DOC = "\n".join([
    "# Retention policy", "",
    "## Storage",
    "",
    "In order to facilitate the retention of session rows the system "
    "leverages a robust and scalable architecture designed for storage "
    "purposes going forward.",
    "",
    "## Archival",
    "",
    "It should be noted that the archival tier is, in point of fact, a "
    "cost saving measure that the organisation put in place some time ago.",
    "",
]) + "\n"


def test_a_substituted_job_names_who_really_answered_in_job_spans(
        kv, monkeypatch, tmp_path, capsys):
    """`--agent codex`, but every job falls through to OTHER. The
    run record's `agent` field stays what was asked for; each `job_spans`
    entry must still carry the real writer, `substituted: True`, and
    `answered_by_state: "read"` -- not a bare count anywhere, the fact
    itself, per job.
    """
    src, out = tmp_path / "doc.md", tmp_path / "out.md"
    src.write_text(DOC)

    def launcher(prompt, requested_agent, timeout, say=None, avoid=(),
                answered=None):
        if say:
            say(f"{requested_agent} failed, answered by {OTHER} instead — "
                f"usage limit reached")
        if answered:
            answered(OTHER, OTHER, True)
        return json.dumps({"edits": [], "notes": ["nothing to do"]}), None

    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "--agent", "codex", "--any-agent",
                                      "-o", str(out)])
    try:
        kv.main()
    except SystemExit:
        pass
    capsys.readouterr()

    rec = json.loads(kv.run_record_path(out).read_text())
    assert rec["agent"] == "codex", "the requested agent must be unchanged"
    spans = rec["job_spans"]
    assert spans, "the run dispatched no jobs -- nothing to prove"
    assert all(j["substituted"] for j in spans), spans
    assert all(j["answered_by"] == OTHER for j in spans), spans
    assert all(j["answered_by_state"] == "read" for j in spans), spans
    assert rec["substituted_jobs"] == len(spans), rec

    wrote = kv.answering_backends(rec)
    assert wrote == [OTHER], wrote
