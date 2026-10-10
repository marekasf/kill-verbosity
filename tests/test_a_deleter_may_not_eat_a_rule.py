"""`rules_eaten` exempted the specialists that do the deleting."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

RULE_ROW = (
    "| T73 | Apply the backwards test to the mutation set: **a mutation must "
    "never break the identical controls, and every control must fire "
    "alone.** A stale cell must never be refreshed in place, because the "
    "wrong value then stands forever |"
)

NEUTRAL_ROW = "| T55 | The planner recosts the wider index on every vacuum |"

PADDING_ROW = (
    "| T54 | At this point in time, it is worth noting that the above was, "
    "in and of itself, basically fine |"
)

DOC = "\n".join([
    "# Scope progress",
    "",
    "Ordinary prose that the specialists are not being asked about here.",
    "",
    "| ID | What |",
    "|---|---|",
    RULE_ROW,
    NEUTRAL_ROW,
    PADDING_ROW,
    "",
    "More ordinary prose, so the table is not the whole file.",
    "",
])

RULE_LINE = 7
PADDING_LINE = 9

GUTTED = (
    "| T73 | Apply the backwards test to the mutation set: a mutation must "
    "never break the identical controls |"
)


def _lines():
    return DOC.split("\n")


def _merge(kv, who, edits):
    """One reply through the real `merge`, as `cmd_run` builds the call."""
    lines = _lines()
    prose, heads, tables, quotes = kv.mask(DOC)
    editable = kv.editable_lines(prose, tables, heads, quotes)
    for e in edits:
        e.setdefault("old", lines[e["line"] - 1])
        e.setdefault("why", "shorter")
        e.setdefault("op", "replace")
    reply = {"specialist": who, "lo": 1, "hi": len(lines), "edits": edits}
    _out, applied, refused, _drops = kv.merge(
        lines, [reply], editable, quotes, heads)
    return applied, refused


EXEMPTED = ["noise", "planning", "structure"]


@pytest.mark.parametrize("who", EXEMPTED)
def test_a_deleted_rule_bearing_row_is_refused_and_the_reply_still_lands(
        kv, who):
    """The measured case: a whole table row deleted by a deleting specialist."""
    applied, refused = _merge(kv, who, [
        {"line": RULE_LINE, "new": ""},
        {"line": PADDING_LINE, "new": ""},
    ])

    assert [ln for ln, _w, _k, _t in applied] == [PADDING_LINE], (
        applied, refused)
    assert [ln for ln, _w, _r in refused] == [RULE_LINE], refused
    _ln, _why, reason = refused[0]
    assert "states a rule" in reason, reason
    assert "T73" in reason, reason


@pytest.mark.parametrize("who", EXEMPTED)
def test_a_row_gutted_in_place_loses_one_of_its_two_rules_and_is_refused(
        kv, who):
    """The T73 shape, and the one a substring test cannot catch."""
    applied, refused = _merge(kv, who, [{"line": RULE_LINE, "new": GUTTED}])

    assert not applied, applied
    assert [ln for ln, _w, _r in refused] == [RULE_LINE], refused
    assert "states a rule" in refused[0][2], refused


def test_an_honest_shortening_of_the_same_row_is_not_refused(kv):
    """The control, and it is the half that decides whether this is a gate."""
    kept = (
        "| T73 | A mutation must never break the identical controls and "
        "every control must fire alone; a stale cell must never be refreshed "
        "in place, or the wrong value stands forever |"
    )
    applied, refused = _merge(kv, "noise", [{"line": RULE_LINE, "new": kept}])

    assert [ln for ln, _w, _k, _t in applied] == [RULE_LINE], (applied, refused)
    assert not refused, refused



LABELLED = {
    "a capability label": "- Search and filter the broker queues, which you "
                          "must never do mid-compaction [Required]",
    "a checklist tick": "✅ Never restart the broker while a compaction "
                        "is running",
    "half of a definition-list row": ": required for creation, and you must "
                                     "never omit it from the request",
}


def _label_doc(row):
    return "\n".join([
        "# Runbook",
        "",
        "Ordinary prose that says something about the deploy.",
        "",
        row,
        "",
        "More ordinary prose, so the list is not the whole file.",
        "",
    ])


@pytest.mark.parametrize("row", sorted(LABELLED.values()))
def test_a_label_carrying_a_rule_word_is_not_refused(kv, row):
    doc = _label_doc(row)
    lines = doc.split("\n")
    prose, _heads, tables, _quotes = kv.mask(doc)
    reply = {"specialist": "noise",
             "edits": [{"line": 5, "old": lines[4], "new": "",
                        "op": "replace", "why": "a label"}]}

    assert kv.rules_eaten(lines, reply, prose, tables) == {}


def test_the_label_filter_is_what_spares_them(kv, tmp_path):
    """The control on the control: without the filter these DO get refused."""
    mut = _mutant(tmp_path, "        if label_not_rule(s):\n            continue\n",
                  "        if False:\n            continue\n")
    for row in LABELLED.values():
        doc = _label_doc(row)
        lines = doc.split("\n")
        prose, _heads, tables, _quotes = mut.mask(doc)
        reply = {"specialist": "noise",
                 "edits": [{"line": 5, "old": lines[4], "new": "",
                            "op": "replace", "why": "a label"}]}
        assert mut.rules_eaten(lines, reply, prose, tables), (
            "the mutant did not change behaviour on %r, so it says nothing "
            "about the filter" % row)



EXEMPTION = """    at = {e["line"]: e.get("new", "") for e in result.get("edits", [])
          if isinstance(e.get("line"), int) and 1 <= e["line"] <= len(lines)
          and e.get("op", "replace") == "replace"
          and e.get("old", "").strip() == lines[e["line"] - 1].strip()}
"""

RESTORED = """    if result.get("specialist") in DELETERS + MOVERS:
        return {}
""" + EXEMPTION


def _mutant(tmp_path, old, new):
    """`_legacy.py` with one passage replaced, loaded from a COPY in tmp_path."""
    src = (REPO / "killverbosity" / "_legacy.py").read_text()
    assert src.count(old) == 1, (
        "the mutation target is not in the source exactly once, so this "
        "mutant would test nothing: %r" % old)
    path = tmp_path / "mutant_legacy.py"
    path.write_text(src.replace(old, new))

    name = "kv_mutant_%s" % tmp_path.name
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    return mod


@pytest.mark.parametrize("who", EXEMPTED)
def test_restoring_the_exemption_lets_the_deleted_row_through(tmp_path, who):
    """Put the guard back and the deletion lands unrefused -- the run's own
    state before the fix, reproduced rather than asserted from memory."""
    mut = _mutant(tmp_path, EXEMPTION, RESTORED)
    applied, refused = _merge(mut, who, [
        {"line": RULE_LINE, "new": ""},
        {"line": PADDING_LINE, "new": ""},
    ])

    assert sorted(ln for ln, _w, _k, _t in applied) == [RULE_LINE,
                                                        PADDING_LINE], (
        "the mutant did not change behaviour, so it says nothing about the "
        "test: %r" % (refused,))


@pytest.mark.parametrize("who", EXEMPTED)
def test_restoring_the_exemption_lets_the_gutted_row_through(tmp_path, who):
    mut = _mutant(tmp_path, EXEMPTION, RESTORED)
    applied, refused = _merge(mut, who, [{"line": RULE_LINE, "new": GUTTED}])

    assert [ln for ln, _w, _k, _t in applied] == [RULE_LINE], (
        "the mutant did not change behaviour, so it says nothing about the "
        "test: %r" % (refused,))
