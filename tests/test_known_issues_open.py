"""One reproduction per open entry in `docs/known-issues.md`."""

from __future__ import annotations

import sys

import pytest
from conftest import REPO, run_canned, run_tool

sys.path.insert(0, str(REPO / "bin"))

pytestmark = pytest.mark.regression


def _pair(tmp_path, before, after):
    o = tmp_path / "o.md"
    n = tmp_path / "n.md"
    o.write_text(before)
    n.write_text(after)
    return o, n


def _gone(out):
    """The headings the report says pair with nothing in the edit."""
    lines = out.splitlines()
    if not any("headings gone" in x for x in lines):
        return []
    at = next(i for i, x in enumerate(lines) if "headings gone" in x)
    out = []
    for x in lines[at + 1:]:
        if not x.strip():
            continue
        if not x.startswith("  "):
            break
        out.append(x.strip().split(" — ")[0])
    return out



TWO_NOTES = (
    "# Handbook\n\n"
    "## Notes\n\n"
    "The worker retries a failed job three times and no more. The retry "
    "budget is 30 seconds and the operator is paged after it.\n\n"
    "## Other\n\n"
    "Nightly compaction runs at 02:00 and reads the previous day only.\n\n"
    "## Notes\n\n"
    "Backfills need a run of their own before the daily report is built "
    "without any manual step.\n"
)


def test_two_sections_with_the_same_heading_keep_separate_bodies(tmp_path):
    """`## Notes` twice in a file is enough."""
    o, n = _pair(tmp_path, TWO_NOTES,
                 TWO_NOTES.replace("## Notes\n\nBackfills",
                                   "## Backfills\n\nBackfills"))

    out = run_tool("verify", o, n).stdout

    assert _gone(out) == [], out


def test_a_renamed_section_that_grew_is_not_reported_gone(tmp_path):
    """The original sentence is still there, word for word. Only the added
    text pushes the overlap under the threshold."""
    o, n = _pair(
        tmp_path,
        "# Handbook\n\n## Retry policy\n\nThe worker retries a failed job "
        "three times and no more.\n",
        "# Handbook\n\n## Retries\n\nThe worker retries a failed job three "
        "times and no more. The retry budget is 30 seconds and the operator "
        "is paged after it. Nightly compaction runs at 02:00 and reads the "
        "previous day only, so a backfill needs a run of its own before the "
        "daily report is built.\n",
    )

    out = run_tool("verify", o, n).stdout

    assert _gone(out) == [], out


SHORT_BODY = (
    "# Handbook\n\n"
    "## Retry policy\n\n"
    "Three attempts.\n\n"
    "## Compaction\n\n"
    "Nightly compaction runs at 02:00 and reads the previous day only, so a "
    "backfill needs a run of its own.\n"
)


def test_a_two_word_body_still_matches_its_own_rename(tmp_path):
    """`Three attempts.` is the whole section, and it is unchanged."""
    o, n = _pair(tmp_path, SHORT_BODY,
                 SHORT_BODY.replace("## Retry policy", "## Retries"))

    out = run_tool("verify", o, n).stdout

    assert _gone(out) == [], out


def test_a_section_folded_into_another_is_reported_gone_not_renamed(kv):
    """Pinned green. Two old bodies inside one new section is a merge."""
    doomed = set("backfill compaction nightly window".split())
    kept = set("retry budget operator paged".split())
    pairs, gone = kv.heading_moves(
        [(1, 2, "Retry policy"), (5, 2, "Compaction")],
        [(9, 2, "Retries")],
        {"Retry policy": [kept], "Compaction": [doomed]},
        {"Retries": [kept | doomed | {"extra", "words", "here", "too"}]})

    assert sorted(gone) == ["Compaction", "Retry policy"], (pairs, gone)


