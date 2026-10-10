"""RULES LOST must not fail a correct edit that kept the fact."""

import pytest
from conftest import run_tool

pytestmark = pytest.mark.regression

PADDED_ORIG = """# Rust Usage

## Context

Before we get to the actual problem, some background is helpful. In the visual
team, our core consists of a diffing engine that takes two images and compares
them pixel-wise. It should be noted that image sizes range up to 100
megapixels, which is quite large.
"""

PADDED_EDIT = """# Rust Usage

## Context

Our core is a diffing engine comparing two images pixel-wise, with image sizes
ranging up to 100 megapixels.
"""

NO_TOKEN_ORIG = """# Runbook

The importer reads from the staging bucket and writes to the warehouse.

You must never run this against production.

The warehouse is rebuilt nightly by the scheduler.
"""

NO_TOKEN_EDIT = """# Runbook

The importer reads from the staging bucket and writes to the warehouse.

The warehouse is rebuilt nightly by the scheduler.
"""

STRAY_TOKEN_ORIG = """# Runbook

The importer reads from the staging bucket and writes to the warehouse.

You must never retry the loader more than 3 times against production.

The scheduler waits 3 seconds between polls of the queue.
"""

STRAY_TOKEN_EDIT = """# Runbook

The importer reads from the staging bucket and writes to the warehouse.

The scheduler waits 3 seconds between polls of the queue.
"""


RULE_FRAGMENT_ORIG = """# Status

## Goal 3

Say it plainly in Goal 3. The problem is not that review-agent "needs
upgrades". The upgrade is a draft MR nobody has merged, on top of a service
nobody is maintaining but which is still posting to merge requests. Two
actions, not one.
"""

RULE_FRAGMENT_EDIT = """# Status

## Goal 3

The problem is not that review-agent "needs
upgrades". The upgrade is a draft MR nobody has merged, on top of a service
nobody is maintaining but which is still posting to merge requests. Two
actions, not one.
"""

RULE_FRAGMENT_UNRELATED_GOAL_ORIG = """# Status

## Goal 3

Say it plainly in Goal 3. The problem is not that review-agent "needs
upgrades". The upgrade is a draft MR nobody has merged, on top of a service
nobody is maintaining but which is still posting to merge requests. Two
actions, not one.

## Retro

Never skip the Goal 3 review without sign-off from the maintainer.
"""

RULE_FRAGMENT_UNRELATED_GOAL_EDIT = """# Status

## Goal 3

The problem is not that review-agent "needs
upgrades". The upgrade is a draft MR nobody has merged, on top of a service
nobody is maintaining but which is still posting to merge requests. Two
actions, not one.

## Retro

Never skip the Goal 3 review without sign-off from the maintainer.
"""

DESCRIPTIVE_ORIG = """# Status

## Deploys

The rollout finished on Tuesday. Many teams say the deploy went smoothly.
"""

DESCRIPTIVE_EDIT = """# Status

## Deploys

The rollout finished on Tuesday.
"""

RESTATEMENT_ORIG = """# Meeting room booking process

## How to book a room

It should be noted that rooms must be booked at least one day in advance. This
is a rule and it must be followed at all times by everyone.
"""

RESTATEMENT_EDIT = """# Meeting room booking process

## How to book a room

Rooms must be booked at least one day in advance.
"""

DIFFERENT_RULE_ORIG = """# Runbook

## Cancellations

It should be noted that rooms must be booked at least one day in advance.
Cancellations must be made through the online portal only.
"""

DIFFERENT_RULE_EDIT = """# Runbook

## Cancellations

Rooms must be booked at least one day in advance.
"""


def _verify(tmp_path, orig, edit):
    o, n = tmp_path / "orig.md", tmp_path / "new.md"
    o.write_text(orig)
    n.write_text(edit)
    return run_tool("verify", o, n)


def test_a_short_bare_imperative_is_a_lost_rule(tmp_path):
    """"Say it plainly in Goal 3." must not go unreported."""
    r = _verify(tmp_path, RULE_FRAGMENT_ORIG, RULE_FRAGMENT_EDIT)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout
    assert "Say it plainly in Goal 3." in r.stdout, r.stdout


def test_a_short_rule_is_not_pardoned_by_an_unrelated_goal_mention(tmp_path):
    """One coincidentally-shared word must not clear a two-word claim."""
    r = _verify(tmp_path, RULE_FRAGMENT_UNRELATED_GOAL_ORIG,
                RULE_FRAGMENT_UNRELATED_GOAL_EDIT)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout
    assert "Say it plainly in Goal 3." in r.stdout, r.stdout


def test_a_descriptive_sentence_with_mid_clause_say_is_not_a_lost_rule(
        tmp_path):
    """`say` only marks an opening imperative, not any sentence using it."""
    r = _verify(tmp_path, DESCRIPTIVE_ORIG, DESCRIPTIVE_EDIT)

    assert r.returncode != 1, r.stdout
    assert "RULES LOST" not in r.stdout, r.stdout


def test_a_kept_fact_is_not_a_lost_rule(tmp_path):
    """The frame went, the fact stayed. REVIEW, not FAIL."""
    r = _verify(tmp_path, PADDED_ORIG, PADDED_EDIT)

    assert r.returncode == 3, r.stdout
    assert "RULES LOST" not in r.stdout, r.stdout
    assert "rules reworded" in r.stdout, r.stdout


def test_a_rule_of_plain_words_still_fails(tmp_path):
    """No token to match on, so nothing pardons it."""
    r = _verify(tmp_path, NO_TOKEN_ORIG, NO_TOKEN_EDIT)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout


def test_a_token_surviving_elsewhere_does_not_pardon_the_rule(tmp_path):
    """`3` is still in the file. The prohibition is not."""
    r = _verify(tmp_path, STRAY_TOKEN_ORIG, STRAY_TOKEN_EDIT)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout


def test_a_closing_restatement_of_the_rule_above_it_is_not_lost(tmp_path):
    """an emphasis-only restatement carries no claim of its own."""
    r = _verify(tmp_path, RESTATEMENT_ORIG, RESTATEMENT_EDIT)

    assert r.returncode != 1, r.stdout
    assert "RULES LOST" not in r.stdout, r.stdout
    assert "rules reworded" in r.stdout, r.stdout


def test_a_second_different_rule_in_the_same_paragraph_still_fails(tmp_path):
    """The restatement pardon must not reach a genuinely new obligation."""
    r = _verify(tmp_path, DIFFERENT_RULE_ORIG, DIFFERENT_RULE_EDIT)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout
    assert "Cancellations must be made through the online portal only." \
        in r.stdout, r.stdout


SAME_LINE_ORIG = """# Runbook

## Rooms

It should be noted that rooms must be booked at least one day in advance. This is a rule and it must be followed at all times by everyone. Cancellations must be made through the online portal only.
"""

SAME_LINE_EDIT = """# Runbook

## Rooms

Rooms must be booked at least one day in advance.
"""


def test_the_pardon_is_per_sentence_not_per_line(tmp_path):
    """A restatement pardoned on a line must not pardon a new rule beside it."""
    r = _verify(tmp_path, SAME_LINE_ORIG, SAME_LINE_EDIT)

    assert r.returncode == 1, r.stdout
    assert "Cancellations must be made through the online portal only." \
        in r.stdout, r.stdout
