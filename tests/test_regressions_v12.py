"""Round-2 findings, from a review."""

import os

import pytest
from conftest import run_canned, run_tool
from killverbosity.runrecord import record_state, run_record_path, write_run_record

pytestmark = pytest.mark.regression

ORIG = """# Notes

It is worth noting that the deploy finished in the end.

The worker retries the job and pages the operator after 30 seconds.
"""

EDITED = """# Notes

The deploy finished.

The worker retries the job and pages the operator after 30 seconds.
"""


def _pair(tmp_path):
    src, out = tmp_path / "a.md", tmp_path / "a.kv.md"
    src.write_text(ORIG)
    out.write_text(EDITED)
    return src, out


def test_accept_refuses_when_the_run_record_is_missing(tmp_path):
    """Deleting the sidecar turned a refusal into exit 0 and an overwrite."""
    src, out = _pair(tmp_path)

    r = run_tool("accept", src, out)

    assert r.returncode == 1, r.stdout + r.stderr
    assert "a.kv.md.kvrun" in r.stderr, r.stderr
    assert src.read_text() == ORIG, "the target was replaced anyway"


def test_accept_refuses_a_record_from_an_earlier_run(tmp_path):
    """A record older than the output describes a different run."""
    src, out = _pair(tmp_path)
    write_run_record(out, agent="codex", incomplete=[])
    p = run_record_path(out)
    os.utime(p, (p.stat().st_atime, out.stat().st_mtime - 60))

    r = run_tool("accept", src, out)

    assert r.returncode == 1, r.stdout + r.stderr
    assert src.read_text() == ORIG, "the target was replaced anyway"


def test_force_still_accepts_without_a_record(tmp_path):
    """The override has to survive the new refusal, or a tester with a good
    output and a lost sidecar has no way through.
    """
    src, out = _pair(tmp_path)

    r = run_tool("accept", src, out, force=True)

    assert r.returncode == 4, r.stdout + r.stderr
    assert src.read_text() == EDITED
    assert "KV_FORCE overruled" in r.stdout, r.stdout
    assert "no run record" in r.stdout, r.stdout


def test_a_clean_record_still_accepts(tmp_path):
    """The guard must not cost every ordinary run its accept."""
    src, out = _pair(tmp_path)
    write_run_record(out, agent="codex", chat=False, inserted=False,
                     incomplete=[], exempt={})

    assert record_state(out) == "ok"
    r = run_tool("accept", src, out)

    assert r.returncode == 0, r.stdout + r.stderr
    assert src.read_text() == EDITED

LONG = "\n".join(
    ["# Platform notes", ""]
    + [f"The worker retries job {i} and records the outcome in Loki. "
       f"The retry budget is {i * 3} seconds and the operator is paged "
       f"after it. " for i in range(1, 14)]
)


def test_a_baseline_is_not_given_a_second_baseline(kv, monkeypatch, tmp_path):
    """Running on `design-v2.orig.md` wrote `design-v2.orig.orig.md`."""
    src = tmp_path / "design-v2.orig.md"
    src.write_text(LONG + "\n")

    run_canned(kv, monkeypatch, src, tmp_path / "out.md", lambda *_: [])

    assert not (tmp_path / "design-v2.orig.orig.md").exists(), \
        sorted(p.name for p in tmp_path.iterdir())
    assert src.read_text() == LONG + "\n", "the input was used as scratch"


def test_an_ordinary_file_still_gets_a_baseline(kv, monkeypatch, tmp_path):
    """The guard above must not cost every other file its untouched copy."""
    src = tmp_path / "design-v2.md"
    src.write_text(LONG + "\n")

    run_canned(kv, monkeypatch, src, tmp_path / "out.md", lambda *_: [])

    assert (tmp_path / "out.orig.md").read_text() == LONG + "\n"


