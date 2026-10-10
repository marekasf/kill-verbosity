# kill-verbosity — how it works

How the tool is built and why. To use it, read the [user guide](user-guide.md).
For how the skill fires inside Claude Code, read [SKILL.md](../SKILL.md).

## The problem it solves

One agent holding thirty-five simplification rules applies four of them. It
picks the rules easy to see in its span and drops the rest. Telling it to try
harder does not work, because the failure is attention, not effort.

So the rules are split. Each one lives in the prompt of the single specialist
that owns it. A regex table maps every shape to exactly one owner. The
orchestrator finds the shapes, wakes only the specialists whose shapes fired,
and gives each one its own rules and its own span.

## The use cases

Each row is one request. Naming a specialist in `.killverbosity.json` runs only
that one.

| Ask | Scope | Runs | What it may do |
|---|---|---|---|
| "add a summary on top" | whole document | `summary` | insert an opening page |
| "simplify the structure" | whole document | `structure` | move sections, rename headings |
| "it's too long" | section | `noise` | delete what should not exist |
| "drop the roadmap" | whole document | `planning` | delete a whole section of plan |
| "make it actionable" | section | `actionable` | attach a fix to every problem |
| "it won't survive being quoted" | section | `quotable` | put the caveat inside the sentence |
| "simplify the sentences" | section | `prose` | shorten wording, cut paragraphs down |
| "this is a chat reply" | whole message | `--chat` | lead with the point, end on the ask |
| "simplify this code" | one source file | read `specialists/code.md` | not in the pipeline |
| all of the above | mixed | `run FILE` | the full pipeline |

Three of these need the whole file and cannot work on a span:

- **structure** decides section order and which file owns a fact. Both answers
  change when only one section is visible.
- **summary** writes the opening page. It has to read everything first.
- **planning** deletes a section, and whether a section of plan is the
  document's whole point depends on the other sections. On a span it would
  delete the roadmap out of a roadmap.

They are marked `document` scope, so they get the whole file. Every other
specialist gets one span.

`structure` is document scope but not one job. It gets:

- one whole-file job, for section order and fact ownership;
- one **outline job**, carrying the heading list and each heading's word count,
  without the prose. It may send `move` and nothing else. Zero moves is legal,
  but it has to name the two headings it came closest to moving and why it left
  them;
- one **duplicate job per repeated cluster**, each with a real line span. A
  dedup is one edit with two far-apart halves (cut the copy, shorten the
  owner), so both carry the same `group` and land together or not at all. Only
  `structure` is read for that field, a tie over six lines is dropped, and two
  ties that share a line stay two ties: a name reused across unrelated work
  would make one refusal undo all of it.

On a 7000-word document that is eight jobs, not one.

`summary` runs whenever the file owes a summary, including when the document
opens with unheaded prose. It is the only specialist allowed to touch that
opening block: it reads the prose, so it can tell an abstract from an
introduction. Everything else is told to leave those words alone.

## The granularity ladder

Work happens at five sizes. Each one has an owner.

| Size | What it is | Who works at this size |
|---|---|---|
| document | the whole file | `structure`, `summary`, `chat` |
| section | a heading and its body | the chunker groups these |
| span | at most `MAX_SPAN` (80) lines | the unit one section agent is given |
| paragraph | lines between two blanks | `prose` merges these; `noise` deletes them |
| line | one line of the file | every edit is a line edit |

A section longer than 80 lines is cut into spans at the nearest blank line, so
a span never starts halfway through a paragraph. Handing an agent 200 lines for
three hits is where it starts reworking things nobody asked about.

## The flow

```
read file
  │
  ├─ mask()          strip code fences, tables, quotes, tree diagrams
  ├─ find_shapes()   regex tables → [(line, shape, text)]
  ├─ chunk()         group headings into sections
  ├─ opening_summary()  is there one, how long, does it lead with results
  │
  ├─ build_jobs()    one job per (specialist, unit) that has work
  │                  document scope → whole file, on a condition
  │                    structure also gets an outline job (headings only)
  │                    and one job per repeated cluster, each with a span
  │                  section scope  → one job per span that holds its shape
  │
  ├─ job_prompt()    specialist rules + document outline + numbered span
  │                  + which facts in this span appear nowhere else
  │                  + the line range of every sentence that wraps
  │
  ├─ ThreadPoolExecutor   all jobs in flight, JOBS at a time,
  │                       each one a local agent CLI (see Implementation notes)
  │
  ├─ merge()         apply every reply to one copy, in pass order
  │                  widen a one-line edit to the sentence it half covers
  │                  every edit passes the gates below or is refused
  │                  then one more round for the losers on ownership
  │
  └─ verify()        rescan: tokens lost, tokens invented, shapes left
                     0 clean · 3 hits remain · 1 something broke
```

