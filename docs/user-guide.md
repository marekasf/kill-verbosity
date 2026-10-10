# kill-verbosity user guide

Makes a document shorter without losing what it says.

It works in two halves. The script does the counting: it finds the padding, it
checks the result, and it never rewrites a word itself. A local agent CLI does
the writing, one section at a time, with only the rules that section needs.

Read this to use it. [How it works](how-it-works.md) explains how it is built.
[SKILL.md](../SKILL.md) is what Claude reads when the skill fires on its own.
[Compared](compared.md) sets it beside ponytail and the Concise output style.

Testing it? Read [known issues](known-issues.md) first. It lists what is already reported, so
you spend your time on new findings.

## Install

You need Python 3.9 or newer. The tool uses the standard library only, so there
is nothing to install: no packages, no virtual environment.

Clone the repository and link it into `~/.claude/skills` as a Claude Code skill
named `kill-verbosity`:

```bash
git clone https://github.com/marekasf/kill-verbosity ~/src/kill-verbosity
mkdir -p ~/.claude/skills
cd ~/.claude/skills && ln -s ~/src/kill-verbosity kill-verbosity
```

Copying the whole directory into `~/.claude/skills` works too. Link or copy the
whole directory, never the launcher alone: a lone copy or hard link of
`kill-verbosity` cannot find the `killverbosity/` package beside it. On a
system whose default text encoding is not UTF-8 (a Windows code page), the
launcher restarts itself under `python3 -X utf8`, so you do not have to.

Check it:

```bash
cd ~/.claude/skills && kill-verbosity/kill-verbosity selftest
```

It prints `selftest ok (...)` with a count of checks and exits 0. The count
rises whenever a case lands, so read the exit status and not the number.
`selftest` never calls an agent, so it passes with no agent installed.

Run it unpiped. This holds for every command, not just `selftest`; see "Exit
codes" below.

The examples below write the launcher as `kill-verbosity`; use its full path,
or put it on your PATH.

`run` and `crosscheck` call an agent CLI to do the rewriting. Any agent works:

| `--agent` | Runs |
|---|---|
| (not given) | `KV_AGENT` if set, else the first installed of `claude`, `codex`, `agy`, `delegate`; a missing or failing one falls to the next without an error line |
| `claude`, `codex`, `agy`, `delegate` | that CLI, signed in (`delegate` runs in its raw mode, prompt on stdin) |
| `'any command'` | your command: the prompt arrives on stdin, the answer goes to stdout |

`plan`, `verify`, `accept` and `selftest` call nothing.

The prompt always goes to the agent over stdin. `codex` runs in its read-only
sandbox, `claude` runs with no tools, and `agy`, which has no read-only mode,
runs under `--sandbox`. Each call runs in its own process group, and a timeout
kills the whole process tree.

The developer test suite needs pytest and nothing else:
`python3 -X utf8 -m pytest tests` (`-X utf8` matters on Windows, where the
tests otherwise read UTF-8 files as cp1252). Users never need it.

## Use it

Copy the file first. `verify` needs an untouched original, and it refuses when
both paths are the same file.

```bash
cp doc.md /tmp/doc-orig.md

kill-verbosity plan doc.md                    # what is wrong and where
kill-verbosity run doc.md -o doc.new.md       # let an agent fix it
kill-verbosity verify /tmp/doc-orig.md doc.new.md
kill-verbosity accept doc.md doc.new.md       # put the result in place
```

Name the output to `accept` whenever you gave `run` a `-o`. Without `-o`, `run`
writes `doc.kv.md` and `accept doc.md` finds it on its own. `run` prints the
exact line to paste when it finishes. `accept --dry-run` runs every check and
says what it would do without copying anything.

