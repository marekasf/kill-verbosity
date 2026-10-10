"""One test per entry in `docs/known-issues.md`."""
import pytest

from conftest import run_tool


def _pair(tmp_path, before, after):
    o = tmp_path / "o.md"
    n = tmp_path / "n.md"
    o.write_text(before)
    n.write_text(after)
    return o, n



SWAP_BEFORE = """# Worker rules

## Retry policy

The worker must retry a failed upload three times before it gives up.

## Compaction

Nightly compaction runs at 02:00 and never during business hours.
"""

SWAP_AFTER = """# Worker rules

## Retry policy

Nightly compaction runs at 02:00 and never during business hours.

## Compaction

The worker must retry a failed upload three times before it gives up.
"""


def test_a_rule_that_changed_section_makes_the_run_review(tmp_path):
    """Fixed. "…is reported and the edit still lands." """
    o, n = _pair(tmp_path, SWAP_BEFORE, SWAP_AFTER)

    res = run_tool("verify", o, n)

    assert "rules that changed section" in res.stdout, res.stdout
    assert res.returncode == 3, (res.returncode, res.stdout)


def test_deleting_a_section_does_not_report_its_rules_as_moved(tmp_path):
    """The boundary the fix above must stay quiet on."""
    o, n = _pair(
        tmp_path,
        "# Doc\n\n## Retry policy\n\nThe worker retries a failed upload three "
        "times.\n\n## Compaction\n\nCompaction runs nightly.\n",
        "# Doc\n\n## Compaction\n\nThe worker retries a failed upload three "
        "times.\n\nCompaction runs nightly.\n",
    )

    res = run_tool("verify", o, n)

    assert "rules that changed section" not in res.stdout, res.stdout
    assert "headings gone" in res.stdout, res.stdout


SPLICE_BEFORE = """# Worker rules

The worker must retry a failed upload three times before it gives up.

The upload timeout is 30 seconds and the compaction timeout is 90 seconds.

The team reviews every incident report before the weekly meeting.
"""

SPLICE_AFTER = SPLICE_BEFORE.replace(
    "The team reviews every incident report before the weekly meeting.",
    "The team reviews every incident before it gives up.")


def test_a_splice_grafted_from_a_distant_sentence_is_caught(tmp_path):
    """Fixed. "A splice that repeats nothing at the break can pass `verify`." """
    o, n = _pair(tmp_path, SPLICE_BEFORE, SPLICE_AFTER)

    res = run_tool("verify", o, n)

    assert "before it gives up" in res.stdout, res.stdout
    assert res.returncode == 3, (res.returncode, res.stdout)


def test_rewording_a_sentence_the_file_already_repeated_is_not_a_splice(tmp_path):
    """The boundary the fix above must stay quiet on."""
    body = ("The pipeline retries the failed job and records the outcome in "
            "Loki.\n\nSome unrelated line sits here.\n\n")
    o, n = _pair(tmp_path, "# Doc\n\n" + body * 3,
                 ("# Doc\n\n" + body * 3).replace("Loki", "the log store"))

    res = run_tool("verify", o, n)

    assert "text the edit repeated" not in res.stdout, res.stdout


def test_a_repeat_hidden_behind_a_code_span_is_not_a_splice(tmp_path):
    """The other boundary. Two lines that differ only inside a code span."""
    same = "Some unrelated line sits here.\n\n"
    o, n = _pair(
        tmp_path,
        "# Doc\n\n" + same * 4,
        "# Doc\n\nRead `sl-python` skill for lint rules.\n\n" + same * 2
        + "Read `sl-node` skill for lint rules.\n\n" + same,
    )

    res = run_tool("verify", o, n)

    assert "text the edit repeated" not in res.stdout, res.stdout


def test_an_excerpt_runs_past_an_abbreviation(tmp_path):
    """"A shape excerpt stops short on a sentence ending in `e.g.`." Fixed."""
    doc = tmp_path / "d.md"
    doc.write_text("# Handbook\n\nIt is worth noting that we ship daily, "
                   "e.g. on Fridays, without a freeze.\n")

    res = run_tool("plan", doc)

    row = next(l for l in res.stdout.splitlines() if "worth noting" in l)
    assert not row.rstrip().endswith("e.g."), row




def test_a_section_renamed_and_rewritten_is_reported_gone(tmp_path):
    """Pinned. "A section renamed and rewritten in one run can be reported gone." """
    o, n = _pair(
        tmp_path,
        "# Doc\n\n## Retry policy\n\nThe worker retries a failed upload three "
        "times.\n\n## Compaction\n\nCompaction runs nightly.\n",
        "# Doc\n\n## Upload behaviour\n\nEvery send is attempted three times "
        "against the queue.\n\n## Compaction\n\nCompaction runs nightly.\n",
    )

    res = run_tool("verify", o, n)

    assert "headings gone" in res.stdout, res.stdout
    assert "Retry policy" in res.stdout, res.stdout


def test_two_identical_sentences_print_the_same_excerpt(tmp_path):
    """Pinned. "Two hits can still print the same excerpt." """
    doc = tmp_path / "d.md"
    doc.write_text("# Handbook\n\nIt is worth noting that the budget is "
                   "shared.\n\nSome other text sits here.\n\nIt is worth "
                   "noting that the budget is shared.\n")

    res = run_tool("plan", doc)

    rows = [l for l in res.stdout.splitlines()
            if "worth noting" in l and "frame" in l]
    assert len(rows) == 2, res.stdout
    assert rows[0].split("frame")[1] == rows[1].split("frame")[1], rows
    assert rows[0].split()[0] != rows[1].split()[0], rows