`run` writes a sidecar and stops. `accept` reruns `verify` and replaces the
input with the sidecar, refusing on 1. `crosscheck` hands both files to a
second local agent, from a different vendor than the one that wrote the edits,
for the read no regex can do.

That reviewer is asked to read the diff first and judge the change, not the
file. Without that it reports the original's own faults as damage the run
caused — in tests, most of its findings on a typical run. It is also told which
references `noise` dropped on purpose, and to write a repeating problem once
with a list of lines instead of once per line.

`accept` makes taking a good run one step. Without it, the only route to the
real file is copying edits across from the diff, which costs no more than
copying only some, so the agent, not the gates, decides which edits land.
Accepting has to be one step, or the cheapest path for an agent is around the
gates.

Pass order is the order of the `SPECIALISTS` dict: deletions first, so a line
one pass removed does not come back reworded by the next.

## The specialists

Each owns one aspect and reads only its own rules. Prompts live in
`specialists/`, one file each, on top of the shared floor in `_common.md`.

Shape names below match the routing table, so `plan` and `verify` print exactly
these.

| Specialist | Scope | Shapes it owns | Ops |
|---|---|---|---|
| `planning` | document | phase plan, task list, estimate, target date | **delete-section** |
| `noise` | section | process leak, editor note, worklog, changelog narration, commit or checkout ref, draft diff, unexplained reference, unsourced citation, citation plumbing, asks reader to verify, bare internal id, echo, empty framing | replace |
| `actionable` | section | parked problem, vague action, activity report, planning language | replace |
| `quotable` | section | number without its noun, bare nominalisation, evaluative adjective, identifier as subject, inanimate perceiver, idiom | replace |
| `prose` | section | frame, hedge, wrapper, jargon, nominalisation, agreement move, X-not-Y | replace |
| `chat` | document | colon label, message scaffold, buried lead, omission note, corrects the reader | replace, insert |
| `structure` | document | corporate header, plus section order, fact ownership and duplicates — which no regex finds | **move**, replace |
| `summary` | document | none. It is woken by a condition, because it looks for an absence | insert, replace |

`summary` wakes when the file owes one: none at all, one under the minimum, one
over the cap, or unheaded prose at the top that may or may not be the summary.
It does not wake for a **buried** summary. `structure` owns that one. The lines
above a buried summary have no heading, so moving the summary up takes them in
instead of pushing them below it. Instead, `move-block` sends the lede down
`into` its section, leaving the summary alone at the top. `structure` does that
job alone, and every other edit it proposes in that pass is dropped.

No flag answers the unheaded question. Asking the reader hands back the
question `summary` exists to answer, and a person who could answer it would not
need the run. `summary` is handed the block and decides, and is told never to
write a second summary over an existing one.

A `replace` with an empty `new` removes a line, and every deletion but one is
written that way. An op the merge does not implement is refused. The exception,
`delete-section` (described below), removes a whole section at once. A 40-line
roadmap written as 40 empty replaces gives a gate 40 chances to refuse one and
leave half a roadmap behind.

`code` is the ninth prompt. It is not in the pipeline, because `run` works on
Markdown. Read it directly to simplify source.

A specialist is only woken where its own shapes fired. The document-scope ones
cannot be, because they look for absences and an absence never fires a rule.
They are woken by a condition instead.

The `summary` cap is about a fifth of the body, with a floor of 40 words and a
ceiling of 500, so a long report may open on half a page while a short one may
not. A summary that fits in forty words announces the document rather than
stating its result, which its own prompt makes a job. `summary_share`,
`summary_min_words` and `summary_max_words` are profile thresholds.

`structure` has no such test: no regex finds section order or fact ownership,
so skipping it would lose its whole purpose. On a file where nothing fired
anywhere, it is demoted: it reports and does not edit. It can still say the
result is in section 4, and a person decides. Without the demotion, a file with
nothing to fix is the one that gets reordered and renamed.

Both conditions are deterministic, so a second pass over a settled file
schedules nothing that can change it. Without them the tool never reaches a
fixed point: on a transcript a whole run reduced to "add 341 words" and grew
the file 4.5%.

## Why `structure` needs `move`

`structure` is the specialist that can see the whole file, so it is the only
one that can say "the result is buried in section 4". Moving a section is not a
line edit, so without a dedicated op it could only say it, and "simplify the
structure" would be advice-only.

`move` closes that:

```json
{"op": "move", "line": 120, "to": 30, "why": "result first"}
```

Both numbers are heading lines. The section at line 120 goes before the heading
at line 30. Line numbers are the original file's, the same ones every other
specialist sees.

