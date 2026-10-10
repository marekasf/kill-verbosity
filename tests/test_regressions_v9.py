"""One test per numbered defect from one review round."""

import argparse
import json
import os
import subprocess
import sys

import pytest
from conftest import LAUNCHER, REPO, run_canned, run_tool

pytestmark = pytest.mark.regression

FILLER = "The team reviews each deployment for accuracy and records the outcome."


def _policy(title_level, tmp_path, words=90):
    """P340's reproduction: three files identical but for one `#`."""
    p = tmp_path / f"policy-{len(title_level)}.md"
    p.write_text(
        f"{title_level} Generative AI Policy\n\n"
        f"## Summary\n\n"
        f"Use approved tools only and review every output before use.\n\n"
        f"## Body\n\n" + " ".join([FILLER] * words) + "\n"
    )
    return p


def _opening_summary(path):
    r = run_tool("plan", path, "--json")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["opening_summary"]


def test_p340_level_one_title_finds_the_summary(tmp_path):
    """The case that already works. It anchors the two below."""
    assert _opening_summary(_policy("#", tmp_path))["present"] is True


@pytest.mark.parametrize("level", ["##", "###"])
def test_p340_summary_is_found_whatever_level_the_title_uses(level, tmp_path):
    """A Markdown export from Google Docs starts at `##`, so this is a whole
    class of real document reported as having no summary when it has one."""
    assert _opening_summary(_policy(level, tmp_path))["present"] is True


def test_p340_a_first_heading_that_is_the_summary_is_not_a_title(kv):
    """The rule that says a title is not just "the first heading"."""
    doc = [
        "## Summary",
        "",
        "The result in one line.",
        "",
        "plain text.",
        "",
        "more.",
        "",
        "and more.",
        "",
        "end.",
    ]
    heads = [(0, 2, "Summary")]
    assert kv.has_title(heads, doc) is False
    assert kv.opening_summary(heads, doc, kv.SUMMARY_NEEDED_FROM)["present"]


def test_p340_a_summary_insert_lands_under_a_level_two_title(kv):
    """The half that would have got worse if only the detector were fixed."""
    doc = [
        "## Generative AI Policy",
        "",
        "## Body",
        "",
        "Use approved tools.",
        "",
        "More body text here.",
        "",
        "The end of the document.",
    ]
    heads = ((0, 2, "Generative AI Policy"), (2, 2, "Body"))
    got, ok, no, _ = kv.merge(
        doc,
        [
            {
                "specialist": "summary",
                "edits": [
                    {
                        "op": "insert",
                        "line": 8,
                        "new": "## Summary\n\nThe result in one line.",
                        "why": "no summary",
                    }
                ],
            }
        ],
        set(range(1, len(doc) + 1)),
        (),
        heads,
        0,
    )
    assert ok, (ok, no)
    assert not no, no
    title = got.index("## Generative AI Policy")
    summary = next(i for i, ln in enumerate(got) if ln.startswith("## Summary"))
    assert title < summary, got


def test_p340_a_section_heading_with_a_body_is_not_a_title(kv):
    """The wiki layout: no title, the file opens straight into a section."""
    doc = ["## Setup", "", "Install it and run it.", "", "## Notes", "", "More."]
    heads = [(0, 2, "Setup"), (4, 2, "Notes")]
    assert kv.has_title(heads, doc) is False


def _transcript(tmp_path):
    """Timestamp headings, which is what makes the detector read a transcript."""
    p = tmp_path / "call.md"
    p.write_text(
        "# Call\n\n"
        + "".join(
            f"###### 10:0{i % 10} alex\n\n{FILLER} {FILLER}\n\n" for i in range(30)
        )
    )
    return p


def _project(folder, **fields):
    """The project file the tool finds beside the document."""
    (folder / ".killverbosity.json").write_text(json.dumps(fields))


def _only(tmp_path, *names):
    p = _transcript(tmp_path)
    _project(tmp_path, specialists=list(names))
    return p


def test_p357_a_genre_disabled_specialist_is_not_called_nonexistent(tmp_path):
    """`actionable` exists. `genre-transcript.json` switched it off."""
    r = run_tool("run", _only(tmp_path, "actionable"), "--dry-run")
    msg = r.stderr + r.stdout
    assert "no such specialist" not in msg, msg
    assert "switched off" in msg, msg
    assert "genre-transcript" in msg, msg


def test_p357_a_real_typo_still_says_no_such_specialist(tmp_path):
    """The other half. Naming the genre for everything would hide a typo."""
    r = run_tool("run", _only(tmp_path, "nosie"), "--dry-run")
    assert "no such specialist: nosie" in r.stderr + r.stdout


def test_p350_a_wrapped_line_of_backticks_is_named_not_just_numbered(tmp_path):
    """The finding said the tool was wrong. Checked against a CommonMark
    renderer, the document is genuinely broken: the rest of that sentence is
    swallowed into a code block and never displayed. So the error stays, and
    what it says is the fix — the old message gave a line number for a fence
    the author could not find, because `grep '^```'` misses an indented one.
    """
    p = tmp_path / "wrapped.md"
    p.write_text(
        "# Title\n\n"
        "- **Output is a file.** Claude writes JSON to `out_file`;\n"
        '  the script reads it. This sidesteps the fragile "find the\n'
        '  ```json fence in stdout" parsing the MR uses.\n\n'
        + " ".join([FILLER] * 40)
        + "\n"
    )
    r = run_tool("plan", p)
    assert r.returncode == 2, r.stdout
    assert "```json fence in stdout" in r.stderr, r.stderr
    assert "start a wrapped line" in r.stderr, r.stderr


def test_p350_a_forgotten_closer_is_not_blamed_on_wrapping(tmp_path):
    """The other branch. A fence that opens a block after a blank line is a
    forgotten closer, and telling that author to rewrap a paragraph is noise.
    """
    p = tmp_path / "forgot.md"
    p.write_text(
        "# Title\n\nHere is the code:\n\n```python\nx = 1\n\n"
        + " ".join([FILLER] * 40)
        + "\n"
    )
    r = run_tool("plan", p)
    assert r.returncode == 2, r.stdout
    assert "start a wrapped line" not in r.stderr, r.stderr
    assert "Close it" in r.stderr, r.stderr


ES = "El equipo revisa cada despliegue y registra el resultado obtenido."


def test_p342_a_profile_blind_to_the_rule_check_says_so(tmp_path):
    """A Spanish rule can be deleted and the run still exits 3."""
    p = tmp_path / "es.md"
    p.write_text(
        "# Politica\n\n## Resumen\n\n"
        + ES
        + "\n\n## Cuerpo\n\n"
        + " ".join([ES] * 120)
        + "\n"
    )
    _project(tmp_path, profile="es")
    out = run_tool("plan", p).stdout
    assert "no words for" in out, out
    assert "rule word" in out, out


def test_p342_the_default_profile_does_not_warn(tmp_path):
    """The other half, and the reason the warning is scoped to the rule check."""
    p = tmp_path / "en.md"
    p.write_text(
        "# Policy\n\n## Summary\n\n"
        + FILLER
        + "\n\n## Body\n\n"
        + " ".join([FILLER] * 120)
        + "\n"
    )
    assert "no words for" not in run_tool("plan", p).stdout


def _reference(tmp_path):
    """Table rows are what make the detector read a reference document."""
    p = tmp_path / "ref.md"
    out = ["# API Reference", ""]
    for s in range(14):
        out += [f"## Section {s}", "", "| Field | Type | Meaning |", "|---|---|---|"]
        out += [
            f"| field_{s}_{r} | string | the value recorded for run {r} |"
            for r in range(14)
        ]
        out.append("")
    p.write_text("\n".join(out) + "\n")
    return p


def test_p346_a_summary_switched_off_does_not_print_the_demand_for_one(tmp_path):
    """`genre-reference` turns `summary` off because a reference document is not
    owed one. The reason printed was the demand: "MISSING — 2781 words with no
    one-page summary at the top." That is the opposite of why it did not run.
    """
    out = run_tool("run", _reference(tmp_path), "--dry-run").stdout
    line = next(ln for ln in out.splitlines() if ln.strip().startswith("summary"))
    assert "MISSING" not in line, line
    assert "genre-reference" in line, line


def test_p346_the_other_switched_off_specialist_says_so_too(tmp_path):
    """`actionable` went from one job to none on the same profile and printed
    nothing at all, so its absence read as "found nothing" rather than "never
    asked"."""
    out = run_tool("run", _reference(tmp_path), "--dry-run").stdout
    assert "actionable" in out, out
    line = next(ln for ln in out.splitlines() if "actionable" in ln)
    assert "genre-reference" in line, line


