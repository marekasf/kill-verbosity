"""a run deleted a rule and `verify` filed it under ordinary thinning."""

from __future__ import annotations

import pytest

from conftest import run_tool

pytestmark = pytest.mark.regression

NOTE = ("Note: it is absolutely critical that the first item is completed "
        "prior to the commencement of any of the subsequent activities "
        "described above.")

CHECKLIST = """# Cutover checklist

- [ ] Take a full backup of the old router before anything is touched.
- [x] Verify the eMMC boot sync fired on the last kernel bump.
- [ ] Swap the coexistence addresses to .4/.104 in config.sh.
- [ ] Undo the temporary DHCP failover block at step 6.

""" + NOTE + "\n"


def test_the_note_that_was_lost_now_ranks_as_a_rule(kv):
    score, why = kv.finding_rank(NOTE)
    assert score >= 5, (score, why)
    assert "orders" in why, why


@pytest.mark.parametrize("sentence", [
    "Take the backup before you swap the addresses.",
    "The backup is taken prior to the address swap.",
    "Run the backup first, then swap the addresses.",
])
def test_pure_ordering_sentences_all_reach_the_cut(kv, sentence):
    """Their three measured 0-2 scores. The cut at the print site is 5."""
    score, why = kv.finding_rank(sentence)
    assert score >= 5, (sentence, score, why)


@pytest.mark.parametrize("sentence", [
    "Star the repo if this helps, and thanks for reading.",
    "The table below lists every backend.",
    "It is worth noting that the output is written beside the input.",
])
def test_an_ordinary_sentence_is_not_lifted(kv, sentence):
    """The control. A rule that fires on everything reorders nothing."""
    score, _ = kv.finding_rank(sentence)
    assert score < 5, (sentence, score)


def test_a_dropped_ordering_rule_is_printed_in_the_read_first_list(tmp_path):
    """End to end, on the reported pair: the Note deleted and nothing else."""
    doc, out = tmp_path / "checklist.md", tmp_path / "checklist.kv.md"
    doc.write_text(CHECKLIST)
    out.write_text(CHECKLIST.replace(NOTE + "\n", ""))

    r = run_tool("verify", doc, out)
    text = r.stdout + r.stderr

    assert "content dropped" in text, text
    head = text.split("most worth reading")
    assert len(head) == 2, "the read-first list was not printed:\n" + text
    assert "absolutely critical" in head[1].split("\n\n")[0], text
