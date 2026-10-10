---
name: kill-verbosity
description: Simplify documentation and code without changing meaning or behavior. Use when an agent must shorten verbose Markdown, remove jargon, deduplicate facts, delete worklog or temporary state, clarify structure, open a long document with a one-page summary a reader can act on alone, recast a review or report so every finding carries a problem, a fix and what the fix solves, simplify names or control flow, remove dead code, or reduce a refactor to its clearest form. Runs the edits through any AI agent CLI (claude, codex, agy and delegate are auto-detected) and gates the result. Also /kill-verbosity.
---

# Kill verbosity

Make documents and code faster to understand. Cut what the reader does not
need, then shorten what survives. Preserve every unique rule.

One agent holding thirty-five rules applies four of them. So the rules are not
here. Each one lives in the prompt of the specialist that owns it, and the
helper calls those specialists one aspect at a time, each through a local
agent CLI.

Paths below are relative to this skill's directory. `docs/user-guide.md` is
what each command answers and what it cannot check. `docs/how-it-works.md` is
the design: the flow, the gates and why each one exists. Read it before
changing the orchestrator. `docs/known-issues.md` is the open list.

## Run it

In Claude Code the launcher is `~/.claude/skills/kill-verbosity/kill-verbosity`.
Your working directory is the user's project, not this one, so always call it
by that full path.

```bash
kv=~/.claude/skills/kill-verbosity/kill-verbosity
$kv run FILE --dry-run              # the job matrix, nothing sent. Run this first
$kv run FILE                        # the whole pipeline, writes FILE.kv.md
$kv accept FILE                     # put that output in place of FILE
```

`run` takes minutes. Give the Bash call the 600000 ms timeout. Inside Claude
Code the `claude` CLI is already installed, so it is the agent `run` picks.

### Before the first run

1. Python 3.9 or newer. The tool uses the standard library only, so there is
   nothing to install. The whole directory must be in place: a lone copy of
   the launcher cannot find the `killverbosity/` package beside it.
2. Have one AI agent CLI signed in. `claude`, `codex`, `agy` (the
   Antigravity CLI) and `delegate` (a multi-backend dispatcher) are found on
   PATH and used first-installed-first, with the others as fallback. Any other agent works too:
   `--agent '<command>'` (or `KV_AGENT`) runs that command with the prompt on
   stdin and reads the answer from stdout.
3. `$kv selftest`. It runs the tool's own checks: the shape table, the
   routing, the gates. It never calls an agent, so it passes with nothing
   installed and nobody signed in. It tells you the install works. It cannot
   tell you a run will work.

A run with no working agent does not hang. It prints the cause once and ends
in `FAIL — the file is incomplete`. It still writes an output file, and that
file is a copy of the input. It is not a result. If you compare input and
output and nothing was cleaned, look for that `FAIL` line first: it means no
agent answered, not that the tool found nothing to do.

`run` splits the file and routes every shape hit to the one specialist that
owns it. Each specialist gets its own span and its own prompt. The replies
merge into one file, and `verify` gates the result.

It never writes over the input. `verify` needs an untouched original, and the
file you were asked to work on is not yours to overwrite.

### How the agents are called

Every specialist prompt goes to a local CLI over stdin, never on the command
line:

| Agent | Command | Notes |
|---|---|---|
| `claude` | `claude -p --restricted --tools=` | no tools for a specialist; `--tools=Read,Grep,Glob` for `crosscheck` |
| `codex` | `codex exec --skip-git-repo-check --sandbox read-only -` | read-only sandbox |
| `agy` | `agy --input-format stream-json --output-format stream-json --sandbox --dangerously-skip-permissions --disable-slash-commands --print-timeout Ns` | the prompt is one stream-json message; the answer is `result.response` of the last result event. agy has no read-only mode, so it runs under `--sandbox`. `crosscheck` adds `--add-dir` |
| `delegate` | `delegate --mode raw --timeout N --prompt-file -` | `raw` is the one mode with no output contract of its own. delegate's own backend fallback stays on. `crosscheck` also restricts it to backends that can read files |

`gemini` and `antigravity` are accepted as names for `agy`. Any other name is a
usage error (exit 2). Every call runs in its own process group, and a timeout
kills the whole process tree, not just the CLI.

