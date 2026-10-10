"""The summary pointer check grades what the RUN wrote, not what the file holds."""

from __future__ import annotations

import argparse
import contextlib
import io

FILLER = ("The team reviewed the window and recorded what it found in the log "
          "so a later reader can check the numbers against the run that made "
          "them and decide whether the window was the right one to pick. ")

SECTIONS = ((8, "What to change, and why"),
            (15, "The window, and who owns it"),
            (3, "Where the numbers came from"))

ASIDE = ("The team looked at both candidates (Where the numbers came from, and "
         "where they did not) before deciding, and the log carries the run "
         "that settled it. ")

POINTERS = ("The run cut the report and left two decisions open: "
            "(8. What to change, and why) needs a call, and "
            "(15. The window, and who owns it) needs an owner.")


def _body():
    out = []
    for n, title in SECTIONS:
        out += [f"## {n}. {title}\n", FILLER * 14, ""]
    return out


def _original(lede):
    """Title, then unheaded opening prose, then the sections."""
    return "\n".join(["# The window report\n", lede, ""] + _body()) + "\n"


def _edited(lede, summary):
    """The same file with a `## Summary` inserted ABOVE the opening prose."""
    return "\n".join(["# The window report\n", "## Summary\n", summary, "",
                      lede, ""] + _body()) + "\n"


def _verify(kv, tmp_path, original, edited):
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


def test_prose_the_run_did_not_write_is_not_graded_as_its_pointer(kv, tmp_path):
    """The reported failure, through the real command."""
    rc, out = _verify(kv, tmp_path,
                      _original(ASIDE + FILLER * 3),
                      _edited(ASIDE + FILLER * 3, POINTERS))
    assert "SUMMARY POINTERS BROKEN" not in out, out
    assert rc != 1, (rc, out)


def test_the_split_half_is_reported_and_attributed(kv, tmp_path):
    """Reported, not silenced — and said to be the file's and not the run's."""
    _rc, out = _verify(kv, tmp_path,
                       _original(ASIDE + FILLER * 3),
                       _edited(ASIDE + FILLER * 3, POINTERS))
    assert "and where they did not" in out, out
    assert "already in the file, not this run's" in out, out


def test_the_control_the_same_aside_inside_the_written_summary_still_fails(
        kv, tmp_path):
    """The gate, on the input it exists for."""
    rc, out = _verify(kv, tmp_path,
                      _original(FILLER * 4),
                      _edited(FILLER * 4, POINTERS + " " + ASIDE))
    assert "SUMMARY POINTERS BROKEN" in out, out
    assert "and where they did not" in out, out
    assert rc == 1, (rc, out)


def test_the_control_a_pointer_the_run_wrote_at_a_missing_section(kv, tmp_path):
    """The ordinary case the check was built for, still caught."""
    rc, out = _verify(kv, tmp_path,
                      _original(FILLER * 4),
                      _edited(FILLER * 4,
                              POINTERS + " See (Where nobody wrote anything "
                              "up) for the rest."))
    assert "SUMMARY POINTERS BROKEN" in out, out
    assert "Where nobody wrote anything up" in out, out
    assert rc == 1, (rc, out)



def _delivery_section() -> str:
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "specialists/summary.md").read_text()
    return src.split("## How to deliver it", 1)[1]


def test_the_unheaded_rule_leads_the_delivery_section():
    """ORDER, not presence."""
    body = _delivery_section()
    lede_rule = body.find("unheaded prose")
    insert_rule = body.find("insert one immediately")
    assert lede_rule != -1, body
    assert insert_rule != -1, body
    assert lede_rule < insert_rule, body


def test_the_insert_rule_names_the_condition_it_is_now_narrowed_to():
    """The control for the ordering test."""
    body = _delivery_section()
    at = body.find("insert one immediately")
    assert "no unheaded opening" in body[:at], body[:at]
