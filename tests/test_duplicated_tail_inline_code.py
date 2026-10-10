"""A word repeated across a blanked inline-code span is not a duplicated tail.

`mask` blanks inline code to spaces, so "...diverging from the" over
"`TASK_LINE` the genre detector" reached `duplicated_tail` as "the" over
"the genre detector". The one-word fallback paired them and `verify` failed a
file whose wrap was only moved. The span sits between the two words.
"""

from __future__ import annotations

import sys

from conftest import REPO

sys.path.insert(0, str(REPO))

from killverbosity._legacy import duplicated_tail, mask  # noqa: E402


def prose_of(text):
    return mask(text)[0]


def test_word_across_a_blanked_span_at_line_start_is_not_a_repeat():
    text = ("`task list` reads UNCHECKED boxes only, deliberately diverging from the\n"
            "`TASK_LINE` the genre detector reads.\n")
    assert duplicated_tail(prose_of(text)) == []


def test_word_across_a_blanked_span_at_line_end_is_not_a_repeat():
    text = ("It deliberately diverges from the `TASK_LINE`\n"
            "the genre detector reads.\n")
    assert duplicated_tail(prose_of(text)) == []


def test_control_real_one_word_repeat_without_code_still_fires():
    text = ("It deliberately diverges from the\n"
            "the genre detector reads.\n")
    assert duplicated_tail(prose_of(text)) == [(2, "the")]