**If the agent fails, the run falls back by itself.** The other installed
CLIs are tried in turn, in the order `claude`, `codex`, `agy`, `delegate`,
skipping the one already tried and any that is not on PATH. They share the
job's remaining clock, so a fallback never overshoots the budget. With no
`--agent` and no `KV_AGENT` the fall is silent: no error line, the job line
carries `~`, and the `answered by:` line names who answered. When you named
the agent, every fall is printed on stderr naming the job and the agent that
answered instead. Either way the job is recorded as substituted. Only installation is checked, not quota
or login, so a signed-out CLI is tried and fails like any other.

### The tool does the work, not you

`run` is the job. It spawns the agents, merges their replies and gates the
result. You read what it printed and report it.

- **Run it in the foreground.** Backgrounding it and reading the document
  yourself while it works is the worst way to use this. You cannot see the
  progress, you duplicate what the specialists are already doing, and you race
  the tool for the same file. It prints a numbered line per job as each lands,
  and that is the only progress it gives you.
- **Do not hand-edit the file.** Not before the run, not during it, not to
  finish it off afterwards. A hand-made edit list for "whatever it did not fix"
  means nobody can tell which changes came from where.
- **A refusal is the answer, not a to-do.** Every refused edit is printed with
  its line and its reason. It was refused because it was unsafe. Put it in the
  report. Do not apply it by hand.
- **A `note` is for a human.** Specialists raise what no tool can decide. Notes
  go in the report. You do not act on them.
- **If the output is wrong, the tool has a bug.** Say which lines and what went
  wrong. Patching around it by hand hides the bug.

Whether to keep the output is the user's call: show them the report and ask
before `accept`. It is all or nothing.

- Keep it: `$kv accept FILE`. It reruns `verify` and refuses if anything broke.
  It also refuses a run that left a span unedited, because `verify` compares
  two files and cannot see that a specialist died. `accept --dry-run` runs
  every check and prints what `accept` would do without copying anything.
- Drop it: delete `FILE.kv.md` and say why.

There is no third option. Copying some of the edits across by hand puts back
the ones the gates threw out.

Before it replaces anything, `accept` copies the current file to the first
free `<name>.copyN.<ext>`, never reusing a number, and prints the path. A
mistaken `accept` costs a rename, not the text. That copy lands next to the
file, so in a gitignored directory the backup is gitignored too.

`accept` also says when nobody has crosschecked the output. It does not refuse
on that; it only tells you.

### The run record

`run` writes `FILE.kv.md.kvrun` beside the output: which agent the run asked
for (`agent`), whether it read the file as chat, which protected tokens `noise`
was allowed to drop, and which spans died. Each `job_spans` entry also says who
answered that job (`answered_by`, with `answered_by_state` saying whether that
was read, unknowable or not looked at) and whether it was `substituted`;
`substituted_jobs` is the total. `verify`, `accept` and `crosscheck` read it,
so deleting it makes them contradict the run that made the file. A record
older than the output belongs to an earlier run and is ignored with a line
saying so.

More fields answer questions the report itself cannot:

- `source` and `source_at_finish`: the input's digest when the run read it and
  when it finished. Different values mean something else wrote the file while
  the specialists were out. In the output, that looks exactly like a specialist
  putting back text somebody had just removed, so the run says so loudly.
  `null` in the second means the input could not be re-read.
- `frozen_lines` of `document_lines`: how much of the file a `freeze` held out
  of play. `0` means counted and none frozen.
- `editable` and `editable_unfrozen`: lines a specialist could touch, and lines
  it could have touched with nothing frozen. `editable: 0` has two causes with
  opposite remedies: no editable prose at all, or a freeze that took every
  editable line. Only the second gets the `NOTHING IN PLAY` verdict.

### What `accept` refuses

`accept` refuses on four things:

- a run record that is missing, stale or unparseable. An unknown pardon list
  is an empty one, and forgiving nothing means accepting everything;
- an input edited after the run that wrote the output, since accepting would
  throw that edit away;
- spans the run left unedited;
- a `verify` verdict outside PASS and REVIEW.

`KV_FORCE=1 $kv accept FILE` takes the output over any of those four. Use it
only when you have read the whole diff and the gate is wrong. You are
overruling the only check that reads the file as a whole, so say in your
report that you used it and what you read. A forced accept exits 4, not 0, and
prints `KV_FORCE overruled:` naming each gate it went past.