WRAPPED = """# Notes

The worker retries the job and pages the operator after thirty
seconds, and the retry budget is counted per job rather than
per batch across the whole queue in every region we run.

| job | budget |
| --- | ------ |
| a   | 30s    |

The second paragraph is also hard-wrapped at the same margin
so that the file reads as a wrapped file rather than as a
list of short standalone entries that happen to be brief
when somebody writes them out one after another like this.

A third paragraph keeps the count of prose lines above the
threshold the width detector needs before it will call a
file wrapped, which is ten lines of prose with most of them
sitting within twelve characters of the longest one.

The fourth paragraph exists only so that the folding has
more than one candidate to work on and the span map has
something to prove itself against in the test below.
"""


def _fold(kv, text):
    from killverbosity.wrapping import unwrap_source
    return unwrap_source(text.split("\n"), kv.mask)


def test_a_wrapped_paragraph_becomes_one_line(kv):
    """The fragment merge is why four testers got broken English."""
    out, spans = _fold(kv, WRAPPED)

    para = [(t, s) for t, s in zip(out, spans) if t.startswith("The worker")]
    assert len(para) == 1, out
    text, (first, last) = para[0]
    assert "thirty seconds" in text, text
    assert last - first == 2, f"folded {last - first + 1} lines, wanted 3"


def test_folding_leaves_the_table_alone(kv):
    """A row is one line, so a folded row would wrap across three and the
    table would lose its shape. Same cause as the paragraph damage."""
    out, _spans = _fold(kv, WRAPPED)

    rows = [t for t in out if t.startswith("| job") or t.startswith("| a")]
    assert rows == ["| job | budget |", "| a   | 30s    |"], out


def test_an_unwrapped_file_is_not_folded(kv):
    """Its paragraphs are already one line each. Folding would join short
    entries that were meant to stand apart."""
    text = "# Notes\n\n" + "\n".join(f"- entry {i}" for i in range(20)) + "\n"

    out, spans = _fold(kv, text)

    assert out == text.split("\n")
    assert spans == [(i, i) for i in range(len(out))]


def test_a_rewritten_paragraph_leaves_no_fragment_behind(kv, monkeypatch,
                                                         tmp_path):
    """The whole cluster, end to end through the real pipeline."""
    src, out = tmp_path / "w.md", tmp_path / "w.kv.md"
    src.write_text(WRAPPED)
    new = "The worker retries and pages the operator after thirty seconds."

    folded, _spans = _fold(kv, WRAPPED)
    ln, old = next((i + 1, t) for i, t in enumerate(folded)
                   if t.startswith("The worker retries"))

    def reply(who, lo, hi):
        if who != "prose" or not lo <= ln <= (hi if hi else ln):
            return []
        return [{"line": ln, "old": old, "new": new}]

    run_canned(kv, monkeypatch, src, out, reply)
    got = out.read_text()

    assert new.split(" after ")[0] in got, got
    assert "seconds, and the retry budget" not in got, got
    assert "per batch across the whole queue" not in got, got


def test_the_output_keeps_the_original_margin(kv, monkeypatch, tmp_path):
    """Folding is for the run only. A wrapped file must come back wrapped, or
    every accepted run puts one 300-character line into the diff."""
    src, out = tmp_path / "w.md", tmp_path / "w.kv.md"
    src.write_text(WRAPPED)

    run_canned(kv, monkeypatch, src, out, lambda *_: [])
    longest = max(len(l) for l in out.read_text().split("\n"))

    assert longest <= 100, f"longest line {longest}, the file wraps near 62"


NOSUM = "\n".join(
    ["# Platform notes", "", "## Service Overview", ""]
    + [f"The worker retries job {i} and records the outcome in Loki, and the "
       f"retry budget is {i * 3} seconds before the operator is paged.\n"
       for i in range(1, 40)])


