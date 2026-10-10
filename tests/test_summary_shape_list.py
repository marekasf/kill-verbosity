"""A specialist must be judged against the list it is given."""

import re

import pytest

COMMON_MD = "specialists/_common.md"
SUMMARY_MD = "specialists/summary.md"


@pytest.fixture
def blocking(kv):
    names = set(kv.INSERT_BLOCKING)
    assert len(names) >= 15, f"population is {len(names)} shapes"
    return names


def test_every_specialist_is_told_every_blocking_shape(kv, blocking):
    """The list is on the shared floor, so this covers all seven and not
    just the one that mostly inserts."""
    assert len(kv.SPECIALISTS) >= 6, f"{len(kv.SPECIALISTS)} specialists"
    for name in sorted(kv.SPECIALISTS):
        text = kv.specialist_prompt(name, 1143)
        missing = sorted(n for n in blocking if n not in text)
        assert not missing, f"{name} is not told about: {missing}"


def test_the_words_are_the_ones_the_refusal_uses(kv, blocking):
    """The prompt said `em-dash pile-up` and the gate prints `em-dash
    pressure`, so a writer meeting the refusal had to guess it was the same
    rule. One vocabulary is the point of deriving the list."""
    text = kv.specialist_prompt("summary", 1143)
    assert "em-dash pressure" in text
    assert "em-dash pile-up" not in text
    assert "em-dash pressure" in kv.added_shapes(
        "The plan — the one agreed — is the plan — for now — and it holds.")


def test_the_source_is_derived_and_not_a_copy(kv, blocking):
    """A hand-written copy renders identically today and goes stale on the
    next shape added, which is exactly how the ten got there."""
    src = pathlib_read(COMMON_MD)
    assert "{{INSERT_BLOCKING}}" in src
    para = next(p for p in src.split("\n\n") if "{{INSERT_BLOCKING}}" in p)
    spelled = sorted(n for n in blocking if n in para)
    assert not spelled, f"named by hand beside the placeholder: {spelled}"


def test_summary_does_not_keep_a_second_copy(kv, blocking):
    """It carried its own five-name list. Two lists is the same drift one
    file along, and the shared floor already renders into its prompt."""
    for para in pathlib_read(SUMMARY_MD).split("\n\n"):
        named = sorted(n for n in blocking if n in para)
        assert len(named) < 3, f"summary.md re-lists: {named}"
    assert kv.specialist_prompt("summary", 1143).count("activity report") == 1


def test_a_new_blocking_shape_reaches_every_prompt_with_no_edit(kv, blocking,
                                                                monkeypatch):
    """The whole claim of deriving it. Without this the tests above pass for
    a prompt whose list happens to be right today."""
    monkeypatch.setattr(kv, "INSERT_BLOCKING",
                        frozenset(blocking | {"zzz invented shape"}))
    for name in sorted(kv.SPECIALISTS):
        assert "zzz invented shape" in kv.specialist_prompt(name, 1143)


def test_the_two_reporting_exemptions_are_stated(kv):
    """Listing `parked problem` flat would tell the writer never to name an
    open question -- which is the failure `added_shapes` records, since the
    run then closes by asking for the page it just refused."""
    text = kv.specialist_prompt("summary", 1143)
    exempt = sorted(kv.REPORTING_SHAPES & kv.INSERT_BLOCKING)
    assert exempt, "no reporting exemption exists to document"
    for name in exempt:
        assert re.search(rf"`{re.escape(name)}`", text), \
            f"{name} is exempt when the body carries the words and the " \
            f"prompt does not say so"


def test_a_reword_introducing_jargon_really_is_refused(kv):
    """The behaviour that made the old sentence false. Held as a measurement
    and not as a restatement: if this ever stops being true the prose above
    it is what needs changing, and this is what says so."""
    old = "The team finished the report on Tuesday and sent it to reviewers."
    for new, shape in (
            ("The team leveraged synergies to deliver the report Tuesday.",
             "jargon"),
            ("The generation of the report happened Tuesday for reviewers.",
             "bare nominalisation")):
        introduced = (set(kv.added_shapes(new)) - set(kv.added_shapes(old))
                      | (kv.shapes_in(new) - kv.shapes_in(old)))
        assert shape in introduced, f"{shape} not introduced by {new!r}"
        assert shape not in kv.INSERT_BLOCKING


def test_the_floor_no_longer_promises_jargon_is_uncaught(kv):
    """The false half. A control on the fix, not a restatement of it: the
    replacement half must be stated and the insert exception kept, or the
    repair swapped one wrong sentence for another."""
    text = kv.specialist_prompt("summary", 1143)
    assert "nothing will catch" not in text
    assert re.search(r"replacement.{0,200}any.{0,80}shape", text,
                     re.S | re.I), "the replacement rule is not stated"
    assert re.search(r"[Jj]argon is not on that second list", text), \
        "the insert exception is gone, so jargon now reads as refused"


def test_the_insert_exception_the_prose_promises_still_exists(kv):
    """The behavioural half of `Jargon is not on that second list`. Without
    it the prose is held only against the SET, so a gate that stopped
    filtering to `INSERT_BLOCKING` would refuse jargon on an insert while the
    floor kept telling every specialist it lands -- this fix's own defect,
    rebuilt one layer down.
    """
    both = ("## Summary\n\nIt is worth noting that the team leveraged "
            "synergies across the rollout to deliver the report.\n")
    assert "jargon" in kv.shapes_in(both), "the fixture carries no jargon"
    got = kv.added_shapes(both, both)
    assert "frame" in got, "the blocked shape is not refused: filters nothing"
    assert "jargon" not in got, \
        "jargon is refused on an insert, and the floor says it lands"


def test_the_control_a_clean_summary_paragraph_still_lands(kv):
    """A list this long reads as a refusal of everything. It must not be."""
    good = ("## Summary\n\nThree of seven goals are blocked on one missing "
            "service account (Rollout costs). The adoption figure holds at "
            "12 of 30 teams (Open questions).\n")
    assert kv.added_shapes(good, good) == []


def pathlib_read(rel):
    import pathlib
    return (pathlib.Path(__file__).parent.parent / rel).read_text()
