"""One test per numbered row in kill-verbosity-refactor-design.md."""

import json
import sys

import pytest

pytestmark = pytest.mark.regression

ASK = "The summary is buried and it is yours"
DUP = "The pipeline retries the failed job and records the outcome in Loki."
FILLER = (
    "It is worth noting that the deployment check is missing here, and "
    "the team should consider whether to add one going forward. The "
    "review records each outcome so a reader can trace what happened."
)


def _buried_with_extra_structure_jobs(tmp_path):
    """A buried summary on a file that also gives `structure` more than one job."""
    parts = ["# Generative AI Policy", ""]
    parts += [FILLER, ""] * 12
    parts += ["## Summary", "", "Use approved tools only and review outputs.", ""]
    for i in range(8):
        parts += [f"## Section {i}", ""] + [FILLER, ""] * 4 + [DUP, ""]
    p = tmp_path / "buried.md"
    p.write_text("\n".join(parts) + "\n")
    return p


def _dispatch(kv, monkeypatch, path, out):
    """Run the real pipeline with the agent stubbed. One row per job dispatched."""
    seen = []
    real_prompt = kv.job_prompt

    def spy(job, lines, ctx, index, extra, base):
        seen.append((job["specialist"], job["unit"], ASK in ctx))
        return real_prompt(job, lines, ctx, index, extra, base)

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(
        kv, "call_agent", lambda *_: (json.dumps({"edits": [], "notes": ["ok"]}), None)
    )
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(
        sys, "argv", ["kill-verbosity", "run", str(path), "-o", str(out)]
    )
    kv.main()
    return seen


def test_r73_one_job_is_asked_to_report_a_buried_summary(
    kv, monkeypatch, tmp_path, capsys
):
    """The ask sat in the shared context, so all 22 jobs answered it and the two
    notes a person had to read were buried under one sentence repeated."""
    jobs = _dispatch(
        kv,
        monkeypatch,
        _buried_with_extra_structure_jobs(tmp_path),
        tmp_path / "out.md",
    )
    capsys.readouterr()

    structure = [j for j in jobs if j[0] == "structure"]
    assert len(structure) > 1, (
        "the fixture stopped producing several structure jobs, so it can no "
        "longer tell routing by specialist from routing by job"
    )

    asked = [unit for _, unit, has_ask in jobs if has_ask]
    assert asked == ["document"], (
        f"{len(asked)} of {len(jobs)} jobs were asked to report the buried "
        f"summary, not 1: {asked}"
    )