def test_a_renamed_and_rewritten_section_is_reported_gone_on_purpose(tmp_path):
    """Pinned green. The report errs this way deliberately."""
    o, n = _pair(
        tmp_path,
        "# Handbook\n\n## Retry policy\n\nThe worker retries a failed job "
        "three times and no more.\n",
        "# Handbook\n\n## Paging\n\nAn operator is called after the third "
        "attempt.\n",
    )

    assert _gone(run_tool("verify", o, n).stdout) == ["Retry policy"]



def test_a_two_word_splice_is_caught(kv):
    """A rewrite that leaves the same two words either side of a line break."""
    assert kv.tail_added("", "the head of it", "we rewrote the retry policy",
                         "retry policy changed last week")


def test_a_two_word_repeat_the_edit_did_not_make_is_left_alone(kv):
    """The boundary. Two words is only safe where the seam is the edit's own."""
    assert not kv.tail_added("", "we rewrote the retry policy",
                             "we changed the retry policy",
                             "retry policy changed last week")


def test_the_whole_file_scan_still_needs_three_words(kv):
    """`duplicated_tail` walks every line pair in the document, not a seam."""
    pair = ["we rewrote the retry policy", "retry policy changed last week"]

    assert not kv.duplicated_tail(pair)
    assert kv.duplicated_tail(pair, 2)


def test_two_identical_sentences_share_one_excerpt_by_design(tmp_path):
    """Pinned green. Word for word the same, so there is nothing else to print."""
    same = ("It is worth noting that the queue drains slowly under load "
            "today.")
    o, n = _pair(tmp_path, f"# T\n\n{same}\n\n{same}\n",
                 f"# T\n\n{same}\n\n{same}\n")

    row = next(x for x in run_tool("verify", o, n).stdout.splitlines()
               if "frame (" in x)

    assert "L3" in row and "L5" in row, row



def test_an_excerpt_crosses_a_wrapped_line(tmp_path):
    """The sentence ends on the second line. The excerpt reads on to it."""
    doc = tmp_path / "wrapped.md"
    doc.write_text("# T\n\nIt is worth noting that the queue drains\n"
                   "slowly under load today.\n")

    row = next(x for x in run_tool("plan", str(doc)).stdout.splitlines()
               if "  frame " in x)

    assert "slowly under load" in row, row


def test_an_excerpt_stops_at_the_end_of_its_paragraph(tmp_path):
    """Reading on stops at a blank line and at the block below it."""
    doc = tmp_path / "block.md"
    doc.write_text("# T\n\nIt is worth noting that the queue drains\n\n"
                   "| job | state |\n| --- | --- |\n| a | done |\n")

    row = next(x for x in run_tool("plan", str(doc)).stdout.splitlines()
               if "  frame " in x)

    assert "|" not in row and "job" not in row, row



def _summary_doc(kv, monkeypatch, tmp_path, pointer):
    """A run whose `summary` job answers with `pointer` in its opening line."""
    src = tmp_path / "doc.md"
    src.write_text(
        "# Handbook\n\n## The five clusters round two found\n\n"
        + "\n\n".join(
            f"The worker retries job {i} three times and no more. The retry "
            f"budget is {i * 3} seconds and the operator is paged after it. "
            f"Nightly compaction runs at 02:00 and reads the previous day "
            f"only, so a backfill for job {i} needs its own run."
            for i in range(1, 22)) + "\n")

    def reply(who, lo, _hi):
        if who != "summary":
            return []
        return [{"line": 2, "op": "insert", "old": "",
                 "new": f"## Summary\n\nRetries are capped at three "
                        f"{pointer}.", "why": "opening summary"}]

    seen = run_canned(kv, monkeypatch, src, tmp_path / "out.md", reply)
    assert any(who == "summary" for who, _ in seen), sorted({w for w, _ in seen})


def test_a_summary_pointer_at_a_heading_that_does_not_exist_is_refused(
        kv, monkeypatch, tmp_path, capsys):
    """The summary names "the five clusters" for a section called "The five
    clusters round two found". Nothing renamed it, so `dead_pointers` — which
    only knows the headings being renamed — cannot see it.
    """
    _summary_doc(kv, monkeypatch, tmp_path, "(the five clusters listed below)")
    err = capsys.readouterr().err

    assert "asking once more" in err, err
    assert "no heading reads that way" in err, err