### When it fails

`run` exits 0 when it passed, 3 when hits remain but nothing broke, 1 when
`verify` found real damage or a specialist errored, and 2 when it would not
start. Only 1 blocks `accept`. `accept` adds **4, forced**: the copy happened
with a gate overridden.

`crosscheck` adds **5, not checked**: no reviewer answered. Each candidate
outside the writer's own family was either not installed or failed (non-zero
exit, timeout, empty answer), and the reason is recorded in `.kvcross`. It is
never 1, because a reviewer that never spoke found no damage.

`run` adds **6, all substituted**: you named `--agent` explicitly and every job
was answered by a fallback instead. Leaving `--agent` at its default
never triggers it, and neither does a partial substitution, which stays a
warning. Nothing is written on 6, but nothing paid for is lost: the answers
are already banked in the `.kvjournal`. Fix why your agent did not answer and
rerun the same command, or pass `--any-agent` to accept the substituted
answers.

Exit 2 means the input or the arguments are wrong, and nothing ran: the file
is not Markdown, a code fence or the front matter never closes, the text still
carries a file viewer's line numbers, an agent name is unknown, or a marker is
misspelled (`kv:kep` protects nothing). Each one names the line. Fix it and
rerun.

Read what it printed, in this order:

1. **spans left unedited**: the file is incomplete, and there are two reasons
   with opposite answers. The last line the run printed names which.
   - **The budget ran out before the job was sent.** Run the same command
     again, same `--agent`, and do not delete the output. Every answer already
     paid for is banked in the `.kvjournal` beside it, so the rerun pays only
     for what is left. Raise `--timeout` with it or the same budget runs out
     again.
   - **A specialist failed.** It was already retried and fallen back on, so
     asking again will not help. `KV_FORCE=1 $kv accept FILE OUT` first, which
     keeps every landed edit and leaves that span as it arrived; only then
     delete the output and rerun with a different `--agent`. The journal is
     keyed by agent, so that rerun replays nothing, which is why keeping what
     landed comes first.
2. **verify's hard failures**: tokens lost, tokens invented, shapes introduced,
   summary lost. Do not apply the output.
3. **refused edits**: the gates held. Report them. The line above them, "went
   to the line's owner", is bookkeeping: one specialist owns each line and the
   others were turned away. Report the count, not the lines.
4. **shapes surviving**: read and decide.

## Flags

| Flag | Use |
|---|---|
| `--agent NAME\|'COMMAND'` | `run` only. `claude`, `codex`, `agy`, `delegate`, or any command that reads the prompt on stdin and prints the answer. Default: `KV_AGENT`, else the first installed of claude, codex, agy, delegate. The installed ones are tried when it fails |
| `--any-agent` | `run` only. Without it, a run whose jobs were ALL answered by a fallback rather than an explicitly named `--agent` stops before writing (exit 6). This flag accepts those answers and proceeds |
| `--dry-run` | `run`: print the job matrix and whether the agent is installed (`installed, not probed` or `NOT INSTALLED`), and stop. Run this first. `accept`: run every check and copy nothing |
| `--chat` | `run`, `plan`, `verify`, `accept`. The text is a chat reply or a review comment, not a document |
| `--no-agents` | `run` only. Everything except the specialists: the gates, the merge, `verify`, and a run record saying no specialist ran. The output is the input. It exercises the gates and the `accept` refusals on your own tree without calling an agent |
| `-o PATH` | `run` only. Where to write; also spelled `--out`. Default `FILE.kv.EXT` |
| `--timeout S` | `run` only. The whole run, default 3600. Jobs still unsent when it runs out resume on a rerun |
| `--job-timeout S` | `run` only. One specialist call, default 240 |
| `--no-budget` | `run` only. No ceiling on the run. Every job is sent |
| `--no-reorder` | `run` and `plan`. Leave every section where it is: no `move`, no `move-block`, and the order job is not sent. Reordering is the default. Use this when the order is load-bearing, or when someone has to diff the output by hand. The run names every move it makes under `moved —` either way |
| `--full` | every command. Print every finding, not the first few. It lifts the line caps and nothing else; it cannot change a verdict or an exit code |
| `--json` | `plan` only. The work list as JSON (chunks, shape hits, facts, duplicates) instead of the printed report |
| `--in-place` | `verify` only. Show each loss where it sits, as a diff, instead of grouped by check |
| `--context FILE` | `crosscheck` only. Another file the reviewer should read. Repeatable |
| `--backend NAME` | `crosscheck` only. Which local agent reads the result: `codex`, `agy`, `claude` or `delegate`. Overrides `KV_BACKEND`. An agent of the same vendor family as the writer is refused by name |
| `--version` | the program, not a command. Prints the build id and the file it was hashed from |

