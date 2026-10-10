"""A merge-time gate refuses the edit that eats a quotation."""

from __future__ import annotations

import pytest

QUOTE = '"a precise number built on the wrong finish line is worse"'
SECOND = '"a misleading number encourages teams to generate unhelpful code"'

LINES = [
    "# Report",
    "",
    "## Findings",
    "",
    "The reviewer put it plainly: " + QUOTE + " than a blank.",
    "",
    "The team agreed to ship the blank and revisit it later.",
    "",
]

DELETE_L5 = {"op": "replace", "line": 5, "old": LINES[4], "new": "",
             "why": "paragraph wall"}


def _merge(kv, results):
    prose, headings, tables, quotes = kv.mask("\n".join(LINES))
    return kv.merge(
        LINES, results,
        kv.editable_lines(prose, tables, headings, quotes), (), headings)


def _reply(who, *edits, **kw):
    return dict({"specialist": who, "lo": 1, "hi": len(LINES),
                 "edits": list(edits)}, **kw)


@pytest.mark.parametrize("who", ["noise", "planning", "structure", "prose",
                                 "quotable", "chat", "summary", "actionable"])
def test_a_delete_that_eats_a_quotation_is_refused_for_every_specialist(
        kv, who):
    """The measured case. `noise` and `planning` are DELETERS and `structure`
    is the MOVER; `rules_eaten` exempted all three until a later fix, and this gate
    never has."""
    _merged, applied, refused, _ = _merge(kv, [_reply(who, DELETE_L5)])

    assert not applied, applied
    assert len(refused) == 1, refused
    ln, _why, reason = refused[0]
    assert ln == 5, refused
    assert who in reason, reason
    assert "delete" in reason, reason
    assert "a precise number built on the wrong finish line is worse" in reason


def test_a_reword_that_drops_the_quotation_is_refused(kv):
    """Not only a delete. The sentence survives, the quotation does not."""
    edit = {"op": "replace", "line": 5, "old": LINES[4],
            "new": "The reviewer said a precise number on the wrong finish "
                   "line is worse than a blank.",
            "why": "quoted wall"}
    _merged, applied, refused, _ = _merge(kv, [_reply("prose", edit)])

    assert not applied, applied
    assert len(refused) == 1, refused
    assert "reword" in refused[0][2], refused
    assert "a precise number built on the wrong finish line is worse" \
        in refused[0][2]


def test_one_reply_refused_on_the_quote_and_applied_on_the_line_beside_it(kv):
    """Both outcomes in ONE reply."""
    keep = {"op": "replace", "line": 7, "old": LINES[6],
            "new": "The team shipped the blank.", "why": "wordy"}
    _merged, applied, refused, _ = _merge(
        kv, [_reply("noise", DELETE_L5, keep)])

    assert [(a[0], a[2]) for a in applied] == [(7, "reword")], applied
    assert [r[0] for r in refused] == [5], refused


def test_a_reword_that_keeps_the_quotation_verbatim_is_applied(kv):
    """The negative control. The same line, the same specialist, the
    quotation carried through word for word."""
    edit = {"op": "replace", "line": 5, "old": LINES[4],
            "new": "The reviewer said " + QUOTE + " than a blank.",
            "why": "wordy"}
    _merged, applied, refused, _ = _merge(kv, [_reply("prose", edit)])

    assert [(a[0], a[2]) for a in applied] == [(5, "reword")], (applied,
                                                                refused)
    assert not refused, refused


def test_a_quotation_moved_to_another_line_of_the_same_reply_is_applied(kv):
    """Rewrapping a hard-wrapped paragraph moves a quotation onto a different
    line of the same reply, which is the form the prompt asks for. Measured on
    the eval corpus: the one line-level firing over all sixteen reference
    answers is exactly this shape, and it is why the gate reads the whole
    reply and not one line.
    """
    move = [{"op": "replace", "line": 5, "old": LINES[4], "new": "",
             "why": "rewrap"},
            {"op": "replace", "line": 7, "old": LINES[6],
             "new": "The team shipped the blank: " + QUOTE + " than a blank.",
             "why": "rewrap"}]
    _merged, applied, refused, _ = _merge(kv, [_reply("prose", *move)])

    assert sorted(a[0] for a in applied) == [5, 7], (applied, refused)
    assert not refused, refused


