"""An incomplete run gives one instruction, not three that fight."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from killverbosity import budget


def _advice(unsent: int, dead: int, applied: int = 45) -> str:
    return budget.finish_advice(unsent, dead, "prose,quotable", applied,
                                "doc.kv.md", "doc.kv.md.kvjournal")


def test_unsent_jobs_alone_say_rerun_the_same_command():
    out = _advice(3, 0)
    assert "run the same command again" in out
    assert "Delete" not in out


def test_dead_jobs_alone_say_switch_backend_and_what_it_costs():
    out = _advice(0, 2)
    assert "Delete doc.kv.md and rerun with a different --agent" in out
    assert "45 edits" in out
    assert "pays only for what is left" not in out


def test_one_dead_job_makes_the_switch_the_whole_answer():
    """A dead job was asked twice, so the same backend will not answer it, and
    the switch starts the file over — the journal is keyed by backend. Resuming
    first would buy answers that restart throws away."""
    out = _advice(3, 2)
    assert "Delete doc.kv.md and rerun with a different --agent" in out
    assert "run the same command again" not in out


def test_the_unsent_jobs_are_still_named_and_folded_into_that_command():
    out = _advice(3, 2)
    assert "3 unsent jobs" in out
    assert "Raise --timeout" in out


def test_one_unsent_job_is_singular():
    assert "1 unsent job " in _advice(1, 2)


def test_one_landed_edit_is_singular():
    assert "the 1 edit that did land" in _advice(0, 1, applied=1)


def test_no_narrowed_rerun_is_ever_suggested():
    """A second run writes the output from scratch, so redoing the dead spans
    alone throws away every edit that landed."""
    assert "no way to redo the dead spans" in _advice(0, 2)


def test_only_one_command_is_ever_printed():
    for unsent, dead in ((3, 0), (0, 2), (3, 2), (1, 1)):
        out = _advice(unsent, dead)
        commands = ("run the same command again" in out) \
            + ("rerun with a different --agent" in out)
        assert commands == 1, (unsent, dead, out)