def test_p347_one_line_pair_is_printed_once(kv):
    """Two different repeated phrases can sit on the same two lines. The print
    carries the numbers and nothing else, so a run listed `143, 173` twice and
    the five clusters it claimed to show were four rows a reader could separate.
    """
    got = kv.cluster_lines(
        [{"lines": [143, 173]}, {"lines": [143, 173]}, {"lines": [9, 11]}]
    )
    assert got == "143, 173 (2 texts); 9, 11", got


def test_p347_introduced_repeats_come_back_with_their_lines(kv):
    """It was the one count in the block with no line numbers, and the one the
    reader cannot find by eye: a resolved repeat shows in the diff, a new one is
    two lines that now agree and nothing points at either.
    """
    old = [{"text": "a", "lines": [1, 2]}]
    new = [{"text": "a", "lines": [1, 2]}, {"text": "b", "lines": [7, 9]}]
    resolved, introduced = kv.repeat_delta(old, new)
    assert resolved == 0
    assert [d["text"] for d in introduced] == ["b"]
    assert kv.cluster_lines(introduced) == "7, 9"


BRIEF = [
    "# Briefing",
    "",
    "## What Google is actually pitching: AIDLC",
    "",
    "They ship the loop and the review runs inside it.",
    "",
    "## Next steps",
    "",
    "Pick one team and start.",
]
BRIEF_HEADS = [
    (0, 1, "Briefing"),
    (2, 2, "What Google is actually pitching: AIDLC"),
    (6, 2, "Next steps"),
]


def _reword(kv, who, new):
    doc = list(BRIEF)
    return kv.merge(
        doc,
        [
            {
                "specialist": who,
                "edits": [{"line": 3, "old": doc[2], "new": new, "why": "reword"}],
            }
        ],
        set(range(1, len(doc) + 1)),
        (),
        BRIEF_HEADS,
        0,
    )


def test_p352_dropping_a_heading_marker_is_refused(kv):
    """`noise` may reword a heading and may not delete one. Rewording
    "## What Google is actually pitching: AIDLC" into the sentence "Google is
    pitching AIDLC." took the `##` with it, so the section merged into the one
    above and no gate looked. `verify` could only file it after the fact.
    """
    _, ok, no, _ = _reword(kv, "noise", "Google is pitching AIDLC.")
    assert not ok
    assert "merges into the one above" in no[0][2], no


def test_p352_a_reword_that_keeps_the_marker_still_lands(kv):
    """The half that must not break. Given the same file alone, `chat` renamed
    this heading correctly and kept the marker."""
    got, ok, no, _ = _reword(kv, "noise", "## Google's AIDLC pitch")
    assert ok, (ok, no)
    assert not no, no
    assert got[2] == "## Google's AIDLC pitch"


def test_p352_structure_may_still_remove_a_section(kv):
    """Removing a section is `structure`'s call, and the gate must not take it
    away — the empty-heading gate beside it exempts the same specialist."""
    _, ok, no, _extra = _reword(kv, "structure", "Google is pitching AIDLC.")
    assert ok, (ok, no)
    assert not no, no


def _stripped_transcript(tmp_path):
    """A transcript with its timestamp headings gone, so the detector says prose."""
    p = tmp_path / "stripped.md"
    line = (
        "It is worth noting that the deployment check is missing here — and "
        "the team should consider whether to add one going forward, because "
        "the review records each outcome so that a reader can trace exactly "
        "what happened during the run and why it happened that way."
    )
    p.write_text(
        "# Call notes\n\n" + "".join(f"## Turn {i}\n\n{line}\n\n" for i in range(30))
    )
    return p


def test_p351_a_named_genre_profile_sets_the_kind(tmp_path):
    """SKILL.md says naming `--profile` beats the detected genre. It returned
    the detected genre and only declined to load the genre file, so the word
    lists applied and the kind never moved."""
    p = _stripped_transcript(tmp_path)
    assert "read as prose" in run_tool("plan", p).stdout
    _project(tmp_path, profile="genre-transcript")
    out = run_tool("plan", p).stdout
    assert "read as transcript" in out, out


def test_p351_the_override_is_announced(tmp_path):
    """Silently reading a document as something other than what it looks like
    is the same surprise the defect was."""
    p = _stripped_transcript(tmp_path)
    _project(tmp_path, profile="genre-transcript")
    r = run_tool("plan", p)
    assert "named by profile genre-transcript" in r.stderr, r.stderr
    assert "detected prose" in r.stderr, r.stderr


def test_p351_a_domain_profile_leaves_the_kind_alone(tmp_path):
    """`es` carries Spanish words and no opinion about structure. Reading a
    domain profile as a genre would be the filename guess by another route."""
    p = _stripped_transcript(tmp_path)
    _project(tmp_path, profile="es")
    out = run_tool("plan", p).stdout
    assert "read as prose" in out, out


def test_p351_the_advice_is_not_reprinted_after_it_was_followed(tmp_path):
    """The mixed-document line said "Name a genre with --profile if one should
    win", and printed again unchanged when the reader did exactly that."""
    p = tmp_path / "mixed.md"
    body = "The team records each deployment outcome and reviews it later."
    p.write_text(
        "# Mixed\n\n"
        + "".join(
            (
                f"###### 10:0{i % 10} alex\n\n{body}\n\n"
                if i % 3
                else f"## Section {i}\n\n{body} {body}\n\n"
            )
            for i in range(24)
        )
    )
    _project(tmp_path, profile="genre-transcript")
    r = run_tool("plan", p)
    assert "if one should win" not in r.stderr, r.stderr


def test_p351_a_profile_naming_an_unknown_kind_is_refused(tmp_path):
    """The kind is declared data now, so a typo in it has to be caught where it
    is written and named."""
    prof = tmp_path / "bad.json"
    prof.write_text('{"name": "bad", "genre": "transcripts"}')
    p = _stripped_transcript(tmp_path)
    _project(tmp_path, profile=str(prof))
    r = run_tool("plan", p)
    assert r.returncode != 0
    assert "'transcripts' is not a kind" in r.stderr + r.stdout


def test_p351_the_kind_is_declared_not_read_off_the_filename(kv, tmp_path):
    """A copy of a genre profile saved under another name is the same profile.
    Deriving the kind from the stem would lose it, and `--profile` already
    accepts an arbitrary path."""
    import json
    import shutil

    src = kv.PROFILE_DIR / "genre-transcript.json"
    dst = tmp_path / "my-interview-rules.json"
    shutil.copy(src, dst)
    assert json.loads(dst.read_text())["genre"] == "transcript"
    try:
        kv.load_profile(str(dst))
        assert kv.PROFILE_GENRE == "transcript"
    finally:
        kv.reset_profile()
    assert kv.PROFILE_GENRE is None


def _timestamped_call(tmp_path, turns=60):
    turn = (
        "So the thing is we ran the deployment check and it came back "
        "clean, which means the release can go out on Tuesday as planned "
        "and nobody has to stay late for it this week."
    )
    p = tmp_path / "call.md"
    p.write_text(
        "# Call\n\n"
        + "".join(f"###### 10:00:{i:02d} alex\n\n{turn}\n\n" for i in range(turns))
    )
    return p


def test_p358_a_transcript_is_chunked_on_its_timestamps(kv, tmp_path):
    """5695 words came out as one chunk of 1235 lines. Its headings are all
    `######`, so chunking fell through to paragraph runs — and a transcript's
    turns mask as quotations, so that fallback had no prose to break on.
    """
    got = kv.mask(_timestamped_call(tmp_path).read_text(), "call.md")
    chunks = kv.chunk(got[0], got[1])
    assert len(chunks) > 10, len(chunks)
    assert (
        max(c["end"] - c["start"] for c in chunks) < 10
    ), "one chunk still covers most of the file"


def test_p358_a_prose_document_still_cuts_on_its_h2(kv, tmp_path):
    """The levels are tried in order, so a file with `##` headings never
    reaches the deeper ones and its chunking does not move."""
    p = tmp_path / "doc.md"
    p.write_text(
        "# T\n\n"
        + "".join(
            f"## Section {i}\n\n{FILLER}\n\n#### Note {i}\n\n{FILLER}\n\n"
            for i in range(6)
        )
    )
    got = kv.mask(p.read_text(), "doc.md")
    titles = [c["title"] for c in kv.chunk(got[0], got[1])]
    assert titles == ["(preamble)"] + [f"Section {i}" for i in range(6)], titles


