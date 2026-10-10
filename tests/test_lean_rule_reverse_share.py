"""`as_rule` scored a lean rewrite against the wrong direction."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

TAIL = "Confirm the service restarted."

SWEEP_ORIGINAL = (
    "The decision that has been made is that you must never run the apply "
    "step on router4 while it is serving DHCP."
)

SW = {
    "sw1": "You must never run the apply step on router4 while it is serving DHCP.",
    "sw2": "You must never run the apply step on router4 while it serves DHCP.",
    "sw3": "Never run the apply step on router4 while it serves DHCP.",
    "sw4": "Never run apply on router4 while it serves DHCP.",
    "sw5": "Never run apply on router4 while DHCP serves.",
    "sw6": "Never apply on router4 while DHCP serves.",
}
SW_ALREADY_CLEAN = ("sw1", "sw2", "sw3")
SW_WAS_TRIPPING = ("sw4", "sw5", "sw6")

CONTROL_ORIGINAL = "Never run the apply step on router4 while it is serving DHCP."

DEMOTED = "The apply step on router4 runs only after DHCP has stopped serving."
SPLIT_KEEP = ("Never run the apply step on router4.",
              "It is serving DHCP until step 6.")
SPLIT_DROP = ("The apply step on router4 waits.",
              "DHCP is still serving until step 6.")
LEAN_KEEP = "Never run apply on router4 while it serves DHCP."


def _survived(kv, original, rewrite_lines):
    """True if `original`'s rule reads as fully, cleanly kept."""
    o = [original, "", TAIL]
    n = [*rewrite_lines, "", TAIL]
    gone, weak, _thin, _rel = kv.claims_lost(o, n)
    lost = {s for _l, s in gone} | {s for _l, s in weak}
    return original not in lost


@pytest.mark.parametrize("name", SW_ALREADY_CLEAN)
def test_a_form_that_already_read_as_clean_still_does(kv, name):
    assert _survived(kv, SWEEP_ORIGINAL, [SW[name]]), (
        f"{name} regressed: a form the tool already read as a clean "
        "survival now trips")


@pytest.mark.parametrize("name", SW_WAS_TRIPPING)
def test_a_leaner_correct_compression_now_reads_as_clean(kv, name):
    """The RED case. Before the fix these three scored recall against the
    22-word original, fell under `CLAIM_KEPT`, and were only pardoned by the
    `gone`-list rescue -- reported as "rules reworded", not a clean pass.
    `test_the_old_forward_direction_still_trips_the_same_forms` reproduces
    that on a mutant so this assertion is not taken on faith.
    """
    assert _survived(kv, SWEEP_ORIGINAL, [SW[name]]), (
        f"{name} (a correct, leaner compression of the same rule) still "
        "trips -- as_rule is still asking recall-against-the-original")


def test_a_split_that_keeps_the_rule_word_stays_clean(kv):
    assert _survived(kv, CONTROL_ORIGINAL, list(SPLIT_KEEP))


def test_a_lean_one_step_compression_stays_clean(kv):
    assert _survived(kv, CONTROL_ORIGINAL, [LEAN_KEEP])


def test_a_split_that_drops_the_rule_word_from_both_halves_still_trips(kv):
    """The overshoot guard. A reverse-direction test that stopped asking for
    the rule word at all would pardon this too -- the fix must not go that
    far: neither half reads as a rule (`r >= was`) and the original's own
    verb is not one `asked_verbs` reads off "Never run ...", so neither half
    nor the pair should ever reach `as_rule`'s candidate list.
    """
    assert not _survived(kv, CONTROL_ORIGINAL, list(SPLIT_DROP))


def test_a_rule_demoted_to_a_description_still_trips(kv):
    """The other overshoot guard. Same words, same subject, no more rule --
    `runs only after DHCP has stopped serving` is a fact, not a prohibition,
    and reverse word-overlap alone cannot tell the two apart. Only the
    `r >= was or asked_verbs` gate does, and it must still be asked before
    any survivor is a candidate.
    """
    assert not _survived(kv, CONTROL_ORIGINAL, [DEMOTED])



OLD_REV = (
    "        rev = [(rev_share(n), r, t, o) for n, r, o, t, _f, _h in spans]"
)
FORWARD_REV = (
    "        rev = [(share(k, f, h), r, t, o) for n, r, o, t, f, h in spans]"
)


def _mutant(tmp_path):
    """`_legacy.py` with `as_rule` put back to recall-against-the-original."""
    src = (REPO / "killverbosity" / "_legacy.py").read_text()
    assert src.count(OLD_REV) == 1, (
        "the mutation target is not in the source exactly once, so this "
        "mutant would test nothing")
    path = tmp_path / "mutant_legacy.py"
    path.write_text(src.replace(OLD_REV, FORWARD_REV))

    name = "kv_mutant_g593_%s" % tmp_path.name
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    return mod


@pytest.mark.parametrize("name", SW_WAS_TRIPPING)
def test_the_old_forward_direction_still_trips_the_same_forms(tmp_path, name):
    """Put the pre-fix scoring back and the leaner forms trip again -- the
    state this suite's own run was in before the fix, reproduced rather than
    remembered."""
    mut = _mutant(tmp_path)

    assert not _survived(mut, SWEEP_ORIGINAL, [SW[name]]), (
        f"the mutant did not change behaviour on {name}, so it says "
        "nothing about the fix")


def test_the_old_forward_direction_does_not_disturb_the_controls(tmp_path):
    """The mutant changes only the RED forms above -- the already-clean sw1-3
    and the two overshoot controls read the same either way, which is what
    makes the RED/GREEN contrast on sw4-6 the fix's doing and not some wider
    change of behaviour the mutation happened to trigger."""
    mut = _mutant(tmp_path)

    for name in SW_ALREADY_CLEAN:
        assert _survived(mut, SWEEP_ORIGINAL, [SW[name]]), name
    assert not _survived(mut, CONTROL_ORIGINAL, list(SPLIT_DROP))
    assert not _survived(mut, CONTROL_ORIGINAL, [DEMOTED])
