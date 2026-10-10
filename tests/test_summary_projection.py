"""The run asks what the file would look like if every edit landed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from conftest import run_tool

DOC = """# Handbook

The importer reads the manifest and resolves every symbol that it names today.

```
run the importer
```

The scheduler reads the queue and resolves every symbol that it names today.
"""
LINES = DOC.rstrip("\n").split("\n")


def test_a_projection_that_cannot_be_parsed_answers_no(kv):
    """The defect. Line 3 is prose; an edit making it a fence leaves five
    fence markers, and reading that document raised instead of answering."""
    assert kv.summary_opens_after(LINES, {3: "```"}, {3: "prose"}) == 0


def test_a_projection_that_parses_is_still_read(kv):
    """The boundary. The guard must catch a document nobody can parse, not
    every document. A projected summary is still found."""
    written = kv.summary_opens_after(
        LINES, {3: "## Summary\n\nThe importer resolves the manifest nightly."},
        {3: "summary"})
    absent = kv.summary_opens_after(LINES, {3: LINES[2]}, {3: "prose"})

    assert written, "a projected summary went unseen"
    assert not absent, absent


def test_the_run_survives_an_edit_that_breaks_the_projection(kv, monkeypatch,
                                                             tmp_path):
    """End to end. The edit is refused, as it always was — what changed is
    that the run reaches the merge to refuse it."""
    src, out = tmp_path / "d.md", tmp_path / "o.md"
    src.write_text(DOC)

    monkeypatch.setattr(kv, "call_agent", lambda *_: (json.dumps(
        {"edits": [{"line": 3, "op": "replace", "old": LINES[2],
                    "new": "```", "why": "long sentence"}],
         "notes": []}), None))
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(src), "-o", str(out)])
    kv.main()

    assert out.exists(), "the run wrote nothing"
    assert out.read_text().count("```") == 2, out.read_text()


def test_the_input_s_own_broken_fence_is_still_refused(tmp_path):
    """The other boundary, and the reason the raise exists."""
    src = tmp_path / "broken.md"
    src.write_text("# Handbook\n\n```\nrun the importer\n\nMore prose here.\n")

    r = run_tool("run", src, "-o", tmp_path / "o.md")
    said = r.stdout + r.stderr

    assert r.returncode == 2, said
    assert "code fence opened at line 3 never closes" in said, said
    assert not (tmp_path / "o.md").exists()