@pytest.mark.skipif(sys.platform == "win32", reason="uses a /bin/sh stand-in")
def test_p345_one_broken_backend_prints_its_cause_a_handful_of_times(tmp_path):
    """26 jobs died on one missing module and the run printed 425 lines: 78
    copies of the cause and 156 stack-trace headers, over a correct one-sentence
    verdict. The cause belongs once per place that reports, not once per job.
    """
    line = (
        "It is worth noting that the deployment check is missing here and "
        "the team should consider whether to add one going forward, since "
        "the review records each outcome so a reader can trace it."
    )
    src = tmp_path / "doc.md"
    parts = ["# Policy", ""]
    for i in range(12):
        parts += [f"## Section {i}", ""] + [line, ""] * 3
    src.write_text("\n".join(parts) + "\n")

    fake = tmp_path / "bin"
    fake.mkdir()
    codex = fake / "codex"
    codex.write_text(
        "#!/bin/sh\n"
        "echo 'Traceback (most recent call last):' >&2\n"
        "echo '  File x, line 1' >&2\n"
        "echo 'ModuleNotFoundError: No module named nosuchmodule' >&2\n"
        "exit 1\n")
    codex.chmod(0o755)
    r = subprocess.run(
        [sys.executable, str(LAUNCHER), "run", str(src), "--agent", "codex",
         "-o", str(tmp_path / "out.md")],
        capture_output=True, text=True,
        env={**os.environ, "PATH": str(fake)})
    whole = r.stdout + r.stderr
    jobs = whole.count(" proposed  ")
    copies = whole.count("nosuchmodule")
    assert jobs >= 20, f"the fixture stopped producing a pile of jobs: {jobs}"
    assert copies <= 6, f"{copies} copies of one cause across {jobs} jobs"
    assert "never edited" in whole


def test_p345_a_stack_trace_is_cut_to_its_first_two_lines(kv):
    """The first line is usually the frame and the second is the message. Past
    that is the backend's own call stack, which names nothing to act on."""
    assert (
        kv.error_digest("frame\nError: gone\nat a\nat b")
        == "frame · Error: gone … +2 lines"
    )
    assert kv.error_digest("only one") == "only one"
    assert kv.error_digest(None) == ""


def _record(out, **fields):
    """The run record `run` leaves beside its output. Returns its path."""
    p = out.with_suffix(out.suffix + ".kvrun")
    p.write_text(json.dumps(fields))
    return p


def _chat_pair(tmp_path):
    """A message and its simplified output, no run record between them."""
    line = (
        "it is worth noting that the deployment check is missing and the "
        "team should consider adding one going forward, since the review "
        "records each outcome for later tracing."
    )
    src = tmp_path / "reply.md"
    out = tmp_path / "reply.kv.md"
    src.write_text("\n\n".join([line] * 40) + "\n")
    out.write_text(
        "\n\n".join([line.replace("it is worth noting that ", "")] * 40) + "\n"
    )
    return src, out


def test_p356_accept_reads_the_mode_the_run_recorded(tmp_path):
    """`run --chat` recorded the baseline and the unedited spans and not the
    mode, so `accept` rescored a chat reply as a document. The last thing the
    tool said about a message already over its length cap was to add a one-page
    summary to it.
    """
    src, out = _chat_pair(tmp_path)
    _record(out, chat=True)
    r = run_tool("accept", src, out, force=True)
    assert "one-page summary" not in r.stdout, r.stdout


def test_p356_a_document_run_is_still_scored_as_a_document(tmp_path):
    """The other half. No record means no chat, not a guess from the content."""
    src, out = _chat_pair(tmp_path)
    assert "one-page summary" in run_tool("accept", src, out, force=True).stdout


def test_p356_a_stale_record_is_ignored_and_named(tmp_path):
    """A record older than the output belongs to an earlier run. Honouring it
    rescores the file under a mode nothing here asked for."""
    import os

    src, out = _chat_pair(tmp_path)
    stale = _record(out, chat=True)
    old = out.stat().st_mtime - 60
    os.utime(stale, (old, old))
    r = run_tool("accept", src, out, force=True)
    assert "belongs to an earlier run" in r.stdout, r.stdout
    assert "one-page summary" in r.stdout, r.stdout


def _facts_line(path):
    r = run_tool("plan", path)
    assert r.returncode == 0, r.stderr
    return next(ln.strip() for ln in r.stdout.splitlines() if "facts to preserve" in ln)


def test_p343_english_decimals_count_once(tmp_path):
    p = tmp_path / "en.md"
    p.write_text(
        "# T\n\nAccuracy is 69.0% and the rate is 4%. " "The p95 is 5.2 seconds.\n"
    )
    assert "number 3" in _facts_line(p)


def test_p343_spanish_decimal_comma_is_one_number(tmp_path):
    """Same three numbers as the English sentence, written the Spanish way."""
    p = tmp_path / "es.md"
    p.write_text(
        "# T\n\nLa precision es del 69,0% y la tasa es del 4%. "
        "El p95 es 5,2 segundos.\n"
    )
    assert "number 3" in _facts_line(p)


def test_p343_the_guarded_tokens_are_the_ones_on_the_page(kv):
    """The count alone cannot tell a fix from a coincidence."""
    got = kv.facts(
        "La precision es del 69,0% y la tasa es del 4%. " "El p95 es 5,2 segundos."
    )["number"]
    assert set(got) == {"69,0%", "4%", "5,2"}, sorted(got)


def test_p343_a_thousands_comma_is_still_one_number(kv):
    """The other half. English writes `1,500` for one number, and reading every
    comma as a decimal point would have to keep that whole too."""
    assert set(kv.facts("The run took 1,500 ms.")["number"]) == {"1,500ms"}


def test_p327_only_summary_is_asked_to_judge_the_opening(kv):
    """R77. Two flags used to ask the reader whether the unheaded opening was
    the summary. That is the question the specialist is there to answer, and a
    person who could answer it would not need the run.
    """
    hands_off = kv.unheaded_note(40, False)
    judge = kv.unheaded_note(40, True)

    assert "may be the summary already" in hands_off
    assert "Leave those words as they are" in hands_off
    assert "Read them and decide" in judge
    assert "write a summary and insert it above them" in judge


def test_p328_the_header_does_not_count_owner_transfers_as_gate_refusals(kv):
    """R78. The header said "57 refused by the gates" and then reported 17 of
    those as owner transfers, having already counted them once.
    """
    import inspect

    src = inspect.getsource(kv.cmd_run)
    owned = src.index("owned = [r for r in refused if r[2].startswith(_own)]")
    header = src.index("{len(gates)} refused by the gates")
    assert owned < header, (
        "the owned/gates split must happen before the header prints, or the "
        "header counts owner transfers as gate refusals"
    )


def test_p344_the_per_specialist_line_names_an_owner_transfer_as_one(
    kv, monkeypatch, tmp_path, capsys
):
    """The header was fixed and the line under it was not."""
    src = tmp_path / "clash.md"
    body = (
        "It is worth noting that codex suggested the deployment check is "
        "missing and the team should add one."
    )
    plain = (
        "The release runs on Tuesday and the results are recorded for "
        "the following review."
    )
    src.write_text(
        "# Retry Policy\n\n" + body + "\n\n" + "\n\n".join([plain] * 12) + "\n"
    )
    lines = src.read_text().splitlines()
    target = next(i for i, ln in enumerate(lines, 1) if ln == body)

    def reply(who, lo, hi):
        if who not in ("prose", "noise") or not lo <= target <= (hi or 10**9):
            return []
        return [
            {
                "line": target,
                "old": body,
                "new": f"The deployment check is missing, per {who}.",
            }
        ]

    run_canned(kv, monkeypatch, src, tmp_path / "out.md", reply)
    out = capsys.readouterr().out

    loser = [ln for ln in out.splitlines() if "nothing applied" in ln]
    assert loser, f"no specialist reported nothing applied:\n{out}"
    for ln in loser:
        assert (
            "refused by the gates" not in ln
        ), f"an owner transfer is reported as a gate refusal: {ln.strip()}"
        assert "went to the line's owner" in ln, ln.strip()


MESSAGE = """the review agent posted 14 findings on MR !221 yesterday. eleven
of them were real and two of those nobody on the team had spotted.

three were noise. it read a test fixture as production config twice, and once
it flagged a deprecated call that we deliberately keep for the 3.1 clients.

the false-positive rate is the thing to watch. at three in fourteen it is
already borderline for the people who have to read every comment.

i can turn the fixture rule off this week if that helps."""

INVENTED = "Want a shorter in-thread version?"


