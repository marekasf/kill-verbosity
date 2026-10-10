"""R102 — three block forms `mask` kept in prose."""


DOC = """\
Title
=====

Lead paragraph.

a | b
--- | ---
1 | 2

> quoted line one
and this carries on the same quotation.

## Ordinary heading

| x | y |
|---|---|
| 3 | 4 |
"""


def _mask(kv, text):
    prose, headings, tables, quotes = kv.mask(text, "doc")
    return prose, headings, tables, quotes


def test_a_setext_heading_is_a_heading(kv):
    prose, headings, _, _ = _mask(kv, DOC)

    assert ("Title", 1) in [(h[2], h[1]) for h in headings]
    assert prose[0] == "" and prose[1] == ""


def test_a_table_without_outer_pipes_is_a_table(kv):
    prose, _, tables, _ = _mask(kv, DOC)

    assert [t[0] for t in tables] == [6, 7, 8, 15, 17]
    assert all(prose[i - 1] == "" for i in (6, 7, 8, 15, 16, 17))


def test_a_lazy_quotation_line_is_still_the_quotation(kv):
    prose, _, _, quotes = _mask(kv, DOC)

    assert [q[0] for q in quotes] == [10, 11]
    assert prose[10] == ""


def test_front_matter_is_not_read_as_a_heading(kv):
    """Without the front-matter plugin this is the expensive failure."""
    _, headings, _, _ = _mask(kv, "---\ntitle: x\n---\n\n# T\n\nbody.\n")

    assert [h[2] for h in headings] == ["T"]


def test_the_parser_puts_nothing_back_that_the_scan_cut(kv):
    """The scan is the authority wherever it has an answer."""
    prose, headings, tables, quotes = _mask(
        kv, "# T\n\n```\nTitle\n=====\n\na | b\n--- | ---\n```\n\nbody.\n")

    assert [h[2] for h in headings] == ["T"]
    assert tables == [] and quotes == []
