"""The same document and the same answers produce the same file."""
from __future__ import annotations

import hashlib
import json
import random
import sys

from conftest import run_canned

DOC = """# Latency review

It is worth noting that we should utilize the ranking service in order to
facilitate a reduction in the p99, which currently sits at 240 ms.

## Findings

It should be noted that the queue drains in eight seconds under the current
load, and we should probably make a decision about the retry budget.

## Costs

The team will need to prioritize this work prior to the next release in order
to facilitate the saving, which is worth noting at some point.

## What to do

Going forward we should utilize the new path, and it is worth noting that this
will need a decision from the team prior to the cutover.
"""


def _contest_everything(body):
    """Every job rewrites every line it may touch, tagged with its own name."""
    def reply(who, lo, hi):
        top = len(body) if hi is None else min(hi, len(body))
        out = []
        for ln in range(lo, top + 1):
            old = body[ln - 1]
            if not old.strip() or old.lstrip().startswith(("|", "```", ">")):
                continue
            out.append({"line": ln, "old": old, "new": f"{old.rstrip('.')} [{who}]."})
        return out
    return reply


def _shuffled(kv, monkeypatch, seed):
    real = kv.as_completed
    rng = random.Random(seed)
    monkeypatch.setattr(
        kv, "as_completed",
        lambda fs: rng.sample(list(real(fs)), len(list(fs))))


def _run(kv, monkeypatch, tmp_path, seed):
    src = tmp_path / f"d{seed}.md"
    src.write_text(DOC)
    out = tmp_path / f"d{seed}.kv.md"
    body = DOC.rstrip("\n").split("\n")
    _shuffled(kv, monkeypatch, seed)
    seen = run_canned(kv, monkeypatch, src, out, _contest_everything(body))
    return hashlib.md5(out.read_bytes()).hexdigest(), seen


SEEDS = range(8)


def test_several_jobs_share_lines(kv, monkeypatch, tmp_path):
    """The fixture check. With one job per line the rest of the file proves nothing."""
    _, seen = _run(kv, monkeypatch, tmp_path, 0)
    assert len(seen) >= 4, f"only {len(seen)} jobs were dispatched: {seen}"
    assert len({who for who, _unit in seen}) >= 3, seen


def test_the_finishing_order_does_not_change_the_file(kv, monkeypatch, tmp_path):
    """Eight seeded shuffles, one file."""
    digests = {}
    for seed in SEEDS:
        digest, _ = _run(kv, monkeypatch, tmp_path, seed)
        digests.setdefault(digest, []).append(seed)

    assert len(digests) == 1, (
        "the output depends on which agent replied first. `cmd_run` sorts "
        "`results` by specialist before merging; check that sort is still "
        f"there.\n{ {d[:12]: s for d, s in digests.items()} }")


def test_the_results_reach_merge_in_specialist_order(kv, monkeypatch, tmp_path):
    """The mechanism, named. The test above says the file is stable; this says why."""
    order = list(kv.SPECIALISTS)
    orders = []
    real_merge = kv.merge

    def spy(lines, results, *a, **k):
        orders.append([(order.index(r["specialist"]), r["lo"]) for r in results])
        return real_merge(lines, results, *a, **k)

    for seed in SEEDS:
        monkeypatch.setattr(kv, "merge", spy)
        _run(kv, monkeypatch, tmp_path, seed)

    assert orders, "merge was never called"
    for got in orders:
        assert got == sorted(got), f"merge got results out of order: {got}"


TIED = """# Retry review

The retry budget is four attempts and the queue drains in eight seconds.

## Findings

It is worth noting that we should utilize the ranking service in order to
facilitate a reduction in the p99, which sits at 240 ms today.

## Costs

The retry budget is four attempts and the queue drains in eight seconds.

## What to do

Move the ranking call off the request path before the next release ships.
"""

TIED_TEXT = {
    "document": "The queue drains in eight seconds and the retry budget is "
                "four attempts.",
    "repeat · lines 3/12": "The retry budget is four attempts; the queue "
                           "drains in eight seconds.",
}


def _run_tied(kv, monkeypatch, tmp_path, name, reverse):
    src = tmp_path / f"{name}.md"
    src.write_text(TIED)
    out = tmp_path / f"{name}.kv.md"
    body = TIED.rstrip("\n").split("\n")
    units = []

    real_prompt = kv.job_prompt

    def spy(job, *a, **k):
        real_prompt(job, *a, **k)
        units.append(job["unit"])
        return f"@@{job['specialist']}|{job['unit']}|{job['lo']}|{job['hi']}@@"

    def agent(prompt, *_):
        who, unit, _lo, _hi = prompt.split("@@")[1].split("|")
        edits = ([{"line": 3, "old": body[2], "new": TIED_TEXT[unit]}]
                 if who == "structure" and unit in TIED_TEXT else [])
        return json.dumps({"edits": edits, "notes": []}), None

    if reverse:
        real = kv.as_completed
        monkeypatch.setattr(kv, "as_completed", lambda fs: list(real(fs))[::-1])
    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(
        sys, "argv", ["kill-verbosity", "run", str(src), "-o", str(out)])
    kv.main()
    missing = set(TIED_TEXT) - set(units)
    assert not missing, (
        "TIED_TEXT is keyed by unit names the tool no longer emits, so those "
        "jobs returned no edits and there was no tie to observe:\n"
        f"  no longer emitted: {sorted(missing)!r}\n  units seen: {sorted(units)!r}")
    line = out.read_text().split("\n")[2]
    assert line in TIED_TEXT.values(), (
        "line 3 of the output is not either job's edit, so the race assertion "
        "would be comparing an untouched line with itself:\n"
        f"  got: {line!r}\n  expected one of: {sorted(TIED_TEXT.values())!r}")
    return line, units


def test_two_structure_jobs_tie_on_the_sort_key(kv, monkeypatch, tmp_path):
    """The fixture check, because the tie is what the next test is about."""
    _, units = _run_tied(kv, monkeypatch, tmp_path, "t", reverse=False)
    assert "document" in units and "repeat · lines 3/12" in units, units


def test_two_jobs_of_one_specialist_do_not_race(kv, monkeypatch, tmp_path):
    """The sort key has to be total, not nearly total."""
    first, _ = _run_tied(kv, monkeypatch, tmp_path, "a", reverse=False)
    second, _ = _run_tied(kv, monkeypatch, tmp_path, "b", reverse=True)

    assert first == second, (
        "two `structure` jobs tied on the sort key and the faster one won\n"
        f"  submitted order: {first!r}\n"
        f"  reversed order:  {second!r}")


def test_an_uncontested_edit_still_lands(kv, monkeypatch, tmp_path):
    """The boundary. Ordering the results must not drop the ones nothing contests."""
    src = tmp_path / "c.md"
    src.write_text(DOC)
    out = tmp_path / "c.kv.md"
    body = DOC.rstrip("\n").split("\n")
    line = 8
    assert body[line - 1].startswith("It should be noted"), body[line - 1]

    def reply(who, lo, hi):
        if hi is None or not (lo <= line <= hi):
            return []
        return [{"line": line, "old": body[line - 1],
                 "new": "The queue drains in eight seconds under the current"}]

    run_canned(kv, monkeypatch, src, out, reply)

    assert "The queue drains in eight seconds under the current" in out.read_text()
