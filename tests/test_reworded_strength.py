"""`rules reworded` called advice a rule, and the one real rule it found was
correct work.
"""

import argparse
import contextlib
import io

import pytest



def _verify(kv, original, edited):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kv.cmd_verify(argparse.Namespace(
            original=str(original), edited=str(edited), chat=False,
            content_edit=False, exempt=[]))
    return rc, buf.getvalue()


def _reworded(out):
    """The `rules reworded` block's item lines, or [] when it did not fire."""
    lines, inside = [], False
    for ln in out.splitlines():
        if ln.startswith("rules reworded"):
            inside = True
            continue
        if inside:
            if ln.startswith(("  rule ", "  advice")):
                lines.append(ln.strip())
            elif ln.strip():
                break
    return lines



def test_asked_verbs_reads_an_obligation_carrying_its_verb_in_an_infinitive(kv):
    """`must remember to clear` asks for `clear`."""
    got = kv.asked_verbs(
        "you must remember to clear the plaintext afterwards.")
    assert "clear" in got, got

    assert kv.asked_verbs("It should be noted that this covers both.") == set()
    assert kv.asked_verbs(
        "Everything autonomous should be run through the gateway.") == set()

    passive = kv.asked_verbs("The key ought to be rotated each quarter.")
    assert not (passive & kv.inflect.grow("be")), passive

    assert "exercise" not in kv.asked_verbs(
        "You must use the flag to exercise the gates without paying."), \
        "a purpose clause was read as the instructed action"
    assert "read" not in kv.asked_verbs(
        "`--dry-run` cannot, because it writes no record and `accept` needs "
        "one to read.")

    assert "fill" in kv.asked_verbs("please fill out the Request Form.")


def test_the_two_strengths_are_the_same_grammar_decided_by_verb_membership(kv):
    """Why the fix is on the original's side and not in `RECOMMENDATION`."""
    assert kv.rule_strength("Check the plaintext values after sealing.") == 2
    assert kv.rule_strength("Clear the plaintext values after sealing.") == 0



RULE_AND_ADVICE_ORIGINAL = """\
# Deploy runbook

The relay service is the front door for every inbound webhook and it handles
retries on its own.

You must never commit the signing key to version control.

It should be noted that the nightly build runs at 02:00 UTC and reports into
the platform channel.
"""

RULE_AND_ADVICE_EDITED = """\
# Deploy runbook

The relay service is the front door for every inbound webhook and handles
retries itself.

The signing key is not committed to version control.

The nightly build runs at 02:00 UTC and reports into the platform channel.
"""


def test_the_block_separates_a_rule_from_advice_and_prints_the_rule_first(
        kv, tmp_path):
    """One input carrying BOTH shapes, with both outcomes asserted."""
    o, e = tmp_path / "o.md", tmp_path / "e.md"
    o.write_text(RULE_AND_ADVICE_ORIGINAL)
    e.write_text(RULE_AND_ADVICE_EDITED)
    rc, out = _verify(kv, o, e)

    assert rc == 3, f"rc={rc}, and a reworded rule is a review, not a FAIL:\n{out}"
    assert "no block recorded itself" not in out, out

    rows = _reworded(out)
    assert rows, f"the block did not fire at all, so nothing below is tested:\n{out}"
    rules = [r for r in rows if r.startswith("rule ")]
    advice = [r for r in rows if r.startswith("advice")]
    assert len(rules) == 1, rows
    assert len(advice) == 1, rows
    assert "must never commit" in rules[0], rules
    assert "should be noted" in advice[0], advice

    assert rows[0].startswith("rule "), rows

    head = next(l for l in out.splitlines() if l.startswith("rules reworded"))
    assert "1 stated a RULE" in head, head
    assert "1 only gave ADVICE" in head, head


def test_an_advice_only_block_does_not_claim_a_rule_was_stated(kv, tmp_path):
    """The half that was wrong for the whole corpus."""
    o, e = tmp_path / "o.md", tmp_path / "e.md"
    o.write_text(RULE_AND_ADVICE_ORIGINAL.replace(
        "You must never commit the signing key to version control.",
        "You should probably rotate the signing key each quarter."))
    e.write_text(RULE_AND_ADVICE_EDITED.replace(
        "The signing key is not committed to version control.",
        "The signing key is rotated each quarter."))
    rc, out = _verify(kv, o, e)
    assert rc == 3, f"rc={rc}, advice-only is a review, not a FAIL:\n{out}"
    assert "no block recorded itself" not in out, out

    rows = _reworded(out)
    assert rows, f"the block did not fire, so the assertions are vacuous:\n{out}"
    assert not [r for r in rows if r.startswith("rule ")], rows
    head = next(l for l in out.splitlines() if l.startswith("rules reworded"))
    assert "stated a RULE" not in head, head
    assert "only gave ADVICE" in head, head







def test_the_cap_is_one_budget_across_both_kinds(kv, tmp_path):
    """Eight rows in total, not eight of each, and the notice counts rows."""
    rules = [f"You must never delete the {w} record before the audit closes."
             for w in ("alpha", "bravo", "charlie", "delta", "echo",
                       "foxtrot", "golf", "hotel", "india", "juliett")]
    advice = [f"It should be noted that the {w} job runs at 03:00 each night."
              for w in ("kilo", "lima", "mike", "november")]
    o = tmp_path / "o.md"
    e = tmp_path / "e.md"
    o.write_text("# T\n\n" + "\n\n".join(rules + advice) + "\n")
    e.write_text("# T\n\n" + "\n\n".join(
        [r.replace("You must never delete", "The deletion of").replace(
            " before the audit closes", " is held until the audit closes")
         for r in rules]
        + [a.replace("It should be noted that the", "The") for a in advice]) + "\n")
    rc, out = _verify(kv, o, e)

    rows = _reworded(out)
    assert rows, f"the block did not fire, so the cap is untested:\n{out}"
    assert len(rows) <= 8, f"{len(rows)} rows printed under an 8-row cap: {rows}"
    notice = [l for l in out.splitlines() if "worth reading first" in l]
    if len(rows) == 8:
        assert notice, f"8 rows printed and nothing said the list was cut:\n{out}"
    else:
        assert not notice, (
            f"{len(rows)} rows printed — every one of them — and the report "
            f"still announced a truncation:\n{notice}")
    assert rc in (1, 3), rc