A run leaves three files beside the input: `doc.kv.md`, `doc.kv.md.kvrun` and
`doc.kv.md.kvjournal`. Only the first is Markdown, and the same `*.md` that
found `doc.md` matches it, so a script sweeping a directory feeds the previous
output back in and writes `doc.kv.kv.md`. Exclude `*.kv.*` from the glob, or
send outputs elsewhere with `-o`. `run` warns when its input is named like an
output, and does not refuse: a second pass over a condensed file is legitimate.

Add `--chat` for a chat message or a review comment. It scores against a
message, not a document. Six more checks come on: burying the point,
colon-lists, correcting the reader, scaffolding, saying what you left out, and
signing off.

`run --dry-run` prints the job list and whether the chosen agent is installed,
without calling it. Use it before you spend a call.

`plan` and `run --dry-run` print `expected yield:` first: the words on lines a
dispatched candidate fires on or pulls in, over the document's words. It is an
upper bound on what fixing them can remove, not a prediction. Under 5% a run is
unlikely to land much: a long log can carry many hits and still lose under 1%.
When a prior run's output is beside the input, a second line says what that run
removed. A stale record is marked stale.

### If the agent fails

`--agent` names the agent asked first. If it fails on a job, the other
installed CLIs are tried in turn (`claude`, `codex`, `agy`, `delegate`,
skipping any not on PATH), sharing the job's remaining time. With no `--agent`
this is silent; when you named one, each fallback is printed and the job is
recorded as substituted. Only installation
is checked, not quota or sign-in, so a signed-out CLI is tried and fails like
any other.

If you named `--agent` yourself and every job was answered by a fallback, the
run stops before writing (exit 6). Fix the agent and rerun, or pass
`--any-agent` to keep the substituted answers.

## What each command answers

**`plan`**: where the padding is. It masks code fences, tables, blockquotes and
tree diagrams first, so the hits are prose. A regex matches text, not meaning,
so read every hit before touching it. `--json` prints the work list as JSON.
`--no-reorder` leaves sections where they are.

**`run`**: the whole pipeline. It splits the file, sends each section to the
one specialist that owns its problems, merges the replies, and gates the
result. Run it in the foreground; it prints a line per job as each lands.
`--timeout` caps the whole run (default 3600 s) and `--job-timeout` one
specialist call (default 240 s); `--no-budget` lifts the run cap. Jobs still
unsent when the budget runs out resume on a rerun, because every answer is
banked in the journal. `--no-agents` runs everything except the specialists, to
exercise the gates on your own tree without calling an agent.

**`verify`**: what the edit cost. `--in-place` shows each loss where it sits.

| What it prints | What it means |
|---|---|
| tokens lost, tokens invented | a number, path or identifier went or arrived. Exact. A deletion the skill orders is pardoned and listed on its own, except an id or a count, which is reported (exit 3) and never pardoned; anything else reads as damage |
| RULES LOST | a rule, risk, open question or disagreement went, and nothing left says it. Still over-fires |
| FINDING LOST | a dropped sentence sat inside a numbered finding item (`1. `) or a `**Fix:**` line. The `content dropped` list is blind to a sentence with no number, path or rule word, so this one fails the run instead of only listing it |
| content dropped | sentences went and nothing carries them. Deleting noise is the job, so this is a list to read |
| SHAPES SURVIVING | padding still in the file. Fix it, or say why you kept it |
| words replaced one-for-one | every place an edit put one word where another had been, with the new text around it. A substitution inside an otherwise untouched line is the one injury the document-wide checks cannot see |
| GATES BROKEN | a check the tree itself declares (`.killverbosity.gates.json`) passed on the original and fails on the edit |

**`accept`**: puts the output in place of the input, once `verify` allows it.
It first copies the current file to the first free `<name>.copyN.<ext>`. It
warns when nobody has crosschecked the output; it does not refuse on that.

**`crosscheck EDITED ORIG`**: a second opinion from a local agent of a
different vendor than the one that wrote the edits. It is the only step that
reads for meaning. See "Crosscheck" below.

**`trust FILE`**: allows one `.killverbosity.gates.json` to run. Nothing in it
runs until you have read it and trusted it, because it is found by walking up
from the document and could name any command. Editing the file withdraws the
trust.

