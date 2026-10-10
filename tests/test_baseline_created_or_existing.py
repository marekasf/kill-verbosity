"""`run` writes `<name>.orig.md` beside the input as its verify baseline and
prints `baseline: <name>` without saying it CREATED it -- so cleanup after a
rejected run had no way to tell "this run made you a baseline, it is safe to
delete" from "this baseline predates you, leave it alone" without a `stat`.
"""

from __future__ import annotations

from conftest import run_tool

DOC = "# Notes\n\nThe importer reads from the staging bucket.\n\n" \
      "You must never run this against production.\n"


def test_a_fresh_run_says_it_created_the_baseline(tmp_path):
    src = tmp_path / "note.md"
    src.write_text(DOC)
    base = tmp_path / "note.orig.md"
    assert not base.exists()

    r = run_tool("run", src, "--no-agents")

    assert base.is_file(), r.stderr
    assert f"baseline: {base.name} (created)" in r.stderr, r.stderr
    assert f"baseline: {base.name} (existing)" not in r.stderr, r.stderr


def test_a_rerun_over_an_existing_baseline_says_it_found_it(tmp_path):
    src = tmp_path / "note.md"
    src.write_text(DOC)
    base = tmp_path / "note.orig.md"
    OLD_TEXT = "# Notes\n\nAn older baseline that predates this run.\n"
    base.write_text(OLD_TEXT)

    r = run_tool("run", src, "--no-agents")

    assert f"baseline: {base.name} (existing)" in r.stderr, r.stderr
    assert f"baseline: {base.name} (created)" not in r.stderr, r.stderr
    assert base.read_text() == OLD_TEXT, (
        "an existing baseline must not be overwritten -- " + base.read_text())