def test_the_gate_and_verdict_agree_about_the_opening(kv, monkeypatch,
                                                      tmp_path):
    """Ten of the eighteen round-2 findings, and two guards refusing each other."""
    src, out = tmp_path / "d.md", tmp_path / "d.kv.md"
    src.write_text(NOSUM)

    def reply(who, lo, hi):
        if who == "structure":
            return [{"line": 3, "old": "## Service Overview",
                     "new": "## Overview", "why": "shorter"}]
        if who == "summary":
            return [{"op": "insert", "line": 2,
                     "new": "## Summary\n\nThe worker retries every job and "
                            "pages the operator when the budget runs out.\n"}]
        return []

    seen = run_canned(kv, monkeypatch, src, out, reply)
    got = out.read_text()

    assert {"structure", "summary"} <= {who for who, _unit in seen}, seen

    heads = [l for l in got.split("\n") if l.startswith("#")]
    sums = [h for h in heads
            if kv.SUMMARY_HEADING.match(h.lstrip("# ").strip())]
    assert len(sums) == 1, heads
    assert "## Service Overview" in got, "the refused rename was applied"

    prose, hs, _t, _q = kv.mask(got)
    verdict = kv.opening_summary(hs, prose, kv.word_count(got))
    assert verdict and verdict["present"], verdict


def test_the_gate_reads_the_file_not_the_caller(kv):
    """`merge` took `summary_line` on trust and ran its own heading walk."""
    from killverbosity.summary import Rules, opens_with_summary

    rules = Rules(heading=kv.SUMMARY_HEADING,
                  needed_from=kv.SUMMARY_NEEDED_FROM,
                  min_words=kv.SUMMARY_MIN_WORDS, cap=kv.summary_cap)
    text = "# Review call\n\n## Summary of decisions\n\nIt ships.\n"
    prose, heads, _t, _q = kv.mask(text)

    assert kv.opening_summary(heads, prose, kv.word_count(text)) is None
    assert opens_with_summary(heads, prose, kv.word_count(text), rules) == 3


def test_a_reported_line_is_the_line_the_author_wrote(kv, monkeypatch,
                                                      tmp_path, capsys):
    """The debt the fold took on. Folding gives a specialist whole paragraphs,
    so the numbers it answers with count paragraphs, not lines. A refusal then
    names a line the reader cannot find, and the further down the file the
    worse it gets.
    """
    src, out = tmp_path / "w.md", tmp_path / "w.kv.md"
    src.write_text(WRAPPED)
    folded, spans = _fold(kv, WRAPPED)

    ln = max(i for i, t in enumerate(folded) if t.startswith("The fourth")) + 1
    first, last = spans[ln - 1]
    want = f"L{first + 1}-{last + 1}"
    assert first + 1 != ln, "fixture too small to tell the two numberings apart"

    def reply(who, lo, hi):
        if who != "prose" or not lo <= ln <= (hi if hi else ln):
            return []
        return [{"line": ln, "old": folded[ln - 1],
                 "new": "It is worth noting that the fourth paragraph exists."}]

    run_canned(kv, monkeypatch, src, out, reply)
    printed = capsys.readouterr()
    report = printed.out + printed.err

    assert "refused (1)" in report, f"the edit was not refused\n{report}"
    assert f"{want}  " in report, \
        f"wanted {want}, folded line was L{ln}\n{report}"
    assert f"L{ln}  " not in report, f"folded line L{ln} reached the report"


def test_the_map_is_the_identity_on_an_unwrapped_file(kv):
    """A file that does not fold must not have its numbers moved."""
    from killverbosity.wrapping import source_span

    text = "# Notes\n\n" + "\n".join(f"- entry {i}" for i in range(20)) + "\n"
    _out, spans = _fold(kv, text)

    assert [source_span(i, i, spans) for i in (1, 5, 20)] == \
        [(1, 1), (5, 5), (20, 20)]


def test_a_line_past_the_end_is_clamped_not_raised(kv):
    """A specialist can answer with a line outside its span. A wrong number in
    one refusal must not take the whole report down."""
    from killverbosity.wrapping import source_span

    _out, spans = _fold(kv, WRAPPED)

    assert source_span(0, 0, spans) == source_span(1, 1, spans)
    assert source_span(9999, 9999, spans) == \
        source_span(len(spans), len(spans), spans)


def test_every_source_line_is_accounted_for(kv):
    """The spans are what maps a reported line number back to the file. A gap
    or an overlap in them is a wrong line number in the report."""
    src = WRAPPED.split("\n")
    _out, spans = _fold(kv, WRAPPED)

    covered = [i for first, last in spans for i in range(first, last + 1)]
    assert covered == list(range(len(src))), covered


