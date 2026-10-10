"""What `plan` says about the lines no shape fired on, on a chat message."""

from __future__ import annotations

import sys

from conftest import REPO, run_tool

sys.path.insert(0, str(REPO / "bin"))

NOISY = ("It is worth noting that we should consider whether the retry "
         "budget is correct going forward.\n\n") * 2
PLAIN = ("The queue reads each file once and writes the row to Loki. "
         "It retries twice on a timeout and then gives up.\n\n") * 4


def _quiet_line(out):
    lines = out.splitlines()
    at = next(i for i, ln in enumerate(lines) if "found nothing" in ln)
    return lines[at + 1]


def test_a_chat_run_does_not_claim_the_lines_reach_nobody(doc):
    """`chat` is given every line of the message, so they are read."""
    got = _quiet_line(run_tool("plan", doc(NOISY + PLAIN), "--chat").stdout)

    assert "no section specialist was given those lines" in got, got
    assert "come back unchanged" not in got, got


def test_a_document_run_says_who_gets_them_and_what_they_do(doc):
    """"Sent to no specialist" was never true in either mode: `summary` and
    `structure` are document-scope too. What is true is that neither rewords a
    paragraph, which is why `run` leaves them out of its coverage sum."""
    got = _quiet_line(run_tool("plan", doc(NOISY + PLAIN)).stdout)

    assert "no section specialist was given those lines" in got, got
    assert "neither rewords a paragraph" in got, got


def test_chat_is_document_scope(kv):
    """The whole reason the two modes differ. If `chat` ever became
    section-scope the chat wording above would be the wrong one."""
    assert kv.SPECIALISTS["chat"][0] == "document"
    assert "chat" not in kv.DOC_ONLY
