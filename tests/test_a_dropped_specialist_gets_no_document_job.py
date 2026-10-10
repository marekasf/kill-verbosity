"""`run` crashed outright on any document the detector reads as a
checklist. Traceback, no output file, no verdict:
"""

from __future__ import annotations

import pytest

from conftest import run_tool

pytestmark = pytest.mark.regression

CHECKLIST = "# Release checklist\n\n## Milestones\n\n" + "".join(
    "- [ ] **M%d.** The cleanest available answer closed on 2026-09-05 is\n"
    "  obviously the right one and it was renamed in one place while the\n"
    "  other place kept the old name, which is meant to be read with %d.\n"
    % (i, i) for i in range(1, 41))


def test_a_checklist_document_does_not_crash_the_run(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(CHECKLIST)

    r = run_tool("run", doc, "--no-agents")

    assert "Traceback" not in r.stdout + r.stderr, r.stdout + r.stderr
    assert "is not in list" not in r.stdout + r.stderr, r.stdout + r.stderr
    assert (doc.parent / "doc.kv.md").is_file(), r.stdout


def test_the_genre_really_is_the_one_that_drops_the_specialist(tmp_path):
    """The premise, asserted rather than assumed: if the detector stops
    reading this fixture as a checklist, the test above passes while
    exercising nothing."""
    doc = tmp_path / "doc.md"
    doc.write_text(CHECKLIST)

    r = run_tool("run", doc, "--no-agents")

    assert "read as checklist" in r.stdout + r.stderr, r.stdout + r.stderr


def test_a_prose_document_still_gets_its_structure_jobs(tmp_path):
    """The control. The guard must not switch the blocks off for everybody --
    a document with no genre profile keeps `structure`, so the duplicate and
    outline jobs are still built."""
    doc = tmp_path / "doc.md"
    para = ("This paragraph says the same thing twice over, and it is written\n"
            "to wrap so the document has a margin the tool can read.\n\n")
    doc.write_text("# Notes\n\n" + para * 12
                   + "## Second\n\n" + para * 12
                   + "## Third\n\n" + para * 12
                   + "## Fourth\n\n" + para * 12)

    r = run_tool("run", doc, "--dry-run")

    assert "read as checklist" not in r.stdout + r.stderr, r.stdout
    assert "structure" in r.stdout + r.stderr, r.stdout
