"""One-word swaps that
change a factual claim pass every gate as "read these" -- `is -> has` in a
sentence naming a line, `load-bearing -> critical` -- because the tool says
meaning is not checked and none of the existing gates read text for
meaning. Every token count and inventory item (numbers, paths, tickets,
links) survives a swap like this, so nothing else here can catch it.
"""

from __future__ import annotations

import argparse
import contextlib
import io

from conftest import REPO
import sys

sys.path.insert(0, str(REPO / "bin"))

FILLER = ("The report reviewed the window and recorded what it found in "
          "the log so a later reader can check the numbers against the "
          "run that made them. ")

ORIGINAL = ("# Report\n\nThe working rules section is load-bearing: it is "
            "the one place operators check before a rollback. " + FILLER * 6
            + "\n")


def _verify(kv, tmp_path, edited, original=ORIGINAL):
    o = tmp_path / "o.md"
    n = tmp_path / "n.md"
    o.write_text(original)
    n.write_text(edited)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kv.cmd_verify(argparse.Namespace(
            original=str(o), edited=str(n), chat=False,
            content_edit=False, exempt=[]))
    return rc, buf.getvalue()


def test_a_never_swap_word_lost_fails_hard(kv, monkeypatch, tmp_path):
    monkeypatch.setitem(kv.VOCAB, "never_swap", ["load-bearing"])
    swapped = ORIGINAL.replace("load-bearing", "critical")
    rc, out = _verify(kv, tmp_path, swapped)
    assert "NEVER-SWAP WORD LOST" in out, out
    assert "'load-bearing': 1 -> 0" in out, out
    assert rc == 1, (rc, out)


def test_a_word_that_only_moves_is_not_flagged(kv, monkeypatch, tmp_path):
    monkeypatch.setitem(kv.VOCAB, "never_swap", ["load-bearing"])
    moved = ORIGINAL.replace(
        "The working rules section is load-bearing: it is the one place "
        "operators check before a rollback. ",
        "The working rules section matters: it is the one place operators "
        "check before a rollback. It is load-bearing. ")
    rc, out = _verify(kv, tmp_path, moved)
    assert "NEVER-SWAP WORD LOST" not in out, out


def test_the_control_an_unrelated_edit_does_not_fire(kv, monkeypatch, tmp_path):
    monkeypatch.setitem(kv.VOCAB, "never_swap", ["load-bearing"])
    rc, out = _verify(kv, tmp_path, ORIGINAL)
    assert "NEVER-SWAP WORD LOST" not in out, out


def test_an_empty_never_swap_list_is_a_no_op(kv, tmp_path):
    swapped = ORIGINAL.replace("load-bearing", "critical")
    rc, out = _verify(kv, tmp_path, swapped)
    assert "NEVER-SWAP WORD LOST" not in out, out
