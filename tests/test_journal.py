"""A killed run keeps the replies it already paid for."""

import json
import sys

import pytest
from conftest import REPO

DOC = REPO / "tests" / "fixtures" / "review-findings.md"



def _canned(kv, monkeypatch, path, out, stop_after=None, agent_name=None,
            die_after=None, crash_at=None):
    """Run the pipeline against a fake agent. Returns the prompts it answered."""
    asked, crashed = [], []
    real_prompt = kv.job_prompt

    def spy(job, *a, **k):
        real_prompt(job, *a, **k)
        return f"@@{job['specialist']}|{job['lo']}|{job['hi']}@@"

    def agent(prompt, *_):
        if stop_after is not None and len(asked) >= stop_after:
            raise KeyboardInterrupt
        if crash_at is not None and len(asked) == crash_at and not crashed:
            crashed.append(prompt)
            raise RuntimeError("the backend library raised")
        if die_after is not None and len(asked) >= die_after:
            return "", "the backend closed the connection"
        asked.append(prompt)
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(
        sys, "argv", ["kill-verbosity", "run", str(path), "-o", str(out)]
        + (["--agent", agent_name] if agent_name else []))
    try:
        kv.main()
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and not e.code:
            pass
        elif isinstance(e, SystemExit):
            raise
    except RuntimeError:
        if crash_at is None:
            raise
    return asked