Environment: `KV_BACKEND` picks the `crosscheck` reviewer when `--backend` is
not given. `KV_FORCE=1` lets `accept` overrule its gates (see above).

**The specialists run 4 at a time**, so a matrix of N jobs costs
`ceil(N/4) × --job-timeout` of wall clock if every job runs its full ceiling.
When that exceeds `--timeout`, the run says so on stderr at dispatch (on
`--dry-run` too) with both numbers you could raise. It is a warning, not a
refusal: a short budget with a partial run is legitimate, and the answers are
banked.

Above the matrix, `--dry-run` and `plan` print `expected yield:`, the words on
the lines a dispatched candidate fires on or pulls in, against the document's
words. It is an upper bound on what a run can remove, not a prediction. Under
5% it says a run is unlikely to land much. When a prior run's output is beside
the input, a second line says what that run actually removed.

Run `--version` before reporting anything about behaviour. A file date on the
launcher or a symlink says nothing about the build behind it.

Set `--timeout` to at least the run's own measured tail under whatever outer
limit you run below. Every run ends by printing that tail (`Tail: 140s after
the last job was sent`), on the failing path too. The budget governs when jobs
stop being sent; `verify` and the report run after it, outside it. So a
fraction of the outer limit does not work: the tail scales with the document,
and the budget only with what you typed. Under a 600-second command limit,
`--timeout 400` worked on a 50,000-word file. Setting it at all means the run
stops on its own terms, banks what it has and tells you to rerun, instead of
being killed with nothing said.

## Crosscheck

`run` and `crosscheck` are two calls because crosscheck reads both files end
to end in one call and is the slow step.

```bash
$kv run FILE
$kv crosscheck FILE.kv.md FILE.orig.md
```

`run` copies the input to `FILE.orig.EXT` the first time, so `verify` and
`crosscheck` still have an untouched original after anyone edits by hand.

Every gate in this tool matches text. None of them can see "the service has a
consent flow" turned into "the service has **no** consent flow": every token
survived. `crosscheck` is the one step that reads for sense. `run` ends by
printing the command. Skipping it means nothing checked whether the document
is still true.

The reviewer is `--backend`, else `KV_BACKEND`, else the first installed of
`codex`, `agy`, `claude`, `delegate`. It must not be the vendor family that
wrote the edits (codex is OpenAI, agy is Google, claude is Anthropic; delegate
picks its own backend, so it has no fixed family); the writer is read
from `.kvrun` or `.kvcross`, from the agents that actually answered and not
only the one asked for. If the chosen reviewer is not installed, an installed
non-writer is used instead. If the reviewer fails, the next installed
non-writer is tried. When you named the reviewer, each fall prints a line on
stderr naming who failed and who is next; otherwise the fall is silent. With
none left, it prints one `crosscheck: not checked` line and exits 5. The reviewer reads sandboxed copies of
the files in a temporary directory and gets 900 seconds.

Its findings are prose, so they do not change the exit code and they do not
block `accept`. Read them before you accept, and read the text a finding names
before acting on it. A finding that asks you to delete something is a finding
about the document, not about a job.

`--context FILE`, as many times as you need, adds a spec, an earlier review or
the source reports to judge against.

## The other commands

```bash
$kv plan FILE                          # the work list, no agents: hits, repeats, inconsistencies
$kv verify ORIG EDITED                 # 0 clean, 3 hits remain, 1 a fact was lost or invented
KV_BACKEND=agy $kv crosscheck EDITED ORIG
$kv trust DIR/.killverbosity.gates.json
$kv selftest                           # confirms the install and the routing table
```

