"""The numbers in the report have to agree with the findings under them."""

import re

import pytest
from conftest import run_canned, run_tool

pytestmark = pytest.mark.regression

LONG = "\n".join(
    ["# Platform notes", ""]
    + [f"The worker retries job {i} and records the outcome in Loki. "
       f"The retry budget is {i * 3} seconds and the operator is paged "
       f"after it. " for i in range(1, 14)]
)


def test_growth_is_not_printed_as_a_cut(kv, monkeypatch, tmp_path, capsys):
    """A run that grew the file printed "936 → 950 words (-1.5% cut)"."""
    src = tmp_path / "doc.md"
    src.write_text(LONG + "\n")
    body = src.read_text().splitlines()[2]

    def reply(who, lo, hi):
        if who != "prose" or not lo <= 3 <= (hi or 10 ** 9):
            return []
        return [{"line": 3, "old": body, "new": body + " " + body}]

    run_canned(kv, monkeypatch, src, tmp_path / "out.md", reply)
    line = next(x for x in capsys.readouterr().out.splitlines()
                if x.startswith("the document:"))

    before, after = (int(n) for n in re.findall(r"(\d+) → (\d+) words", line)[0])
    assert after > before, f"fixture did not grow the file: {line}"
    assert "cut" not in line, line
    assert "longer" in line, line
    assert "-" not in line.split("(")[1].split(")")[0], line


def test_the_three_edit_buckets_add_up(kv, monkeypatch, tmp_path, capsys):
    """"29 of 52 edits applied, 9 refused by the gates, 16 went to the line's
    owner" adds to 54. One line contested by two specialists was counted once
    as refused and once as owner-lost."""
    src = tmp_path / "doc.md"
    src.write_text(LONG + "\n")
    body = src.read_text().splitlines()[2]

    def reply(who, lo, hi):
        if not lo <= 3 <= (hi or 10 ** 9):
            return []
        return [{"line": 3, "old": body,
                 "new": f"The worker retries and pages the operator, per {who}."}]

    run_canned(kv, monkeypatch, src, tmp_path / "out.md", reply)
    out = capsys.readouterr().out

    assert "Report this." not in out, out
    head = next(x for x in out.splitlines() if " edits applied," in x)
    applied, proposed = (int(n) for n in re.findall(r"(\d+) of (\d+) ", head)[0])
    rest = sum(int(n) for n in re.findall(r"(\d+) (?:refused by the gates|"
                                          r"went to the line's owner)", head))
    assert applied + rest == proposed, head


def _headline(out):
    """The three buckets and the number they are supposed to add to."""
    head = next(x for x in out.splitlines() if " edits applied," in x)
    applied, proposed = (int(n) for n in re.findall(r"(\d+) of (\d+) ", head)[0])
    rest = sum(int(n) for n in re.findall(r"(\d+) (?:refused by the gates|"
                                          r"went to the line's owner)", head))
    return head, applied + rest, proposed


WRAPPED = ("# Platform notes\n\n"
           "It is worth noting that the worker retries the job and records "
           "the outcome after 45s.\n"
           "It is worth noting that the operator is paged once the retry "
           "budget of 12 seconds expires.\n")


NEEDS_SUMMARY = "# Platform notes\n\n" + "\n\n".join(
    f"The worker retries job {i} and records the outcome in Loki. "
    f"The retry budget is {i * 3} seconds and the operator is paged after it. "
    f"Nightly compaction runs at 02:00 and reads the previous day only, so a "
    f"backfill for job {i} needs a run of its own before the report is built."
    for i in range(1, 22)) + "\n"


def test_a_block_rolled_back_is_counted_once(kv, monkeypatch, tmp_path,
                                             capsys):
    """"47 of 68 edits applied, 6 refused, 16 owner" adds to 69."""
    src = tmp_path / "doc.md"
    src.write_text(WRAPPED)
    lines = WRAPPED.splitlines()

    def reply(who, lo, hi):
        if who != "prose" or not lo <= 3 <= (hi or 10 ** 9):
            return []
        return [
            {"line": 3, "old": lines[2], "why": "prose: frame",
             "new": "The worker retries the job and records the outcome."},
            {"line": 4, "old": lines[3], "why": "prose: frame",
             "new": "The operator is paged after 12 seconds."},
        ]

    run_canned(kv, monkeypatch, src, tmp_path / "out.md", reply)
    out = capsys.readouterr().out

    head, got, want = _headline(out)
    assert want == 2, head
    assert "Report this." not in out, out
    assert got == want, head


