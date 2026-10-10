"""The `incomplete` list must let a reader reconcile it with its own count."""

import json
import sys
import time
import types

import pytest


def _Args(**kw):
    """`cmd_accept` takes an argparse namespace. Built here rather than
    driven through `main()` so the assertions are about the refusal and not
    about arg parsing, which `test/kill-verbosity.test.js` already covers.
    """
    return types.SimpleNamespace(**{"chat": False, "freeze": None,
                                    "project": None, "searched": None,
                                    "gates_file": None, **kw})


def test_the_record_a_REAL_RUN_writes_carries_the_unit(kv, tmp_path,
                                                       monkeypatch, capsys):
    """Injectivity, on the one artefact `accept` reads -- driven through a
    real `run` and read back off disk.
    """
    tails = [f"waiting at station {n}" for n in range(1, 31)]
    lines = ["# Queue notes", ""] + [
        f"It should be noted that the worker, in point of fact, retries job "
        f"{i} and records the outcome in the store for the purposes of a "
        f"later inspection by whichever operator happens to be {t}."
        for i, t in enumerate(tails, 1)]
    src = tmp_path / "doc.md"
    src.write_text("\n".join(lines) + "\n")
    out = tmp_path / "out.md"

    real_prompt = kv.job_prompt
    seen = []

    def spy(job, *a, **kw):
        real_prompt(job, *a, **kw)
        return f"@@{job['specialist']}@@"

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        seen.append(prompt.split("@@")[1])
        if len(seen) == 1:
            time.sleep(6)
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", [
        "kill-verbosity", "run", str(src), "-o", str(out),
        "--timeout", "5", "--job-timeout", "4"])
    try:
        rc = kv.main()
    except SystemExit as e:
        rc = e.code
    capsys.readouterr()
    assert rc == 1, f"a run with unsent spans exited {rc}"

    spans = json.loads(kv.run_record_path(out).read_text())["incomplete"]
    assert len(spans) >= 3, f"nothing went unsent: {spans}"
    structure = [s for s in spans if s.startswith("structure ")]
    assert len(structure) >= 2, f"the colliding jobs did not run: {spans}"
    assert all("(" in s for s in spans), f"a span with no unit: {spans}"
    assert any("(document)" in s for s in structure), structure
    assert len({s for s in structure}) >= 2, \
        f"distinct structure jobs wrote one string: {structure}"


@pytest.mark.parametrize("spans,want_lines,want_mult", [
    (["structure lines 1-32 (document)",
      "prose lines 2-23 (chunk 2 (1/2) · part 2)"], 2, False),
    (["structure lines 1-32 (repeat · lines 3/32)",
      "structure lines 1-32 (repeat · lines 3/32)",
      "structure lines 1-32 (document)"], 2, True),
    (["prose lines 2-23 (chunk 1 · part 1)",
      "prose lines 2-23 (chunk 1 · part 1)",
      "prose lines 2-23 (chunk 1 · part 1)",
      "structure lines 1-32 (document)"], 2, True),
])
def test_accept_prints_a_list_that_reconciles_with_its_count(
        kv, tmp_path, capsys, spans, want_lines, want_mult):
    src = tmp_path / "doc.md"
    src.write_text("# T\n\nA line of prose here.\n")
    out = tmp_path / "out.md"
    out.write_text("# T\n\nA line of prose here.\n")
    kv.write_run_record(out, source=kv.source_fingerprint(src.read_text()),
                        incomplete=list(spans))
    rc = kv.cmd_accept(_Args(file=str(src), edited=str(out)))
    err = capsys.readouterr().err
    assert rc == 1, "an incomplete run was accepted"
    assert f"left {len(spans)} span(s) unedited" in err, err
    body = [l for l in err.splitlines() if l.startswith("  ")
            and "lines" in l]
    assert len(body) == want_lines, body
    assert ("×" in err) is want_mult, err
    if want_mult:
        total = sum(int(l.split("×")[1]) if "×" in l else 1 for l in body)
        assert total == len(spans), (total, len(spans), body)


def test_a_complete_run_is_still_accepted(kv, tmp_path):
    """The control on the whole file: `incomplete: []` must not refuse."""
    src = tmp_path / "doc.md"
    src.write_text("# T\n\nA line of prose here.\n")
    out = tmp_path / "out.md"
    out.write_text("# T\n\nA line of prose here.\n")
    kv.write_run_record(out, source=kv.source_fingerprint(src.read_text()),
                        incomplete=[])
    assert kv.cmd_accept(_Args(file=str(src), edited=str(out))) == 0
    assert out.read_text() == src.read_text()
