# Simplify — clean up notes and code

Use this prompt to make a file easier to read without changing what it means. It works on two kinds
of file:

- **Documentation** — a `CLAUDE.md` notes file or any markdown doc.
- **Code** — a source file in any language.

Run it on one file, several files, or a whole tree (every `sources/*/CLAUDE.md`, or every file you
touched in a change) in turn.

Your job: make the file **simpler and clearer without changing what it does**. In prose, rewrite
the words, not the facts. In code, rewrite the form, not the behavior. Never delete findings,
numbers, evidence, guards, or tests.

## The one rule that never changes

Do not change meaning.

- In a doc, the reworded sentence must claim exactly what the old one claimed.
- In code, the same inputs must give the same outputs and the same side effects. This is a refactor,
  not a rewrite. If a change would alter behavior, do not make it — note it separately (see Output).

---

# For documentation

## What the document is

These notes are written for the team, not the public. Technical terms are fine when they carry real
meaning and are explained on first use.

Four problems to fix:

- needless jargon
- tangled sentences
- one idea restated on every page
- text written to be stored rather than read: research trails, cross-reference webs, notes to self

Read the whole file first. Then work top-down: what the document is, its structure, its repetition,
then its sentences and words.

### Write the minimum that works

This applies to every sentence in every genre, not only to chat messages. The best sentence is the
one you never wrote.