def test_a_summary_refused_whole_is_counted_in_no_bucket(kv, monkeypatch,
                                                         tmp_path, capsys):
    """"31 of 44 applied, 5 refused, 7 owner" adds to 43."""
    src = tmp_path / "doc.md"
    src.write_text(NEEDS_SUMMARY)

    def reply(who, lo, hi):
        if who != "summary":
            return []
        return [{"op": "insert", "line": 2, "old": "",
                 "why": "summary: the file needs one",
                 "new": "## Summary\n\nIt is worth noting that the worker "
                        "retries and the operator is paged.\n"}]

    run_canned(kv, monkeypatch, src, tmp_path / "out.md", reply)
    out = capsys.readouterr().out

    head, got, want = _headline(out)
    assert "summary answer refused" not in out
    assert want, head
    assert "Report this." not in out, out
    assert got == want, head


def test_every_list_can_be_printed_in_full(tmp_path):
    """`… showing 8 of 12` and no way to reach the other four."""
    o = tmp_path / "o.md"
    n = tmp_path / "n.md"
    o.write_text("# Budgets\n\n" + " ".join(
        f"Region {i} holds {i * 7} nodes." for i in range(1, 13)) + "\n")
    n.write_text("# Budgets\n\n" + " ".join(
        f"Region {i} holds nodes." for i in range(1, 13)) + "\n")

    short = run_tool("verify", o, n)
    full = run_tool("verify", o, n, "--full")

    m = re.search(r"…\s*showing (\d+) of (\d+)", short.stdout)
    assert m, short.stdout
    shown, total = int(m.group(1)), int(m.group(2))
    assert shown < total, short.stdout
    assert f"TOKENS LOST — {total} protected tokens" in short.stdout, short.stdout
    assert "showing" not in full.stdout, full.stdout
    assert "84" in full.stdout.split("tokens reshaped")[0], full.stdout
    assert "84" not in short.stdout, short.stdout


def test_full_widens_the_shape_quotes_as_well_as_the_list(tmp_path):
    """`--full` gave every hit a row and left every quote cut at 34 characters."""
    o = tmp_path / "o.md"
    n = tmp_path / "n.md"
    o.write_text("# T\n\nThe clean index URL hides the token from the log. "
                 "The clean report shows the retry budget in seconds.\n")
    n.write_text(o.read_text())

    def row(res):
        return next(x for x in res.stdout.splitlines()
                    if "evaluative adjective (" in x)

    assert "…" in row(run_tool("verify", o, n)), row(run_tool("verify", o, n))
    wide = row(run_tool("verify", o, n, "--full"))
    assert "hides the token from the log." in wide, wide
    assert "shows the retry budget in seconds." in wide, wide
    assert "'…clean index URL" in wide, wide
    assert "'…clean report" in wide, wide


def test_a_missing_summary_is_not_called_an_over_cap_one(tmp_path):
    """The verdict named the wrong condition, including on a run whose 90-word
    summary was well under the cap and on one with no summary at all.
    """
    o = tmp_path / "o.md"
    n = tmp_path / "n.md"
    big = "\n".join(
        ["# Platform notes", ""]
        + [f"The worker retries job {i} and records the outcome in Loki. "
           f"The retry budget is {i * 3} seconds and the operator is paged "
           f"after it. " for i in range(1, 41)]
    )
    o.write_text(big + "\n")
    n.write_text(big.replace("job 40", "job 40,") + "\n")

    r = run_tool("verify", o, n)

    assert "opening summary: MISSING" in r.stdout, r.stdout
    assert "an over-cap summary" not in r.stdout, r.stdout
    assert "no opening summary" in r.stdout, r.stdout


def test_the_headline_names_every_count_it_leaves_out(tmp_path):
    """It named the length candidates and said nothing about the other two."""
    p = tmp_path / "doc.md"
    p.write_text(
        "# Notes\n\n"
        "The deploy — which was late — broke — again — and it — really — did.\n\n"
        "One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten. Eleven.\n\n"
        "It is worth noting that the deployment finished in the end.\n"
    )
    out = run_tool("plan", p).stdout
    head = next(x for x in out.splitlines() if "fault-shape" in x)

    assert "em-dash 1" in out and "wall 1" in out, out
    assert "1 fault-shape in" in head, head
    assert "em-dash paragraph" in head and "paragraph wall" in head, head


