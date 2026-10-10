"""`KEEP WHAT LANDED FIRST` must not lead a message about nothing."""

import pytest

ARGS = dict(who="summary", out_name="out.md", journal="out.md.kvjournal",
            accept_cmd="doc.md out.md")


def test_a_run_that_landed_edits_leads_with_keeping_them(kv):
    """The positive control, in the same file rather than a separate arm:
    without it a gate on `applied` could be always-on and every assertion
    below would still pass."""
    said = kv.budget.finish_advice(unsent=0, dead=1, applied=431, **ARGS)
    assert said.startswith("KEEP WHAT LANDED FIRST"), said
    assert "KV_FORCE=1" in said
    assert "Otherwise delete out.md" in said
    assert "431 edits that did land" in said


def test_a_run_that_landed_nothing_leads_with_the_only_remedy(kv):
    said = kv.budget.finish_advice(unsent=0, dead=1, applied=0, **ARGS)
    assert said.startswith("Delete out.md"), said
    assert "KEEP WHAT LANDED FIRST" not in said
    assert "KV_FORCE=1" not in said
    assert "Otherwise" not in said, said
    assert "costs the 0 edits" not in said, said
    assert "landed no edits" in said


def test_the_specialist_is_named_in_both(kv):
    """The remedy is `a different --agent`, which is unactionable without
    knowing which one died."""
    for applied in (0, 431):
        said = kv.budget.finish_advice(unsent=0, dead=1, applied=applied,
                                       **ARGS)
        assert "summary died twice" in said, (applied, said)


@pytest.mark.parametrize("applied", [0, 431])
def test_unsent_jobs_are_still_folded_into_the_one_command(kv, applied):
    """Two commands read as a choice, and resuming is bought and then
    discarded by the switch. The fold must survive the zero case."""
    said = kv.budget.finish_advice(unsent=3, dead=1, applied=applied, **ARGS)
    assert "3 unsent jobs too" in said
    assert "Raise --timeout with it" in said


def test_the_unsent_only_path_is_untouched(kv):
    """R6's own subject, and the control that this edit did not reach it:
    with nothing dead the answer is resume and must not mention deleting."""
    said = kv.budget.finish_advice(unsent=4, dead=0, applied=0, **ARGS)
    assert "run the same command again" in said
    assert "Delete" not in said and "delete" not in said, said
    assert "--agent" not in said, said
