"""A second ask has to be a different ask."""

import json
import sys

import pytest

pytestmark = pytest.mark.regression

DOC = "\n".join(
    ["# Platform notes", ""]
    + [f"The worker retries job {i} and records the outcome in Loki. "
       f"The retry budget is {i * 3} seconds and the operator is paged "
       f"after it. " for i in range(1, 14)]
)


def _run(kv, monkeypatch, tmp_path, first):
    """Answer every job with `first`, then valid JSON. Returns the prompts."""
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")
    prompts, asked = [], set()

    def agent(prompt, *_):
        prompts.append(prompt)
        who = prompt[:400]
        if who in asked:
            return json.dumps({"edits": [], "notes": []}), None
        asked.add(who)
        return first, None

    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit:
        pass
    return prompts


def test_a_rejected_answer_is_quoted_back_on_the_retry(kv, monkeypatch,
                                                       tmp_path, capsys):
    """Valid JSON of the wrong shape. The model cannot guess what to change."""
    bad = json.dumps({"edits": [{"line": "3", "old": "a", "new": "b"}],
                      "notes": []})

    prompts = _run(kv, monkeypatch, tmp_path, bad)
    capsys.readouterr()

    assert len(prompts) > 1, "nothing was retried"
    retries = [p for p in prompts if "Your last answer was rejected" in p]
    assert retries, "the retry sent the same prompt again"
    assert "no integer `line`" in retries[0], retries[0][-600:]


def test_a_retried_job_does_not_kill_the_run(kv, monkeypatch, tmp_path,
                                             capsys):
    """The journal was one handle opened around the thread pool."""
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")
    out = tmp_path / "out.md"
    body = src.read_text().splitlines()[2]
    calls = []

    def agent(prompt, *_):
        calls.append(prompt)
        if len(calls) == 1:
            return "", "codex: chain exhausted"
        return json.dumps({"edits": [{"line": 3, "old": body,
                                      "new": "The worker retries job 1 and "
                                             "pages after 3 seconds."}],
                           "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "-o", str(out)])
    try:
        kv.main()
    except SystemExit as e:
        assert e.code in (0, 3), f"the run died: {e.code}"
    printed = capsys.readouterr()

    assert len(calls) > 1, "nothing was retried"
    assert "I/O operation on closed file" not in printed.out + printed.err
    assert out.exists(), "the run wrote no output"
    assert "pages after 3 seconds" in out.read_text(), out.read_text()


def test_a_backend_error_adds_nothing_to_the_prompt(kv, monkeypatch, tmp_path,
                                                    capsys):
    """The answer was never the problem, so quoting it back is noise."""
    seen = []

    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")

    def agent(prompt, *_):
        seen.append(prompt)
        if len(seen) == 1:
            return "", "agy: command not found"
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit:
        pass
    capsys.readouterr()

    assert not any("Your last answer was rejected" in p for p in seen), seen[-1]
