"""In an 85-job run, decision 4 of a plan document lost its numbered heading and question; the
appendix runs 3, unnumbered prose, 5, and no structure check fired (RULES
LOST only caught it by accident -- six sentences inside item 4 happened to
match a rule pattern).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys

from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))

FILLER = "Some detail about this decision that a reader would want to see. "


def _list_doc(items):
    body = ["# Rollout plan", "", "## Decisions", ""]
    for n, text in items:
        if n is None:
            body.append(text)
        else:
            body.append(f"{n}. {text}")
        body.append("")
    return "\n".join(body) + "\n"


ORIGINAL_ITEMS = [(i, f"Decision {i}. {FILLER}") for i in range(1, 7)]
ORIGINAL = _list_doc(ORIGINAL_ITEMS)

BROKEN_ITEMS = [(i, f"Decision {i}. {FILLER}") for i in (1, 2, 3)] \
    + [(None, f"This decision no longer carries a number. {FILLER}")] \
    + [(i, f"Decision {i}. {FILLER}") for i in (5, 6)]
BROKEN = _list_doc(BROKEN_ITEMS)


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


def test_a_demoted_middle_item_fails_verify(kv, tmp_path):
    rc, out = _verify(kv, tmp_path, BROKEN)
    assert "ORDERED LIST BROKEN" in out, out
    assert "missing 4" in out, out
    assert rc == 1, (rc, out)


def test_the_control_a_clean_rewording_does_not_fire(kv, tmp_path):
    reworded = _list_doc([(i, f"Item {i} was reworded but kept its number. "
                          + FILLER) for i in range(1, 7)])
    rc, out = _verify(kv, tmp_path, reworded)
    assert "ORDERED LIST BROKEN" not in out, out


def test_a_short_list_under_the_threshold_is_not_checked(kv):
    prose = ["1. First.", "2. Second."]
    assert kv.ordered_runs(prose) == []


def test_ordered_runs_survives_a_prose_paragraph_between_markers(kv):
    prose = ["1. First.", "2. Second.", "3. Third.",
             "Unrelated commentary paragraph here.",
             "5. Fifth.", "6. Sixth.", "7. Seventh."]
    runs = kv.ordered_runs(prose)
    assert runs == [(1, 2, 3), (5, 6, 7)], runs