@pytest.fixture
def doc(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(DOC.read_text())
    return p


def test_a_killed_run_banks_what_it_answered(kv, monkeypatch, doc, tmp_path):
    out = tmp_path / "doc.kv.md"
    asked = _canned(kv, monkeypatch, doc, out, stop_after=2)

    assert len(asked) == 2
    rows = [json.loads(x)
            for x in kv.journal_path(out).read_text().splitlines()]
    assert len(rows) == 2
    assert {r["key"] for r in rows} == {kv.journal_key(p) for p in asked}


def test_the_rerun_pays_only_for_what_is_left(kv, monkeypatch, doc, tmp_path):
    out = tmp_path / "doc.kv.md"
    first = _canned(kv, monkeypatch, doc, out, stop_after=2)
    second = _canned(kv, monkeypatch, doc, out)

    assert out.is_file(), "the rerun wrote no output"
    assert not set(first) & set(second), "a banked answer was bought again"
    assert second, "the rerun asked nothing at all"
    assert not kv.journal_path(out).exists(), "the journal outlived the output"


def test_an_edited_source_throws_the_journal_away(kv, monkeypatch, doc,
                                                  tmp_path):
    """The prompts carry the document, so a change already moves every key.
    This is the second lock: one stale row and the whole file is refused."""
    out = tmp_path / "doc.kv.md"
    _canned(kv, monkeypatch, doc, out, stop_after=2)

    assert kv.read_journal(out, "not-the-fingerprint") == {}


def test_switching_backend_does_not_replay_the_first_ones_answers(
        kv, monkeypatch, doc, tmp_path):
    """The prompt does not say which agent sent it, so nothing else stops the
    second backend being credited with the first one's work."""
    out = tmp_path / "doc.kv.md"
    first = _canned(kv, monkeypatch, doc, out, stop_after=2, agent_name="codex")
    second = _canned(kv, monkeypatch, doc, out, agent_name="gemini")

    assert set(first) <= set(second), "a banked codex answer was reused"


def test_the_second_backend_can_still_resume_its_own_run(
        kv, monkeypatch, doc, tmp_path):
    """One row it does not recognise makes `read_journal` refuse the file, so a
    switch that appended would bury the new backend's answers behind the old
    one's and every rerun after it would pay again."""
    out = tmp_path / "doc.kv.md"
    _canned(kv, monkeypatch, doc, out, stop_after=2, agent_name="codex")
    first = _canned(kv, monkeypatch, doc, out, stop_after=2,
                    agent_name="gemini")
    second = _canned(kv, monkeypatch, doc, out, agent_name="gemini")

    assert not set(first) & set(second), "gemini paid for its own answer twice"


def test_the_same_backend_still_resumes(kv, monkeypatch, doc, tmp_path):
    out = tmp_path / "doc.kv.md"
    first = _canned(kv, monkeypatch, doc, out, stop_after=2, agent_name="codex")
    second = _canned(kv, monkeypatch, doc, out, agent_name="codex")

    assert not set(first) & set(second), "a banked answer was bought again"


def test_a_run_with_a_dead_job_keeps_its_journal(kv, monkeypatch, doc,
                                                 tmp_path):
    """The run finishes, says it cannot be accepted and asks for a rerun. The
    answers it did buy have to survive that."""
    out = tmp_path / "doc.kv.md"
    asked = _canned(kv, monkeypatch, doc, out, die_after=2)

    assert len(asked) == 2, "the fake backend answered more than it was told to"
    assert kv.journal_path(out).is_file(), \
        "the rerun it asks for pays for every job again"


def test_a_crashing_job_does_not_take_the_others_answers_with_it(
        kv, monkeypatch, doc, tmp_path):
    """The design doc carried "a crash mid-run throws away every paid call" as
    open. It is not: the journal closed it. This is the test that says so, and
    that fails if an `except Exception` is ever put where it would swallow the
    write.
    """
    out = tmp_path / "doc.kv.md"
    asked = _canned(kv, monkeypatch, doc, out, crash_at=2)

    assert kv.journal_path(out).is_file(), \
        "a crash threw away every answer the run had already paid for"
    rows = [json.loads(x)
            for x in kv.journal_path(out).read_text().splitlines()]
    assert len(rows) == len(asked), \
        f"{len(asked)} answers bought, {len(rows)} banked"


def test_the_rerun_after_a_crash_buys_only_the_job_that_crashed(
        kv, monkeypatch, doc, tmp_path):
    out = tmp_path / "doc.kv.md"
    first = _canned(kv, monkeypatch, doc, out, crash_at=2)
    second = _canned(kv, monkeypatch, doc, out)

    assert out.is_file(), "the rerun wrote no output"
    assert not set(first) & set(second), "a banked answer was bought again"
    assert len(second) == 1, \
        f"the rerun bought {len(second)} jobs; only the crashed one was missing"


def test_a_clean_run_deletes_its_journal(kv, monkeypatch, doc, tmp_path):
    out = tmp_path / "doc.kv.md"
    _canned(kv, monkeypatch, doc, out)

    assert not kv.journal_path(out).exists()


def test_a_half_written_last_line_is_dropped(kv, tmp_path):
    """What a kill mid-write leaves behind."""
    out = tmp_path / "doc.kv.md"
    kv.journal_path(out).write_text(
        json.dumps({"source": "f", "key": "a", "result": {"edits": []}})
        + '\n{"source": "f", "key": "b", "resu')

    assert list(kv.read_journal(out, "f")) == ["a"]


def test_a_row_that_is_not_a_row_is_dropped(kv, tmp_path):
    """A line can be valid JSON and still not be one of ours."""
    out = tmp_path / "doc.kv.md"
    kv.journal_path(out).write_text(
        '3\n[]\n{"source": "f"}\n'
        + json.dumps({"source": "f", "key": "a", "result": {"edits": []}}))

    assert list(kv.read_journal(out, "f")) == ["a"]


def test_the_journal_survives_a_document_that_is_not_ascii(kv, tmp_path):
    """The prompts carry the document, so the answers carry its characters."""
    out = tmp_path / "doc.kv.md"
    kv.journal_path(out).write_text(
        json.dumps({"source": "f", "key": "a", "result": {"note": "wpłynął ×"}}),
        encoding="utf-8")

    assert kv.read_journal(out, "f")["a"] == {"note": "wpłynął ×"}
