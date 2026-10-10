"""A heading that says do-not-edit, and the three shapes that ignored it."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from conftest import run_tool

FRAME = ("It is worth noting that the {w} reads the {o}, resolves every symbol "
         "it names, and writes the resolved {o} back to the warehouse before "
         "the nightly {w} job takes the lock on it.")
DASHES = ("The {w} runs first — before the lock is taken — and the {o} it "
          "writes is the one the next stage reads.")
WALL = ("The {w} starts. It reads the {o}. It resolves the symbols. It writes "
        "the {o} back. It releases the lock. It exits.")


def _doc(marker="NOTE FOR AGENTS"):
    """Each of the three shapes twice: once frozen, once not."""
    return "\n\n".join([
        "# Handbook",
        FRAME.format(w="importer", o="manifest"),
        DASHES.format(w="importer", o="manifest"),
        WALL.format(w="importer", o="manifest"),
        f"## {marker}",
        FRAME.format(w="compactor", o="segment map"),
        DASHES.format(w="compactor", o="segment map"),
        "### A subsection under the marked heading",
        WALL.format(w="compactor", o="segment map"),
        "## An ordinary heading after it",
        FRAME.format(w="replicator", o="follower set"),
    ]) + "\n"


def _frozen_lines(text, marker="NOTE FOR AGENTS"):
    """1-based lines from the marked heading to the next same-level one."""
    lines = text.rstrip("\n").split("\n")
    start = lines.index(f"## {marker}") + 1
    end = lines.index("## An ordinary heading after it")
    return set(range(start, end + 1))


def _flagged(stdout):
    """Every line number the plan lists as something to fix."""
    return {int(m.group(1)) for m in
            re.finditer(r"^\s*(\d+)\s{2,}\S", stdout, re.M)}


def test_the_marked_section_is_never_listed_as_work(tmp_path):
    """The defect. Two long sentences, one em-dash paragraph and one wall sat
    inside the marked section, and the plan listed all four."""
    p = tmp_path / "d.md"
    p.write_text(_doc())
    frozen = _frozen_lines(p.read_text())

    listed = _flagged(run_tool("plan", p).stdout)

    assert not listed & frozen, sorted(listed & frozen)


def test_the_same_shapes_outside_it_are_still_listed(tmp_path):
    """The boundary. The filter has to drop a section, not a shape: the three
    paragraphs above the marker carry the same three shapes and stay."""
    p = tmp_path / "d.md"
    p.write_text(_doc())
    frozen = _frozen_lines(p.read_text())

    listed = _flagged(run_tool("plan", p).stdout)

    assert listed - frozen, "the plan listed nothing at all"
    assert 3 in listed, sorted(listed)


def test_an_ordinary_heading_freezes_nothing(tmp_path):
    """The other boundary. Same document, heading renamed: every line the
    marked version dropped comes back."""
    marked, plain = tmp_path / "m.md", tmp_path / "p.md"
    marked.write_text(_doc())
    plain.write_text(_doc(marker="Notes on the compactor"))
    section = _frozen_lines(marked.read_text())

    with_marker = _flagged(run_tool("plan", marked).stdout)
    without = _flagged(run_tool("plan", plain).stdout)

    assert without & section, "nothing in that section was ever a hit"
    assert without - with_marker == without & section, \
        sorted(without - with_marker)


def test_a_heading_about_the_marker_is_not_a_marker(tmp_path):
    """`MARKER` is anchored at the start of the heading text so a heading
    explaining the convention does not freeze the section explaining it."""
    p = tmp_path / "d.md"
    p.write_text(_doc(marker="What NOTE FOR AGENTS means"))
    section = _frozen_lines(p.read_text(), "What NOTE FOR AGENTS means")

    listed = _flagged(run_tool("plan", p).stdout)

    assert listed & section, sorted(listed)


def test_a_specialist_is_not_asked_to_fix_a_frozen_line(kv, monkeypatch,
                                                        tmp_path):
    """`plan` and `run` build the flag list separately, so both need the fix."""
    p, out = tmp_path / "d.md", tmp_path / "o.md"
    p.write_text(_doc())
    frozen = _frozen_lines(p.read_text())
    prompts = []

    real = kv.job_prompt
    monkeypatch.setattr(kv, "job_prompt",
                        lambda job, *a, **k: (prompts.append(real(job, *a, **k))
                                              or "@@x@@"))
    monkeypatch.setattr(kv, "call_agent",
                        lambda *_: (json.dumps({"edits": [], "notes": []}),
                                    None))
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(p), "-o", str(out)])
    kv.main()

    flagged = {int(m.group(1)) for text in prompts
               for m in re.finditer(r"^\s*(\d+)\s{2,}(?:long sentence|"
                                    r"em-dash pressure|paragraph wall)",
                                    text, re.M)}
    assert not flagged & frozen, sorted(flagged & frozen)


def test_a_refused_frozen_edit_says_the_section_is_marked(kv):
    """Nothing stops a specialist editing a line nobody flagged, so the merge
    still has to refuse one — and say why.
    """
    text = _doc()
    body = text.rstrip("\n").split("\n")
    prose, headings, tables, quotes = kv.mask(text, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)
    line = min(n for n in _frozen_lines(text) if body[n - 1].strip()
               and not body[n - 1].startswith("#"))
    assert line not in editable, "the frozen gate never ran"

    out, applied, refused, _ = kv.merge(
        body, [{"specialist": "prose", "lo": 1, "hi": len(body),
                "edits": [{"line": line, "old": body[line - 1],
                           "new": "The compactor resolves the map."}]}],
        editable, (), headings)

    assert not applied and out[line - 1] == body[line - 1], applied
    assert refused[0][2] == "line is inside a section marked do-not-edit", \
        refused
