"""A named person said it. That is content, not decoration."""
from killverbosity.attribution import lines


def L(*rows):
    return lines(list(rows))


def test_a_name_and_a_date_is_a_record():
    assert L("**Alex, 2026-09-02:** fix it, not write it.") == {1}


def test_a_possessive_is_a_record():
    assert L("**Alex's answer to that:** fix it, not write it.") == {1}


def test_the_real_line_that_was_lost():
    assert L("**Alex's answer to that: fix it, not write it.**") == {1}


def test_a_two_word_name_still_matches():
    assert L("**Priya Kumar, 2026-05-14:** ship it this week.") == {1}


def test_a_bare_label_is_not_a_record():
    """`**Note:**` and `**Warning:**` are decoration. Freezing every bold
    label would freeze most of the document and the pass would do nothing."""
    assert L("**Note:** this is ordinary emphasis.") == set()
    assert L("**Warning:** mind the gap.") == set()


def test_a_group_without_a_date_is_not_a_record():
    """Requiring a digit is what keeps `**Engineering, all teams:**` out."""
    assert L("**Engineering, all teams:** please read.") == set()


def test_a_lowercase_possessive_is_not_a_name():
    assert L("**today's plan:** do the thing.") == set()


def test_a_list_item_attribution_is_found():
    """Decision logs write them as bullets more often than as paragraphs."""
    assert L("- **Alex, 2026-09-02:** fix it, not write it.") == {1}


def test_an_attribution_mid_sentence_is_left_alone():
    """Only at the start of a line. Inside a sentence it is a mention, and
    freezing the whole line would freeze ordinary prose that names someone."""
    assert L("As **Alex, 2026-09-02:** said, we ship.") == set()


def test_the_right_line_number_comes_back():
    assert L("intro", "", "**Alex, 2026-09-02:** yes.", "tail") == {3}


def test_several_attributions_all_come_back():
    got = L("**Alex, 2026-09-02:** yes.", "**Sam, 2026-04-01:** no.")
    assert got == {1, 2}



def test_a_company_possessive_is_frozen_too_and_that_is_the_safe_direction():
    """DECLARED LIMIT, asserted rather than left in a docstring."""
    assert L("**Acme's approach:** ship the smallest thing.") == {1}


def test_a_long_possessive_phrase_is_not_frozen():
    """The other end of the same limit: the middle is capped at 60 characters."""
    middle = "answer to the question that came up in the review last week and"
    assert len(middle) > 60
    assert L(f"**Alex's {middle}:** fix it.") == set()



def test_an_attribution_reaches_the_protected_set(kv):
    """A module nothing calls protects nothing."""
    prose = ["# T", "", "**Alex, 2026-09-02:** fix it, not write it.", "",
             "An ordinary paragraph that a specialist may shorten."]
    got = kv.keep_lines(prose)
    assert 3 in got, got
    assert 5 not in got, got
