"""Round 3 findings."""

from conftest import run_canned, run_tool
from killverbosity import moves, pointers, unmask

QUOTED = ('It cannot see "X causes Y" turned into "X does not cause Y", and it '
          'cannot protect a fact that carries no number, path or identifier, '
          'which is the whole reason a reader still has to read the diff '
          'before accepting anything at all.')

MASKDOC = f"""# Platform notes

## What the checker misses

{QUOTED}
It reports and never fails, because the corpus has correct edits on both sides.
A count written out in words that goes missing is one such edit.
A credited person's name that a reword quietly drops is another one of them.
"""


def test_a_refused_edit_quotes_the_source_not_the_mask(tmp_path, kv,
                                                       monkeypatch, capsys):
    """The refusal names the sentence, with its quotations still in it."""
    doc = tmp_path / "m.md"
    doc.write_text(MASKDOC)
    out = tmp_path / "m.kv.md"

    def reply(who, lo, hi):
        if who == "prose" and lo <= 5 <= hi:
            return [{"line": 5, "old": QUOTED,
                     "new": "The checker is a text matcher.",
                     "why": "shorter"}]
        return []

    run_canned(kv, monkeypatch, doc, out, reply)
    printed = "".join(capsys.readouterr())

    assert "X causes Y" in printed, printed
    assert "It cannot see    " not in printed, printed


def test_the_plan_hit_list_quotes_the_source_not_the_mask(tmp_path):
    """`plan` prints the same sentences and had the same leak."""
    doc = tmp_path / "m.md"
    doc.write_text(MASKDOC)

    printed = run_tool("plan", doc).stdout

    assert "X causes Y" in printed, printed
    assert "It cannot see    " not in printed, printed


WRAPPED = """# Notes

## What the checker does

The run reads the file and reports every shape that it found, and a note
on the ordering is printed beside the list so the reader knows what it
is looking at.

The list is ordered by line so that a reader can walk the file from the
top to the bottom while holding the printed report beside it as they go
through it.

The second pass over the same output was measured across nine samples
and bought very little in the end, so the tool does not offer a revision
pass at all.

Every gate matches text rather than meaning, so a sentence turned around
keeps all of its words and passes each of the checks that run before the
file lands.

A reader who wants the short version can read the header line, which
names the count and the cost, and then decide whether the rest is worth
their attention.
"""


def test_a_wrapped_file_says_what_the_fold_will_count(tmp_path):
    """`plan` counts the lines as written and names the number `run` will get."""
    doc = tmp_path / "w.md"
    doc.write_text(WRAPPED)

    plan = run_tool("plan", doc).stdout

    assert "0 fault-shapes" in plan, plan
    note = [l for l in plan.splitlines() if "hard-wraps" in l]
    assert note, plan
    assert "counts 1 there" in note[0], note[0]


def test_one_run_prints_one_before_count(tmp_path):
    """The header and the footer count the same file the same way."""
    doc = tmp_path / "w.md"
    doc.write_text(WRAPPED)
    edited = tmp_path / "w.kv.md"
    edited.write_text(WRAPPED.replace("nine samples\nand bought very little "
                                      "in the end, so", "nine samples\nand "
                                      "bought little, so"))

    plan = run_tool("plan", doc).stdout
    checked = run_tool("verify", doc, edited).stdout

    note = [l for l in plan.splitlines() if "hard-wraps" in l]
    assert note, plan
    n = note[0].split("counts ")[1].split()[0]
    footer = [l for l in checked.splitlines() if l.startswith("shapes ")]
    assert footer, checked
    assert footer[0].split()[1] == n, (footer[0], note[0])


def test_a_file_that_does_not_wrap_gets_no_fold_note(tmp_path):
    doc = tmp_path / "flat.md"
    doc.write_text("# Flat\n\n## Body\n\nOne short line per paragraph here.\n")

    assert "hard-wraps" not in run_tool("plan", doc).stdout


def test_a_quoted_sentence_is_cut_on_a_word(tmp_path):
    """A cut quote ends on a word and says it was cut."""
    long = ("Fixed: the truncated lists print everything, the growth printed "
            "as a cut, and the headline that named no count.")
    cut = unmask.quote(long)

    assert cut.endswith("…"), cut
    assert len(cut) <= 61, cut
    assert not cut[:-1].endswith(" "), cut
    assert long.startswith(cut[:-1]), cut


def test_a_short_sentence_is_not_marked_as_cut():
    assert unmask.quote("Three words here.") == "Three words here."


DECLINED = [
    "Considered moving 'Adding things' (line 142) before 'Testing' (line 129) "
    "and 'Invariants and gotchas' (line 148) before 'Adding things' "
    "(line 142), but kept the current order as it flows logically from "
    "high-level architecture to setup and reference.",
    "Considered moving “What to send back” before “The five "
    "clusters round 2 found”; kept both because reporting belongs last.",
    "Considered moving \"What is open\" (line 155) above \"What is fixed\" "
    "(line 96) and sent neither, because the corrections-then-fixed-then-open "
    "order already reads straight.",
    "I considered moving 'What is open' (155) and 'What is fixed' (96) to "
    "line 15 but kept them in place because it reads better.",
    'Keep "What is fixed" after "What was wrong in this review," and "What is '
    'left in the POC" after "What is open"',
]