def test_an_exhausted_budget_stops_the_run_and_a_rerun_finishes_it(
        kv, monkeypatch, tmp_path, capsys):
    """T5. `--timeout` is the budget for the run, not for one call."""
    src, out = tmp_path / "d.md", tmp_path / "d.kv.md"
    src.write_text(NOSUM)

    now = [0.0]
    real = kv.budget.Budget
    monkeypatch.setattr(kv.budget, "Budget",
                        lambda total: real(total, clock=lambda: now[0]))

    sent = []

    def reply(who, lo, hi):
        sent.append((who, lo, hi))
        now[0] += 10.0
        return []

    queued = list(run_canned(kv, monkeypatch, src, out, reply,
                             extra=["--timeout", "25"]))
    first = list(sent)
    stopped = "".join(capsys.readouterr())

    assert len(queued) > len(first), (
        f"the budget never ran out: {len(queued)} jobs, all sent")
    assert "budget ran out" in stopped, stopped
    journal = kv.journal_path(out)
    assert journal.exists(), "the finished answers were not kept"

    sent.clear()
    run_canned(kv, monkeypatch, src, out, reply, extra=["--timeout", "9000"])
    again = list(sent)
    resumed = "".join(capsys.readouterr())

    assert f"resuming: {len(first)} answer" in resumed, resumed
    assert len(again) == len(queued) - len(first), (
        f"{len(first)} sent, then {len(again)}, of {len(queued)} jobs")
    assert not journal.exists(), "the journal outlived the run that finished"


MOVEDOC = "\n".join(
    ["# Platform notes", "", "## Overview", "",
     "The worker retries each job and pages the operator.", ""]
    + [f"The retry budget is {i * 3} seconds on job {i}.\n" for i in range(1, 30)]
    + ["## What to send back", "", "Send the diff and the run record.", ""])
MOVED_FROM = next(i for i, l in enumerate(MOVEDOC.split("\n"), 1)
                  if l.startswith("## What"))


def _heads(text):
    return [l for l in text.split("\n") if l.startswith("#")]


def test_a_described_move_is_made_or_listed(kv, monkeypatch, tmp_path, capsys):
    """T6. `structure` wrote the move it wanted as English and moved nothing."""
    src, out = tmp_path / "d.md", tmp_path / "d.kv.md"
    src.write_text(MOVEDOC)

    asked = f"move ## What to send back from line {MOVED_FROM} to 3"
    declined = "move ## Overview from line 3 to 9, so no move needed"

    def notes(who, lo, hi):
        return [asked, declined] if who == "structure" else []

    seen = run_canned(kv, monkeypatch, src, out, lambda *_: [], notes=notes)
    report = "".join(capsys.readouterr())

    assert "structure" in {who for who, _unit in seen}, seen
    assert _heads(MOVEDOC)[-1] == "## What to send back", "the fixture moved"
    assert _heads(out.read_text()) == [
        "# Platform notes", "## What to send back", "## Overview"], \
        out.read_text()
    assert "1 section moved" in report, report

    assert declined in report, report


def test_a_move_out_of_the_file_stays_a_note(kv):
    """"from line 101 to README" names no line here, so no tool in this run
    can make it and the notes list is where it belongs."""
    assert kv.moves.as_edit("move the Ollama gotcha from line 101 to README",
                            300) is None
    assert kv.moves.as_edit("move line 7 into Summary at line 13", 300) == {
        "op": "move-block", "line": 7, "into": 13,
        "why": "described in a note: move line 7 into Summary at line 13"}


def test_a_move_off_the_end_of_the_file_is_not_made(kv):
    """A line number the note invented is refused here rather than reaching
    the gates as a move onto a line that does not exist."""
    assert kv.moves.as_edit("move ## Notes from line 3 to 9000", 40) is None
    assert kv.moves.as_edit("move ## Notes from line 9000 to 3", 40) is None