def test_an_ordinary_aside_in_the_summary_is_left_alone(
        kv, monkeypatch, tmp_path, capsys):
    """The boundary of the check above."""
    _summary_doc(kv, monkeypatch, tmp_path, "(about half of them)")
    assert "no heading reads that way" not in capsys.readouterr().err

    _summary_doc(kv, monkeypatch, tmp_path,
                 "(the retry budget is 30 seconds)")
    assert "no heading reads that way" not in capsys.readouterr().err



def test_a_hole_inside_a_code_fence_is_protected(tmp_path):
    """A template that put `{{USER_FOCUS}}` in an example block could lose it
    with nothing printed."""
    o, n = _pair(
        tmp_path,
        "# Template\n\nThe focus is substituted in.\n\n"
        "```text\nAnswer this: {{USER_FOCUS}}\n```\n",
        "# Template\n\nThe focus is substituted in.\n\n"
        "```text\nAnswer this:\n```\n",
    )

    res = run_tool("verify", o, n)

    assert res.returncode == 1, res.stdout


def test_only_the_placeholder_is_read_out_of_a_fence(tmp_path):
    """The boundary of the fix above."""
    o, n = _pair(
        tmp_path,
        "# Template\n\nThe focus is substituted in.\n\n"
        "```python\nretries = 47\n```\n",
        "# Template\n\nThe focus is substituted in.\n\n"
        "```python\nretries = 3\n```\n",
    )

    res = run_tool("verify", o, n)

    assert "47" not in res.stdout, res.stdout


def test_a_spelled_out_count_that_goes_missing_fails_the_run(tmp_path):
    """known-issues.md said this one reports and never fails. It fails."""
    o, n = _pair(
        tmp_path,
        "# Handbook\n\nThe review confirmed three key architectural "
        "properties of the retry path before the change landed.\n",
        "# Handbook\n\nThe review confirmed key architectural properties of "
        "the retry path before the change landed.\n",
    )

    res = run_tool("verify", o, n)

    assert res.returncode == 1, res.stdout
    assert "TOKENS LOST" in res.stdout, res.stdout


def test_a_credited_name_a_reword_drops_only_reports(tmp_path):
    """Pinned green. It prints and exits 3 on purpose."""
    o, n = _pair(
        tmp_path,
        "# Handbook\n\nKuldeep's wrong turn on the retry budget was caught in "
        "review before it reached the release branch.\n",
        "# Handbook\n\nThe wrong turn on the retry budget was caught in "
        "review before it reached the release branch.\n",
    )

    res = run_tool("verify", o, n)

    assert res.returncode == 3, (res.returncode, res.stdout)
    assert "Kuldeep" in res.stdout, res.stdout


SWAPPED_BEFORE = """# Worker rules

## Retry policy

The worker must retry a failed upload three times before it gives up.

## Compaction

Nightly compaction runs at 02:00 and never during business hours.
"""

SWAPPED_AFTER = """# Worker rules

## Retry policy

Nightly compaction runs at 02:00 and never during business hours.

## Compaction

The worker must retry a failed upload three times before it gives up.
"""


def test_a_rule_pasted_whole_under_another_heading_is_reported(tmp_path):
    """The move `relocated` exists for, and the one it could not see."""
    o, n = _pair(tmp_path, SWAPPED_BEFORE, SWAPPED_AFTER)

    res = run_tool("verify", o, n)

    assert res.returncode == 3, f"exit {res.returncode}:\n{res.stdout}"
    assert "rules that changed section" in res.stdout, res.stdout
    assert "2 rules turned up under a different heading" in res.stdout, res.stdout


def test_a_rule_that_stayed_in_its_section_is_not_reported(tmp_path):
    """Pinned green. The guard's own job, and the fix must not cost it."""
    o, n = _pair(
        tmp_path,
        SWAPPED_BEFORE,
        SWAPPED_BEFORE.replace("never during business hours",
                               "never in the day"),
    )

    res = run_tool("verify", o, n)

    assert "rules that changed section" not in res.stdout, res.stdout


