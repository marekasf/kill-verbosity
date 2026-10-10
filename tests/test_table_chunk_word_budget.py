"""a chunk's word budget must count a table row's real content, not the
blank `mask()` leaves in its place.
"""

MAX_SPAN_WORDS = 800

HEAD = "# Actions\n\n| Id | Action | Why this one | Done when |\n| :--- | :--- | :--- | :--- |\n"

_SENTENCE = ("the service silently drops a retry after the third attempt and "
             "nothing downstream is told the request never landed, which is "
             "the exact failure a customer reported on ticket OPS-{i:04d} "
             "last week, and the fix is not merely a longer timeout, it is a "
             "written retry contract the caller can rely on instead of "
             "guessing at the undocumented behaviour")


def _row(i):
    return (f"| N{i} | **Fix retry contract {i}.** | The {_SENTENCE.format(i=i)}. "
            f"Reported {i} times this quarter | One written contract and a "
            f"test that fails without it |\n")


ROWS = [_row(i) for i in range(1, 21)]
DOC = HEAD + "".join(ROWS)


def test_the_fixture_is_actually_over_the_word_budget(kv):
    prose, _heads, tables, _quotes = kv.mask(DOC, "t")
    real = kv.with_table_text(prose, tables)
    total = sum(len(real[i].split()) for i in range(len(real)))
    assert total > MAX_SPAN_WORDS, total


def test_a_hit_in_an_unsplit_appendix_no_longer_spans_the_whole_table(kv):
    prose, headings, tables, _quotes = kv.mask(DOC, "t")
    chunks = kv.chunk(prose, headings, tables=tables)
    assert len(chunks) == 1, [c["title"] for c in chunks]
    c = chunks[0]
    wc = sum(len(ln.split()) for _, ln in c["lines"])
    assert wc > MAX_SPAN_WORDS, wc
    wins = kv.windows(c["start"], c["end"], (), words=kv._span_words(c))
    assert len(wins) > 1, wins
    first_row, last_row = c["start"] + 2, c["end"]
    assert not any(lo <= first_row and hi >= last_row for lo, hi in wins), wins


def test_without_tables_the_old_blind_count_is_what_chunk_falls_back_to(kv):
    prose, headings, tables, _quotes = kv.mask(DOC, "t")
    assert tables, "fixture must actually contain table rows"
    c = kv.chunk(prose, headings)[0]
    wc = sum(len(ln.split()) for _, ln in c["lines"])
    assert wc < MAX_SPAN_WORDS, wc
    wins = kv.windows(c["start"], c["end"], (), words=kv._span_words(c))
    assert wins == [(c["start"], c["end"])], wins


def test_plan_reports_the_appendix_as_split_for_dispatch(tmp_path):
    from conftest import run_tool

    f = tmp_path / "appendix.md"
    f.write_text(DOC)
    r = run_tool("plan", f)
    assert r.returncode == 0, (r.returncode, r.stdout)
    assert "split into" in r.stdout and "for dispatch" in r.stdout, r.stdout