def _chat_files(tmp_path, edited_body):
    orig = tmp_path / "msg.orig.md"
    orig.write_text(MESSAGE + "\n")
    edited = tmp_path / "msg.kv.md"
    edited.write_text(edited_body + "\n")
    return orig, edited


def test_p354_a_chat_insert_is_refused(kv):
    """The tool may not add a line to a message it did not write."""
    doc = ["a line of the message.", "", "another line."]
    edits = [
        {
            "specialist": "chat",
            "edits": [
                {"op": "insert", "line": 3, "new": INVENTED, "why": "end with the ask"}
            ],
        }
    ]

    _out, ok, no, _x = kv.merge(list(doc), edits, {1, 3}, chat=True)
    assert not ok, f"the insert landed on a chat message: {ok}"
    assert no, "nothing was refused"
    assert "one author" in no[0][2], no


def test_p354_a_document_may_still_be_inserted_into(kv):
    """The ban is on the mode. A document still gets its summary."""
    doc = ["a line of the message.", "", "another line."]
    edits = [
        {
            "specialist": "chat",
            "edits": [
                {"op": "insert", "line": 3, "new": INVENTED, "why": "end with the ask"}
            ],
        }
    ]

    out, ok, no, _x = kv.merge(list(doc), edits, {1, 3}, chat=False)
    assert ok, "the insert was refused on a document"
    assert not no, no
    assert INVENTED in out


def test_p354_a_sentence_that_arrived_fails_the_chat_verify(tmp_path):
    """The reproduced defect: it used to exit 3, so `accept` took it."""
    orig, edited = _chat_files(tmp_path, MESSAGE + "\n\n" + INVENTED)

    r = run_tool("verify", orig, edited, "--chat")
    assert r.returncode == 1, f"exit {r.returncode}, not a failure:\n{r.stdout}"
    assert "TEXT ADDED" in r.stdout, r.stdout
    assert INVENTED in r.stdout, r.stdout


def test_p354_a_reword_that_appends_is_caught_too(tmp_path):
    """The other way in. The insert ban alone leaves this one open."""
    orig, edited = _chat_files(
        tmp_path,
        MESSAGE.replace(
            "i can turn the fixture rule off this week if that helps.",
            "i can turn the fixture rule off this week. " + INVENTED,
        ),
    )

    r = run_tool("verify", orig, edited, "--chat")
    assert r.returncode == 1, f"exit {r.returncode}, not a failure:\n{r.stdout}"
    assert "TEXT ADDED" in r.stdout, r.stdout


def test_p354_a_document_is_not_scored_for_arrivals(tmp_path):
    """Without --chat nothing changes: a summary pass writes new sentences."""
    orig, edited = _chat_files(tmp_path, MESSAGE + "\n\n" + INVENTED)

    r = run_tool("verify", orig, edited)
    assert "TEXT ADDED" not in r.stdout, r.stdout
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize(
    ("name", "edited"),
    [
        (
            "split",
            MESSAGE.replace(
                "the false-positive rate is the thing to watch. "
                "at three in fourteen it is\n"
                "already borderline for the people who have to read every comment.",
                "the false-positive rate is the thing to watch. three in fourteen is\n"
                "borderline. the people who read every comment feel it first.",
            ),
        ),
        (
            "delete",
            MESSAGE.replace(
                "three were noise. it read a test fixture as production config "
                "twice, and once\nit flagged a deprecated call that we deliberately "
                "keep for the 3.1 clients.\n\n",
                "",
            ),
        ),
        (
            "reorder",
            "i can turn the fixture rule off this week if that helps.\n\n"
            + MESSAGE.rsplit("\n\n", 1)[0],
        ),
        (
            "rewrite",
            "the review agent left 14 findings on MR !221 yesterday. eleven held up, "
            "and\ntwo of those nobody on the team had caught.\n\n"
            "three were noise. twice it took a test fixture for production config, "
            "and once\nit objected to a deprecated call we keep on purpose for the "
            "3.1 clients.\n\n"
            "the false-positive rate is what to watch. at three in fourteen it is "
            "already\nborderline for anyone who reads every comment.\n\n"
            "i can switch the fixture rule off this week if that helps.",
        ),
    ],
)
def test_p354_a_legitimate_chat_edit_is_not_an_arrival(tmp_path, name, edited):
    """The false-positive guard. Swap in a naive gate and these go red."""
    orig, out = _chat_files(tmp_path, edited)

    r = run_tool("verify", orig, out, "--chat")
    assert "TEXT ADDED" not in r.stdout, f"{name} reads as invented:\n{r.stdout}"


def test_p354_the_whole_run_refuses_the_insert(kv, monkeypatch, tmp_path, capsys):
    """End to end, not through merge directly. This is the reported path."""
    src = tmp_path / "msg.md"
    src.write_text(MESSAGE + "\n")
    out = tmp_path / "msg.kv.md"
    last = "i can turn the fixture rule off this week if that helps."
    target = next(i for i, ln in enumerate(MESSAGE.splitlines(), 1) if ln == last)

    def reply(who, lo, hi):
        if who != "chat" or not lo <= target <= (hi or 10**9):
            return []
        return [
            {"line": target, "op": "insert", "new": INVENTED, "why": "end with the ask"}
        ]

    run_canned(kv, monkeypatch, src, out, reply, extra=("--chat",))
    printed = capsys.readouterr().out

    assert INVENTED not in out.read_text(), "the invented line was written"
    assert "one author" in printed, printed


BRIEFING = """I've read the whitepaper. This is the missing context. Let me now
give you a real briefing on what Sam is asking you to weigh in on.

Google is pitching a managed stack. Sam wants us to decide whether we adopt it
or keep the plumbing we already run.

### The customization story (this is the part that matters)

Their tuning path is closed. We would send prompts to their endpoint and take
whatever version they serve that week.

Want me to write up the two options side by side?"""

PROMOTED = "The customization story matters."


def _briefing(tmp_path, edited_body):
    orig = tmp_path / "brief.orig.md"
    orig.write_text(BRIEFING + "\n")
    edited = tmp_path / "brief.kv.md"
    edited.write_text(edited_body + "\n")
    return orig, edited


def test_p353_a_lead_lifted_from_a_heading_fails_the_chat_verify(tmp_path):
    """The reported defect. A heading is about its section, not the message."""
    body = BRIEFING.split("\n\n")
    body[0] = PROMOTED
    orig, edited = _briefing(tmp_path, "\n\n".join(body))

    r = run_tool("verify", orig, edited, "--chat")
    assert r.returncode == 1, f"exit {r.returncode}, not a failure:\n{r.stdout}"
    assert "TEXT ADDED" in r.stdout, r.stdout
    assert PROMOTED in r.stdout, r.stdout


def test_p353_cutting_the_parenthetical_alone_passes(tmp_path):
    """The specialist made two edits. Only one of them was wrong."""
    orig, edited = _briefing(
        tmp_path,
        BRIEFING.replace(
            "### The customization story (this is the part that matters)",
            "### The customization story",
        ),
    )

    r = run_tool("verify", orig, edited, "--chat")
    assert r.returncode == 0, f"the correct edit was refused:\n{r.stdout}"


def test_p353_a_lead_promoted_from_the_body_passes(tmp_path):
    """The edit this must never refuse: a real result buried in the body."""
    buried = (
        "i looked at the retry logic this afternoon.\n\n"
        "there are three call sites and they each wrap the same client.\n\n"
        "the real point is that the third site retries a non-idempotent\n"
        "write, so a timeout there can double-charge an account.\n\n"
        "shall i open a ticket for it?"
    )
    lead = (
        "the third site retries a non-idempotent write, so a timeout there\n"
        "can double-charge an account."
    )
    orig = tmp_path / "retry.orig.md"
    orig.write_text(buried + "\n")
    edited = tmp_path / "retry.kv.md"
    edited.write_text(
        lead
        + "\n\n"
        + buried.replace(
            "the real point is that the third site retries a non-idempotent\n"
            "write, so a timeout there can double-charge an account.\n\n",
            "",
        )
        + "\n"
    )

    r = run_tool("verify", orig, edited, "--chat")
    assert r.returncode == 0, f"a real buried lead was refused:\n{r.stdout}"


def test_p353_a_lead_the_body_already_states_is_not_an_arrival(tmp_path):
    """The paired contrast. Same promoted line, and here the body says it."""
    grounded = BRIEFING.replace(
        "Their tuning path is closed.",
        "Their tuning path is closed, and the customization story is the one\n"
        "that really matters here.",
    )
    orig = tmp_path / "grounded.orig.md"
    orig.write_text(grounded + "\n")
    edited = tmp_path / "grounded.kv.md"
    edited.write_text(
        PROMOTED
        + "\n\n"
        + grounded.replace(
            "### The customization story (this is the part that matters)",
            "### The customization story",
        )
        + "\n"
    )

    r = run_tool("verify", orig, edited, "--chat")
    assert (
        "TEXT ADDED" not in r.stdout
    ), f"a lead the body states was called invented:\n{r.stdout}"