**`--version`**: prints the build id and the file it was hashed from. Run it
before reporting anything about behaviour.

**Every list is truncated, and `--full` is the list.** The default shows the
first few of each block and prints `… showing 8 of 35`, so a reader who stops
there has seen a sample, not the findings. It matters most on the swap list,
which a reader must judge item by item. `--full` lifts the line caps and
nothing else. It cannot change a verdict or an exit code, so always pass it
when a person will read the output.

## Crosscheck

```bash
kill-verbosity crosscheck doc.kv.md doc.orig.md
KV_BACKEND=claude kill-verbosity crosscheck doc.kv.md doc.orig.md --context spec.md
```

The reviewer is `--backend`, else `KV_BACKEND`, else the first installed of
`codex`, `agy`, `claude` and `delegate`. It must not be the vendor family that wrote the
edits (codex is OpenAI, agy is Google, claude is Anthropic), and the writer is
read from the run record, so a same-family reviewer is refused by name.

If the chosen reviewer is not installed, an installed agent from another family
is used instead. If it fails (non-zero exit, timeout, empty answer), the next
one is tried. With none left, `crosscheck` exits 5 and records why in the
`.kvcross` file beside the output. The reviewer reads sandboxed copies of the
files in a temporary directory, with read-only tools, and gets 900 seconds.

The reviewer's findings are prose and do not block `accept`, but a finding of
kind `reversed_rule`, `weakened_rule` or `lost_fact` makes `crosscheck` exit 3
(review), so a meaning loss never exits 0. Any other kind (for example
`verbose`) leaves the exit at 0. Read the findings before you accept.
`--context FILE`, repeatable, adds a spec or a source document for the reviewer
to judge against.

## Exit codes

0 pass, 3 review, 1 broken, 2 bad input. Then three codes that only one command
uses: from `accept`, **4 forced**; from `crosscheck`, **5 not checked**; from
`run`, **6 all substituted**.

3 has **two** verdict words. `REVIEW` is the ordinary one. `NOTHING IN PLAY`
means a `freeze` matched every editable line, so no specialist got a span and
the file was only checked against itself. It is not 0, because `PASS` says
nothing needs reading and here nothing was read. It is not 1, because the
freeze was deliberate. `structure` is still sent, so a section move or summary
can land. Narrow `freeze.lines` to leave part of the file in play.

4 means the copy happened and a gate was overridden to let it (`KV_FORCE=1`).
It is not 0, so `KV_FORCE=1 kill-verbosity accept FILE && deploy` does not
deploy a forced result. It is not 1, because nothing was broken: the file on
disk is the run's output, as asked for. Treat 4 as "landed, and say so in your
report". The run prints `KV_FORCE overruled:` and names every gate it went
past.

5 means `crosscheck`'s reviewer never answered: every candidate outside the
writer's family was missing or failed. It is not 1. With no review, nothing was
found broken. Read stderr: each fallback names the failed candidate and the
next one tried, and the last line names every candidate tried.

6 means a fallback answered every job in `run` instead of the `--agent` you
named. An unset `--agent` never triggers it, and a partial substitution stays a
warning. Nothing is written, because writing would record a vendor swap you
never agreed to as accepted. It is not 1: no gate found damage. The answers are
saved in `FILE.kv.EXT.kvjournal`, so `--any-agent` or a rerun after fixing the
agent reuses them without paying twice.

Read exit codes off an unpiped run. A pipe gives you the last command's status,
not the tool's: `verify orig.md new.md | tail` prints REVIEW and exits 0.
Redirect instead.

```bash
kill-verbosity verify /tmp/doc-orig.md doc.new.md > /tmp/kv.txt 2>&1
echo $?
```

## Read all four lists

**A FAIL means something. Report it.**