**The unit is a section, not a line range.** The agent names two headings and
`section_span()` works out the rest: a heading owns everything down to the next
heading of the same level or higher, so a `##` carries its `###` subsections.

That choice makes the op safe. An agent sending its own `(line, span)` range
can take half a list, one arm of a table, the back half of a blockquote, or a
span that opens before a code fence and closes inside it. Each of those needs
its own gate, and each gate guesses what the agent meant. Two headings cannot
express any of them, so there is nothing to guard against. There is no size cap
either: a big section is still one section.

Those gates exist, under `move-block` below. `move` keeps its two headings: it
moves whole sections, and nothing about it needs a range.

A move relocates text without rewriting it, so it cannot lose a fact. That is
why it is safe to allow at all, and why `verify` stays green across one.

Two things neither move can do. Each stays a `note`:

- split one section into two, or merge two into one. Both need a heading
  written or removed, and neither op writes text;
- move a fact to a different file. `run` reads one file and writes one file, so
  cross-file ownership is always advice.

## `move-block`, for prose with no heading over it

Prose can sit in the wrong place too. A lede above the summary has no heading,
so `move` cannot name it, and a buried summary is buried by exactly that prose.
`move-block` takes a line range instead:

```json
{"op": "move-block", "line": 5, "thru": 11, "into": 59, "why": "lede belongs in Background"}
```

The block runs from line 5 to line 11 and lands directly under the heading on
line 59, as that section's opening. Lines 5 to 11 must hold no heading: a range
that has one is refused, for the reason at the end of this section.

`into` is a line number, like `to`, and must be a heading's line. Its only
other value is one past the last line of the body, which sends the block to the
bottom, above the trailing footnote definitions. A section name there is
refused with a message saying it takes a number.

`move` names the heading it goes *before*; `move-block` names the section it
goes *into*. That difference is why the two are separate ops rather than one
with an optional range.

`move-block` has the gates a range needs. The main one is that a block is a
whole run of non-blank lines, with a blank line or the file's edge above and
below. A range ending inside a fence has a non-blank line under it, and so does
half a list and one arm of a table.

Two shapes pass that rule because they can hold a blank line, and each has its
own check. A fenced block can contain blank lines, so its first half passes the
edge rule, and moving three lines out of a fence turns the closer into an
opener. A list with blank lines between its items is one list, and every item
passes the edge rule alone; so does the indented paragraph under a bullet,
which would move without its bullet. List material with more list material
directly across an edge is the middle of a list, not a block.

A heading inside the range is refused rather than handled: it raises the
ownership question this op exists to sidestep, and `move` already carries a
section.

Only `structure` may send one, and on a buried summary it is the only op it may
send: every other edit in that pass is dropped.

## `delete-section`, for a roadmap in a document that is not one

Four shapes name a schedule rather than a proposal: `phase plan`, `task list`,
`estimate`, `target date`. Rewording does not fix them. A phase table reworded
is still a phase table. `planning` owns the four and sends one op:

```json
{"op": "delete-section", "line": 120, "why": "the rollout plan is not part of the design"}
```

One heading line, and the section it owns goes: `section_span()` computes the
range the same way `move` does, so a `##` carries its `###` subsections, its
tables and its fences.

`task list` reads UNCHECKED boxes only, deliberately diverging from the
`TASK_LINE` the genre detector reads. An unchecked box is a plan and a checked
one is a record of finished work; in a fix log every `- [x]` row is that
document's evidence, and deleting their section would delete the record. A
checked box matches nothing rather than being re-homed on `worklog`:
`genre-checklist` switches `planning` off and leaves `worklog` on, so a
finished checklist would have every row ordered deleted instead.

**Why one op and not forty replaces.** Every other delete here is a `replace`
with an empty `new`: 40 edits for a 40-line roadmap, each gated separately. One
refusal (a `kv:keep` line, a frozen line, a line another specialist claimed)
leaves the other 39 applied and half a roadmap in the file, worse than either
answer. The op itself has to be atomic. `group`, the other way to tie edits
together, cannot carry this: `ties()` only reads a group on a `replace`, and
`MAX_GROUP_LINES` is 6.

So the whole span is checked first, and the op is refused whole if the span's
BODY schedules nothing, or if it holds a `kv:keep` line, a frozen line, a line
already claimed, or the opening summary. The removal is recorded as a move with
no destination, the way the rebuild already drops lines it re-emits elsewhere,
so no second mechanism has to stay in step.

A heading recording a dated status — `### Parser — DONE (2026-05-12)`,
`## 2026-09-13 — Triage decisions` — is refused the same way:
`protected.dated_status_lines()` adds the heading's own line to the same
`marked | frozen | set(held)` union `delete-section` already checks, and
`merge`'s `move` gate checks it too. Without it such headings drift through
every other gate: `noise`'s date-plus-verb rule reads line text, and a
heading's name is never handed to it. Only the heading's own line goes into
the frozen set, unlike a `kv:keep` or `NOTE FOR AGENTS` section: the record
that must survive is the heading text, not whatever is written under it.

