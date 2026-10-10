"""`delete-section` took a quotation out with its section, and nothing
in `merge` refused it.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

QUOTE = ('"The rollout freeze must never move past November," the director '
         "said in the kickoff.")

DOC = "\n\n".join([
    "# Handbook",
    "lede",
    "## Phase 2 - Rollout",
    "Target date: 2026-10-01, owner Dana.",
    QUOTE,
    "## Result",
    "the answer is 42",
]) + "\n"

DOC_NO_QUOTE = "\n\n".join([
    "# Handbook",
    "lede",
    "## Phase 2 - Rollout",
    "Target date: 2026-10-01, owner Dana.",
    "The director confirmed the freeze in the kickoff.",
    "## Result",
    "the answer is 42",
]) + "\n"


def _lines(doc):
    return doc.rstrip("\n").split("\n")


def _run(kv, doc):
    body = _lines(doc)
    ln = next(i for i, s in enumerate(body, 1) if s.startswith("## Phase 2"))
    prose, headings, tables, quotes = kv.mask(doc, "d.md")
    editable = kv.editable_lines(prose, tables, headings, quotes)
    return kv.merge(
        body,
        [{"specialist": "planning", "lo": 1, "hi": len(body),
          "edits": [{"line": ln, "op": "delete-section",
                     "why": "the rollout plan is not part of this "
                            "handbook"}]}],
        editable, {l for l, _ in quotes}, headings)


def test_delete_section_is_refused_when_the_section_carries_a_quotation(kv):
    out, applied, refused, _ = _run(kv, DOC)

    assert not applied, applied
    assert refused, "the section was deleted and took its quotation with it"
    assert "quotation" in refused[0][2], refused[0]
    assert "must never move past November" in "\n".join(out), out


def test_the_same_scheduled_section_without_a_quotation_still_deletes(kv):
    """CONTROL for the whole test above: without this, a gate that refuses
    every `delete-section` -- quotation or not -- would pass the first test
    for the wrong reason."""
    out, applied, refused, _ = _run(kv, DOC_NO_QUOTE)

    assert not refused, refused
    assert applied and applied[0][2] == "delete-section", applied
    _out = "\n".join(out)
    assert "Target date" not in _out and "kickoff" not in _out, _out
    assert "## Result" in _out and "the answer is 42" in _out, _out