On a corpus of documents with hand-written ideal edits, `verify` FAILs none,
returns REVIEW on all but one, and passes that one. A rule split into bullets
passes. So does `15 regions` → `fifteen regions`. A dated correction in a
plain sentence comes back REVIEW. So any FAIL you see is a finding.

On that corpus, tokens lost or invented and RULES LOST printed on none, because
they are silent unless something really went. Content dropped printed on most,
because deleting noise is the job. SHAPES SURVIVING printed on about a third.

The last two are lists to read, not failures. Fix each hit, or say in your
report why you kept it: a quoted example, a precise technical name, a credited
person. These numbers come from the check's own build corpus, so treat them as
a floor. A correct edit called broken on your document is a finding.

## Tell it a hit is correct

A hit you keep comes back on the next pass, and on everybody else's. Three
comments settle it in the document instead of in a report:

```markdown
The scan reports weak crypto.  <!-- kv:keep -->

<!-- kv:allow flaky, EX -->

<!-- kv:allow-shape parked problem, commit or checkout ref -->
```

`kv:keep` protects the line it sits on. `kv:allow` stops those words firing a
shape anywhere in the file, for a product name the tool reads as an opinion.
`kv:allow-shape` turns those shapes off file-wide, for a document *about* the
shape: a plan with a findings-table row per parked problem, or an analysis
citing the commit each claim was checked against. An unknown shape name is
refused, with the closest real one. `SKILL.md` has the full table, including
`kv:freeze` for a multi-paragraph block and `kv:summary`.

A heading recording a dated status (`## 2026-03-02 — DONE`) is protected like a
`kv:keep` line, without the comment: no specialist renames, moves or deletes
the section under it.

Use a comment for a shape the document keeps hitting for one reason. A single
correct hit is cheaper to explain in the report.

`.killverbosity.json` beside or above a document sets its folder's `profile`,
`specialists` and `targets`, and can declare `refuse` (an advisory warning
about a file) or `freeze` (lines no edit may touch). `SKILL.md` has the full
format.

`accept` refuses on a FAIL. If you have read the diff and the edit is right:

```bash
KV_FORCE=1 kill-verbosity accept doc.md
```

It prints what it overruled and exits 4. Say so in the run report.

**Worth reporting either way:** a fact that went missing and no list mentioned
it. A silent check is easy to miss.

## What it cannot check

It matches text, not meaning. It will not notice "X causes Y" turned into "X
does not cause Y". Only `crosscheck` reads for sense, and only if you run it.

It can only protect a fact that carries a number, path, link or identifier. A
plain-English fact has nothing to match on. Read the diff.

A prompt template gives it nothing at all. A file of `<role>` and `<task>`
blocks carries no such token, so `verify` on one cannot tell you whether
anything broke.

Length finds candidates and never decides. A file can pass every length check
and still be unreadable. A shorter file that lost a fact failed.

It checks that an agent is installed, never that it is signed in or has quota.
A run where no agent answered still writes an output, which is a copy of the
input, and ends in `FAIL — the file is incomplete`.

## Known gaps

- **`run` normally comes back above its target.** It aims at half of what it
  sent a specialist and lands near 1.2 times that. Past 1.5 is the tail, about
  one run in twelve, and the report says which side a run is on. Report a run
  past 1.5, and name the file.
- **Several detectors work off fixed phrase lists, so they miss anything not on
  the list.** `idiom` knows "under the hood" and misses "grind to a halt". A
  miss is expected; report it as an example, not as a crash.
- A bare dotfile is not protected. `` `.env` `` in backticks is; plain `.env`
  is not.
- `verify` runs once over the finished file, not after each section.
- `run` reads one file and writes one file. A move to another file is a note.

`known-issues.md` has the full list.

## When it goes wrong

Report these, with the file, the command you ran and the `--version` output:

- a fact that went missing and `verify` said nothing;
- a shape it flagged that was correct: a quoted example, a precise technical
  name, or a person credited rather than padded;
- padding it walked straight past;
- output that reads worse than the input.

The last one is the one to send even if you cannot say why.