**The body test, which is the gate that decides most refusals.** The document's
genre says whether a plan belongs in this file at all; the section's own body
says whether this one IS a plan. `plan_body_lines()` reads the body for an
unchecked box, an estimate, a target date, a labelled owner or a calendar date,
and a section carrying none of them is refused however its heading reads. The
heading LINE is excluded from the body, and that exclusion is the rule:
`## Phase 1: Reconnaissance` over four paragraphs of method is a step a reader
follows, and `PHASE_HEAD` cannot tell it from a rollout section by its name.

Three narrowings, each with its own case:

- **`phase plan` is not a body marker.** It matches a heading, so a
  `### Phase 2a` inside the span would count and the hole reopens one level
  down. The cost is that a plan whose body is nothing but `- Milestone 3: ship
  it` bullets, with no date, owner or estimate, is flagged and not cut.
- **A date beside a completion verb does not count.** `re-derived 2026-09-07`
  is provenance, and a lessons document carrying one would otherwise authorise
  its own deletion. That is the checked/unchecked box distinction one type
  along.
- **A bare `@handle` is not an owner** and neither is an `| Owner |` table
  column. In prose a handle is a credited person, and an ownership table in a
  design document is not a schedule; a real plan table is reached by its dates.

`planning` sees only the outline, so each heading there is marked
`[body schedules: date, task list]` or `[body schedules: nothing]`: the gate's
own markers, from one function, because a writer refused by a rule its prompt
never showed resends the same edit. `structure`'s outline carries no mark: its
question is order and not deletion.

Two consequences of the op itself:

- every protected token in the span is registered as dropped on purpose, or
  `verify` would hard-fail `TOKENS LOST` over a roadmap's own dates;
- every line in the span is claimed, so a later specialist's reword inside it
  is refused by name rather than reported as applied to text the output does
  not contain.

**The genre gate, which is not optional and is not sufficient either.**
`roadmap` is a detected genre, so a document that IS a roadmap loads
`profiles/genre-roadmap.json` and switches `planning` off. Without it the
specialist deletes the roadmap from a roadmap document, correctly by its own
rules. The detector is heading-marked like `transcript` and `log`: a document
with most of its body under phase headings is one, while a design document with
one pasted phase section stays `prose` and loses the table. `log` is tested
before `roadmap`, so a dated changelog heading still reads as a log.

`genre-checklist` and `genre-log` switch `planning` off for the same reason — a
checklist IS a task list, and a log's entries carry the dates and the phase
names the specialist is there to remove. `genre-reference` and
`genre-transcript` deliberately do NOT: a reference document's genre is its
table rows, so planning language in one is an ordinary section rather than the
thing that makes the file a reference, and `planning` is woken only by its own
hits, whose only source in a transcript would be a heading, which
`TIMESTAMP_HEAD` files as speech before `PHASE_HEAD` can read it. **A caveat on
all of it: `genre-log` does not load on most documents a reader would call a
changelog.** Common changelog conventions all read as `prose`, because
`DATE_HEAD` requires the date to LEAD the heading and the convention puts the
version first (`## [1.2.0] - 2026-09-01`). Moving the date to the front does
not fix it either — the entries live under `### Added` / `### Fixed`
subsections whose own headings carry no date, and `genre_mix` splits at every
heading. So on a real changelog the genre gate is not what protects the file;
read the plan.

**And the genre gate protects the WRONG half, which is why the body test
exists.** All three plan profiles carry `"planning": null`, so this specialist
only runs on documents that are NOT plan-genre. The genre half is therefore
guaranteed wherever the op is reachable, and it protects documents the detector
reads as plans rather than ones a reader would call one. Take two methodology
documents differing only in how many headings are ordinal: the phase-HEAVY one
reads as `roadmap` and is protected by misdetection, and the phase-LIGHT one,
the shape a real `SKILL.md` has, reads as `prose`, and without the body test
`delete-section` would delete the two sections that ARE the document. The genre
protection is strongest where the file looks most like a plan and absent where
it looks most like a method.

Zero deletions is legal and not free: the prompt requires a `note` saying which
sections were looked at and why each stays, because the job is woken by the
outline and an empty reply looks the same as one that did not read it.

## The gates

Every edit passes all of these or it is refused and printed. Nothing is dropped
silently.