def test_a_rule_under_a_renamed_heading_is_not_reported(tmp_path):
    """Pinned green. Renaming a heading is `structure`'s own job."""
    o, n = _pair(tmp_path, SWAPPED_BEFORE,
                 SWAPPED_BEFORE.replace("## Retry policy", "## Upload retries"))

    res = run_tool("verify", o, n)

    assert "rules that changed section" not in res.stdout, res.stdout


def test_a_rule_under_a_new_heading_is_not_reported(tmp_path):
    """Pinned green. A heading inserted over prose re-parents it."""
    o, n = _pair(
        tmp_path,
        "# Worker rules\n\nThe worker must retry a failed upload three times "
        "before it gives up.\n",
        "# Worker rules\n\n## Summary\n\nThe worker must retry a failed "
        "upload three times before it gives up.\n",
    )

    res = run_tool("verify", o, n)

    assert "rules that changed section" not in res.stdout, res.stdout




def test_a_gone_heading_says_whether_its_facts_are_still_in_the_file(tmp_path):
    """The evidence that tells the two cases apart, since the pairing cannot."""
    before = ("# Doc\n\n## Retry policy\n\nThe worker retries a failed upload "
              "three times.\n\n## Compaction\n\nCompaction runs nightly.\n")
    tail = "\n## Compaction\n\nCompaction runs nightly.\n"

    def row(after):
        o, n = _pair(tmp_path, before, after)
        out = run_tool("verify", o, n).stdout
        lines = out.splitlines()
        at = next(i for i, x in enumerate(lines) if "headings gone" in x)
        return next(x.strip() for x in lines[at + 1:] if x.strip())

    kept = row("# Doc\n\n## Upload behaviour\n\nEvery send is attempted three "
               "times against the queue.\n" + tail)
    assert kept.startswith("Retry policy — its 1 protected token is still"), \
        kept

    lost = row("# Doc" + tail)
    assert "is gone from the file" in lost, lost

    bare = _pair(tmp_path, "# Doc\n\n## Notes\n\nSome prose, nothing to "
                           "trace.\n" + tail, "# Doc" + tail)
    out = run_tool("verify", *bare).stdout
    assert "no number, path or identifier under it to trace" in out, out


@pytest.mark.xfail(strict=True,
                   reason="reported gone on purpose; a wrong 'gone' is "
                          "checked and found, a wrong 'renamed' is not")
def test_cost_a_renamed_and_rewritten_section_is_reported_gone(tmp_path):
    """The section is in the file under its new name and the report says gone."""
    o, n = _pair(
        tmp_path,
        "# Handbook\n\n## Retry policy\n\nThe worker retries a failed job "
        "three times and no more.\n",
        "# Handbook\n\n## Paging\n\nAn operator is called after the third "
        "attempt.\n",
    )

    assert _gone(run_tool("verify", o, n).stdout) == [], (
        "the section is in the file under its new name")


def test_a_hand_written_pointer_at_a_missing_heading_is_reported(tmp_path):
    """It used to come back PASS at exit 0 with the pointer never mentioned."""
    orig = (
        "# Handbook\n\n"
        "## Summary\n\n"
        "Retries are capped at three (the five clusters listed below).\n\n"
        "## The five clusters\n\n"
        "Body text here about retries and the operator.\n")
    o, n = _pair(tmp_path, orig,
                 orig.replace("## The five clusters", "## Cluster notes"))

    res = run_tool("verify", o, n)

    assert "five clusters" in res.stdout, (
        f"exit {res.returncode} and nothing said about the pointer\n"
        f"{res.stdout}")
    assert res.returncode == 3, (
        f"a dead pointer needs a reader, so it is REVIEW\n{res.stdout}")