`plan` is for looking, not for working. Use it to see what `run` will route
before spending agent time, or to answer "what is wrong with this file" without
changing it. It is not a licence to make the edits by hand.

`plan` also prints two layout notes no specialist acts on, because both need a
judgement about what the author meant:

- **a seam inside a wall**: on a paragraph over 150 words, the sentence where
  the subject changes, so there is somewhere to put a sub-heading.
- **a list written as prose**: three or more sentences in a row opening on the
  same word. Turning them into bullets can drop the words that carried the
  logic between them, so the tool points and stops.

`trust` acknowledges one `.killverbosity.gates.json`, described below. Nothing
in that file runs until it is trusted, and editing it withdraws the trust.

## Folder settings: `.killverbosity.json`

A profile and a specialist list are properties of the folder the document
lives in, so they go in `.killverbosity.json` beside it rather than on every
command line:

```json
{"profile": "clinical", "specialists": ["noise", "prose"], "targets": ["docs/*.md"]}
```

The tool searches for that file from the document upward, not from your shell,
so a document scores the same read from its own folder and from the
repository root. `targets` (optional) are globs relative to that file; a
document matching none of them reads as though the file were not there, and
the search keeps going upward.

### `refuse`: a warning about a file

```json
{"refuse": {"paths": ["status*.md"],
            "reason": "the test suite splits these rows on `|` and asserts a cell count"}}
```

**`refuse` is advisory. It refuses nothing.** Every command runs in full; a
match prints one line on stderr naming the file, the pattern, the declaring
file and your `reason`. Globs are matched relative to the declaring file. A
bare string, `{"refuse": "reason"}`, covers the whole tree and is almost never
what someone means.

It is for two hazards, and `reason` is where you say which, because the tool
prints your words and asserts no cause of its own. One is a file another tool
parses by line, where a reflow this tool calls clean is unreadable to that
one. The other is a generated file, where an edit is wasted: the next
regeneration reverts it. Write one hazard per declaration. `reason` is printed
for every path the declaration covers, so a second hazard wants a second
`.killverbosity.json` in the subdirectory it applies to; the nearest one wins.

When a declaration warns you:

1. Run `plan` on the file anyway. It writes nothing, and the findings are real;
   take them to whatever generates or owns the file.
2. Report it as written ("2 files declared, ran anyway, reason quoted"), never
   as "kill-verbosity is unavailable here".
3. You decide. If the reason says the file is parsed by line or by row, prefer
   `plan`, `verify` and `crosscheck`, which write nothing, and think before
   `run`.
4. Do not narrow someone else's declaration yourself. Say what you believe and
   let whoever wrote it rewrite it.
5. If the hazard is a set of lines rather than the whole file, that is `freeze`.

### `freeze`: when the hazard is a line

A refusal is about the whole file, and the hazard usually is not. In a typical
status document only the table rows are parsed, perhaps 8% of the lines, and
the rest is exactly this tool's job.

```json
{
  "freeze": {
    "paths": ["status*.md"],
    "lines": ["^\\s*\\|", "^## "],
    "reason": "rows are split on `|` and must keep exactly 6 cells; every `## ` ends a span for the section reader"
  }
}
```

A line matching any pattern in `lines` is blanked out of the scanned prose and
taken out of the editable set. No specialist is sent into it, `merge` refuses
any edit that lands on it, `verify` refuses when one changed anyway (so
`accept` refuses too), and it comes out of the run byte-identical. `paths` is
optional; omit it to freeze those lines in every document under the
declaration. `lines` and `reason` are required.

- **Write the patterns from your parsers, not from your prose.** The pattern
  nobody guesses is usually a delimiter such as `^## `: a heading inserted
  between two rows silently truncates the section the parser reads.
- **Over-match on purpose.** A frozen line no parser reads costs a few lines of
  uneditable prose. An unfrozen line a parser reads is a corrupted file.
- **A freeze that matches no line says so, loudly, and protects nothing.** Fix
  the patterns before running.
- **It is not `kv:keep`.** That marker protects a line by being written on it,
  which adds text to a table cell, and a fixed cell count is what the freeze
  protects.
- **It protects only lines you can name, for readers you can name.** A
  weakened word (`because` to `per`, every token surviving) is not a parse
  break, and no line rule sees it. A file read by parsers you cannot list is
  not covered by any freeze. Do not run `accept` on such a file; use `plan`,
  `verify` and `crosscheck`.