| Gate | Refuses |
|---|---|
| span | an edit outside the lines the specialist was given |
| match | `old` that does not match the file, ignoring leading and trailing spaces |
| owner | a second claim on the same words another specialist already changed |
| fence | a reword inside a code fence, table diagram or blank line |
| block | an insert into a code fence, table, indented block or tree diagram. A blank line is still a legal anchor |
| quote | a reword inside a blockquote, unless `noise` sent it |
| facts | a reword that drops a number, path, ticket, link or `code span` |
| wrap | a reword that leaves half a hard-wrapped sentence stranded |
| behead | a delete that leaves the line above not finishing its sentence |
| repeat | an edit that would leave the same words on both sides of a line break |
| insert | a second insert at the same line |
| shapes | an insert whose own text carries a shape this skill removes |
| summary heading | a rename that takes the summary out of the vocabulary the detector reads |
| orphan | a heading rename that breaks an in-document link the same reply does not rewrite |
| second summary | a `summary` insert opening a file that already opens with one |
| pointer | a `summary` line naming a section another specialist renames in the same run |

**Ownership.** Pass order decides who claims a line first, with one exception:
inside the opening summary `summary` goes first, and in `--chat` mode `chat`
does. They run late and own those lines; without this, `summary` loses most of
its edits to its own section. Ownership is first refusal, not a veto: if any
gate refuses the owner's edit, the next specialist may claim the line. Another
specialist's delete overrides ownership, because rewording a line that should
not exist is wasted either way.

A line is not one thought: first-claim per line alone can cause nearly half of
a run's refusals, with `prose` landing none of its edits. So the losers get a
second round against the text that won. Each change is the middle of its own
diff; where two middles do not touch, the specialists edited different words
and both land. Where the line holds one sentence they were, and first-claim
still settles it. Round two never runs a third.

**Wrap.** A sentence wrapped over two lines, a specialist rewrites one of them,
and the other is left as a fragment. It breaks both ways: rewriting the head
into a whole sentence orphans the tail below; rewriting the tail and swallowing
the word that finished the line above orphans the head.

`verify` cannot see the stranded fragment: every token is still in the file, so
the token check and the shape scan both pass. On a 2000-line document it can
happen several times in one run and reach a human as an unusable file.

Refusing it outright was the wrong answer, though: the wrap gate became the
largest source of refusals, with `summary` losing every edit to it. Each of
those replies could have been completed from the line numbers alone.
`_common.md` tells the specialist the form — the rewrite on the run's first
line, `new: ""` on the rest — but counting the lines a sentence spans is the
arithmetic models do badly.

So the tool does it. The job prompt lists each wrapped sentence with its line
range, and the merge finishes a reply that is **one line short** of the run.
The widened edit is then indexed, fact-checked and gated like any other, so a
widening that would drop a number or a whole sentence is still refused.

One line short, no more. Taking two unaddressed lines because the head got
shorter is a guess about what the specialist meant to cut, not bookkeeping.
Most wrapped sentences in ordinary Markdown span two lines, so the narrow rule
keeps nearly all of the benefit and none of the guessing. Widening also stops
at a `kv:keep` line: a sentence can start on open prose and run onto a
protected one, and widening over it would break the one promise the marker
makes.

What is left refuses as before, and names the line it would have stranded.

**Behead and repeat.** The wrap gate only guards a neighbour nobody touched,
which misses two cases. `structure` sends a dedup as "cut this line, shorten
that one", so both lines are in the edited set, the wrap gate skips each, and
the surviving line ends on "and". And a tail rewritten into a whole sentence
repeats the words still on the line above it — a wrap the gate cannot see,
because the tail now opens on a capital.

**Shapes.** An insert is the one edit nobody has read. Every other edit
replaces a line the shape rules already scanned, so a specialist writing a new
frame while removing another gets caught. `summary` mostly inserts, and without
this gate it reliably opens documents with the planning language and the empty
framing the rest of the run just deleted ("as discussed in §…"), and the run
then fails on its own summary.

It blocks the shapes that are always wrong in new prose, not every shape. The
rest of the table flags a precise technical name as often as a real problem,
and `jargon` firing on "TOCTOU" in a summary about a TOCTOU race would leave
the document with no summary at all. Those still reach `verify`, where a person
reads them.

Three shapes describe the document's own content rather than the writing:
parked problem, unexplained reference, bare internal id. Text carrying one
may be reporting what the document says. A summary owes the reader the open
questions, and `parked problem` sees `TBD` and `X%`, so naming one would refuse
the summary on every document that has one. An insert is excused for those
three when the document already says it.

Which is judged on the marker and the words around it. `TBD`, `X%` and `???` do
not say which question is open, so matching the marker alone would let one real
`TBD` in the body license every invented one. Matching the sentence back
verbatim is too strict the other way: a summary rewords the question it
reports, saying "the target is X%" for the body's "the adoption target is X%".
One content word in common separates them.