def test_plan_says_how_much_of_the_file_goes_to_nobody(tmp_path):
    """A span specialist gets a chunk only when one of its shapes fired there."""
    p = tmp_path / "doc.md"
    p.write_text("# Notes\n\n" + "".join(
        f"## Section {i}\n\nThe worker records run {i} in the log store.\n\n"
        for i in range(1, 5))
        + "## Last\n\nIt is worth noting that the deployment finished.\n")

    out = run_tool("plan", p).stdout

    assert "found nothing" in out, out
    line = out.split("found nothing")[1].splitlines()[1]
    sent, total = (int(x)
                   for x in re.findall(r"(\d+) of (\d+) prose words", line)[0])
    assert 0 < sent < total, line
    assert "no section specialist was given those lines" in line, line


def test_the_coverage_line_does_not_read_as_a_smaller_headline(tmp_path):
    """Two counts of two different things, and both were called "words"."""
    p = tmp_path / "doc.md"
    p.write_text(
        "# Notes\n\n| col | note |\n|---|---|\n| a | one two three four |\n\n"
        + "".join(f"## Section {i}\n\nThe worker records run {i} in the log "
                  f"store.\n\n" for i in range(1, 5))
        + "## Last\n\nIt is worth noting that the deployment finished.\n")

    out = run_tool("plan", p).stdout
    line = out.split("found nothing")[1].splitlines()[1]

    total = int(re.findall(r"\d+ of (\d+) prose words", line)[0])
    header = int(re.findall(r"—\s+(\d+) words", out)[0])
    assert total < header, \
        f"the table cells are counted in both: {total} of {header}"
    assert " of {} words".format(total) not in out, \
        "the coverage total is printed unqualified somewhere and still clashes"


def test_coverage_total_matches_headline_prose_population(tmp_path):
    """the headline's "N of them prose" and the coverage line's "X of Y
    prose words" have to count the SAME population, and on a real document
    (docs/rollout/plan.md) they didn't — headline said
    "23475 of them prose", coverage said "26 of 37734 prose words". The
    coverage total silently included table-cell text: `chunk()` restores
    table cells into the lines it sums for span-costing, but the
    headline's `scanned_words` is `mask()`'s `prose` alone, tables excluded.
    """
    p = tmp_path / "doc.md"
    p.write_text(
        "# Notes\n\n"
        "| col | note |\n|---|---|\n| a | one two three four |\n\n"
        "## Section 1\n\nThe worker logs each run in the store.\n\n"
        "## Section 2\n\nThe worker closes the file at the end.\n")

    out = run_tool("plan", p).stdout
    head = next(x for x in out.splitlines() if "fault-shape" in x)
    coverage = out.split("found nothing")[1].splitlines()[1]

    HAND_COUNTED_PROSE_WORDS = 16

    headline_prose = int(re.search(r"(\d+) of them prose", head).group(1))
    coverage_total = int(re.findall(r"\d+ of (\d+) prose words", coverage)[0])

    assert headline_prose == HAND_COUNTED_PROSE_WORDS, head
    assert coverage_total == HAND_COUNTED_PROSE_WORDS, coverage


G412_G413_FIXTURE = (
    "# Notes\n\n"
    "## Section 1\n\n"
    "Phase 1 ships next quarter.\n\n"
    "The worker logs each run in the store.\n\n"
    "The worker closes the file at the end.\n\n"
    "## Section 2\n\n"
    "Phase 1 ships next quarter.\n\n"
    "The worker logs each run in the store.\n\n"
    "The worker closes the file at the end.\n"
)
HAND_TOTAL_WORDS = 50
HAND_PROSE_WORDS = 42
HAND_FAULT_SHAPES = 2
HAND_YIELD_LINES = 8
HAND_YIELD_WORDS = 48


