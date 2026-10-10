"""Later findings from a review."""

import pytest

pytestmark = pytest.mark.regression



def test_a_possessive_between_the_two_numbers_is_the_same_ratio(kv):
    """A filler word between the numbers hid the ratio entirely."""
    was = kv.facts("It used 11 of its 17 prompts.").get("ratio")
    now = kv.facts("It used 11 of 17 prompts.").get("ratio")

    assert was == now == {"11 of 17"}, (was, now)


def test_a_spelled_ratio_with_a_filler_reads_the_same(kv):
    """The filler is stripped after the spelled numbers become digits."""
    got = kv.facts("It used eleven of its seventeen prompts.").get("ratio")

    assert got == {"11 of 17"}, got


@pytest.mark.parametrize("said", [
    "It used 2 of the 3 runs.",
    "It used 2 of all 4 things.",
    "It covered 45 of only 72 lines.",
])
def test_the_common_fillers_all_collapse(kv, said):
    got = kv.facts(said).get("ratio")
    assert got and all(" of " in v and v.count(" ") == 2 for v in got), got


@pytest.mark.parametrize("said", [
    "one of the reasons we stopped",
    "any of the four remaining checks",
    "it is one of those days",
])
def test_a_phrase_that_is_not_a_ratio_does_not_become_one(kv, said):
    """`of the` alone is not a ratio. Only a number on each side is."""
    assert not kv.facts(said).get("ratio"), (said, kv.facts(said).get("ratio"))


def test_a_ratio_still_reads_without_any_filler(kv):
    """The plain form must not regress."""
    assert kv.facts("It used 11 of 17 prompts.").get("ratio") == {"11 of 17"}
    assert kv.facts("It used 71 / 92 of them.").get("ratio") == {"71 / 92"}



def test_the_merge_does_not_depend_on_which_answer_arrives_first(
        kv, monkeypatch, tmp_path):
    """Two runs, same jobs, answers arriving in opposite orders, same output."""
    import json
    import re
    import sys
    import threading
    import time
    import zlib

    doc = "# Notes\n\n" + "\n\n".join(
        f"It is worth noting that section {i} has, at this point in time, "
        f"a retry count that nobody has actually gone and checked."
        for i in range(8)) + "\n"

    SHAPES = ("Section {i} has a retry count nobody has checked.",
              "Nobody has checked the retry count of section {i}.",
              "The retry count of section {i} is unchecked.",
              "Section {i} has an unchecked retry count.")

    def run(reverse):
        src = tmp_path / f"doc{int(reverse)}.md"
        src.write_text(doc)
        out = tmp_path / f"out{int(reverse)}.md"
        turn, lock = {"n": 0}, threading.Lock()

        def agent(prompt, *_a):
            with lock:
                turn["n"] += 1
                k = turn["n"]
            time.sleep(0.04 * (k if not reverse else 12 - k))

            if "the shape of the whole document" not in prompt:
                return json.dumps({"edits": [], "notes": []}), None

            edits = []
            for ln, text in re.findall(r"^\s*(\d+) \| (\S.*)$", prompt,
                                       re.M)[:2]:
                m = re.search(r"section (\d+)", text)
                if not m:
                    continue
                edits.append({"op": "replace", "line": int(ln), "old": text,
                              "new": SHAPES[zlib.crc32(prompt.encode())
                                            % len(SHAPES)].format(i=m.group(1)),
                              "why": "wordy"})
            return json.dumps({"edits": edits, "notes": []}), None

        monkeypatch.setattr(kv, "call_agent", agent)
        monkeypatch.setattr(kv, "JOBS", 4)
        monkeypatch.setattr(sys, "argv",
                            ["kill-verbosity", "run", str(src), "-o", str(out)])
        try:
            kv.main()
        except SystemExit:
            pass
        return out.read_text() if out.exists() else None

    first, second = run(False), run(True)

    assert first and second, (first, second)
    assert first.count("It is worth noting") < doc.count("It is worth noting"),\
        first
    assert first == second, (
        "the same edits merged differently because they came back in a "
        "different order\n--- first:\n" + first + "\n--- second:\n" + second)



def test_the_document_scope_jobs_are_sent_before_the_section_jobs(
        kv, monkeypatch, tmp_path):
    """One run left all 13 `structure` jobs and the only `summary` job unsent."""
    import json
    import sys
    import threading

    doc = "# Notes\n\n" + "\n\n".join(
        f"## Part {i}\n\nIt is worth noting that section {i} has, at this "
        f"point in time, a retry count that nobody has actually gone and "
        f"checked." for i in range(6)) + "\n"
    src = tmp_path / "doc.md"
    src.write_text(doc)

    order, lock = [], threading.Lock()

    def agent(prompt, *_a):
        who = ("structure" if "the shape of the whole document" in prompt
               else "summary" if "# Your aspect: the opening summary" in prompt
               else "other")
        with lock:
            order.append(who)
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit:
        pass

    assert "structure" in order, order
    last_doc = max(i for i, w in enumerate(order) if w != "other")
    first_section = next((i for i, w in enumerate(order) if w == "other"), None)
    if first_section is not None:
        assert last_doc < first_section, order