`noise` is exempt from the facts gate. Deleting a dead commit ref is its job.
Its losses still show up in `verify`, where a human reads them.

An unimplemented op is refused too. Otherwise `{"op": "delete"}` falls through
to the replace path and writes `new`, usually nothing, over the line.

Moves add their own:

| Gate | Refuses |
|---|---|
| mover | a move from any specialist except `structure` |
| heading | a `line` or `to` that is not a heading |
| title | moving the title, or landing a section above it |
| no-op | a destination where the section already sits |
| nesting | a destination heading deeper than the section, which would reparent it |
| deleted | a source or destination heading an earlier pass removed |
| overlap | a section already moved, or one an earlier move targets inside |

`to` takes one value that is not a heading: one past the last line, which sends
the section to the bottom.

`delete-section` adds four, all of them read over the whole span before a line
goes:

| Gate | Refuses |
|---|---|
| section deleter | a `delete-section` from any specialist except `planning` |
| atomicity | a span holding a `kv:keep` line, a frozen line, or a line an earlier pass claimed |
| summary | deleting the opening summary section, or the title |
| overlap | a span an earlier move or delete already took |

There is no fence gate and no size gate. A section holds whole fences by
construction, and its size is not a property a gate can judge. The one fence
arithmetic a delete does need is in `merge`'s own parity check, which counts
code-fence lines across the whole file: the deleted spans are subtracted before
the count, so a deleted section's fences do not read as a masking defect, and
an odd number left over is still refused, because a section boundary cannot
fall inside a fence.

## Why line edits and not rewritten text

A specialist returns edits, never a rewritten document. An edit carries the
line it replaces, and the orchestrator refuses it unless that line still
matches the file.

This buys three things:

- a specialist that misread the line it is rewriting does not get to rewrite it;
- seven agents merge without a diff3, because each line has one owner;
- every refusal names a line, so a bad reply costs one line and not the file.

The orchestrator also knows something no specialist can: which facts in a span
appear nowhere else in the document. A specialist sees one span and cannot tell
a repeated ticket from the only mention of one. Every job is told.

## What `verify` can and cannot check

`verify` rescans the edited file for every shape and compares protected tokens
against the original.

Hard failures — something broke:

- a protected token that was in the original and is not in the result;
- a protected token that appeared from nowhere;
- a shape the pass introduced, counted by growth and not by text match;
- a summary the pass lost;
- an in-document link with no heading to land on, that resolved before the pass.

The link check is the one thing no gate can do. `structure` renames headings
and `summary` writes the opening page from the same original in parallel, and
neither sees the other's reply. Each edit is right on its own; only the
finished file shows that three summary links now point at nothing.

Fence tags are counted per language, not by position. File-wide numbering would
make one section move renumber every fence below it, and the whole set would
read as lost and reinvented.

Read-and-decide — shapes that survived. Some are correct: a quoted example, a
precise technical name, a credited person.

It matches text, not meaning. It will not catch "X causes Y" turned into "X
does not cause Y", and it cannot protect a fact carrying no number, path, link
or identifier. Read the diff.

## Folders

```
kill-verbosity/             the repository root is the skill directory
├── SKILL.md                what the skill does, when it fires, how to run it
├── kill-verbosity          the launcher: finds killverbosity/ beside itself
├── killverbosity/          the orchestrator package, standard library only
│   └── mdblocks.py         the built-in CommonMark block parser
├── specialists/
│   ├── _common.md          the floor every specialist stands on
│   ├── noise.md            ┐
│   ├── actionable.md       │
│   ├── quotable.md         │ one prompt per specialist
│   ├── prose.md            │ loaded by specialist_prompt()
│   ├── chat.md             │
│   ├── structure.md        │
│   ├── summary.md          │
│   ├── planning.md         ┘
│   ├── code.md             read by hand, not in the pipeline
│   └── jargon-hunt.md      every rule as one prompt, not loaded by run
├── profiles/
│   ├── genre-*.json        loaded automatically when a genre is detected
│   └── *.json              domains and languages, named in .killverbosity.json
├── docs/
│   ├── user-guide.md       how to use it
│   ├── how-it-works.md     this file
│   └── known-issues.md     open issues
└── tests/                  pytest suite, for development only
```

`jargon-hunt.md` holds every rule in one prompt, as they stood before the split
across eight specialists. `run` does not load it, since `specialist_prompt()`
opens files by specialist name, so nothing checks the split against it and
nothing catches it drifting. When a rule changes in a specialist prompt, change
it there too.

`profiles/` holds the data the shapes are built from. `genre-*.json` loads
automatically when `plan` or `run` recognises the document's genre; everything
else is named in `.killverbosity.json`. See `SKILL.md` for the format.