def test_expected_yield_names_its_population_not_the_headlines_shapes(
        tmp_path):
    """on `docs/rollout/plan.md` the headline said
    "32 fault-shapes" and the very next printed line said "the words on the
    348 lines a shape fired on" -- eleven times as many lines as the headline
    just reported shapes. The wording claimed a shape fired on each of those
    348 lines; it fired on 32.
    """
    p = tmp_path / "doc.md"
    p.write_text(G412_G413_FIXTURE)

    out = run_tool("plan", p).stdout
    head = next(x for x in out.splitlines() if "fault-shape" in x)
    yield_ = next(x for x in out.splitlines() if x.startswith("expected yield:"))

    assert f"{HAND_FAULT_SHAPES} fault-shapes in {HAND_TOTAL_WORDS} words" \
        in head, head
    m = re.search(r"at most (\d+) of (\d+) words \((\d+\.\d)%\), the words "
                  r"on the (\d+) lines?", yield_)
    assert m, yield_
    at, of, _pct, lines = (int(m.group(1)), int(m.group(2)), m.group(3),
                            int(m.group(4)))
    assert at == HAND_YIELD_WORDS, yield_
    assert of == HAND_TOTAL_WORDS, yield_
    assert lines == HAND_YIELD_LINES, yield_
    assert "a shape fired on" not in yield_, yield_
    assert "fault-shape" in yield_, \
        f"the line does not relate its own count to the headline's: {yield_}"


def test_rate_names_its_denominator_and_prints_the_total_words_rate(
        tmp_path):
    """the headline's "(X per 1000 over the N counted kinds, ...)"
    divided by the prose word count alone and never said so. A file that is
    mostly tables or code reads a worse rate than the same fault count would
    give over the whole file, and nothing beside the number told a reader
    which one they were looking at -- so two files could not be compared by
    this rate at all.
    """
    p = tmp_path / "doc.md"
    p.write_text(G412_G413_FIXTURE)

    out = run_tool("plan", p).stdout
    head = next(x for x in out.splitlines() if "fault-shape" in x)

    assert f"{HAND_FAULT_SHAPES} fault-shapes in {HAND_TOTAL_WORDS} words, " \
        f"{HAND_PROSE_WORDS} of them prose" in head, head
    assert "47.6 per 1000 prose words over the 1 counted kind" in head, head
    assert f"40.0 per 1000 of all {HAND_TOTAL_WORDS} words" in head, head


def test_a_file_that_skipped_no_words_says_nothing_about_coverage(tmp_path):
    """The title is its own chunk and holds no words, so a clean short file
    printed "0 of 8 words (0%)" — a warning about nothing."""
    p = tmp_path / "doc.md"
    p.write_text("# Notes\n\nIt is worth noting that the deploy finished.\n")

    assert "no specialist" not in run_tool("plan", p).stdout


def test_over_target_says_whether_the_run_finished(kv, monkeypatch, tmp_path,
                                                   capsys):
    """The ratio alone does not."""
    src = tmp_path / "doc.md"
    src.write_text(LONG + "\n")
    lines = src.read_text().splitlines()

    verbs = "retries requeues restarts resumes replays reruns revives " \
            "reissues repeats reschedules reloads reconnects refires".split()
    sinks = ["Loki", "the log store", "the journal", "the audit trail",
             "Grafana", "the index", "the archive", "the ledger", "the shard",
             "the bucket", "the stream", "the table", "the cache"]

    def shorter(_who, lo, hi):
        return [{"line": n, "old": lines[n - 1],
                 "new": f"The worker {verbs[n - 3]} job {n - 2} and writes the "
                        f"outcome to {sinks[n - 3]}. Its budget is "
                        f"{(n - 2) * 3} seconds."}
                for n in range(max(lo, 3), min(hi or 15, 15) + 1)]

    run_canned(kv, monkeypatch, src, tmp_path / "a.md", shorter)
    inside = next(x for x in capsys.readouterr().out.splitlines()
                  if "over target" in x)

    run_canned(kv, monkeypatch, src, tmp_path / "b.md", lambda *_: [])
    untouched = next(x for x in capsys.readouterr().out.splitlines()
                     if "over target" in x)

    ratio = float(re.search(r"\(([\d.]+)x\)", inside)[1])
    assert 1 < ratio <= kv.OVER_TARGET_BAND, inside
    assert "This one is normal." in inside, inside
    assert float(re.search(r"\(([\d.]+)x\)", untouched)[1]) > \
        kv.OVER_TARGET_BAND, untouched
    assert "the pass stopped early" in untouched, untouched