KEPT = [
    "decide whether the unheaded opening at lines 3-9 is the summary",
    "The opening is unheaded; a human must decide.",
    "Line 111 cannot lose a sentence without dropping facts or evidence.",
    "move `## Overview` from line 3 to 9, so no move needed",
]


def test_a_move_the_specialist_declined_is_not_a_note():
    for note in DECLINED:
        assert moves.declined_move(note), note


def test_a_note_that_is_not_about_a_move_is_kept():
    for note in KEPT:
        assert not moves.declined_move(note), note


def test_a_real_move_request_is_still_promoted():
    """Dropping declined moves must not stop a move being made."""
    note = "move `## What to send back` from line 119 to 13"
    assert not moves.declined_move(note)

    results = [{"specialist": "structure", "edits": [], "notes": [note]}]
    done = moves.promote(results, 200)

    assert len(done) == 1, done
    assert results[0]["notes"] == []
    assert results[0]["edits"][0]["op"] == "move"


def test_a_declined_move_leaves_no_note_and_no_edit():
    results = [{"specialist": "structure", "edits": [], "notes": [DECLINED[0]]}]
    done = moves.promote(results, 200)

    assert done == []
    assert results[0]["notes"] == []
    assert results[0]["edits"] == []


POINTDOC = "\n".join(
    ["# Platform notes", "", "## Report counts", ""]
    + [f"The worker retries job {i} and records the outcome in Loki, and the "
       f"retry budget is {i * 3} seconds before the operator is paged.\n"
       for i in range(1, 40)]
    + ["## Exit-code measurement", "",
       "Read the exit code from a command that is not piped anywhere."])


def test_a_summary_pointer_follows_the_rename(tmp_path, kv, monkeypatch,
                                              capsys):
    """`structure` renames a heading, `summary` points at it, both land."""
    doc = tmp_path / "p.md"
    doc.write_text(POINTDOC)
    out = tmp_path / "p.kv.md"

    def reply(who, lo, hi):
        if who == "structure":
            return [{"line": 3, "old": "## Report counts",
                     "new": "## Some report counts", "why": "clearer"}]
        if who == "summary":
            return [{"op": "insert", "line": 2,
                     "new": "## Summary\n\nThe header and the footer disagree "
                            "on a wrapped file. (Report counts) Read the exit "
                            "code off an unpiped command. "
                            "(Exit-code measurement)",
                     "why": "the file opens with no result"}]
        return []

    run_canned(kv, monkeypatch, doc, out, reply)
    printed = "".join(capsys.readouterr())
    written = out.read_text() if out.exists() else ""

    assert "sent after a heading" in printed, printed
    assert "(Some report counts)" in written, written
    assert "(Report counts)" not in written, written
    assert "(Exit-code measurement)" in written, written
    assert "asking once more" not in printed, printed


def test_a_pointer_at_a_deleted_heading_is_still_dead():
    """Renamed is not the same as gone. A pointer with nowhere to go stays."""
    headings = [(2, 2, "Report counts")]
    m = pointers.rename_map(headings, {3: ""})

    assert m == {"Report counts": ""}
    results = [{"specialist": "summary",
                "edits": [{"new": "the result. (Report counts)"}]}]
    assert pointers.follow(results, m) == []
    assert results[0]["edits"][0]["new"] == "the result. (Report counts)"


def test_a_pointer_is_matched_whatever_its_case():
    headings = [(2, 2, "Overview")]
    m = pointers.rename_map(headings, {3: "## What this is"})
    results = [{"specialist": "summary",
                "edits": [{"new": "the team pays for it (overview) monthly"}]}]

    assert pointers.follow(results, m) == [("overview", "What this is")]
    assert results[0]["edits"][0]["new"] == \
        "the team pays for it (What this is) monthly"


def test_only_the_summary_has_its_brackets_rewritten():
    headings = [(2, 2, "Costs")]
    m = pointers.rename_map(headings, {3: "## Spending"})
    results = [{"specialist": "prose",
                "edits": [{"new": "the team pays for it (Costs) monthly"}]}]

    assert pointers.follow(results, m) == []
    assert results[0]["edits"][0]["new"] == \
        "the team pays for it (Costs) monthly"


def test_a_table_row_falls_back_to_the_line():
    """Where the widths disagree, the whole source line is the honest answer."""
    src = ["| a | the cell text |"]
    masked = ["| a |"]

    assert unmask.as_written(src, masked, 1, "cell") == "| a | the cell text |"


def test_a_line_number_off_the_end_returns_the_sentence_unchanged():
    assert unmask.as_written(["one"], ["one"], 9, "kept") == "kept"