`targets` narrows a declaration's `profile`/`specialists` to the globs it
names, the same arithmetic `refuse.paths` already does for a refusal: a
document under the declaring directory matching none of them is read as if the
declaration were not there, and `find_project` resumes the walk upward past it
rather than stopping. Without it, a declaration written for one file applies to
every unrelated document under the same directory; `targets` lets the
declaration say which documents it is about without moving the file.

## Install

Python 3.9 or newer, standard library only. There is no install step, no
virtual environment and no dependency to fetch.

Clone or copy the repository into a directory named `kill-verbosity`, then link
it into Claude Code's skills directory:

```bash
cd ~/.claude/skills && ln -s /path/to/kill-verbosity .
```

Copying the whole directory there also works. The launcher finds the
`killverbosity/` package beside its resolved path, so a symlink to the
directory or the launcher works; a hard link or a lone copy of the launcher
cannot find the package. Where the default text encoding is not UTF-8 (Windows
code pages), the launcher re-executes under `python -X utf8` so it reads its
shipped files correctly.

The tests need pytest and nothing else: `python3 -m pytest`. `selftest` needs
nothing at all and runs in-process.

## Implementation notes

**Specialists run through local agent CLIs.** There is no service and no API
key in the tool. Each job spawns one agent CLI, chosen with `run --agent`
(default: the first installed of `claude`, `codex`, `agy`). Those three run
with no tools or a read-only sandbox; any other command given as
`--agent '<command>'` runs as given, prompt on stdin, answer on stdout:

- `claude -p --restricted --tools=` for a specialist, and
  `--tools=Read,Grep,Glob` for `crosscheck`;
- `codex exec --skip-git-repo-check --sandbox read-only -`;
- `agy` in stream-json mode under `--sandbox`; agy has no read-only mode, so
  the sandbox is the boundary. The answer is `result.response` of the last
  result event.

**The prompt always goes over stdin, never argv.** A span plus its rules is
large enough to hit command-line length limits, and argv is visible to every
user on the machine in a process listing.

**A timeout kills the whole process tree.** An agent CLI starts its own
helpers, and killing only the direct child leaves them holding the output pipes
open, so the call hangs past its timeout. Every spawn starts in its own session
(POSIX) or process group (Windows), and on timeout the whole group is killed
(`killpg`, or `taskkill /T /F`). `killverbosity/spawn.py` is the one place this
happens.

**A failed agent falls back to the other installed CLIs.** If the agent a job
asked for fails, the other local CLIs are tried in turn — claude, codex, agy,
skipping the one asked for and any not on PATH — sharing the job's remaining
time. A job answered by a fallback is reported as substituted, because its
edits came from a different model than the one requested. If `--agent` was
named explicitly and every job was answered by a fallback, the run stops before
writing (exit 6) unless `--any-agent` says any agent will do. `crosscheck`
falls back the same way but never to an agent of the writer's vendor, since a
second opinion from the same family is not a second opinion; when no eligible
reviewer is left it exits 5 and records why. Only installation is checked
before a run, not login or quota, so an agent that is installed but signed out
shows up as a failure and a fallback.

**Markdown blocks come from a built-in parser.** `killverbosity/mdblocks.py` is
a port of markdown-it-py's block rules (the CommonMark preset, plus the GFM
table rule and front matter), kept rule for rule so its token types and line
maps match the original. It replaced the third-party library so the tool needs
nothing outside the standard library.
It does block parsing only — no inline parsing, no rendering — because the
orchestrator needs three answers a line-at-a-time scan cannot give: setext
headings, tables written without outer pipes, and lazy blockquote continuation
lines.

**Run it in the foreground.** It prints a numbered line per job as each lands,
with elapsed seconds and the edit count. A long run is minutes of silence
otherwise, which reads as a hang and gets killed or worked around by hand.

**A heading is an ATX heading.** One to six hashes, at most three spaces of
indent, followed by whitespace or end of line. `#hashtag`, `#######` and an
indented `## example` inside a code sample are not headings. Each one read as a
heading opens a phantom section, and a move can cut a real section in half at
it.

**A fence closes on a bare delimiter.** ` ```literal ` inside a ` ```text `
block is content. One helper, `fence_delim`, answers this for both readers, so
neither carries its own copy to get wrong.

**`mask()` runs first.** Code fences, tables, blockquotes and tree diagrams are
stripped before any regex sees the text, so hits are prose and not a directory
listing.

Masked is not the same as refused. `editable_lines()` puts table rows and
blockquote lines back, so a specialist may rewrite them; only fence bodies and
tree diagrams are out. The claim check reads cell text for that reason — a cell
saying "stops new traffic reaching the node and waits for in-flight requests to
finish" can become "drains the node" with every other gate green.