### `.killverbosity.gates.json`: the tree's own checks

A tree can declare its own structural checks beside its `.killverbosity.json`.
`verify` runs each one twice, against the original and against the edit:

```json
{"gates": [{"name": "status-rows", "argv": ["python3", "tools/check_rows.py", "{edited}"], "timeout": 60}]}
```

`argv` is a list with no shell. At least one argument must name `{edited}`,
and `{original}` is available too; a check that cannot see the edit would pass
for ever. `timeout` is whole seconds, 1 to 3600. A check that passes on the
original and fails on the edit fails `verify`. A check already failing on the
original also fails it, unless you excuse it by name with `KV_GATE_OK=name`.
A check that passes even when `{edited}` points at a missing file is reported
as blind.

The file is found by walking up from the document, so a file you never opened
could name a command. That is why **nothing in it runs until you trust it**:
read it, then run `$kv trust PATH`. The acknowledgement is tied to the file's
exact bytes.

## Overriding it from inside the file

HTML comments settle an argument with the tool once, in the document, so
nobody has to keep refusing the same hit.

| Marker | What it does |
|---|---|
| `<!-- kv:keep -->` | on a line: no specialist may edit that line |
| `<!-- kv:freeze -->` ... `<!-- kv:end -->` | everything between, blank lines included: no specialist may edit or flag any of it |
| `<!-- kv:allow flaky, EX -->` | anywhere in the file: those words never fire a shape |
| `<!-- kv:allow-shape parked problem -->` | anywhere in the file: those shapes never fire at all |
| `<!-- kv:summary -->` | above the first section heading: the opening prose is the summary, so no Summary section is inserted (below it: exit 2) |

A line opening `CRITICAL INFO FOR AGENTS` is a `kv:keep` without writing one,
and it protects its whole paragraph, down to the next blank line, because the
instruction wraps. `kv:freeze` protects everything up to the next `kv:end`, or
to the end of the document if `kv:end` is never written. A heading recording a
dated status (`## 2026-03-02 — DONE`) is protected the same way: no specialist
renames, moves or deletes the section under it.

```markdown
The scan reports weak crypto.  <!-- kv:keep -->

<!-- kv:freeze -->
1. Never delete a decision without a citation.

2. Every claim carries the command that produced it.
<!-- kv:end -->

<!-- kv:allow flaky, EX -->

<!-- kv:allow-shape parked problem, inanimate perceiver -->
```

Use `kv:allow` when a word this tool reads as an opinion is the product's name
or the field's own term. Use `kv:keep` for a line that has to stay exactly as
it is: a quotation, a command, a legal sentence.

Use `kv:allow-shape` when the document is *about* the shape. A file explaining
what a parked problem is has to show one, so it reads as a file full of them.
Name only the shapes the document discusses; a name the shape table does not
have is refused, with the closest real name.

## Domains and document kinds

The shapes, the words and the numbers are not fixed. Every one of them is data
in a profile in `profiles/`, and the default profile is a software repository
writing English and Polish.

`plan` and `run` print how they read the file:

```
Release checklist  —  312 words, 3 chunks  ·  read as checklist, profile genre-checklist
```

Six kinds are detected: checklist, log, prose, reference, roadmap, and transcript.
The kind decides which rules apply. A reference document is not asked for a
summary or for a conclusion at the end of each section, because a glossary
entry only reports. A log keeps its dated entries instead of having them
deleted as worklog. A roadmap keeps its roadmap: `planning` is switched off,
because a document whose sections are phases and milestones is made of the
shape that specialist deletes. Rule sentences are protected on every document,
whatever its kind, by the `rule word` bank below.

Anything else (a domain, another language, a house that numbers its findings
differently) is a profile, named in `.killverbosity.json`:

```json
{"profile": "clinical"}      // profiles/clinical.json
{"profile": "./mine.json"}   // a path, for one that does not ship
```

A profile is JSON. Each key replaces a list, or edits it with `add` and `drop`:

