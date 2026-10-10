"""R3's second half: the run record carries BOTH line numbers."""

from __future__ import annotations

import pytest


def test_the_output_line_is_found_after_a_rewrap_shifted_it(kv):
    """The whole point: the merge line and the output line DIFFER."""
    merged = ["# Doc", "", "first para.", "", "the reworded line is here.", ""]
    assert kv.output_line(merged, "the reworded line is here.") == 5
    wrapped = ["# Doc", "", "- the reworded", "  line is", "  here.", ""]
    assert kv.output_line(wrapped, "- the reworded line is here.") == 3


def test_not_found_is_none_and_never_the_nearest_guess(kv):
    """A later specialist can reword the same line again."""
    assert kv.output_line(["# Doc", "", "something else."],
                          "the reworded line is here.") is None
    assert kv.output_line(["# Doc"], "") is None


def test_an_ambiguous_match_is_none_rather_than_the_first(kv):
    """`find` would hand back the first occurrence with no way to say so."""
    twice = ["the same sentence.", "", "the same sentence."]
    assert kv.output_line(twice, "the same sentence.") is None
    once = ["the same sentence.", "", "a different one."]
    assert kv.output_line(once, "the same sentence.") == 1


def test_the_field_is_absent_when_there_was_no_output_to_look_in(kv):
    """ABSENT and `None` are different answers and both are needed."""
    applied = [(3, "prose", "replace",
                ("the parser is open", "the parser is shut"))]
    blind = kv.word_swaps(applied)
    assert blind and "line_out" not in blind[0], blind
    seeing = kv.word_swaps(applied, ["", "", "the parser is shut"])
    assert seeing and seeing[0]["line_out"] == 3, seeing
    missing = kv.word_swaps(applied, ["", "", "something else entirely"])
    assert missing and missing[0]["line_out"] is None, missing


def test_the_report_prints_both_only_when_they_differ(kv, tmp_path,
                                                     monkeypatch, capsys):
    """Driven through the REAL `verify`, with a hand-written run record."""
    import json
    orig = tmp_path / "doc.md"
    out = tmp_path / "doc.kv.md"
    orig.write_text("# Doc\n\nthe parser stays open.\n")
    out.write_text("# Doc\n\nthe parser is open.\n")
    rec = kv.run_record_path(out)
    rec.write_text(json.dumps({
        "agent": "codex", "no_agents": False, "chat": False,
        "inserted": False, "summary_added": False, "exempt": [],
        "incomplete": [], "refused_summary": None,
        "source": kv.source_fingerprint(orig.read_text()),
        "swaps": [
            {"line": 3, "line_out": 7, "by": "prose",
             "was": "stays", "now": "is", "in": "the parser is open."},
            {"line": 9, "line_out": 9, "by": "noise",
             "was": "very", "now": "quite", "in": "a short line"},
        ]}))
    monkeypatch.setattr("sys.argv",
                        ["kill-verbosity", "verify", str(orig), str(out)])
    try:
        kv.main()
    except SystemExit:
        pass
    said = capsys.readouterr()
    text = said.out + said.err
    assert "2 words replaced" in text, (
        "EMPTY: the swap block never printed, so nothing below is about the "
        f"format -- {text[-500:]!r}")
    assert "line 3->7" in text, text
    assert "~line 9" in text, text
    assert "9->9" not in text, text


def test_the_record_a_REAL_RUN_writes_carries_the_output_line(kv, tmp_path,
                                                             monkeypatch):
    """End to end into the `.kvrun`, because the record SITE was unheld."""
    import json
    import sys
    _tails = ["on call", "asleep", "paged", "off shift", "on the rota",
              "in the office", "at the console"]
    lines = ["# Queue notes", ""] + [
        f"It should be noted that the worker, in point of fact, retries job "
        f"{i} and records the outcome in the store for the purposes of a "
        f"later inspection by whichever operator happens to be {t}."
        for i, t in enumerate(_tails, 1)]
    src = tmp_path / "doc.md"
    src.write_text("\n".join(lines) + "\n")
    out = tmp_path / "out.md"
    target = lines[2]

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        return json.dumps({"edits": [
            {"op": "replace", "line": 3, "old": target,
             "new": target.replace("inspection", "review")}],
            "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(src), "-o", str(out)])
    try:
        kv.main()
    except SystemExit:
        pass
    rec = kv.run_record_path(out)
    assert rec.exists(), f"EMPTY: no run record was written to {rec}"
    swaps = json.loads(rec.read_text()).get("swaps") or []
    assert swaps, (
        "EMPTY: the run recorded no swap, so nothing below is about the field "
        f"-- record={rec.read_text()[:400]!r}")
    assert all("line_out" in x for x in swaps), swaps
    assert [x["was"] for x in swaps] == ["inspection"], swaps
    assert swaps[0]["line_out"] is not None, swaps
    landed = out.read_text().split("\n")[swaps[0]["line_out"] - 1]
    assert "review" in landed, (swaps[0], landed)
