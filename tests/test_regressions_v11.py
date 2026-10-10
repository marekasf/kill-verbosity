"""One test per defect found in the v11 tester round."""

import pytest
from conftest import run_tool

pytestmark = pytest.mark.regression


def _pair(tmp_path, original, edited):
    """Write an original and an edit, return both paths."""
    o = tmp_path / "orig.md"
    n = tmp_path / "new.md"
    o.write_text(original)
    n.write_text(edited)
    return o, n



A1_ORIG = """# Release gate

## What the gate checks

The pipeline blocks a merge when coverage drops below eighty percent. It is worth noting that this threshold was agreed in March.

Every deploy writes an audit row to the ledger. This is the part that matters for the auditors.
"""

A1_NEW = """# Release gate

## What the gate checks

The pipeline blocks a merge when coverage drops below eighty percent.

Every deploy writes an audit row to the ledger.
"""


def test_a1_content_dropped_names_the_clause_that_went(tmp_path):
    """The two dropped clauses are named and the two survivors are not."""
    o, n = _pair(tmp_path, A1_ORIG, A1_NEW)
    out = run_tool("verify", o, n).stdout

    assert "It is worth noting that this threshold was agreed in March" in out
    assert "This is the part that matters for the auditors" in out
    assert "The pipeline blocks a merge" not in out, out
    assert "Every deploy writes an audit row" not in out, out


def test_a1_a_code_span_is_printed_as_the_author_wrote_it(tmp_path):
    """The guard on the fix this replaced."""
    o, n = _pair(
        tmp_path,
        "# Rules\n\nUse concrete types. It is worth noting that we allow "
        "no `Any` types anywhere in `src/`.\n",
        "# Rules\n\nUse concrete types.\n",
    )
    out = run_tool("verify", o, n).stdout

    assert "no `Any` types" in out, out


def test_a1_the_two_dropped_clauses_are_the_two_reported(tmp_path):
    """The count is right today even though the text shown is not."""
    o, n = _pair(tmp_path, A1_ORIG, A1_NEW)
    out = run_tool("verify", o, n).stdout

    assert "content dropped — 2 sentences" in out, out



A3_ORIG = """# Task list

## 0. Make the code readable

The parser needs names a reader can follow.

## 13. What was done correctly

The retry budget is right and the tests cover it.
"""

A3_NEW = """# Task list

## 13. Settled work

The retry budget is right and the tests cover it.

## 0. Make the code readable

The parser needs names a reader can follow.
"""


def test_a3_a_heading_renamed_and_moved_is_not_gone(tmp_path):
    """Its body is word for word in the edit, under a new name."""
    o, n = _pair(tmp_path, A3_ORIG, A3_NEW)
    out = run_tool("verify", o, n).stdout

    assert "headings gone" not in out, out
    assert "1 heading was renamed" in out, out
    assert "no link or mention left pointing at the old name" in out, out


def test_a3_a_heading_whose_body_also_went_is_still_gone(tmp_path):
    """The false-positive guard. Pair on body overlap and this must stay red."""
    o, n = _pair(
        tmp_path,
        A3_ORIG,
        "# Task list\n\n## 0. Make the code readable\n\n"
        "The parser needs names a reader can follow.\n",
    )
    out = run_tool("verify", o, n).stdout

    assert "headings gone" in out, out
    assert "13. What was done correctly" in out, out



A6_ORIG = """# Handbook

## The one thing to do first

Commit the working tree before you switch branches.

## Runtime risks

The retry budget is shared across every worker.
"""

A6_NEW = A6_ORIG.replace(
    "## The one thing to do first", "## Commit the working tree first"
)


def test_a6_no_anchor_links_means_no_broken_link_warning(tmp_path):
    """Nothing in this file points at the old heading."""
    o, n = _pair(tmp_path, A6_ORIG, A6_NEW)
    out = run_tool("verify", o, n).stdout

    assert "1 heading was renamed" in out, out
    assert "no link or mention left pointing at the old name" in out, out
    assert "breaks every" not in out, out


def test_a6_a_real_inbound_anchor_is_still_named(tmp_path):
    """The other half, and the reason the sentence above can simply go."""
    linked = A6_ORIG.replace(
        "The retry budget is shared across every worker.",
        "See [the first step](#the-one-thing-to-do-first) before you start.",
    )
    o, n = _pair(
        tmp_path,
        linked,
        linked.replace(
            "## The one thing to do first", "## Commit the working tree first"
        ),
    )
    r = run_tool("verify", o, n)

    assert r.returncode == 1, r.stdout
    assert "LINKS BROKEN" in r.stdout, r.stdout
    assert "#the-one-thing-to-do-first" in r.stdout, r.stdout



B1_ORIG = """# Vendor review

The Feb 27 meeting confirmed three key architectural properties. The agent built context across sessions, it survived a restart, and it exported traces to our own store.

The team will decide by 12 March.
"""

B1_NEW = """# Vendor review

At the Feb 27 meeting the agent built context across sessions, survived a restart, and exported traces to our own store.

The team will decide by 12 March.
"""


def test_b1_a_spelled_out_count_is_a_protected_fact(tmp_path):
    """"three" is gone from the whole file and the run must say so."""
    o, n = _pair(tmp_path, B1_ORIG, B1_NEW)
    r = run_tool("verify", o, n)

    assert r.returncode == 3, f"exit {r.returncode}:\n{r.stdout}"
    assert "ids and counts in deleted text" in r.stdout, r.stdout
    assert "number: 3" in r.stdout, r.stdout
    assert "confirmed three key architectural properties" in r.stdout, r.stdout