def test_p353_the_chat_prompt_restricts_a_lead_to_body_prose():
    """A prompt fix with no guard is a prompt fix that silently regresses."""
    chat_md = REPO / "specialists" / "chat.md"
    paras = chat_md.read_text().split("\n\n")
    rule = next(p for p in paras if "buried lead" in p.lower())

    assert "body" in rule.lower(), rule
    assert "heading" in rule.lower(), rule


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the arrivals check matches content words, not claims. Both reviewers "
        "refused a gate here and each named a different legitimate edit it would "
        "refuse, so R94 is fixed in the prompt and this hole stays open. Turning "
        "green means someone closed it — update the design doc."
    ),
)
def test_p353_the_gate_misses_a_lead_whose_words_are_in_the_body(tmp_path):
    """agy found this. The body shares the words and denies the claim."""
    thin = BRIEFING.replace(
        "Their tuning path is closed.",
        "Their customization path is closed and the story they tell about\n"
        "tuning is thin.",
    )
    orig = tmp_path / "thin.orig.md"
    orig.write_text(thin + "\n")
    edited = tmp_path / "thin.kv.md"
    edited.write_text(
        PROMOTED
        + "\n\n"
        + thin.replace(
            "### The customization story (this is the part that matters)",
            "### The customization story",
        )
        + "\n"
    )

    r = run_tool("verify", orig, edited, "--chat")
    assert "TEXT ADDED" in r.stdout, r.stdout


def test_r100_quiet_chunks_are_counted_not_listed(tmp_path):
    """A 30-turn transcript printed 31 rows and 30 of them said nothing."""
    out = run_tool("plan", _transcript(tmp_path)).stdout

    assert out.count("(nothing found)") <= 1, out
    assert "chunks found nothing" in out, out


def test_r100_a_chunk_that_found_something_still_prints(tmp_path):
    """The collapse must not hide work. This is the whole risk of it."""
    p = tmp_path / "mixed.md"
    p.write_text(
        "# Notes\n\n"
        + "".join(f"## Section {i}\n\n{FILLER} {FILLER}\n\n" for i in range(5))
        + "## Last\n\nIt is worth noting that the deployment finished.\n"
    )
    out = run_tool("plan", p).stdout

    assert "6 chunks found nothing: 1-6" in out, out
    assert "── chunk 7" in out, out
    assert "frame" in out, out


def test_r100_number_spans_folds_runs(kv):
    """The list is most of the file, so commas would be their own wall."""
    assert kv.number_spans([2, 3, 4, 7]) == "2-4, 7"
    assert kv.number_spans([5]) == "5"
    assert kv.number_spans([9, 1, 2]) == "1-2, 9"



RAGGED = """the review agent posted 14 findings on MR !221 yesterday. eleven
of them were real and two of those nobody on the team had spotted.

three were noise. it read a test fixture as production config twice, and once
it flagged a deprecated call that we deliberately keep for the 3.1 clients."""


def _rewrite_first_paragraph(kv, monkeypatch, tmp_path, extra):
    """Replace the opening sentence in the wrap form: the whole rewrite on the
    run's first line, an empty string for every line under it."""
    src = tmp_path / "msg.md"
    src.write_text(RAGGED + "\n")
    out = tmp_path / "msg.kv.md"

    src_lines = RAGGED.split("\n")

    def reply(who, lo, hi):
        if who != "chat" or not lo <= 1 <= (hi or 10**9):
            return []
        return [
            {
                "line": 1,
                "op": "replace",
                "why": "cut the frame",
                "old": src_lines[0],
                "new": "the review agent posted 14 findings on MR !221 "
                "yesterday. eleven held up and two of those nobody on "
                "the team had spotted.",
            },
            {
                "line": 2,
                "op": "replace",
                "old": src_lines[1],
                "new": "",
                "why": "cut the frame",
            },
        ]

    run_canned(kv, monkeypatch, src, out, reply, extra=extra)
    return out.read_text()


def test_r90_chat_joins_each_paragraph_to_one_line(kv, monkeypatch, tmp_path):
    """A chat client wraps for itself, so a rewritten line must not carry the
    wrap points of the file it replaced."""
    body = _rewrite_first_paragraph(kv, monkeypatch, tmp_path, ("--chat",))

    paras = [p for p in body.strip().split("\n\n") if p.strip()]
    assert paras, body
    for p in paras:
        assert "\n" not in p, f"paragraph still wrapped:\n{body}"


def test_r90_document_mode_still_rewraps(kv, monkeypatch, tmp_path):
    """The join is chat-only. A file keeps its margin."""
    body = _rewrite_first_paragraph(kv, monkeypatch, tmp_path, ())

    assert "\n" in body.strip().split("\n\n")[0], body


@pytest.mark.parametrize(
    ("name", "src"),
    [
        (
            "a nested bullet came back flush left",
            ["- outer", "  - inner", "  - inner two"],
        ),
        (
            "a table written without outer pipes became one line",
            ["Name | Value", "--- | ---", "A | B"],
        ),
        (
            "a setext underline joined its own title",
            ["Title", "=====", "", "Body text."],
        ),
        (
            "a lazy blockquote continuation lost its `>`",
            ["> Exact words", "continued here", "and here"],
        ),
        ("a fence body is not prose", ["```py", "x = 1", "y = 2", "```"]),
    ],
)
def test_r90_join_leaves_a_shape_it_cannot_join_alone(kv, name, src):
    """One unjoinable line leaves its whole paragraph alone, so the worst case
    is an unjoined line and never a corrupted block."""
    assert kv.join_paragraphs(src) == src, name


def test_r90_join_keeps_one_bullet_per_line(kv):
    """A bullet opens a line, so its continuation folds into it and the next
    bullet still starts one. The indent of the opening line is kept."""
    src = [
        "- first bullet runs",
        "  onto a second line",
        "  - nested one",
        "    wrapping too",
        "- second bullet",
    ]

    assert kv.join_paragraphs(src) == [
        "- first bullet runs onto a second line",
        "  - nested one wrapping too",
        "- second bullet",
    ]


def test_r90_join_leaves_a_heading_on_its_own_line(kv):
    """A heading that absorbed the paragraph under it would merge two blocks."""
    src = ["# Title", "", "a line", "and its rest."]

    assert kv.join_paragraphs(src) == ["# Title", "", "a line and its rest."]


def test_join_keeps_one_lettered_option_per_line(kv):
    """A lettered option list (`a.`, `b.`, `c.`) is a bullet too."""
    src = [
        "a. Start slowing earlier - move the $10 down, so the brake",
        "   comes on gently over more requests instead of hitting a wall.",
        "b. Ask SRE to raise the $15.",
        "c. Leave it alone.",
    ]

    assert kv.join_paragraphs(src) == [
        "a. Start slowing earlier - move the $10 down, so the brake comes "
        "on gently over more requests instead of hitting a wall.",
        "b. Ask SRE to raise the $15.",
        "c. Leave it alone.",
    ]


def test_join_control_still_folds_ordinary_prose(kv):
    """The control for the fix above: ordinary hard-wrapped prose with no
    list marker at all must still fold into one line, or the fix has only
    made the tool stop joining anything."""
    src = ["This is a plain sentence that", "wraps over two lines and should",
           "fold into one."]

    assert kv.join_paragraphs(src) == [
        "This is a plain sentence that wraps over two lines and should "
        "fold into one."]



POLITE = (
    "If you would like to use a new Licensed or Unlicensed Generative "
    "AI Tool, you are required to please fill out the Request Form in "
    "Appendix B."
)
DIRECT = (
    "To use a new Licensed or Unlicensed Generative AI Tool, fill out "
    "the Request Form in Appendix B."
)
ADVISED = (
    "The process owners should work with the AI Panel to explore "
    "options for the process."
)
STATED = (
    "The process owners work with the AI Panel to change the process "
    "for options so it complies."
)


def _weakened(kv, before, after):
    return [s for _ln, s in kv.claims_lost(before.split("\n"), after.split("\n"))[1]]


def test_r83_dropping_please_is_not_a_weakened_rule(kv):
    """`fill out` is more of an instruction than `please fill out`, not less.
    The old check keyed on the modal words, so losing them read as a loss."""
    assert _weakened(kv, POLITE, DIRECT) == []


