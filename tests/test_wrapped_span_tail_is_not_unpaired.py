"""The tail of a quotation or code span wrapped across two
lines kept its text, so its lone delimiter reached the prose stream and the run
hard-failed as UNPAIRED with the quotation intact."""

from __future__ import annotations


def _prose(kv, text):
    return kv.mask(text, "doc.md")[0]


def test_wrapped_quotation_tail_is_not_unpaired(kv):
    prose = _prose(kv, '"A line that is nothing but one whole quotation."\n\n'
                       'He said "a quotation that wraps across\n'
                       'the line break like this one does."\n')
    assert kv.unpaired_paragraphs(prose) == {}
    assert prose[0] == '"A line that is nothing but one whole quotation."'


def test_wrapped_code_span_tail_is_not_unpaired(kv):
    prose = _prose(kv, "`a whole code span on its own line`\n\n"
                       "Run `python3 -m pytest tests\n"
                       "--collect-only`\n")
    assert kv.unpaired_paragraphs(prose) == {}
    assert prose[0] == "`a whole code span on its own line`"