def _verify(kv, tmp_path, orig, new):
    """Run `verify ORIG EDITED` and give back what it printed."""
    import io
    import sys
    import contextlib
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(orig)
    b.write_text(new)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        old = sys.argv
        sys.argv = ["kill-verbosity", "verify", str(a), str(b)]
        try:
            kv.main()
        except SystemExit:
            pass
        finally:
            sys.argv = old
    return buf.getvalue()


def test_a_credited_name_said_fewer_times_is_reported(kv, tmp_path):
    """Dana fell from four mentions to two and nothing was said."""
    orig = ("# Notes\n\nDana's initial flag opened the thread.\n\n"
            "The retry cap was set per Dana's recap of the incident.\n\n"
            "Dana owns the rollback switch.\n\n"
            "Dana decides whether the rollout goes ahead.\n")
    new = ("# Notes\n\nInitial flag opened the thread.\n\n"
           "The retry cap was set after the incident.\n\n"
           "Dana owns the rollback switch.\n\n"
           "Dana decides whether the rollout goes ahead.\n")

    out = _verify(kv, tmp_path, orig, new)

    assert "credited names that went" in out, out
    assert "said fewer times than before: Dana 4→2" in out, out


def test_a_credited_name_said_the_same_number_of_times_is_not_reported(
        kv, tmp_path):
    """The name must not be reported just because a sentence was reworded."""
    orig = ("# Notes\n\nDana's initial flag opened the thread.\n\n"
            "Dana owns the rollback switch.\n")
    new = ("# Notes\n\nDana flagged it first.\n\n"
           "Dana owns the rollback switch.\n")

    assert "said fewer times than before" not in _verify(kv, tmp_path, orig, new)



def test_a_drop_excused_because_the_token_is_elsewhere_is_reported(kv):
    """Two facts sharing a value excused each other and nothing was said."""
    lines = ["Retention is 12 months across the board.",
             "Loki logs are kept for 12 months.",
             "Backtrace is kept for 12 months."]
    idx = kv.token_lines(lines)

    excused = []
    refused = kv.tokens_dropped("prose", lines[1], "Loki logs are kept.",
                                index=idx, ln=2, excused=excused)

    assert refused == "", refused
    assert excused, "the drop was excused and never mentioned"
    tok, at = excused[0]
    assert 1 in at and 3 in at, (tok, at)


def test_shortening_a_summary_line_the_body_restates_is_still_allowed(kv):
    """The case the excuse was written for. It must not start refusing."""
    lines = ["Retention is 12 months across the board.",
             "Loki logs are kept for 12 months.",
             "Backtrace is kept for 12 months."]
    idx = kv.token_lines(lines)

    assert kv.tokens_dropped("prose", lines[0], "Retention is uniform.",
                             index=idx, ln=1) == ""


def test_a_drop_with_no_copy_anywhere_is_still_refused(kv):
    """The gate still does its job when there is nothing to excuse it."""
    lines = ["We saw 52 failures."]
    assert kv.tokens_dropped("prose", lines[0], "We saw failures.",
                             index=kv.token_lines(lines), ln=1) == "52"



@pytest.mark.parametrize("said", [
    "<something you could not decide, one short sentence>",
    "<shape name>",
    "  <the replacement>  ",
])
def test_the_prompts_own_placeholder_is_not_a_finding(kv, said):
    """The model echoed the reply template and it printed as a finding."""
    assert kv.echoed_template(said), said


@pytest.mark.parametrize("said", [
    "the <b> tag here is deliberate",
    "check whether <100ms is achievable",
    "this section repeats the one above",
])
def test_a_real_note_that_contains_angle_brackets_survives(kv, said):
    assert not kv.echoed_template(said), said



def test_a_journal_from_another_build_is_not_reused(kv, tmp_path):
    """One resume began on one build and finished on another."""
    from killverbosity.runrecord import read_journal, journal_path
    import json

    out = tmp_path / "o.md"
    key, paid = "abc123", '{"edits": []}'

    def bank(build):
        journal_path(out).write_text(json.dumps(
            {"key": key, "result": paid,
             "source": kv.source_fingerprint(f"codex\0{build}\0the text")}
            ) + "\n", encoding="utf-8")

    same = kv.source_fingerprint(f"codex\0{kv.build_id()}\0the text")
    bank(kv.build_id())
    assert read_journal(out, same) == {key: paid}, "the same build must resume"

    bank("522e20a4 17254L")
    assert read_journal(out, same) == {}, "another build must not be reused"



def test_a_ratio_across_a_line_break_is_the_same_ratio(kv):
    """Verify reported TOKENS LOST on a ratio that never left the file."""
    wrapped = 'It then says "showing 5\nof 8", so the duplicates consume it.'
    joined = 'It then says "showing 5 of 8", so the duplicates consume it.'

    assert kv.facts(wrapped).get("ratio") == kv.facts(joined).get("ratio") \
        == {"5 of 8"}


@pytest.mark.parametrize("wrapped,flat", [
    ("we saw 47 of\n57 fail", "we saw 47 of 57 fail"),
    ("`some\nspan` here", "`some span` here"),
])
def test_no_fact_carries_the_newline_a_reword_put_in_it(kv, wrapped, flat):
    assert kv.facts(wrapped) == kv.facts(flat), (wrapped, flat)