def test_another_replys_text_does_not_excuse_the_drop(kv):
    """`kept` is one reply, never the run."""
    other = _reply("summary", {"op": "replace", "line": 7, "old": LINES[6],
                               "new": "The team shipped it: " + QUOTE + ".",
                               "why": "summary"})
    _merged, _applied, refused, _ = _merge(
        kv, [_reply("noise", DELETE_L5), other])

    assert 5 in [r[0] for r in refused], refused


def test_a_quotation_inside_a_code_fence_is_not_this_gates_business(kv):
    """The same exclusion `quoted_claims` and `QUOTATIONS LOST` make."""
    lines = ["# Doc", "", "```text", 'log.info(' + QUOTE + ')', "```", "",
             "Some prose that says nothing in particular at all."]
    prose, headings, tables, quotes = kv.mask("\n".join(lines))
    assert not kv.quoted_claims(lines), kv.quoted_claims(lines)
    _merged, _applied, refused, _ = kv.merge(
        lines, [{"specialist": "noise", "lo": 1, "hi": len(lines),
                 "edits": [{"op": "replace", "line": 4, "old": lines[3],
                            "new": "", "why": "noise"}]}],
        kv.editable_lines(prose, tables, headings, quotes), (), headings)

    assert not [r for r in refused if "somebody else's words" in r[2]], refused


def test_the_unit_reads_the_same_spans_the_end_of_run_check_reads(kv):
    """`quotes_dropped` scores through `quoted_claims`, not a second regex."""
    line = "He said " + QUOTE + " and left."
    assert kv.quotes_dropped(line, "He left.")
    assert not kv.quotes_dropped(line, "He said " + QUOTE + ".")
    assert not kv.quotes_dropped(
        line, "He said \"a precise number built on the\n  wrong finish line "
              "is worse\".")
    assert not kv.quotes_dropped("## A " + QUOTE + " heading", "## A heading")
    assert not kv.quotes_dropped("| " + QUOTE + " | done |", "| gone | done |")


WRAPPED = [
    "# Report",
    "",
    "## Findings",
    "",
    "The reviewer put it plainly: " + QUOTE + " than a blank, and",
    "the team agreed to ship the blank instead of the wrong number.",
    "",
]


def test_a_neighbour_is_not_cleared_by_an_edit_this_gate_will_refuse(kv):
    """The gate has to be answerable UP FRONT as well as at merge time."""
    prose, headings, tables, quotes = kv.mask("\n".join(WRAPPED))
    _merged, applied, refused, _ = kv.merge(
        WRAPPED,
        [{"specialist": "prose", "lo": 1, "hi": len(WRAPPED),
          "edits": [{"op": "replace", "line": 5, "old": WRAPPED[4],
                     "new": "", "why": "wall"}]},
         {"specialist": "noise", "lo": 1, "hi": len(WRAPPED),
          "edits": [{"op": "replace", "line": 6, "old": WRAPPED[5],
                     "new": "The team shipped the blank.", "why": "wordy"}]}],
        kv.editable_lines(prose, tables, headings, quotes), (), headings)

    assert not applied, applied
    at = {r[0]: r[2] for r in refused}
    assert "somebody else's words" in at.get(5, ""), refused
    assert "would be left as a fragment" in at.get(6, ""), refused


def test_two_quotations_on_one_line_are_both_named(kv):
    line = "They wrote " + QUOTE + " and " + SECOND + " in the same week."
    gone = kv.quotes_dropped(line, "")

    assert "a precise number built on the wrong finish line is worse" in gone
    assert "a misleading number encourages teams to generate unhelpful code" \
        in gone
