"""A reply that denies having source lines, and a span with no lines in it."""

from __future__ import annotations


def test_no_source_lines_regex_matches_the_reported_wording():
    from killverbosity import _legacy as kv
    assert kv._NO_SOURCE_LINES_RE.search(
        "I could not find any edits: no numbered source lines were provided.")
    assert kv._NO_SOURCE_LINES_RE.search(
        "No source lines were given for this span.")
    assert not kv._NO_SOURCE_LINES_RE.search(
        "The source is fine; here are three edits to the lines.")


def test_a_reply_denying_source_lines_is_treated_as_a_failed_job(kv):
    raw = '{"edits": [], "notes": ["no numbered source lines were provided"]}'
    payload, err = kv.parse_reply(raw)
    assert err is None, "the JSON itself is well-formed"
    assert kv._NO_SOURCE_LINES_RE.search(raw), (
        "the guard's own regex must fire on the exact reported wording")


def test_empty_span_error_flags_a_span_with_no_lines(kv):
    lines = ["one", "two", "three"]
    job = {"lo": 3, "hi": 2, "outline": None}
    msg = kv.empty_span_error(job, lines)
    assert msg is not None and "empty" in msg, (
        f"a span past the end of the document must be flagged, got {msg!r}")


def test_empty_span_error_is_none_for_a_real_span(kv):
    lines = ["one", "two", "three"]
    job = {"lo": 1, "hi": 2, "outline": None}
    assert kv.empty_span_error(job, lines) is None, (
        "a span that actually holds text must not be flagged")


def test_empty_span_error_does_not_apply_to_outline_jobs(kv):
    lines = ["one", "two", "three"]
    job = {"lo": 5, "hi": 6, "outline": "# some heading table"}
    assert kv.empty_span_error(job, lines) is None
