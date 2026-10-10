"""The target is charged only on the words the run could reach."""

import json
import sys

import pytest

pytestmark = pytest.mark.regression

CLEAN = "\n\n".join(
    f"Region {i} runs {i * 4} workers. It writes to the shared queue."
    for i in range(1, 26)
)
DIRTY = ("It is worth noting that the deployment check is missing here, and "
         "the team should consider whether to add one going forward.")

DOC = (f"# Platform notes\n\n## Regions\n\n{CLEAN}\n\n## Review\n\n{DIRTY}\n")


def _run(kv, monkeypatch, tmp_path):
    src = tmp_path / "doc.md"
    src.write_text(DOC)
    monkeypatch.setattr(
        kv, "call_agent",
        lambda *a: (json.dumps({"edits": [], "notes": []}), None))
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit:
        pass


def test_unsent_words_are_not_charged_at_the_target(kv, monkeypatch, tmp_path,
                                                    capsys):
    """Half the file at the target, plus everything nobody was given."""
    _run(kv, monkeypatch, tmp_path)
    out = capsys.readouterr().out

    row = next(x for x in out.splitlines() if "over target" in x)
    words, aim = (int(n) for n in row.split()[2:5:2])
    assert 0 < aim < words, row
    assert aim > round(words * 0.5), (
        f"{aim} is still the whole file charged at the target: {row}")


def test_the_unsent_share_is_reported(kv, monkeypatch, tmp_path, capsys):
    """A low target that the run then matches still hides the untouched half."""
    _run(kv, monkeypatch, tmp_path)
    out = capsys.readouterr().out

    assert "not sent to anyone" in out, out
    row = next(x for x in out.splitlines() if "not sent to anyone" in x)
    unsent, total = (int(n) for n in row.split()[4:7:2])
    assert 0 < unsent < total, row


def test_a_file_sent_whole_says_nothing_about_coverage(kv, monkeypatch,
                                                       tmp_path, capsys):
    """No row when there is nothing to report."""
    src = tmp_path / "doc.md"
    src.write_text(f"# Notes\n\n{DIRTY}\n")
    monkeypatch.setattr(
        kv, "call_agent",
        lambda *a: (json.dumps({"edits": [], "notes": []}), None))
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit:
        pass

    assert "not sent to anyone" not in capsys.readouterr().out