def test_b1_a_count_dropped_from_surviving_text_fails(tmp_path):
    """The damaging half of the same finding, and the one that has to be hard."""
    o, n = _pair(
        tmp_path,
        "# Audit\n\nThe review confirmed three key architectural properties "
        "of the gateway.\nIt asks for three kinds of name: users, service "
        "accounts and teams.\n",
        "# Audit\n\nThe review confirmed key architectural properties of the "
        "gateway.\nIt asks for users, service accounts and teams.\n",
    )
    r = run_tool("verify", o, n)

    assert r.returncode == 1, f"exit {r.returncode}, not a failure:\n{r.stdout}"
    assert "TOKENS LOST" in r.stdout, r.stdout


def test_b1_a_count_deleted_with_its_sentence_is_still_named(tmp_path):
    """The soft half, which the tool cannot rule on and must not hide."""
    o, n = _pair(
        tmp_path,
        "# Ticket\n\nThe form asks for three kinds of name: users, service "
        "accounts and teams.\n",
        "# Ticket\n\nThe form asks for teams.\n",
    )
    r = run_tool("verify", o, n)

    assert r.returncode == 3, f"exit {r.returncode}:\n{r.stdout}"
    assert "ids and counts in deleted text" in r.stdout, r.stdout
    assert "number: 3" in r.stdout, r.stdout
    assert "three kinds of name" in r.stdout, r.stdout


def test_b1_a_bare_number_word_is_not_a_fact(tmp_path):
    """The false-positive guard."""
    o, n = _pair(
        tmp_path,
        "# Notes\n\nOne of the workers restarts on a bad config, "
        "and no one has traced why.\n",
        "# Notes\n\nA worker restarts on a bad config and nobody has traced why.\n",
    )
    r = run_tool("verify", o, n)

    assert r.returncode != 1, r.stdout



B2_ORIG = """# Review notes

The section walks through the history of Kuldeep's wrong turn on the sampling code.

The fix is to sample after the filter, not before it.
"""

B2_NEW = B2_ORIG.replace("Kuldeep's wrong turn", "the wrong turn")


def test_b2_a_credited_name_cannot_be_dropped_by_a_reword(tmp_path):
    """Reported and read, not failed."""
    o, n = _pair(tmp_path, B2_ORIG, B2_NEW)
    r = run_tool("verify", o, n)

    assert r.returncode == 3, f"exit {r.returncode}:\n{r.stdout}"
    assert "credited names that went" in r.stdout, r.stdout
    assert "said fewer times than before: Kuldeep 1→0" in r.stdout, r.stdout


def test_b2_a_name_in_text_the_skill_deletes_is_not_reported(tmp_path):
    """The second false-positive guard."""
    o, n = _pair(
        tmp_path,
        "# Notes\n\nDana's point about the duplication is a fair one and I "
        "agree with it.\n\nEvery fix lands twice.\n",
        "# Notes\n\nEvery fix lands twice.\n",
    )
    r = run_tool("verify", o, n)

    assert "said fewer times than before" not in r.stdout, r.stdout


def test_b2_a_capitalised_word_that_is_not_a_name_may_go(tmp_path):
    """The false-positive guard."""
    o, n = _pair(
        tmp_path,
        "# Notes\n\nMonday's deploy was clean. Every check passed on the first run.\n",
        "# Notes\n\nThe Monday deploy was clean. Every check passed first time.\n",
    )
    r = run_tool("verify", o, n)

    assert r.returncode != 1, r.stdout



X1_SRC = """# Runbook

The deploy job blocks a merge when coverage drops below eighty percent.

It is worth noting that this threshold was agreed in March.
"""

X1_OUT = """# Runbook

The deploy job blocks a merge when coverage drops below eighty percent.
"""

X1_LATER = "\nThe rollback path uses the previous image digest recorded by the release job.\n"


def _after_a_run(kv, tmp_path, source, output):
    """The two files `run` leaves behind: the output and its record."""
    src = tmp_path / "doc.md"
    out = tmp_path / "doc.kv.md"
    src.write_text(source)
    out.write_text(output)
    kv.write_run_record(
        out,
        agent="codex",
        chat=False,
        inserted=False,
        exempt=[],
        incomplete=[],
        source=kv.source_fingerprint(source),
    )
    return src, out


def test_x1_accept_refuses_when_the_source_changed_after_the_run(kv, tmp_path):
    src, out = _after_a_run(kv, tmp_path, X1_SRC, X1_OUT)
    src.write_text(X1_SRC + X1_LATER)

    r = run_tool("accept", src, out, cwd=str(tmp_path))

    assert r.returncode != 0, f"accepted anyway:\n{r.stdout}\n{r.stderr}"
    assert "rollback path" in src.read_text(), "the edit made after the run is gone"


def test_x1_accept_still_works_on_an_untouched_source(kv, tmp_path):
    """The false-positive guard. The ordinary path must stay one command."""
    src, out = _after_a_run(kv, tmp_path, X1_SRC, X1_OUT)

    r = run_tool("accept", src, out, cwd=str(tmp_path))

    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert src.read_text() == X1_OUT


def test_x1_force_still_overrules_a_changed_source(kv, tmp_path):
    """KV_FORCE is the one way past it, and it says what it costs."""
    src, out = _after_a_run(kv, tmp_path, X1_SRC, X1_OUT)
    src.write_text(X1_SRC + X1_LATER)

    r = run_tool("accept", src, out, cwd=str(tmp_path), force=True)

    assert r.returncode == 4, f"{r.stdout}\n{r.stderr}"
    assert src.read_text() == X1_OUT
    assert "KV_FORCE overruled" in r.stdout, r.stdout
    assert "changed after the run" in r.stdout, r.stdout
