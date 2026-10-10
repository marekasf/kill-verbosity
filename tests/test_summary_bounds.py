"""nothing bounded the summary insert itself."""
from __future__ import annotations


def _doc(sections=6, sentences=84):
    """A title and `sections` `##` sections, no summary anywhere."""
    lines = ["# Retry budget review", ""]
    headings = [(0, 1, "Retry budget review")]
    for i in range(1, sections + 1):
        headings.append((len(lines), 2, f"Section {i}"))
        lines.append(f"## Section {i}")
        lines.append("")
        lines.append(" ".join(
            f"Request {i}{n} took {100 + n} ms on attempt {n % 4}."
            for n in range(1, sentences + 1)))
        lines.append("")
    return lines, headings


INSERT_LINE = 3


def test_fixture_is_an_h1_title_over_h2_sections_with_no_summary(kv):
    doc, headings = _doc()
    assert doc[0] == "# Retry budget review"
    assert doc[INSERT_LINE - 1] == "## Section 1", doc[INSERT_LINE - 1]
    assert headings[0][1] == 1 and all(h[1] == 2 for h in headings[1:])
    words = kv._summary_words("\n".join(doc))
    assert words >= 3000, words
    assert kv.summary_cap(words) == kv.SUMMARY_MAX_WORDS


def test_an_h1_summary_above_h2_sections_is_refused(kv):
    """The defect. An H1 inserted over H2 sections has no terminator short of
    EOF, so it would own every section that follows."""
    doc, headings = _doc()
    results = [{"specialist": "summary", "edits": [
        {"line": INSERT_LINE, "op": "insert",
         "new": "# Summary\n\nRequest 11 took 101 ms on attempt 1.\n",
         "why": "one page"}]}]

    _out, applied, refused, _ = kv.merge(
        list(doc), results, set(range(1, len(doc) + 1)), headings=headings)

    assert not any(a[2] == "insert" for a in applied), applied
    assert refused, "the reparenting insert should have been refused"
    assert "re-parent" in refused[0][2], refused


def test_a_summary_at_the_sections_own_level_is_accepted(kv):
    """The control. Same insertion point, level matched to the sections: its
    territory stops at the next `##`, so nothing is re-parented."""
    doc, headings = _doc()
    results = [{"specialist": "summary", "edits": [
        {"line": INSERT_LINE, "op": "insert",
         "new": "## Summary\n\nRequest 11 took 101 ms on attempt 1.\n",
         "why": "one page"}]}]

    _out, applied, refused, _ = kv.merge(
        list(doc), results, set(range(1, len(doc) + 1)), headings=headings)

    assert not refused, refused
    assert [a[2] for a in applied] == ["insert"], applied
    assert "## Summary" in _out[INSERT_LINE - 1] or any(
        "## Summary" in l for l in _out), _out


def test_an_oversized_summary_is_refused(kv):
    """The other bound. Right level, wrong size: `summary_cap` sizes the
    opening page against the body, and a reply can still write past it."""
    doc, headings = _doc()
    cap = kv.summary_cap(kv._summary_words("\n".join(doc)))
    body = " ".join(
        f"Attempt {n} finished the retry budget review at {100 + n} ms."
        for n in range(1, 140))
    assert kv._summary_words(body) > cap, (
        "fixture must exceed the cap for this to be the gate under test")
    results = [{"specialist": "summary", "edits": [
        {"line": INSERT_LINE, "op": "insert", "new": f"## Summary\n\n{body}\n",
         "why": "one page"}]}]

    _out, applied, refused, _ = kv.merge(
        list(doc), results, set(range(1, len(doc) + 1)), headings=headings)

    assert not any(a[2] == "insert" for a in applied), applied
    assert refused, "the oversized summary should have been refused"
    assert "word" in refused[0][2] and "cap" in refused[0][2], refused


def test_the_swallow_gate_holds_on_a_12k_word_document(kv):
    """Same shape as the real hit: the structural gate reads heading levels,
    not word counts, so it must fire the same way on a document sized like
    the one that actually reparented — not only on the smaller fixture above,
    where a live run happened to rewrite the opening instead of inserting."""
    doc, headings = _doc(sections=10, sentences=200)
    words = kv._summary_words("\n".join(doc))
    assert words >= 12000, words
    results = [{"specialist": "summary", "edits": [
        {"line": INSERT_LINE, "op": "insert",
         "new": "# Summary\n\nRequest 11 took 101 ms on attempt 1.\n",
         "why": "one page"}]}]

    _out, applied, refused, _ = kv.merge(
        list(doc), results, set(range(1, len(doc) + 1)), headings=headings)

    assert not any(a[2] == "insert" for a in applied), applied
    assert refused and "re-parent" in refused[0][2], refused