def test_the_refusal_list_says_it_is_counting_groups(kv, monkeypatch, tmp_path,
                                                     capsys):
    """The headline counts refused edits, the list counts rows after the fold."""
    src = tmp_path / "doc.md"
    src.write_text(LONG + "\n")
    lines = src.read_text().splitlines()

    def reply(who, lo, hi):
        if who != "prose":
            return []
        return [{"line": n, "old": lines[n - 1],
                 "new": "We should drop the retry and page the operator."}
                for n in (3, 5) if lo <= n <= (hi or 10 ** 9)]

    run_canned(kv, monkeypatch, src, tmp_path / "out.md", reply)
    out = capsys.readouterr().out

    head = next(x for x in out.splitlines() if " refused by the gates" in x)
    listed = next(x for x in out.splitlines() if x.startswith("refused ("))
    n_head = int(re.search(r"(\d+) refused by the gates", head)[1])
    rows = sum(1 for x in out.split(listed)[1].splitlines() if x.startswith("  L"))

    assert n_head > rows, f"fixture did not fold: {head} / {listed}"
    assert str(n_head) in listed, f"the list never names the headline's count: {listed}"
    assert f"in {rows} group" in listed, listed


def test_one_em_dash_paragraph_is_not_plural(tmp_path):
    """"em-dash: 1 paragraphs hold more than one". The same line five below it
    has the singular right."""
    o = tmp_path / "o.md"
    n = tmp_path / "n.md"
    o.write_text("# Notes\n\nThe deploy finished late.\n")
    n.write_text("# Notes\n\nThe deploy — the second one — finished late.\n")

    out = run_tool("verify", o, n).stdout

    assert "em-dash: 1 paragraph holds more than one" in out, out


def test_a_rollback_is_not_counted_as_an_ownership_refusal(kv):
    """A rolled-back line quotes the refusal that broke its block."""
    import inspect

    src = inspect.getsource(kv.cmd_run)

    assert 'if "already changed by" in r[2]' not in src, \
        "a substring test files a rollback under the ownership rule"
    assert "r[2].startswith(_own)" in src, "the split is not anchored"

    head = kv.owner_report([(2, "prose: x", "already changed by structure")],
                           "already changed by ", [])[0]
    assert "1 to structure" in head, head


def test_a_pointer_inside_a_pointer_is_read_whole(kv):
    """`\\(([^()\\n]{3,60})\\)` cannot cross an inner bracket or a line."""
    assert kv.outer_brackets("see (the plan (step 4) applies) now") == \
        ["the plan (step 4) applies"]
    assert kv.outer_brackets("a (pointer split\nacross two lines) here") == \
        ["pointer split\nacross two lines"]
    assert kv.outer_brackets("an (unclosed one") == []
    assert kv.outer_brackets("(one) and (two)") == ["one", "two"]


SECTIONS = {
    "alpha": "The worker must never retry a failed job more than three times. "
             "The retry budget is 30 seconds and the operator is paged after "
             "it. Every outcome is recorded in the log store for later.",
    "beta": "Nightly compaction runs at 02:00 and takes about twenty minutes. "
            "It reads the previous day only, so a backfill needs its own run.",
}


def _doc(*sections):
    return "# Platform notes\n\n" + "".join(
        f"## {title}\n\n{SECTIONS[key]}\n\n" for title, key in sections)


def test_a_heading_renamed_and_moved_keeps_its_rules(tmp_path):
    """The delete and the insert sit in different diff blocks, so the two
    never meet. The section reads as destroyed, and every rule under it as
    having changed owner, with its body word for word under the new name.
    """
    o = tmp_path / "o.md"
    n = tmp_path / "n.md"
    o.write_text(_doc(("Alpha", "alpha"), ("Beta", "beta")))
    n.write_text(_doc(("Beta", "beta"), ("Retry limits", "alpha")))

    out = run_tool("verify", o, n).stdout

    assert "headings gone" not in out, out
    assert "rules that changed section" not in out, out
    assert "1 heading was renamed" in out, out


def test_one_specialist_saying_it_twice_is_not_two_specialists(
    kv, monkeypatch, tmp_path, capsys
):
    """A specialist gets one job per section, so `structure` can send the same
    note twice. The line dropped the first member and named what was left, so
    it printed "1 more said this, from structure"."""
    src = tmp_path / "doc.md"
    src.write_text(LONG + "\n")
    note = "the opening needs a person to decide what it is for"

    seen = run_canned(kv, monkeypatch, src, tmp_path / "out.md",
                      lambda *_: [],
                      notes=lambda who, *_: [note] if who == "structure" else [])
    out = capsys.readouterr().out

    assert sum(1 for w, _u in seen if w == "structure") > 1, \
        f"fixture gave structure one job, so it cannot repeat itself: {seen}"
    assert note in out, out
    assert "more said this" not in out, out
    assert "structure raised it in" in out, out
