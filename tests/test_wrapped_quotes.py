"""A hard-wrapped sentence is quoted whole, not as its first line."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from killverbosity import unmask

from conftest import run_tool


RULE = ("Never run the importer against the production warehouse without a\n"
        "snapshot, and never do it during the nightly window when the ETL job\n"
        "is holding the table lock.")

WHOLE = " ".join(RULE.split())


def _pair(tmp_path, was, now):
    a, b = tmp_path / "was.md", tmp_path / "now.md"
    a.write_text(was)
    b.write_text(now)
    return a, b


def test_a_wrapped_rule_is_quoted_to_the_end(tmp_path):
    o, n = _pair(tmp_path,
                 f"# Notes\n\n{RULE}\n\nThe queue is drained in order.\n",
                 "# Notes\n\nThe queue is drained in order.\n")

    r = run_tool("verify", "--full", o, n)

    assert r.returncode == 1, r.stdout
    assert WHOLE in r.stdout, r.stdout


def test_without_full_the_quote_says_it_was_cut(tmp_path):
    o, n = _pair(tmp_path,
                 f"# Notes\n\n{RULE}\n\nThe queue is drained in order.\n",
                 "# Notes\n\nThe queue is drained in order.\n")

    r = run_tool("verify", o, n)

    assert "…" in r.stdout, r.stdout
    assert "nightly…" in r.stdout or "the…" in r.stdout, r.stdout
    assert "nightl…" not in r.stdout, r.stdout


def test_a_code_span_in_a_wrapped_rule_is_printed_not_blanked(tmp_path):
    rule = ("Never run `bin/importer --force` against the production\n"
            "warehouse without a snapshot of the audit table.")
    o, n = _pair(tmp_path,
                 f"# Notes\n\n{rule}\n\nThe queue is drained in order.\n",
                 "# Notes\n\nThe queue is drained in order.\n")

    r = run_tool("verify", "--full", o, n)

    assert "`bin/importer --force`" in r.stdout, r.stdout


def test_joined_falls_back_to_the_whole_span_when_the_offset_is_lost():
    """A masked line whose width the strip changed cannot be offset into."""
    src = ["  `code` and the rest", "of the sentence here"]
    masked = ["         and the rest", "of the sentence here"]

    got = unmask.joined(src, masked, 1, 2, "no such text")

    assert got == "`code` and the rest of the sentence here"


def test_joined_reads_one_sentence_out_of_a_line_holding_two():
    src = ["First one here. Second one runs on", "to the next line."]
    masked = list(src)

    got = unmask.joined(src, masked, 1, 2,
                        "Second one runs on to the next line.")

    assert got == "Second one runs on to the next line."


def test_joined_stops_at_the_end_of_the_file():
    src = ["only line"]
    masked = list(src)

    assert unmask.joined(src, masked, 1, 9, "only line") == "only line"


def test_joined_refuses_a_line_number_outside_the_file():
    src = ["only line"]

    assert unmask.joined(src, list(src), 0, 1, "s") == "s"
    assert unmask.joined(src, list(src), 5, 6, "s") == "s"


def test_joined_finds_a_sentence_carrying_an_html_comment():
    """`sentence_spans` strips the comment, so only the head is a substring."""
    src = ["Never run this <!-- kv:allow -->against production without a",
           "snapshot of the audit table taken first."]
    masked = list(src)

    got = unmask.joined(src, masked, 1, 2,
                        "Never run this against production without a "
                        "snapshot of the audit table taken first.")

    assert got.startswith("Never run this <!-- kv:allow -->against"), got
    assert got.endswith("first."), got


def test_two_sentences_masking_alike_do_not_get_a_guessed_span(tmp_path):
    """"Read `foo`. Read `bar`." blanks to one text twice. Neither is invented."""
    o, n = _pair(
        tmp_path,
        "# Notes\n\nRead `foo`. Read `bar`.\n\nNever drop the audit table\n"
        "without a snapshot taken first.\n",
        "# Notes\n\nRead `foo`. Read `bar`.\n",
    )

    r = run_tool("verify", "--full", o, n)

    assert r.returncode == 1, r.stdout
    assert "Never drop the audit table without a snapshot taken first." \
        in r.stdout, r.stdout