def test_r83_advice_restated_as_fact_is_reported(kv):
    """The edit that really changed the meaning. `should work` is a
    recommendation and `work` states it as a fact, and neither side was a rule
    word, so the old check could not see either end of it."""
    assert _weakened(kv, ADVISED, STATED) == [ADVISED]


@pytest.mark.parametrize(
    ("strength", "sentence"),
    [
        (2, "You must fill out the form before the deadline."),
        (2, "Never run this against production."),
        (2, "Check the log before you retry."),
        (1, "The process owners should work with the AI Panel."),
        (1, "Reviewers are expected to read the diff."),
        (0, "Block storage is cheaper than object storage."),
        (0, "Run make to build the project."),
        (0, "Use the flag to skip the check."),
        (0, "Hold times were long that week."),
    ],
)
def test_r83_the_strength_scale(kv, strength, sentence):
    assert kv.rule_strength(sentence) == strength, sentence


def test_r83_a_rule_reduced_to_advice_is_reported(kv):
    """`must` → `should` keeps a marker, so "is any rule left" said yes."""
    before = "Every contributor must sign the agreement before opening an MR."
    after = "Every contributor should sign the agreement before opening an MR."

    assert _weakened(kv, before, after) == [before]


def test_r83_advice_that_stayed_advice_is_not_reported(kv):
    """The false-positive guard for the new rung."""
    before = "The process owners should work with the AI Panel on options."
    after = "The process owners should work with the AI Panel to pick options."

    assert _weakened(kv, before, after) == []


def test_r83_asked_verbs_reads_a_request_and_a_nominalisation(kv):
    """Two grammars, and each has to stay out of the other's way."""
    assert "fill" in kv.asked_verbs("please fill out the Request Form")
    assert kv.asked_verbs("Nothing polite here at all.") == set()

    got = kv.asked_verbs("Next, the classification of findings should be "
                         "carried out by CVSS band.")
    assert "classify" in got
    assert "classification" not in got

    assert "run" in kv.asked_verbs("At this stage, the running of a dependency "
                                   "audit should take place.")
    assert "run" not in kv.asked_verbs("The audit is running against the "
                                       "changed manifest right now.")

    assert "accept" not in kv.asked_verbs(
        "It refuses a stale record: `verify` reads on, `accept` does not, "
        "because acceptance of an unknown pardon list is not a decision.")


def test_r83_a_de_nominalised_rule_is_not_a_weakened_rule(kv):
    """The tool was reporting the edit `prose.md` orders by name."""
    before = ("Next, the classification of findings should be carried out by "
              "CVSS band Critical High Medium Low.")
    after = "Classify findings by CVSS band Critical High Medium Low."
    assert _weakened(kv, before, after) == []

    described = ("The classification of findings by CVSS band Critical High "
                 "Medium Low is what the report contains.")
    assert _weakened(kv, before, described) == [before]



RULE_KEPT = ("The dispatcher must never write a customer access token into "
             "the request log.")
RULE_GONE = ("The dispatcher handles the customer access token and the "
             "request log.")


def _verify(tmp_path, before, after):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(f"# Doc\n\n{before}\n")
    b.write_text(f"# Doc\n\n{after}\n")
    return run_tool("verify", a, b)


def test_an_obligation_deleted_under_surviving_nouns_reaches_review(tmp_path):
    """Every content word of the rule is still in the file and the rule is not."""
    r = _verify(tmp_path, RULE_KEPT, RULE_GONE)

    assert r.returncode == 3, r.stdout + r.stderr
    assert "rules reworded" in r.stdout, r.stdout


def test_the_same_rule_condensed_is_not_reported(tmp_path):
    """The control, and it is the half that matters: a strong condensation
    keeps the obligation in a third of the words. Firing here would refuse
    exactly what the pass exists to produce."""
    r = _verify(tmp_path, RULE_KEPT,
                "Never write a customer access token to the request log.")

    assert "rules reworded" not in r.stdout, r.stdout



TURN = (
    "The team reviews each deployment. It records the outcome. "
    "A third sentence here."
)


def _call(n=12):
    turns = []
    for i in range(n):
        turns += [f"###### 0:{i:02d} alex", "", TURN, ""]
    return "# Call notes\n\n" + "\n".join(turns)


def _sentences(kv, prose):
    return sum(1 for _ in kv._split(" ".join(prose)))


def test_r101_a_transcript_is_counted_turn_by_turn(kv):
    """Every turn masks as a quotation, so counting masked prose alone read
    the whole call as one sentence and "the survivors got longer" was dead."""
    doc = _call()

    assert _sentences(kv, kv.mask(doc)[0]) == 1
    assert _sentences(kv, kv.countable(doc)) == 36


def test_r101_a_blockquote_is_still_left_out(kv):
    """Someone else's words inside a document the pass may not touch. Counting
    them adds a number nobody can act on, so only turns come back."""
    doc = (
        "# Doc\n\n> Someone else said this. And this too.\n\n"
        "Our own sentence here. And another one.\n"
    )

    assert _sentences(kv, kv.countable(doc)) == 2


def test_r101_one_timestamp_heading_is_not_a_transcript(kv):
    """The masking needs two, so the counter must not disagree with it."""
    doc = (
        "# Notes\n\n###### 0:01 alex\n\n"
        + TURN
        + "\n\n## Analysis\n\nOur own sentence.\n"
    )

    assert kv.countable(doc) == kv.mask(doc)[0]


def test_r101_the_run_reports_a_real_sentence_count(kv, monkeypatch, tmp_path):
    """End to end. The reported defect is a line in the run report."""
    src = tmp_path / "call.md"
    src.write_text(_call())
    out = tmp_path / "call.kv.md"
    target = next(i for i, ln in enumerate(_call().splitlines(), 1) if ln == TURN)

    def reply(who, lo, hi):
        if who != "noise" or not lo <= target <= (hi or 10**9):
            return []
        return [
            {
                "line": target,
                "op": "replace",
                "old": TURN,
                "new": "The team reviews each deployment.",
                "why": "someone else's words are not a delete",
            }
        ]

    run_canned(kv, monkeypatch, src, out, reply)
    body = out.read_text()

    assert _sentences(kv, kv.countable(body)) > 1, body



LONG_CHAT = (
    "the review agent posted findings on the merge request yesterday "
    "and most of them held up under a second read by the team. "
) * 30


def _capped_pair(tmp_path, before, after):
    a, b = tmp_path / "msg.orig.md", tmp_path / "msg.kv.md"
    a.write_text(before.strip() + "\n")
    b.write_text(after.strip() + "\n")
    return a, b


def test_r96_a_message_still_over_the_cap_is_review(tmp_path):
    """One edit cannot close a gap of eight times the cap, and nothing looked
    at the cap after the edits, so the run said PASS."""
    trimmed = LONG_CHAT.replace("under a second read by the team. ", "", 5)
    r = run_tool("verify", *_capped_pair(tmp_path, LONG_CHAT, trimmed), "--chat")

    assert r.returncode == 3, r.stdout
    assert "over the chat cap" in r.stdout, r.stdout


def test_r96_a_message_under_the_cap_still_passes(tmp_path):
    """The false-positive guard."""
    r = run_tool(
        "verify",
        *_capped_pair(
            tmp_path,
            "the fixture rule is off. i can turn it back on.",
            "the fixture rule is off. i can turn it on.",
        ),
        "--chat",
    )

    assert r.returncode == 0, r.stdout


def test_r96_a_document_is_not_held_to_the_chat_cap(tmp_path):
    """The cap is a message's, so the same pair without `--chat` is clean."""
    trimmed = LONG_CHAT.replace("under a second read by the team. ", "", 5)
    r = run_tool("verify", *_capped_pair(tmp_path, LONG_CHAT, trimmed))

    assert r.returncode == 0, r.stdout
    assert "over the chat cap" not in r.stdout, r.stdout



ECHO = (
    "the pipeline retries the failed job and records the outcome in the "
    "log store for later"
)


def _repeat_doc(tmp_path):
    """A document with an untouched sentence an edit can accidentally echo."""
    p = tmp_path / "doc.md"
    p.write_text(
        "# Runbook\n\n## Retries\n\n"
        f"{ECHO} auditing by the team.\n\n"
        "## Notes\n\n"
        "It is worth noting that the deployment check is missing here and the "
        "team should consider adding one.\n\n"
        "## More\n\n" + FILLER + "\n"
    )
    return p