def test_an_ordinary_bracket_is_not_read_as_a_pointer(tmp_path):
    """The false positive that got the one-document version refused."""
    orig = ("# Handbook\n\n## Summary\n\nThe backend is chosen for you "
            "(auto-picked) and the run says which.\n\n## Paging rules\n\n"
            "An operator is called after the third attempt.\n")
    o, n = _pair(tmp_path, orig,
                 orig.replace("## Paging rules", "## Paging"))

    res = run_tool("verify", o, n)

    assert "pointers with no section" not in res.stdout, res.stdout


def test_two_hits_in_one_table_row_print_different_excerpts(tmp_path):
    """Three hits, one row, and it used to print the row three times."""
    doc = tmp_path / "t.md"
    doc.write_text("# T\n\n| Check | Note |\n|---|---|\n"
                   "| retry | it is worth noting that this is utilized in "
                   "order to drain |\n")

    rows = [x for x in run_tool("plan", str(doc)).stdout.splitlines()
            if x.strip().startswith("5  ")]
    excerpts = [x.split(None, 2)[2] for x in rows]

    assert len(excerpts) == 3, rows
    assert len(set(excerpts)) == 3, (
        "every hit on the row printed the same excerpt\n  "
        + "\n  ".join(rows))


@pytest.mark.xfail(strict=True,
                   reason="one-way containment called 3569 deletions renames "
                          "on 4000 documents")
def test_cost_a_folded_section_is_reported_as_a_rename(kv):
    """Two old bodies inside one new section is a merge, and it reads as two
    deletions.
    """
    doomed = set("backfill compaction nightly window".split())
    kept = set("retry budget operator paged".split())

    _pairs, gone = kv.heading_moves(
        [(1, 2, "Retry policy"), (5, 2, "Compaction")],
        [(9, 2, "Retries")],
        {"Retry policy": [kept], "Compaction": [doomed]},
        {"Retries": [kept | doomed | {"extra", "words", "here", "too"}]})

    assert "Retry policy" not in gone, (
        "the body is inside the new section, so this is a rename")


def test_an_unclear_that_states_an_open_question_still_fails(tmp_path):
    """The green half of the pair below."""
    before = ("# Retries\n\nThe worker retries three times.\n\nIt is unclear "
              "whether the 30s budget covers the third attempt.\n")
    after = "# Retries\n\nThe worker retries three times.\n"

    o, n = _pair(tmp_path, before, after)
    res = run_tool("verify", o, n)

    assert res.returncode == 1, res.stdout
    assert "RULES LOST" in res.stdout, res.stdout


def test_a_chat_sign_off_is_not_a_lost_rule(tmp_path):
    """A deleted sign-off fails the run, and it is the edit the tool asks for."""
    before = ("# Status update\n\nThe migration is done. Nine of eleven repos "
              "are on the new runner.\n\nLet me know if you have any questions "
              "or if anything above is unclear, and I will do my best to "
              "answer.\n")
    after = ("# Status update\n\nThe migration is done. Nine of eleven repos "
             "are on the new runner.\n")

    o, n = _pair(tmp_path, before, after)
    res = run_tool("verify", o, n)

    assert "RULES LOST" not in res.stdout, res.stdout
    assert res.returncode != 1, res.stdout


def test_a_sign_off_that_puts_the_word_first_is_not_a_lost_rule(tmp_path):
    """"If anything is unclear, let me know" is the same padding reversed."""
    before = ("# Status update\n\nThe migration is done. Nine of eleven repos "
              "are on the new runner.\n\nIf anything above is unclear, let me "
              "know.\n")
    after = ("# Status update\n\nThe migration is done. Nine of eleven repos "
             "are on the new runner.\n")

    o, n = _pair(tmp_path, before, after)
    res = run_tool("verify", o, n)

    assert "RULES LOST" not in res.stdout, res.stdout
    assert res.returncode != 1, res.stdout