A cell IS in the shape scan for every rule but the two in `CELL_BLIND`:
`find_shapes` gets `mask()`'s rows as well as its prose, because a table holds
authored prose and excluding it lets verbosity hide where no rule looks. The
two exclusions have different reasons. `number without its noun` is a shape a
cell can never satisfy: the noun is the column header, above the cell rather
than after the figure. `worklog` is one a cell does satisfy and must not be
scanned for: the shape is deletion-ordered, so in a table the text ordered cut
is a cell's value. In a status inventory, `DONE (2026-05-12)` cells are the
column the table exists for. A dated heading still fires; only the cell is
blind.

**Shapes are four tables.** `EXISTENCE` fires on a match. `SUBSTITUTION` fires
when a better word exists. `OCCURRENCE` fires on count, not presence. `CHAT`
fires only under `--chat`. `PREPROCESS` rewrites the line before the others
read it.

**Tokens are indexed once.** `token_lines()` maps every protected token to the
lines holding it, once per run. Each job then asks `only_copy()` what is unique
to its span. Scanning the document inside every job would repeat that work once
per job.

**Line numbers never shift during a merge.** Every specialist reads the
original file, so every edit is in original coordinates and must stay valid
until the last one lands. Nothing renumbers: a deleted line becomes `None` in a
list the same length as the file, an insert waits in a side dict keyed by the
line it goes above, and a move records a source range and a destination.
Renumbering happens once, in the final rebuild, after every edit is in.

That is also why a move carries post-edit text. The rebuild emits `out[j]`, so
a line another specialist reworded moves in its reworded form, and a line
`noise` deleted does not come back.

**Failures are loud.** A specialist that times out leaves its span unedited.
`verify` sees a smaller consistent file and passes it, so `run` returns
non-zero when any specialist failed, whatever `verify` said.

**The output is never the input.** `verify` needs an untouched original, and
the input file is not the tool's to overwrite. `run` refuses when the two paths
resolve to the same file.

**Importing it in a test.** The orchestrator is an ordinary package, so with
the repository root on `sys.path` it imports directly:

```python
from killverbosity import _legacy as kv

kv.RECOMMENDATION.match("Verify the checksum before deploy.")
kv.VOCAB["safe_acronyms"]
```

That reaches every regex, threshold and vocabulary list from outside, so a
check like "every summary heading noun has its plural" can be a test rather
than a one-off script. A check that only needs the tool's own tables belongs in
`selftest`, which already runs in-process.

## Known limits

- `collapse_blanks` protects fenced blocks but not indented code blocks, so a
  blank run inside a four-space code block collapses when any edit lands. Any
  accepted edit also collapses a double blank line the author wrote on purpose.
- A dotfile is protected by its backticks alone. The path rule wants a word
  boundary before the name, so a leading dot defeats it:
  `` `.env` `` is a code token and bare `.env` is nothing. Every other
  identifier reads the same with or without backticks.
- The wrap gate reads the two lines either side of an edit. A sentence wrapped
  over three lines, or one whose other half a *later* gate refuses, can still
  strand a fragment.
- The widening finishes a reply one line short of a wrapped sentence. A reply
  two or more lines short is refused, so a three-line sentence with one line
  edited still costs its edit.
- A line carrying the tail of one sentence and the head of the next is in no
  run at all, because widening across it would take a sentence nobody touched.
  Edits on those lines get no help.
- `verify` runs once, over the finished file, not after every chunk: a bad edit
  in chunk 2 is not seen until chunk 15 lands. There is no per-chunk original
  to compare against mid-run.
- Cross-file moves are notes. `run` reads one file and writes one file.
- A link from another file to a heading this run renames is not checked. The
  orphan gate reads the one file it was given; grep the directory.

## Adding a rule

Feedback names one phrase. That phrase is a shape, and the shape repeats.
Fixing the quoted line and stopping is why the same feedback comes back next
round.

1. Name the shape behind the example. "One caveat before we trust a pass" is a
   frame, not a phrase.
2. Add the regex to the matching table, and the owning specialist to
   `SPECIALISTS`. `selftest` fails if a shape has no owner or two.
3. Add the rule and its example to that specialist's prompt.
4. Add a case to `cmd_selftest`: the line that must fire, and a near-miss that
   must not.

## Adding a specialist

1. Write `specialists/<name>.md`. It stands on `_common.md`, so state only what
   it owns.
2. Add it to `SPECIALISTS` with its scope and its shapes. Position in the dict
   is pass order.
3. Add it to `DOC_ONLY` or `CHAT_ONLY` if it only makes sense for one document
   kind.
4. If it needs an op nobody else has, add the op to `parse_reply` and its gates
   to `merge`, and restrict it by name the way `MOVERS` restricts `move`.