```json
{
  "name": "clinical",
  "domain_jargon": ["per protocol", "care pathway", "patient journey"],
  "safe_metaphors": {"add": ["titre", "washout", "arm"]},
  "units": {"add": ["mg", "mL", "mmHg"]},
  "id_families": ["[A-Z]{2,4}-\\d{2,5}"],
  "never_swap": ["must", "never", "load-bearing"],
  "thresholds": {"long_sentence": 35, "summary_share": 0.12},
  "langs": ["en", "es"],
  "words": {"es": {"summary heading": ["resumen", "conclusiones"]}},
  "shapes": {"drop": ["worklog"], "add": {"passive dosing": "was administered"}},
  "specialists": {"summary": null}
}
```

`"specialists": {"name": null}` switches one off. `"shapes": {"drop": [...]}`
takes any shape, whichever family it lives in. Naming a profile yourself
always beats the detected kind. `never_swap` fails `verify` (exit 1) if a
listed word's count anywhere in the document goes down: no other gate reads
for meaning, so a one-word swap that changes a claim (`is` to `has`,
`load-bearing` to `critical`) otherwise passes.

`words` carries a language's phrases. Beyond the chat shapes it takes four
lists that decide how the file is read at all:

| List | What it decides |
|---|---|
| `summary heading` | which heading means "this section is the summary" |
| `rule word` | whether a section states rules, so it is read as a rules file |
| `claim word` | which sentences are a rule, a risk, an open question or a disagreement, and so may not be deleted |
| `abbreviation` | which full stops do not end a sentence |

A language may give words for some shapes and not others. The ones it has no
words for are switched off rather than refused.

A profile that asks for something impossible is refused with the reason, not
ignored: an unknown key, a share above 1, a count that is not whole, a section
that is not an object, a shape no specialist owns, a shape name already taken,
a unit spelling with no family, a language with no words, a broken pattern.

## The specialists

Each owns one aspect and sees only its own rules, from `specialists/<name>.md`
on top of `specialists/_common.md`. Pass order is top to bottom: deletions
before rewording, so a line one pass removed does not come back reworded by the
next.

| Specialist | Scope | Owns |
|---|---|---|
| `planning` | document | the sections that exist to schedule work: phase plan, task list, estimate, target date. It is handed the heading list and never the prose, and it has one op nobody else has, `delete-section`, which takes a heading and the whole section under it. First in pass order, because it deletes. `genre-roadmap`, `genre-checklist` and `genre-log` switch it off |
| `noise` | section | what should not exist: process leak, editor note, draft diff, worklog, commit or checkout ref, unexplained reference, asks reader to verify, unsourced citation, citation plumbing, echo, empty framing, changelog narration, bare internal id, defers its own point |
| `actionable` | section | every finding carries a problem, a fix and what the fix solves: parked problem, vague action, activity report, planning language |
| `quotable` | section | the quote test, whether the line still means what it meant when lifted out alone: number without its noun, identifier as subject, evaluative adjective, inanimate perceiver, bare nominalisation, idiom |
| `prose` | section | the words: frame, hedge, purpose hedge, wrapper, agreement move, jargon, nominalisation, X-not-Y, em-dash pressure, long sentence, paragraph wall, repeated list item, mixed list styles |
| `chat` | document | `--chat` only: colon label, message scaffold, omission note, sign-off, corrects the reader, buried lead |
| `structure` | document | the job of the file, result first, one owner per fact, headings, duplicates. Moves whole sections. One shape: corporate header |
| `summary` | document | the one-page opening summary a long document owes its reader. No shape of its own: it looks for an absence, and an absence never fires a rule |

`specialists/code.md` is for source code. It is not in the pipeline (`run`
works on Markdown), so read it directly when the thing to simplify is code.

`specialists/jargon-hunt.md` is not a specialist. It is the single prompt the
others were split out of. Read it by hand; the specialist list does not accept
it. Nothing checks that the split still covers it.

A specialist is only woken where its own shapes fired. The two document-scope
ones that look for absences are the exception. `structure` runs on every
document. `summary` runs once the file passes 800 words, the length at which
it owes the reader a summary. In `--chat` neither runs, and `chat` runs
instead.

Naming specialists in `.killverbosity.json` does not overrule their wake
conditions. If none of the named ones has anything to answer, the run exits 2
and prints the condition that blocked each. If some do, the idle ones are named
on stderr and the rest run.