def _echo_reply(target):
    def reply(who, lo, hi):
        if who != "prose" or not lo <= target <= (hi or 10**9):
            return []
        return [
            {
                "line": target,
                "op": "replace",
                "why": "shorter",
                "new": f"{ECHO} auditing.",
            }
        ]

    return reply


def test_r81_an_edit_that_repeats_untouched_text_is_refused(kv, monkeypatch, tmp_path):
    """The replacement echoes a sentence the pass never touched, so the file
    ends with a repeat it did not start with."""
    src = _repeat_doc(tmp_path)
    out = tmp_path / "doc.kv.md"
    body = src.read_text().splitlines()
    noisy = next(
        i for i, ln in enumerate(body, 1) if ln.startswith("It is worth noting")
    )

    def reply(who, lo, hi):
        if who != "prose" or not lo <= noisy <= (hi or 10**9):
            return []
        return [
            {
                "line": noisy,
                "op": "replace",
                "old": body[noisy - 1],
                "why": "cut the frame",
                "new": f"{ECHO} auditing by the team.",
            }
        ]

    run_canned(kv, monkeypatch, src, out, reply)
    written = out.read_text()

    assert (
        kv.repeat_delta(
            kv.duplicates(kv.mask(src.read_text())[0]),
            kv.duplicates(kv.mask(written)[0]),
        )[1]
        == []
    ), written


def test_r81_the_scan_runs_before_the_write(kv):
    """The whole of the fix. The scan existed; it ran after `write_text`."""
    import inspect

    body = inspect.getsource(kv.cmd_run)
    scan = body.index("repeat_blame(_added, results)")
    assert body.count('open(out_path, "w"') == 1, "anchor is ambiguous"
    write = body.index('open(out_path, "w"')
    assert scan < write, "the duplicate scan is still behind the write"


def test_r81_blame_matches_on_text_not_on_line_numbers(kv):
    """A cluster is numbered in the merged file and an edit in the original."""
    added = [{"text": kv.repeat_key(ECHO)}]
    guilty = {"op": "replace", "new": f"{ECHO} auditing."}
    innocent = {"op": "replace", "new": "Something else entirely, unrelated."}
    results = [{"specialist": "prose", "edits": [guilty, innocent]}]

    assert kv.repeat_blame(added, results) == {id(guilty)}


def test_r81_a_repeat_nobody_owns_blames_nobody(kv):
    """Several edits can build one repeat between them, and picking one to
    drop is worse than letting verify report the cluster."""
    added = [{"text": kv.repeat_key(ECHO)}]
    results = [
        {
            "specialist": "prose",
            "edits": [{"op": "replace", "new": "the pipeline retries"}],
        }
    ]

    assert kv.repeat_blame(added, results) == set()



RULE = (
    "It is worth noting that you must never store a customer token in "
    "the request log."
)
CHAFF = (
    "It is worth noting that the review records each outcome so that a "
    "reader can trace exactly what happened during the release."
)


def _rule_doc(tmp_path):
    """Four rewritable lines and one rule, each in its own section."""
    body = ["# Release notes", ""]
    for i in range(4):
        body += [f"## Section {i}", "", CHAFF, ""]
    body += ["## Rules", "", RULE, ""]
    src = tmp_path / "doc.md"
    src.write_text("\n".join(body) + "\n")
    return src, body.index(RULE) + 1


def _eat_the_rule(src, replacement="Tokens are written to 1Password."):
    lines = src.read_text().splitlines()

    def reply(who, lo, hi):
        if who != "prose":
            return []
        return [
            {
                "line": i,
                "old": ln,
                "new": replacement
                if ln == RULE
                else "The review records each outcome.",
            }
            for i, ln in enumerate(lines, 1)
            if lo <= i <= (hi or 10**9) and ln in (RULE, CHAFF)
        ]

    return reply


def test_r76_an_edit_that_eats_a_rule_is_refused(kv, monkeypatch, tmp_path, capsys):
    """The whole row, end to end."""
    src, rule_ln = _rule_doc(tmp_path)
    out = tmp_path / "out.md"
    run_canned(kv, monkeypatch, src, out, _eat_the_rule(src))
    report = capsys.readouterr().out

    assert (
        out.read_text().splitlines()[rule_ln - 1] == RULE
    ), "the rule was rewritten away"
    assert "states a rule" in report, report
    assert (
        run_tool("verify", src, out).returncode != 1
    ), "verify still fails the whole run"


def test_r76_the_rest_of_the_run_still_lands(kv, monkeypatch, tmp_path):
    """The point of refusing one edit instead of failing the run."""
    src, _ = _rule_doc(tmp_path)
    out = tmp_path / "out.md"
    run_canned(kv, monkeypatch, src, out, _eat_the_rule(src))

    assert "The review records each outcome." in out.read_text()


def test_r76_a_rule_that_is_only_reworded_is_left_alone(kv, monkeypatch, tmp_path):
    """The gate must not refuse the edit the pass exists to make."""
    src, rule_ln = _rule_doc(tmp_path)
    out = tmp_path / "out.md"
    shorter = "Never store a customer token in the request log."
    run_canned(kv, monkeypatch, src, out, _eat_the_rule(src, shorter))

    assert out.read_text().splitlines()[rule_ln - 1] == shorter


WRAPPED = [
    "You must never store a customer token in the",
    "request log, because the log is world readable.",
]


@pytest.mark.parametrize(
    "edits",
    [
        [
            {
                "line": 3,
                "new": "Never store a customer token in the request log; "
                "the log is world readable.",
            },
            {"line": 4, "new": ""},
        ],
        [
            {"line": 3, "new": "Never store a customer token in the request log."},
            {"line": 4, "new": "The log is world readable."},
        ],
        [{"line": 4, "new": "because anyone can read it."}],
    ],
)
def test_r76_a_legitimate_rewrite_of_a_wrapped_rule_is_not_refused(kv, edits):
    assert _eaten(kv, ["# T", "", *WRAPPED], edits) == {}


def test_r76_a_plain_fact_is_not_held_to_the_rule_bar(kv):
    """`sentences_lost` already covers plain sentences at its own bar. This
    gate is the four a pass may never drop, and nothing else."""
    lines = [
        "# T",
        "",
        "The release runs on Tuesday and the results go to " "the review board.",
    ]
    assert _eaten(kv, lines, [{"line": 3, "new": "Deploys are " "automated."}]) == {}


def test_r76_a_deleter_is_no_longer_exempt(kv):
    """The fix took the exemption off, and this is the assertion that held it."""
    lines = ["# T", "", "You must never store a customer token in the log."]
    assert _eaten(kv, lines, [{"line": 3, "new": ""}], who="noise")
    assert _eaten(kv, lines, [{"line": 3, "new": ""}])


def test_r76_advice_hardened_into_a_rule_is_not_a_loss(kv):
    """It got stronger. R83 taught `claims_lost` the difference and this gate
    inherits it by calling that, not a second threshold."""
    lines = ["# T", "", "You should not store a customer token in the " "request log."]
    assert (
        _eaten(
            kv,
            lines,
            [{"line": 3, "new": "Never store a customer " "token in the request log."}],
        )
        == {}
    )


def _eaten(kv, lines, edits, who="prose"):
    """`rules_eaten` with the masks `merge` hands it, and a matching `old`."""
    prose, _h, tables, _q = kv.mask("\n".join(lines))
    for e in edits:
        e.setdefault("old", lines[e["line"] - 1])
    return kv.rules_eaten(lines, {"specialist": who, "edits": edits}, prose, tables)


def test_r76_a_rule_whose_other_half_is_untouched_is_not_refused(kv):
    """What the span growth is for."""
    lines = [
        "## Logging",
        "",
        "Before the request is written to the log you must",
        "remove the token, and never write it to disk.",
    ]
    edits = [{"line": 4, "new": "strip the token, and keep it out of disk " "files."}]

    assert kv.claims_lost([lines[3]], [edits[0]["new"]])[
        0
    ], "the fragment alone must read as a lost rule, or this proves nothing"
    assert _eaten(kv, lines, edits) == {}


def test_r76_the_end_of_run_backstop_still_fails(tmp_path):
    """Per-edit refusal does not replace `RULES LOST`. That block still
    catches a loss no single edit explains."""
    src, _ = _rule_doc(tmp_path)
    edited = tmp_path / "edited.md"
    edited.write_text(src.read_text().replace(RULE, "Tokens are written to 1Password."))
    r = run_tool("verify", src, edited)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout


def test_r76_the_pipeline_leaves_the_default_profile_behind(kv, monkeypatch, tmp_path):
    """Pins the leak the isolation fixture in `conftest` exists to clean up."""
    src = tmp_path / "call.md"
    src.write_text(
        "# Call\n\n"
        + "".join(
            f"###### 10:00:{i:02d} alex\n\n{FILLER} {FILLER}\n\n" for i in range(30)
        )
    )
    run_canned(kv, monkeypatch, src, tmp_path / "out.md", lambda *_: [])

    assert kv.PROFILE_GENRE == "transcript", "the run did not load a genre"




def _moved(kv, text, edit, before=None):
    """Run one `move-block` through `merge` and report what happened."""
    lines = text.split("\n")
    _p, heads, _t, _q = kv.mask("\n".join(lines))
    results = [{"specialist": "structure", "edits": [edit], "lo": 1, "hi": len(lines)}]
    if before:
        results.insert(0, before)
    out, applied, refused, _x = kv.merge(
        lines, results, set(range(1, len(lines) + 1)), headings=heads
    )
    return out, bool(applied), [r[2] for r in refused]


LEDE = "# T\n\nlede one.\nlede two.\n\n## Summary\n\nUse tools.\n\n## Body\n\nbody."
FENCE = "# T\n\n```\nalpha\n\nbeta\n```\n\n## H\n\nbody."
LOOSE = "# T\n\n- first\n\n- second\n\n## H\n\nbody."
DETAIL = "# T\n\n- Item 1\n\n  Indented details.\n\n## H\n\nbody."


def test_r71_prose_with_no_heading_over_it_can_move(kv):
    """The row itself: a lede above the summary, sent below it."""
    out, applied, refused = _moved(
        kv, LEDE, {"op": "move-block", "line": 3, "thru": 4, "into": 10}
    )

    assert applied, refused
    assert out.index("lede one.") > out.index("Use tools.")
    assert out.index("lede two.") == out.index("lede one.") + 1


def test_r71_only_structure_may_send_one(kv):
    """And the refusal says "block", not "section"."""
    lines = LEDE.split("\n")
    _p, heads, _t, _q = kv.mask(LEDE)
    _o, applied, refused, _x = kv.merge(
        lines,
        [
            {
                "specialist": "prose",
                "lo": 1,
                "hi": len(lines),
                "edits": [{"op": "move-block", "line": 3, "thru": 4, "into": 10}],
            }
        ],
        set(range(1, len(lines) + 1)),
        headings=heads,
    )

    assert not applied
    assert refused[0][2] == "only structure may move a block"


@pytest.mark.parametrize(
    ("text", "edit", "reason"),
    [
        (FENCE, {"line": 3, "thru": 4, "into": 12}, "half a fenced block"),
        (FENCE, {"line": 6, "thru": 7, "into": 12}, "half a fenced block"),
        (LOOSE, {"line": 5, "thru": 5, "into": 10}, "part of a list"),
        (LOOSE, {"line": 3, "thru": 3, "into": 10}, "part of a list"),
        (DETAIL, {"line": 3, "thru": 3, "into": 10}, "part of a list"),
        (DETAIL, {"line": 5, "thru": 5, "into": 10}, "part of a list"),
        (
            "# T\n\n## H\n\nbody.\n\nTitle\n=====",
            {"line": 7, "thru": 8, "into": 3},
            "holds a heading",
        ),
        (
            "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n## H\n\nbody.",
            {"line": 5, "thru": 5, "into": 10},
            "runs straight into it",
        ),
        (
            "# T\n\nalpha.\n\n## H\n\nbody.",
            {"line": 3, "thru": 5, "into": 8},
            "holds a heading",
        ),
        (LEDE, {"line": 3, "into": 10}, "`thru` is not a line"),
        (LEDE, {"line": 4, "thru": 3, "into": 10}, "`thru` is not a line"),
    ],
)
def test_r71_a_block_move_that_would_corrupt_the_file_is_refused(
    kv, text, edit, reason
):
    out, applied, refused = _moved(kv, text, {"op": "move-block", **edit})

    assert not applied, out
    assert any(reason in r for r in refused), refused


@pytest.mark.parametrize(
    ("text", "edit"),
    [
        (FENCE, {"line": 3, "thru": 7, "into": 12}),
        (LOOSE, {"line": 3, "thru": 5, "into": 10}),
        (DETAIL, {"line": 3, "thru": 5, "into": 10}),
        (
            "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n## H\n\nbody.",
            {"line": 3, "thru": 5, "into": 10},
        ),
        (
            "# T\n\n## H\n\nbody.\n\nalpha\n\n---\n\nbeta",
            {"line": 9, "thru": 9, "into": 3},
        ),
        (
            "# T\n\n- a\n\nplain para.\n\n- b\n\n## H\n\nbody.",
            {"line": 5, "thru": 5, "into": 9},
        ),
    ],
)
def test_r71_a_whole_block_still_moves(kv, text, edit):
    _out, applied, refused = _moved(kv, text, {"op": "move-block", **edit})

    assert applied, refused


def test_r71_a_no_op_block_move_is_refused(kv):
    """A block already where it is asked to go."""
    _out, applied, refused = _moved(
        kv, LEDE, {"op": "move-block", "line": 8, "thru": 8, "into": 6}
    )

    assert not applied
    assert refused == ["it is already there"]


def test_r71_a_block_may_not_be_sent_into_the_title(kv):
    """The title's section is where a buried summary's preamble already sits."""
    _out, applied, refused = _moved(
        kv, LEDE, {"op": "move-block", "line": 8, "thru": 8, "into": 1}
    )

    assert not applied
    assert refused == [
        "the title owns the whole file — give the line of the heading "
        "this belongs under"
    ]


def test_r71_a_deletion_inside_the_block_does_not_stop_it(kv):
    """The block travels with the sentence missing, which is what both asked."""
    out, applied, refused = _moved(
        kv,
        "# T\n\nalpha.\nbeta.\ngamma.\n\n## H\n\nbody.",
        {"op": "move-block", "line": 3, "thru": 5, "into": 10},
        before={
            "specialist": "noise",
            "lo": 1,
            "hi": 9,
            "edits": [{"op": "replace", "line": 4, "old": "beta.", "new": ""}],
        },
    )

    assert applied, refused
    assert "beta." not in out
    assert out.index("alpha.") > out.index("body.")
    assert out.index("gamma.") == out.index("alpha.") + 1


def test_r71_the_outline_job_may_not_send_one(kv):
    """That job is handed headings, not prose, so it cannot see a block."""
    lines = LEDE.split("\n")
    _p, heads, _t, _q = kv.mask(LEDE)
    _o, applied, refused, _x = kv.merge(
        lines,
        [
            {
                "specialist": "structure",
                "outline": True,
                "lo": 1,
                "hi": len(lines),
                "edits": [{"op": "move-block", "line": 3, "thru": 4, "into": 10}],
            }
        ],
        set(range(1, len(lines) + 1)),
        headings=heads,
    )

    assert not applied
    assert "may only send `move`" in refused[0][2]


def test_r71_the_report_counts_blocks_apart_from_sections(kv, monkeypatch, tmp_path):
    """End to end, through the real pipeline and the real report."""
    src = tmp_path / "doc.md"
    src.write_text(LEDE.replace("body.", "It is worth noting that body.") + "\n")

    def reply(who, _lo, _hi):
        if who != "structure":
            return []
        return [
            {
                "op": "move-block",
                "line": 3,
                "thru": 4,
                "into": 10,
                "why": "lede after the summary",
            }
        ]

    out = tmp_path / "out.md"
    run_canned(kv, monkeypatch, src, out, reply)
    body = out.read_text()

    assert body.index("lede one.") > body.index("Use tools.")


def test_the_run_record_survives_into_accept(kv, monkeypatch, tmp_path, capsys):
    """A real run writes it, `accept` reads it, and accepting deletes it."""
    src = tmp_path / "p.md"
    src.write_text(
        "# Policy\n\n## Summary\n\nUse approved tools only.\n\n"
        + "\n\n".join([FILLER] * 20)
        + "\n"
    )
    out = tmp_path / "p.kv.md"
    run_canned(kv, monkeypatch, src, out, lambda *_: [], extra=("--chat",))
    capsys.readouterr()

    record = json.loads((tmp_path / "p.kv.md.kvrun").read_text())
    assert record["agent"] in kv.LOCAL_AGENTS
    assert record["chat"] is True
    assert record["incomplete"] == []

    monkeypatch.setenv("KV_FORCE", "1")
    kv.cmd_accept(argparse.Namespace(file=str(src), edited=str(out), chat=False))
    capsys.readouterr()

    assert not (
        tmp_path / "p.kv.md.kvrun"
    ).exists(), "the record outlived the run it describes"
