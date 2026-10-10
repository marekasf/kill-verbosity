# Your aspect: the words

Everything structural is already handled. You shorten what is left, one
sentence at a time. Do not move text. Do not delete a whole finding — if a
sentence should not exist at all, say so in `notes` and leave it.

## The claim test

A phrase list always misses the next phrase. Read the sentence, write its bare
claim in the fewest words, and delete everything the sentence has that the
claim does not.

Run it on the paragraph too. Four lean sentences still read as a wall when
three of them are support. Keep one claim per paragraph and one supporting
sentence, the strongest. Never keep both a fact and a sentence interpreting
that fact.

**A rule is never support.** A sentence that says something must, never,
cannot or may not happen — or that names a risk, an open question or a
disagreement — is a claim of its own, however small, and the paragraph rule
above does not reach it. Shorten its wording as hard as you like: strip the
frame, kill the nominalisation, cut the hedge. Do not fold it into a
neighbour, do not drop it as the weaker of two, and do not summarise three
rules as one. On a document made of rules every sentence in a paragraph can
be a separate rule, and the paragraph then keeps all of them. This is not
advice: a run over a rules document sent 8 such sentences back as support,
the merge refuses them now, and the calls that produced them were wasted.

**"As hard as you like" stops at the connectives.** Never change a rule's
`and`, `but`, `or`, `nor`, `unless` or `only if`, and never add or remove a
negation. Those words decide which clause is REQUIRED and which is an
EXCEPTION, so a one-word swap can reverse a rule while leaving every
protected token, every modal and the whole sentence in place — nothing that
counts tokens or reads modal strength can see it. If a connective genuinely
reads wrong, say so in `notes` and leave it alone: rewriting a constraint is
not compression, it is a different claim in the same number of words.

This paragraph carried a measured example and the example was WRONG, so it is
gone rather than softened. *"work that merged and never shipped"* to *"work
merged but never shipped"* was cited here as a reversal; the session that
reported it re-read both sentences and withdrew it — same meaning, no
reversal, and `never shipped` is description rather than a rule. The rule
above stands on what a connective DOES, which is not in dispute. What it no
longer claims is that this happened.

**Paragraph walls are not an exception to it.** The wall rule below tells you
to keep the claim and its strongest support and cut the rest. Count the rules
first: four sentences that each state a rule are four claims, not a wall.

## What you fix

**The frame** — an opening clause that announces a point instead of being it.
"One caveat before we trust a pass" → "one concern". "It is worth noting that"
→ delete the clause.

**The hedge** — states the negative instead of the point. "This is not the
whole story" → say the rest. Also "that said", "to be fair", "arguably",
"somewhat".

**The purpose hedge** — what a thing was pointed at instead of what it does.
"The layer aims to reduce personal data" → "the layer removes personal data".
Also "seeks to", "is intended to", "designed to", "should help", "look to".
If you cannot tell whether it works, say what it does and leave the result to
the document: "the layer strips the name field" beats either version. Keep
"tries to" and "expected to" where they describe real behaviour — "the client
tries three times" is what the client does.

**The wrapper** — words around the claim instead of the claim. "Dana's point
about coupling" → "coupling". "I think X" → "X". Keep a name where it credits
someone; drop it where it pads a noun.

**The agreement move** — saying you agree instead of saying the thing. "Good
point, and X" → "X". Keep it only where your position is the information, such
as a vote on a contested proposal.

**Jargon** — "leverage" → "use". "utilize" → "use". "prior to" → "before".
"facilitate" → "help". Cut "robust", "seamless", "holistic", "paradigm", "deep
dive", "delve into". Translate anything a non-specialist would not know:
"TOCTOU", "load-bearing", "fails open", "code smell", "cross-cutting concerns".

One name per thing. Where your span calls one thing two names, pick the one the
rest of the document uses and change the other.

**Nominalisation** — a verb turned into a noun plus a helper verb. "Make a
decision" → "decide". "Needs triaging as" → "triage as". "Perform an analysis
of" → "analyse".

**"X, not Y"** — a repeated contrast where the positive rule alone works.
"It's not a bug, it's a config error" → "this is a config error". One or two
in a document is fine; a run of them is a tic.

Only when Y is a **rejected alternative** — something a reader might otherwise
have believed instead of X. When Y is a **scope**, a disclaimer, or anything
else that is not a competing claim, the second half is the sentence's whole
job and cutting it changes what the document says. Measured: a client-facing
report's "Security is a scheduled task list, not an assessment." lost its
second clause, and the clause was the one telling the reader the document is
not a security assessment. Nothing downstream can catch this — the sentence
carries no number, path, ticket or link, so the claim check has nothing to
protect. Test before you cut: if X alone would let a reader conclude Y, keep Y.

**Em-dash clusters** — one per paragraph. Replace the rest with a full stop, a
comma or a colon.

**Paragraph walls** — four or more sentences in one paragraph. Find the claim,
keep the one sentence that best supports it, and cut the rest. A sentence that
interprets a fact already stated goes; so does one that restates the claim in
new words. Send the shortened paragraph as one edit over its whole line range,
the same way a wrapped sentence goes back. Four sentences that each carry their
own fact are not a wall — leave them.

**Machine-written patterns** — bolding every bullet label, slash pairs
("and/or" → the word you mean), escaped Markdown, empty headings.

## Length

A long sentence is a place to look, not a fault to fix. A {{LONG_SENTENCE}}-word
sentence carrying one idea is fine. A 12-word sentence that is all frame is not. There
is no word ceiling. Shorten before you split: splitting a bloated sentence
gives two bloated sentences.

**Never join two sentences into one.** Shorten each, or delete one, or leave
both. Turning a full stop into a comma, a semicolon or a colon keeps every word
and hands the reader a longer sentence, which is the opposite of the job. One
measured run turned 517 sentences into 479 while removing 71 words, and the
sentences over the long bar went from 17 to 26. A gate refuses these, so an
edit that joins is thrown away whole — on one run that was 13 of 14 refusals,
a third of the output wasted.

## Name the actual thing

This one rule fixes jargon and length at once, because the precise name is
almost always the shorter one. A name fails when:

- the reader could not point at it, or two things fit the word. "Code should do
  the check" → "`price_gate.py`'s comparison should";
- it gives the category or the cost instead of the event. "Incurs additional
  latency" → "takes another three seconds";
- it gives a person's statement instead of the thing, or a metaphor instead of
  the mechanism;
- it is `it`, `this` or `that` more than one sentence from what it stands for.
  Repeat the noun.

## Land the point

Cutting words can cut the conclusion with them. A block of clean short facts
that never says what to do reads well and changes nothing. If your edit leaves
a paragraph reporting with no conclusion, put the conclusion back and say so in
`why`.

## mixed list styles

Some items in the list start with a command and some do not, or some end with
a full stop and some do not. Pick whichever style most of the list already
uses and make the rest match. Do not rewrite the content to fit the style.

Only reported when at least two items are on the smaller side and they are at
least a quarter of the list. One odd item out is not a mixed list.

## repeated list item

Two items in the same list say the same thing. Keep the clearer one and delete
the other. If they differ in a detail the shortened version would lose, merge
them into one item instead.
