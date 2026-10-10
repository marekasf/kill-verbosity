"""Round 4 findings that were designed and left open. Built after testing."""

from killverbosity import blame, budget, pointers


def _key(text):
    """Stand-in for `repeat_key`: normalised words, which is what it returns."""
    return " ".join(text.lower().split())


BLOCK = {337, 338, 339, 340, 341, 342, 343}


def test_a_lost_rule_is_refused_on_its_own_lines_only():
    assert blame.carriers(340, 341, BLOCK) == {340, 341}


def test_every_line_of_a_wrapped_rule_is_refused():
    """Keeping any one of them lands half a rule, so all three go."""
    assert blame.carriers(340, 342, BLOCK) == {340, 341, 342}


def test_a_rule_on_a_line_nobody_edited_refuses_nothing():
    assert blame.carriers(400, 401, BLOCK) == set()


def test_a_rule_partly_outside_the_edit_block_keeps_the_edited_half():
    assert blame.carriers(342, 345, BLOCK) == {342, 343}


REPEAT = {"text": "the pipeline retries the failed job and records it",
          "lines": [12, 40]}


def test_a_dedup_refusal_names_the_specialist_that_wrote_the_repeat():
    results = [
        {"specialist": "prose",
         "edits": [{"line": 8, "new": "Something else entirely."}]},
        {"specialist": "noise",
         "edits": [{"line": 12,
                    "new": "The pipeline retries the failed job and records "
                           "it in Loki."}]},
    ]
    assert blame.repeat_rows([REPEAT], results, _key, 6) == [
        (12, "noise", REPEAT["text"])]


def test_every_dropped_edit_gets_its_own_row():
    """One row per cluster left the other edits in no bucket, and the run
    printed its own arithmetic error and asked the reader to report it."""
    results = [
        {"specialist": "prose",
         "edits": [{"line": 12,
                    "new": "The pipeline retries the failed job and records "
                           "it in Loki."},
                   {"line": 40,
                    "new": "The pipeline retries the failed job and records "
                           "it in Grafana."}]},
    ]
    rows = blame.repeat_rows([REPEAT], results, _key, 6)

    assert [ln for ln, _w, _t in rows] == [12, 40]


def test_an_edit_carrying_no_repeat_gets_no_row():
    results = [{"specialist": "prose",
                "edits": [{"line": 3, "new": "Unrelated text."}]}]
    assert blame.repeat_rows([REPEAT], results, _key, 6) == []


def test_an_edit_with_no_line_falls_back_to_the_cluster():
    results = [{"specialist": "summary",
                "edits": [{"op": "insert",
                           "new": "The pipeline retries the failed job and "
                                  "records it in Loki."}]}]
    assert blame.repeat_rows([REPEAT], results, _key, 6) == [
        (12, "summary", REPEAT["text"])]


def _clock(now):
    return lambda: now[0]


def test_a_job_with_a_quarter_of_its_clock_is_not_sent():
    """Seven jobs died on 49s or less of a 240s allowance and the run blamed
    the backend. None of them had a clock to answer on."""
    now = [0.0]
    b = budget.Budget(3600, clock=_clock(now))

    assert not b.starved(240)
    now[0] = 3600 - 59
    assert b.starved(240)


def test_a_short_run_budget_is_the_ceiling_it_is_judged_against():
    """`--timeout 25` starved its own first job when the raw 240 was the bar."""
    now = [0.0]
    b = budget.Budget(25, clock=_clock(now))

    assert not b.starved(240)
    now[0] = 20.0
    assert b.starved(240)


def test_no_budget_never_starves_a_job():
    assert not budget.Budget(None).starved(240)


def test_the_backend_advice_names_flags_this_tool_has():
    err = ("agy exited 124: timed out after 240s — raise --timeout or pass "
           "--no-timeout to allow retries")
    out = budget.local_flags(err)

    assert "--no-timeout" not in out, out
    assert "--job-timeout" in out, out
    assert "agy exited 124" in out, out


def test_an_error_with_no_flag_advice_is_left_alone():
    err = "agy exited 1: model not found"
    assert budget.local_flags(err) == err


REAL_TIMEOUT = ("agy exited 124: agy timed out after 240s — raise the limit "
                "with --timeout <seconds>, disable it with --no-timeout, or "
                "narrow the task")


def test_the_real_backend_timeout_advice_is_replaced_whole():
    """Both halves are wrong: `--no-timeout` does not exist here and
    `--timeout` is the whole run rather than one call."""
    out = budget.local_flags(REAL_TIMEOUT)

    assert "--no-timeout" not in out, out
    assert "raise the limit with --timeout" not in out, out
    assert "--job-timeout" in out, out
    assert out.count("raise --job-timeout") == 1, out
    assert "agy exited 124" in out, out


def test_the_advice_is_swapped_once_not_twice():
    """Three alternations over one clause must not stack three replacements."""
    assert budget.local_flags(
        "x — raise --timeout or pass --no-timeout to allow retries"
    ).count("--job-timeout") == 1


STALE = [
    "# Guide",
    "",
    "## Known failures",
    "",
    "The retry loop gives up after three attempts.",
    "",
    "## Next steps",
    "",
    'See "What does not work" below for the failure list.',
]


def test_a_renamed_heading_still_named_in_prose_is_reported():
    """The report promised this and only ever read `](#anchor)` links in the
    neighbouring files. The reference that was there is prose, in this file."""
    assert pointers.stale_mentions(STALE, "What does not work", {3}) == [9]


def test_a_one_word_heading_name_is_left_alone():
    """"Overview" shares its name with every ordinary use of the word."""
    assert pointers.stale_mentions(["the overview says so"], "Overview") == []


def test_the_heading_line_itself_is_not_a_stale_mention():
    assert pointers.stale_mentions(["## What does not work"],
                                   "What does not work", {1}) == []


def test_a_name_nobody_still_uses_reports_nothing():
    assert pointers.stale_mentions(STALE, "Next steps here", {3}) == []


def test_a_longer_word_is_not_a_reference_to_a_shorter_heading():
    """A substring test read "latest plan" as a mention of "Test plan"."""
    assert pointers.stale_mentions(["we shipped the latest plan"],
                                   "test plan") == []


def test_a_heading_name_ending_on_punctuation_still_matches():
    """`\\b` matches nothing after a bracket, so the lookaround does it."""
    assert pointers.stale_mentions(['see "What is open?" below'],
                                   "What is open?") == [1]


def test_a_fenced_copy_of_the_old_name_is_not_a_reference():
    raw = ["```", "What does not work", "```"]
    masked = ["", "", ""]
    at = pointers.unreadable(raw, masked)

    assert pointers.stale_mentions(raw, "What does not work", at) == []


def test_a_quoted_reference_survives_the_same_filter():
    """Masking blanks a quotation too, and that is the shape worth finding."""
    raw = ['See "What does not work" below.']
    masked = ["See                        below."]

    assert pointers.unreadable(raw, masked) == set()
    assert pointers.stale_mentions(raw, "What does not work") == [1]