`noise` may empty a section and may reword a heading. It may not delete one.
Removing a section is `structure`'s call, because it is the only specialist
that can see what still links to it.

## How the merge is safe

Specialists return line edits, never rewritten text. An edit carries the line
it replaces, and the orchestrator refuses it unless that line matches the file
apart from leading and trailing spaces. A specialist that misread the line it
is rewriting does not get to rewrite it. An edit outside the span the
specialist was given is refused too, and so is one inside a quotation unless
`noise` sent it.

Only `structure` may move whole sections. It names two headings, the section
to move and the heading it goes before, and the orchestrator works out the
range. It cannot send a line range of its own, so it cannot take half a list
or a span that ends inside a code fence. A move relocates text without
rewriting it, so it cannot lose a fact.

A reword may not drop a number, path, ticket, link or `code span` from the line
it replaces. That edit is refused at the line that ate the fact, which is more
use than `verify` naming the token twenty edits later. `noise` is exempt:
deleting a dead commit ref is its job.

Each line has one owner. The first specialist to claim it in pass order keeps
it; every later claim is reported, never silently dropped. Inside the opening
summary `summary` claims first, and in `--chat` mode `chat` does, whatever pass
order says. It is first refusal, not a veto: if the owner's edit fails a gate,
the next specialist gets the line. A reword inside a code fence, a table
diagram or a blank line is refused outright, and so is an insert at those
places, because a line dropped into a table or an indented block breaks it.
Two anchors are always legal: a heading, and a blank line, except a blank line
with block content on both sides of it.

An opening summary goes under the title, or at the top of a file that has no
title. Wherever the specialist aimed it, that is where it lands.

No two lines in one run may be rewritten to the same sentence: folding
eighteen repeated paragraphs into eighteen copies of one pointer is not
deduplication. Short repeats are fine; two cells both cut to "None" are two
cells. A summary may name an open question the document already records.

Three more gates read the seam between one line and the next. A delete that
leaves the line above ending on "and" is refused. So is an edit that leaves the
same words on both sides of a line break. And `summary` may not open a file
that already opens with a summary, nor point at a section another specialist
is renaming in the same run.

A specialist sees one span, so it cannot tell a repeated identifier from the
document's only mention of one. The orchestrator can, and every job is told
which facts in its span appear nowhere else in the file.

Everything refused is printed. So is every `note`: the things no tool can
decide, which a specialist is told to raise rather than guess at.

## What only a human can check

`verify` runs at the end of `run`. It rescans for every shape and checks that
nothing left the file. Tokens lost, tokens invented, shapes introduced, a lost
summary and lost rules are hard failures. Shapes surviving, dropped content and
gone headings are lists to read and decide on.

Two checks answer "was anything removed", and they cover different facts:

- the token gate, for a fact carrying a number, path, link or identifier;
- the claim check, for a fact carrying none. Every sentence in the original
  must have its content words together in some surviving sentence. A sentence
  stating a rule, a risk, an open question or a disagreement must survive, and
  its loss fails the run. Anything else that went is listed for reading,
  because deleting noise is the job.

It matches text, not meaning. It will not catch "X causes Y" turned into "X
does not cause Y". Read the diff.

Then confirm these five yourself:

- every subject and object is a thing the reader can point at;
- the opening summary states results, and a reader who stops after it knows
  what was found and which section to open next;
- every finding carries its problem, its fix and what the fix solves;
- headings describe distinct content;
- every section ends on a decision or an action.

Length is not on the list. A shorter document that lost a fact failed, and a
file can pass every length check and still be unreadable.

On a dense rules document a cut of one or two per cent is the expected result,
not a broken run: the file is instructions, and shortening an instruction is
how it stops being true. A large cut on that kind of file is the thing to
check. Read the run's own count of what it did (summaries written, sections
moved, duplicates folded, paragraphs merged) before the word delta.

Adding a rule, a shape or a specialist is covered in `docs/how-it-works.md`.

## Output

Report:

- the before and after word count;
- the main deletions and structural changes;
- what each specialist refused, and why;
- which agent answered, and any substitution the run reported;
- anything left unchanged because its meaning, behavior or safety role was
  unclear;
- useful changes not applied because they would alter meaning or public APIs.

No introduction, praise, feature tour or repeated summary: the reader came for
the changes, and the list above already is the summary.