def test_a_polish_sign_off_is_not_a_lost_rule(tmp_path):
    """`niejasne` is the Polish bank's word and both banks are on by default."""
    before = ("# Status\n\nMigracja jest gotowa. Dziewięć z jedenastu repo "
              "działa na nowym runnerze.\n\nJeśli coś jest niejasne, dajcie "
              "znać.\n")
    after = ("# Status\n\nMigracja jest gotowa. Dziewięć z jedenastu repo "
             "działa na nowym runnerze.\n")

    o, n = _pair(tmp_path, before, after)
    res = run_tool("verify", o, n)

    assert "RULES LOST" not in res.stdout, res.stdout
    assert res.returncode != 1, res.stdout


def test_a_rule_between_the_word_and_the_invitation_keeps_its_score(tmp_path):
    """The gap is what tells the two apart when the word comes first."""
    before = ("# Deploys\n\nThe runner deploys on merge.\n\nIf ownership is "
              "unclear, stop deployment and let me know.\n")
    after = "# Deploys\n\nThe runner deploys on merge.\n"

    o, n = _pair(tmp_path, before, after)
    res = run_tool("verify", o, n)

    assert res.returncode == 1, res.stdout
    assert "RULES LOST" in res.stdout, res.stdout




def test_genre_checklist_is_not_asked_for_a_summary(tmp_path):
    """A checklist owes no opening summary: the list IS the summary."""
    doc = tmp_path / "tasks.md"
    doc.write_text(
        "# Release checklist\n\n"
        + "".join(
            f"- [ ] step {i}: check the reading on the host and record the "
            f"exit code beside it in the ledger row\n"
            for i in range(1, 71)
        ),
        encoding="utf-8",
    )

    out = run_tool("plan", doc).stdout
    assert "profile genre-checklist" in out, out[:400]
    assert "opening summary:" not in out, out[:800]


def _lede_doc(title_then, lede, sections=6, rows=8):
    """A document whose lede is `lede`, optionally under a heading."""
    body = "".join(
        f"\n## Section {i}\n\n"
        + "".join(
            f"The resolver consults stage {i} step {j} and records the outcome "
            f"with its duration, so a later reader can reconstruct which "
            f"branch was taken and why the answer took as long as it did.\n"
            for j in range(1, rows + 1)
        )
        for i in range(1, sections + 1)
    )
    return f"# Gateway resolution notes\n\n{title_then}{lede}\n{body}"


def test_giving_the_lede_a_heading_does_not_flip_the_verdict(tmp_path):
    """The escape hatch for legitimate opening prose is keyed on the prose
    being UNLABELLED, so any document that answers UNHEADED's question loses it.
    """
    lede = (
        "This document records how the gateway resolves a request, which "
        "services it consults in order, and what each failure mode looks like "
        "from the caller's side so an operator can tell them apart without "
        "reading the code. It is scope and not summary: every stage below is "
        "described where it runs, and nothing here restates a result."
    )
    bare = tmp_path / "bare.md"
    headed = tmp_path / "headed.md"
    bare.write_text(_lede_doc("", lede), encoding="utf-8")
    headed.write_text(_lede_doc("## Scope\n\n", lede), encoding="utf-8")

    a = run_tool("plan", bare).stdout
    b = run_tool("plan", headed).stdout

    assert "read as prose" in a and "read as prose" in b, (a[:200], b[:200])
    assert "opening summary: UNHEADED" in a, a[:600]
    assert "opening summary: MISSING" not in b, b[:600]


def test_a_summary_heading_over_the_lede_passes(tmp_path):
    """The control for the test above: not every heading loses the lede."""
    lede = (
        "This document records how the gateway resolves a request, which "
        "services it consults in order, and what each failure mode looks like "
        "from the caller's side so an operator can tell them apart without "
        "reading the code. It is scope and not summary: every stage below is "
        "described where it runs, and nothing here restates a result."
    )
    doc = tmp_path / "summary.md"
    doc.write_text(_lede_doc("## Summary\n\n", lede), encoding="utf-8")

    out = run_tool("plan", doc).stdout
    assert "opening summary: 'Summary' at line 3" in out, out[:600]
    assert "opening summary: MISSING" not in out, out[:600]