Borrowed from YAGNI, the first rung of the laziness ladder in
[Ponytail](https://github.com/DietrichGebert/ponytail). Same idea, applied to prose. Walk the ladder
on every sentence and stop at the first rung that fits:

1. Does the reader need it? No → cut it.
2. Is it already stated elsewhere in the file? Yes → cut it, or leave a one-line pointer.
3. Can one or two words do the job? Yes → use them.
4. Can an existing table, bullet, or heading carry it? Yes → put it there.
5. Can one sentence do it? Yes → write one.
6. Otherwise write the shortest version that keeps the meaning.

Explanations get the same treatment. One example beats a paragraph about the example. A table beats
three sentences that compare three things.

**Non-negotiable, whatever the rung.** Ponytail keeps validation, security, and error handling
whatever the ladder says. The equivalents here are facts, numbers, evidence, findings, open
questions, and the conclusion. Minimal never means dropping those (see What you must NOT change).

### Decide what the document is — and who reads it

A document that does not know its own genre keeps hedges, research trails, and notes to self.

- Name the genre and the reader in the title and first line ("This is the rollout plan for X", or
  "This is the input to the plan, not the plan itself"). If the file drifts between working notes,
  analysis, and deliverable, pick the one it mostly is and flag the drift (see Output).
- Match the detail to the reader. Ticket IDs, config dumps, and CI mechanics do not belong in a
  document for a manager. Move them to an appendix or a working file, leave one summary line in the
  body, and delete nothing.

### Shape the structure

- Put the point first. The reader meets the conclusion, plan, or answer on page one; background and
  evidence go after it, or in an appendix. Moving whole blocks is allowed — rewriting them is not.
- Name headings after the problem being solved, not the artifact produced ("Clear the identity
  block", not "Agent rules v2"). A renaming, not a restructure.
- Promote what matters. If the text calls something "the biggest item" and it sits at the bottom,
  give it a heading that matches.
- Use headings and bullets so a reader can scan; group related points.
- Keep tables for what is naturally a table (settings, limits, file references). Cap cells at one
  line: the table is the index, the body holds the one full statement.
- If a long plan lacks a one-page summary of its sequence and gates, do not write one — that is new
  content. List it as a suggestion (see Output).

### Say each thing once

- One home per fact. State every rule, fact, and example in full in the one section where it
  belongs. Everywhere else, cut to a one-line pointer ("attribution rules — see Goal 1") or delete
  the mention if the pointer adds nothing.
- Reverse the machine inversion: generated text repeats each **conclusion** in five homes and
  states each **fact** once at maximum compression. A readable document does the opposite — one
  fact, explained; one conclusion, stated once.
- Collapse identical stub blocks (the same "Owner: TBD" lines under every heading) into one
  statement. Say once, up front, _why_ something is TBD instead of scattering bare placeholders.
- Cut cross-reference churn. Parenthetical join-keys and repeated "see section X" pointers turn
  prose into a lookup table. Point-first ordering removes most of them; delete the rest that add
  nothing.
- Collapse citation plumbing. "Person + channel + date + link" mid-sentence becomes one
  reader-facing sentence with the link on the words; full provenance goes to a working log. Keep
  the one or two quotes that genuinely earn their place.

### Write for the reader, not the next step

Cut everything addressed to the author or to a future processing step rather than the reader:

- Fact-check asides and confidence commentary ("verify before quoting", "unverifiable",
  "lighter-confidence"). Anything not solid enough to state plainly comes out or moves to a
  working log.
- Sentences that tell the reader how to treat the text ("treat this as…", "cite as…", "record as
  contested", "trust the record"). State the conclusion or cut it.
- Meeting-note voice ("X's view, not settled in the call"). A real disagreement becomes one
  plainly stated open question; the attribution goes to the working log. Never close or drop the
  disagreement itself.
- Rebuttals of people who are not in the room. Detection phrases: "this is not…", "this
  settles…", "but X does not mean Y". If no reader raised the objection, cut the clause; if one
  did, it is an open question stated once, not an inline argument.
- Reasoning narration between facts ("this is why", "the lesson is", "this maps onto"). Keep the
  fact that follows.

### Simplify the words

Simple English is not optional. A reader should never have to stop on a word.

- Swap long or fancy words for short everyday ones.
- Turn noun-clumps back into verbs.
- Cut filler that adds no meaning ("it should be noted that", "in terms of", "basically", "various").
- **No idioms and no metaphors.** They are the worst kind, because the writer reads them as vivid
  and the reader reads them as noise. If a phrase describes something physical that is not
  physically happening, replace it with what is actually happening.
- Test each word: would you use it talking to someone outside your team? If no, replace it.
- Name the actual thing. That has its own section below, because it is the rule this file gets wrong
  most often.

| Not simple                             | Simple                                   |
| -------------------------------------- | ---------------------------------------- |
| "it eyeballs the magnitude"            | "it checks the number looks about right" |
| "without paying for judge calls again" | "without running the judges again"       |
| "grades leniently"                     | "goes soft"                              |
| "bad annotations"                      | "mislabelled"                            |
| "reaches the same soundness"           | "is just as sound"                       |
| "deltas"                               | "changes"                                |
| "cadence"                              | "schedule"                               |
| "utilise"                              | "use"                                    |
| "leverage"                             | "use"                                    |
| "facilitate"                           | "help"                                   |
| "in order to"                          | "to"                                     |
| "prior to"                             | "before"                                 |
| "perform an evaluation of"             | "evaluate"                               |
| "make a decision"                      | "decide"                                 |

Keep a term when the team uses it as a term of art. Gloss it once on first use, then reuse it.

### Name the actual thing

The single highest-value rule in this file, for jargon and for verbosity at once. Vague naming is
what makes a short sentence unreadable, and the precise name is almost always shorter than the vague
one.

Five ways a name fails. Each has a test that needs no word list.

**1. Too broad to point at.** Could the reader point at what you named? If two different things fit
the word, it names neither.

| Fails                      | Names it                                |
| -------------------------- | --------------------------------------- |
| "code should do the check" | "`price_gate.py`'s comparison should"      |
| "the system handles it"    | "the router handles it"                 |
| "we store it"              | "the gate stores both SQL strings"      |
| "an LLM call"              | "a judge call" (when that is which one) |

Watch the contrast especially: "code, not the judge" fails because the judge is also code.

**2. The category or the cost instead of the event.** Say what happens.

| Fails                          | Names it                    |
| ------------------------------ | --------------------------- |
| "paying for judge calls again" | "running the judges again"  |
| "incurs additional latency"    | "takes another 3 seconds"   |
| "a maintenance burden"         | "someone has to re-gold it" |

**3. A person's statement instead of the thing.** See type 7, the wrapper. "Ana's point about
coupling" is not a thing; coupling is.

**4. A metaphor instead of the mechanism.** "it eyeballs the magnitude" names nothing that happens.
"it checks the number looks about right" does.

**5. A pronoun with no visible owner.** "it", "this", "that" more than one sentence from what they
stand for. Repeat the noun. It costs two words and saves a re-read.

The one exception: keep the real name of a thing even when it is technical (a metric code, a service
name, a table name, a config key). A precise technical name is not jargon. Gloss it once on first use, then
reuse it.

### Fix the sentences

- One idea per sentence. If a sentence chains two clauses that could each stand alone, split it.
  Detection: a comma followed by "so", "and", "but", "which", or "because", where the text after
  the comma has its own subject and verb.
- Do not split when the two halves only make sense together. A "so" or "because" that shows why
  one fact follows from another is carrying meaning, so keep it and keep one sentence.
- A long sentence is a place to look, not a fault to fix. A 30-word sentence carrying one
  idea is fine; a 12-word sentence that is all frame is not. There is no word ceiling.
  Shorten before you split — splitting a bloated sentence gives two bloated sentences.
- A colon followed by three or more items is a list, not a sentence. Make it bullets.
- Use active voice — say who does what ("the function calls the service", not "the service is
  called").
- Put the main point first, then the detail.
- The read-aloud test: if you cannot say the sentence to a colleague without restarting it,
  rewrite it.

### What a simplification pass must survive

Short is not the goal. A block is done when the reader can answer three questions:

1. What does this mean?
2. So what?
3. What should I do?

A block that fails any of them is shorter but not simpler. Add the missing answer, or cut the block.

Text fails in three directions, not one. Cutting words only fixes the first:

| Failure         | Looks like                                        | Fix                           |
| --------------- | ------------------------------------------------- | ----------------------------- |
| Too long        | frames, hedges, citation-speak, repeated evidence | cut the words                 |
| Too short       | fragments the reader reassembles, bare facts      | put the connecting words back |
| Short and empty | clean sentences, no conclusion, nothing to do     | state the point and the ask   |

### Fix the shape everywhere, not the flagged instance

A reviewer names one phrase. That phrase is a shape, and the shape repeats across the file. Fixing
only the line they quoted invites the same feedback next round.

On every piece of feedback:

1. Name the shape behind the example.
2. Grep the file for that shape, not that phrase.
3. Fix every hit, including the ones nobody flagged.
4. Add the shape to these rules, with the example as an example.

Sentence length finds candidates. It never decides the fix, and a file can pass every length check
while still being unreadable.

### Kill verbosity

Goal: the fewest words that keep the meaning.

**Fix the shape, not the phrase.** The tables below are examples, not the rule. A pass that greps
only the listed phrases leaves every other phrase of the same shape in place. That is the most common
way this rule gets applied badly.

**The claim test comes first.** A list of known phrases will always miss the next one, so start with
a test that needs no list:

1. Read the sentence.
2. Write the bare claim in the fewest words you can.
3. Compare. Everything the sentence has that the claim does not is padding.
4. Delete the padding.

**Run it on the paragraph too, not only the sentence.** A paragraph of four lean sentences still
reads as a wall of text when three of them are support. This is the most common way a file passes
every sentence-level check and is still unreadable.

- One claim per paragraph. Write it in the fewest words, then count the sentences that are not it.
- Keep at most one supporting sentence, and only the strongest one. Cut the rest.
- Never keep both a fact and a sentence interpreting that fact. Merge them or drop the fact.
- A paragraph that needs three supports is two paragraphs, or it belongs in the document rather than
  the message.

| Wall of text                                                                                                                                                                                                                                                                                                           | The claim, kept                                                                                                      |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| "code should decide pass or fail, keep the judge for the failures. judges are the lenient ones — one judge scored 72.6% where the three-judge mean was 61.6%. on a number check that means waving through close-enough. comparing two result sets is just an equality check, so code gives the same answer every run." | "code should do the number check, not the judge — a judge accepts close-enough. then use the judge on the failures." |

**Evidence is not exempt.** A true number is still padding when it does not change what the reader
would do. Before keeping one, say which decision it moves. If the answer is none, it belongs in the
document, not the message. Watch for a number that is true of a neighbouring question and reads as proof
of this one.

| Sentence                                                            | Bare claim                            | Padding deleted               |
| ------------------------------------------------------------------- | ------------------------------------- | ----------------------------- |
| "but Ana's point about coupling is the one I'd worry about most" | "coupling is the risk"                | 8 of 12 words                 |
| "Ravi's point that not all tools use SQL is correct"              | "not all tools use SQL"               | the frame around it           |
| "The judge is worth more on the failures"                           | "the judge does more on the failures" | a value word for a plain verb |

Apply the test to every sentence. The eight types below are what it usually finds.

**1. The frame** — an opening clause that announces a point instead of being it.

Test: take everything before the first colon, comma, or dash. If it states no fact, it is a frame.
A frame gets one or two words, or deletion. Never more.

| Verbose                                          | Killed              |
| ------------------------------------------------ | ------------------- |
| "one more, worth knowing before we trust a pass" | "also"              |
| "one caveat before we trust a pass"              | "one concern"       |
| "It is worth noting that"                        | delete              |
| "Worth saying plainly to close it"               | delete              |
| "The good news is that"                          | delete              |
| "Being honest about the evidence"                | delete              |
| "Where I land:"                                  | delete              |
| "What is still open is the ordering"             | "the order is open" |
| "One thing worth tightening"                     | "one fix"           |
| "Two things follow if X"                         | "if X:"             |
| "The split that matches that"                    | "so"                |
| "for a reason that looks like"                   | "it looks like"     |

**2. The hedge** — states the negative instead of the point. It gives the reader nothing to use.

| Verbose                                                                             | Killed                    |
| ----------------------------------------------------------------------------------- | ------------------------- |
| "a failing case doesn't always mean the model was wrong, the gold can be wrong too" | "the gold can be wrong"   |
| "this is not the whole story"                                                       | say the rest of the story |
| "it is not always the case that X"                                                  | say when X is false       |

**3. Citation-speak** — how a paper reads, not how anyone talks. Give the conclusion. Keep at most
one number, and only when it changes what the reader would do.

| Verbose                                                                                   | Killed                                      |
| ----------------------------------------------------------------------------------------- | ------------------------------------------- |
| "Zhong measured 6.5% of wrong queries matching the gold result, 11% on the hardest split" | "a single dataset can pass a wrong query"   |
| "Anthropic's system beat single-agent Opus 4 by 90.2% at about 15 times the tokens"       | "more agents cost more for the same result" |

**4. Evidence the reader already has** — noise, however well sourced. Say the new thing. In a
thread, anything already argued there is repetition.

**5. A verb turned into a noun plus a helper verb.**

| Verbose                    | Killed         |
| -------------------------- | -------------- |
| "needs triaging as"        | "triage as"    |
| "have to travel with"      | "must go with" |
| "we lose being able to"    | "we can't"     |
| "perform an evaluation of" | "evaluate"     |
| "is not enough to trust"   | "cannot prove" |

**6. The echo** — a closing sentence that restates the opening one in new words. Cut the closer.

| Verbose                                                                                 | Killed                   |
| --------------------------------------------------------------------------------------- | ------------------------ |
| "The gap is wider than groundedness. (two facts). The gap sits in the set of scorers."  | drop the last sentence   |
| "That is better than X: it keeps Y honest and it does not cost Z" (Y and Z just stated) | "That is better than X." |

**7. The wrapper** — words around the claim instead of the claim. Two flavours, same fix.

Opinion wrapper: your judgement of the claim, standing where the claim should be. Attribution
wrapper: a person's statement about a thing, standing where the thing should be.

Test: delete the wrapper. If the sentence still says the thing, the wrapper was padding.

| Verbose                                     | Killed                         |
| ------------------------------------------- | ------------------------------ |
| "Ana's point about coupling"             | "coupling"                     |
| "Ravi's point that not all tools use SQL" | "not all tools use SQL"        |
| "is the one I'd worry about most"           | "is the risk"                  |
| "is the one that matters"                   | "matters"                      |
| "I think X"                                 | "X"                            |
| "X is correct and understated"              | "X, and it is worse than that" |
| "is worth more on"                          | "does more on"                 |

Credit still belongs to people. Keep the name where it earns something ("Ana's right about the
coupling"), and drop it where it only pads a noun ("Ana's point about coupling" → "coupling").

**8. The agreement move** — saying you agree instead of saying the thing. It repeats what the other
person just said, so it adds nothing. Engaging with an argument already shows that you accept it.

| Verbose                                       | Killed  |
| --------------------------------------------- | ------- |
| "Ana's right about the coupling though. X" | "X"     |
| "yeah, X. so we're all after the same thing"  | "X"     |
| "good point, and X"                           | "X"     |
| "as you said, X"                              | "X"     |
| "I do agree with your idea, and X"            | "X"     |
| "last one. X"                                 | "and X" |

Keep it only when your position is the information: a vote on a contested proposal, where nobody yet
knows which side you are on. A bare "+1 on connecting the server" earns its place. "Ana's right
about the coupling" does not, because the paragraph that follows already argues his case.

**The one limit: clarity beats brevity.** Cut words that carry no meaning. Never cut the words that
carry the link between two facts. If the shorter version makes the reader work out how the pieces
connect, it is worse.

| Over-shortened                               | Clear                                                                    |
| -------------------------------------------- | ------------------------------------------------------------------------ |
| "show a judge the gold and it goes lenient." | "a judge that can see the gold goes lenient, it eyeballs the magnitude." |
| "cheap fix, we keep both SQLs."              | "cheap fix though — we already store both SQLs."                         |
| "two queries, nothing re-runs."              | "costs two queries, no agent or judge calls."                            |

Signs you went too far:

- short sentences with no connecting words
- a fact with no hint of why it matters
- a pronoun the reader has to trace back
- a noun phrase where a verb was needed

### Land the point

Cutting words can cut the conclusion with them. A block of clean short facts that never says what to
do is clear and useless. After every simplification, check what the reader is meant to do with it.

- Every section ends with the decision, the action, or what the facts mean. Not with the last fact.
- Every proposal keeps its reason attached. See the next rule.
- Every message ends with one ask. Name it, and name who does it.
- If a block only reports, either add the conclusion or cut the block. Facts nobody acts on are
  padding, however short.
- Do not invent a conclusion the source did not have. If there is none, say the question is open and
  who owns it (see What you must NOT change).

| Reports and stops                                              | Lands the point                                                            |
| -------------------------------------------------------------- | -------------------------------------------------------------------------- |
| "a single dataset can pass a wrong query. we store both SQLs." | "…so re-run the pair over a second window and require both to match."      |
| "the gold can be wrong — 52.8% has bad annotations."           | "…so a failure needs a gold-wrong outcome, not only model-wrong."          |
| three paragraphs of findings, no ending                        | "so three changes, all cheap: A, B, C. if that sounds right I'll do them." |

### A proposal needs the concern, the change, and the reason

A bare change is not actionable. The reader cannot judge it, so they cannot agree to it. Every
proposal carries three parts:

1. **The concern** — what goes wrong today.
2. **The change** — what to do instead, concretely.
3. **The reason** — why the change fixes the concern.

Drop any part and the point stops working. A change with no concern reads as preference. A concern
with no change reads as a complaint. A change with no reason cannot be argued with, so it gets
ignored.

| Not actionable                           | Actionable                                                                                             |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| "two windows per pass"                   | "a wrong query can match the gold by luck on one window, so require a match on two — it catches those" |
| "compare the sets before the judge runs" | "keep the number check in code, so the verdict is the same every run and rescoring stays cheap"        |
| "a gold-wrong outcome on failures"       | "without it, gold errors get charged to the model and the team chases bugs that are not there"         |

The same applies to a list of changes. Attach the reason to each item, or drop the list. A checklist
of bare changes tells the reader nothing they can act on.

### Do not hand out work

Simplifying a recommendation must not change who owns it. Feedback on someone else's work proposes;
it does not volunteer you, them, or anyone else.

- Never write "I'll do X" unless the source says you are doing X.
- Never assign a task to a named person the source did not assign.
- Feedback ends with a question or an offer, not a plan. "Worth folding into TASK-241?" beats "I'll
  add them to the release branch."
- Keep whose thing it is. Their branch, their dataset, their ticket.

### Chat messages: same rules, less slack

Every rule above already applies. A message typed into a chat app or a PR comment has no room to
miss any of them, and four extra rules of its own:

- Match how the channel writes. Lower case sentence starts are usually right.
- No colon-lists. One idea per paragraph, blank line between paragraphs.
- No links inside a sentence unless the link is the point.
- End with the ask. It is a question or an offer, never a plan for someone else's work.

Then compare it to a real message from that channel. Longer per line means go back up the ladder.

### Cut the machine tells

Patterns that read as generated text even when every fact is right. Each has a checkable budget:

- **The ", not Y" tic** ("a signal, not a gate"). Each invents a strawman and knocks it down.
  Budget: at most three per document, kept only where the contrast is the actual decision or
  someone really argued Y. Otherwise state the positive half alone.
- **Em-dash stacking.** At most one em-dash per paragraph. Turn appositives into a second sentence
  or a plain parenthesis; turn dash-lists into bullet lists.
- **Verdict closers** ("Not a blocker." "Trust the record."). End the paragraph when its content
  ends; if the verdict carries real content, fold it into the sentence that carries the evidence.
- **Labelled micro-structures inside bullets** ("Concretely:", "Fix:" nested in a list item). One
  structural level per idea: promote it to a subsection or drop the label.
- **Uniform bold.** When every bullet starts with a bolded label, none stands out. Reserve bold
  for decisions, rules, and gates; evidence reads quieter. After the pass, bold _is_ the
  navigation.
- **Slash pairs** ("shared/autonomous", "review / sign-off"). Each slash usually hides a decision
  never made. Pick the term that is meant, or spell the pair out once and then use one word. Keep
  the slash only for fixed names (SOC 2 / ISO 27001).
- **Machine artifacts.** Remove escaped markdown (`\!`, `\.`, `\~`), tracker query-strings in
  links, double blank lines between bullets, and orphaned or mis-indented lines.

### Handle jargon and acronyms

- The first time a needed technical term or product name appears, add a short plain-English gloss
  in brackets, then keep using the term. Example pattern: `Hasura (the tool that turns the
database into an API)`.
- If a term is used only once or twice and a plain phrase works just as well, use the plain phrase.
- Spell out an acronym the first time it appears. If it shows up only once, just use the words.
- Watch for a multi-word phrase repeated verbatim like a code variable ("the agentic good
  practices", fifteen times). Define it once with a short handle — "the agent rules (Goal 1)" —
  then use the handle or plain English.
- Never invent a term. If you are unsure what something means, leave it and flag it (see Output).

### Make it consistent

- Pick one name for each thing and use it everywhere. If the file calls the same thing three
  names, choose one and change the rest.
- Explain each term the same way every time, and the same way sibling files in the set explain it.
- Keep headings, bullet style, and formatting uniform.

### De-blame the findings

A finding describes the system, not the person who built it. Keep the fact, drop the blame. Soften
_who_, never _what_: the risk and its severity stay as they were.

- Attribute a problem to the code or the conditions, not a person. "The check is missing", not
  "X forgot the check". "The config allowed it", not "someone misconfigured it".
- Cut names, "you", and team labels out of findings — including forecasts of who will resist a
  change. Say what the system does, not who did it or who will object.
- Do not guess at intent or skill. No "sloppy", "lazy", "should have known", "obvious mistake".
  State what is true and what the fix is.
- Use neutral verbs. The passive voice is fine here when it lets you name a fault without pointing
  at a person ("the token was logged in plain text").
- Never delete or weaken a risk while de-blaming it. If you cannot reword without losing the
  point, leave it and flag it (see Output).

---

# For code

## What the code is

Same goal as prose: the reader understands it faster, with less effort. No new features, no bug
fixes, no performance work.

Read the whole file first. Run the project's test command (see the README or CI config) for a
baseline. No test suite means no safety net, so be more cautious and say so in the Output.

### Simplify the names

- Rename unclear _local_ identifiers to say what they hold or do (`d` → `days_left`, `tmp` →
  `parsed_row`, an internal `helper` → `normalize_address`). Leave anything callers depend on, such
  as an exported name or a public function. That is a public-surface change (see what you must NOT
  change).
- Drop noise that adds nothing (`dataManager` → `store`, `MyHelperUtil` → the thing it actually is),
  again only for names that are not part of the public surface.
- Replace a clever expression with the plain one when both read the same to the machine.

### Untangle the logic

- One job per function. If a function does three things, split it into three named functions.
- Return early to cut nesting. Prefer a flat sequence of guards over a deep `if/else` pyramid.
- Name a tangled condition instead of inlining it (`if is_expired(token):`, not a four-clause boolean).
- Delete dead code: unused variables, commented-out blocks, stale flags. A defensive guard or safety
  check is never "dead code", even when it looks unreachable. If you are not sure a branch is truly
  dead, leave it and flag it (see Output).

### Handle comments and jargon

- A comment should say _why_, not restate _what_ the line already shows. Cut comments that just echo
  the code.
- Explain a non-obvious term, magic number, or workaround once, where it lives. Link the spec or ticket
  if there is one.
- Never leave a comment that the code no longer matches. Fix it or delete it.
- De-blame comments too: cut names, blame, and subjective digs ("Bob's hack", "this is wrong",
  "stupid API"). Keep any real warning, but reword it to describe the code, not a person (see
  De-blame the findings).

### Make it consistent

- Match the surrounding file: same naming style, same error handling, same import and formatting
  patterns.
- Use one name per concept across the file. Do not call the same thing `user`, `account`, and `member`.
- Prefer a pattern already used in the file over a new one that does the same job.

### Reduce, don't rewrite

- Remove duplication by reusing what is already there. Do not invent a framework or an abstraction.
- Prefer small, obvious changes over a big refactor. Keep the diff small enough to review at a glance.

---

## What you must NOT change

**In documentation:**

- **Facts, numbers, and meaning.** Rewording must not shift what a sentence claims.
- **Evidence.** Keep every file path and line reference (for example `file.ts:130`).
- **Status tags on numbers.** Keep any marker that says whether a number is measured, taken from
  settings/config, or unknown. These are load-bearing — do not drop or soften them.
- **Findings.** Do not delete a risk, gap, or open question to make the text shorter. Shorten the
  wording, not the list.
- **Open disagreements.** A recorded disagreement stays open. Reword it into one plainly stated
  open question; do not settle it, close it, or omit it.
- **Deliberate placeholders.** A TBD that marks a decision someone else must make is content, not
  clutter. Consolidate the stubs, state the reason once, but do not fill them in or delete them.
- **The document's shape.** Moving whole blocks (point first, evidence to an appendix, promoting a
  buried section) is allowed. Do not dissolve the file into a new structure, split it, or rewrite it
  into a different document. List a fuller rework as a suggestion (see Output).
- **Code, commands, config keys, identifiers.** Leave them exactly as written.

**In code:**

- **Behavior.** Same inputs → same outputs, same side effects. This is a refactor only.
- **Public surface.** Do not change function signatures, exported names, routes, or schemas that
  callers depend on, unless the task explicitly says to.
- **The tests.** They must still pass, unchanged. A green suite is your proof that behavior held.
- **Error handling and edge cases.** Do not drop a guard, a `catch`, a null check, or a boundary case
  to make the code look tidy.
- **Numbers, constants, config keys, and identifiers** that carry external meaning.

Do not add new content. No summaries, no "key takeaways", no praise, no new features, no severity
ratings that were not already there. The goal is a cleaner version of the same file.

## How to run it

1. Read the file end to end. For a doc, decide what it is and who reads it. For code, find and run
   the project's test command first to get a baseline; if there is none, note that in the Output.
2. Build a short term list as you go: each technical term, name, or identifier, its one-line plain
   gloss, and the single spelling you will standardise on. Reuse glosses and names from sibling
   files so the whole set matches.
3. **Pass 1 — structural: move and delete, don't reword.** Reorder point-first, pick one home per
   repeated fact and cut the rest to pointers, delete the author's scratch and machine artifacts,
   move wrong-altitude detail to an appendix, shrink table cells. Cheap and safe; it removes most
   of the noise before any rewording starts.
4. **Pass 2 — verbosity.** Run this before any judgement pass. Walk the ladder in Write the minimum
   that works on each sentence, then the eight verbosity types in order, then turn colon-lists into
   bullets. **Shorten before you split**: splitting a sentence whose phrases are still bloated gives
   two bloated sentences.

   Length only finds the sentence, it is not the fix. Build the work list with this:

   ```bash
   # longest sentences first — each is a place to look for a phrase you can cut
   python3 - <<'EOF'
   import re, sys, pathlib
   text = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "FILE.md").read_text()
   body = [l for l in text.split("\n") if not l.startswith(("|", "#", "- ["))]
   for para in "\n".join(body).split("\n\n"):
       for s in re.split(r"(?<=[.!?]) +", " ".join(para.replace("> ", "").split())):
           if len(s.split()) > 20:
               print(len(s.split()), "|", s[:160])
   EOF
   ```

   Skip verbatim quotes, link lists, and tables.

5. **Pass 3 — prose.** The word, jargon, de-blame, and machine-tell rules, applied to what is left.
   Never run one broad "make it sound natural" rewrite — it regenerates the same patterns with new
   words. Apply the specific rules, one at a time.
6. Check the style budget — each line verifiable with `grep`, `wc`, or the script above:
   - long sentences read and decided, not cut to a count;
   - none of the eight verbosity types left (grep the example tables);
   - every subject and object is a thing the reader can point at;
   - no sentence that rung 1 or rung 2 of the ladder would have cut;
   - at most one em-dash per paragraph;
   - at most three ", not Y" constructions in the whole document;
   - bold only on decisions, rules, and gates;
   - no parenthesis inside a parenthesis;
   - no bullet longer than two lines; table cells one line.
7. Check that the same number says the same thing everywhere. When one fact has two homes, the
   copies drift. Grep each figure you kept and compare the sentences around it. A document that
   quotes 5% in one section and 6.5% in another for the same finding has a factual bug, not a
   style bug — fix it or flag it.
8. Accept or loop. For a doc: read the opening page aloud — any sentence you must restart gets
   rewritten; every conclusion has exactly one home; nothing changed meaning; every number keeps
   its status tag. For code: run the tests again — they must still pass — and confirm the diff is
   a refactor, not a behavior change.

## Output

- Apply the cleanup directly to the file.
- Then give a short, flat report:
  - a list of the main changes (jargon replaced → plain wording, terms standardised, sentences
    split, blame language neutralised, repeats collapsed to one home, scratch removed, blocks
    reordered or moved to an appendix; identifiers renamed, functions split, dead code removed,
    duplication folded), and
  - a separate list of anything you could not safely simplify, each with its location, so a human
    can resolve it. For docs: the meaning was unclear. For code: intent was unclear, there were no
    tests to confirm safety, or the simpler form would have changed behavior.
- If you spot a change worth making that is _not_ a pure simplification — a likely bug, a behavior
  change, a missing test, a missing summary page, a file split, a fuller restructure — do not apply
  it. List it separately as a suggestion.
- No other framing or summary sections.

## Quick reference

| Do                                                    | Don't                                                     |
| ----------------------------------------------------- | --------------------------------------------------------- |
| Say what the document is, on line one                 | Drift between notes, analysis, and deliverable            |
| Put the point first; evidence after or in an appendix | Bury the point under background sections                  |
| One home per fact; one-line pointers elsewhere        | Restate the same rule in four sections                    |
| State a fact once and explain it                      | Repeat conclusions while compressing every fact           |
| Write for the reader                                  | Leave notes to self, hedges, or "how to treat this text"  |
| State an open question plainly, once                  | Argue inline with people who aren't in the room           |
| Use short, everyday words and names                   | Use long or fancy words, or vague names                   |
| Say what is physically happening                      | Reach for an idiom or a metaphor                          |
| One idea per sentence; one job per function           | Chain three ideas with commas; three jobs in one function |
| Shorten the phrase, then split the sentence           | Split a long sentence and keep the long phrases           |
| Say "also"                                            | Say "one more, worth knowing before we trust a pass"      |
| Longer and clear beats short and cryptic              | Chop a sentence into fragments the reader reassembles     |
| Say the new thing                                     | Repeat evidence the thread already has                    |
| End on the action or the decision                     | End on the last fact and leave the reader guessing        |
| Give the concern, the change, and the reason          | List bare changes with no reason attached                 |
| Propose on someone else's work                        | Volunteer yourself or them to do it                       |
| Fix the shape across the file                         | Fix only the line the reviewer quoted                     |
| Ask: what does it mean, so what, what do I do         | Stop when the text is short                               |
| Walk the ladder: does the reader need it at all       | Write it, then try to shorten it                          |
| Write the bare claim, then compare                    | Trust a phrase blacklist to catch the next one            |
| Run the claim test on the paragraph                   | Check sentences only, and ship a wall of text             |
| Keep one support, the strongest                       | Stack a fact, its reading, and a justification            |
| Name the thing                                        | Name someone's point about the thing                      |
| Name what the reader can point at                     | Use a word that fits both sides of your contrast          |
| Say what happens                                      | Name its cost, its category, or a metaphor for it         |
| Repeat the noun                                       | Leave "it" two sentences from its owner                   |
| Make the argument                                     | Say that you agree, then make the argument                |
| One example instead of a paragraph about it           | Explain the example as well as show it                    |
| "a single dataset can pass a wrong query"             | "Zhong measured 6.5% of wrong queries matching the gold"  |
| Keep the "so" that shows why                          | Drop the link and leave two bare facts side by side       |
| Write a chat message the way the channel writes       | Write chat the way you write a doc                        |
| Explain a term once, then reuse one handle            | Use a term raw, or repeat it like a variable name         |
| One name per thing, used everywhere                   | Three names for the same thing                            |
| Bold only decisions, rules, and gates                 | Bold the label of every bullet                            |
| Pick one term for every "X / Y" pair                  | Weld two words with a slash to dodge the choice           |
| Return early; flatten nesting                         | Build deep `if/else` pyramids                             |
| Keep every number, tag, and file reference            | Drop evidence or status tags to save space                |
| Keep behavior, guards, and tests intact               | Drop a guard or change a result to look tidy              |
| State the fault, not the culprit                      | Name a person, or guess intent, in a finding              |
| Shorten the wording                                   | Shorten the list of findings                              |
| Move blocks; refactor in small steps                  | Rewrite into a new document, or add content               |
| Check the budget with `grep`; read the top aloud      | Run one broad "make it sound human" pass                  |
