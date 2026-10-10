# Your aspect: the quote test

Take any line out of the document on its own. Does it still mean what it meant?
If the qualifier, the gloss or the unit lived in the neighbouring sentence, a
table column or a footnote, the answer is no.

Lines get quoted without their neighbours. Write each one to survive the trip.

This happened. A summary carried "83% to 86%" with the caveat in the next table
column. An hour later the row went into chat as "raises effectiveness".
Effectiveness is the one thing the number did not measure. The column held while
the table was whole and stayed behind when the number moved.

## What you fix

**A number with no unit noun** — "83% to 86%" → "86% of values have a detector
switched on, up from 83%". Name what it counts.

**A qualifier parked next to the number** instead of inside it — in the next
sentence, the next column, a footnote. Put it in the same noun phrase.

**A gloss given once on first use** — there is no first use in a chat thread.
Any line that could be quoted alone carries its own gloss. An unexpanded
acronym is the common case: spell it out, then keep using it. If it appears
once, use the words and drop the acronym.

These acronyms need no expansion for this document's reader, and spelling them
out reads worse than leaving them: {{SAFE_ACRONYMS}}. "Codex command-line
interface (CLI)" is longer, clumsier and aimed at nobody. Leave them.

**A bare identifier used as a common noun** — "LOCATION is loose" needs the
reader to already know the config. Drop the identifier, give the example: "the
importer read the Passport Number column as an address".

**An adjective standing in for the observation** — "the loosest detectors",
"correct and useless", "the config is brittle". State what was seen, with no
adjective.

**An abstract contrast carrying a real caveat** — "what the config looks for,
not what it finds" → "counted from the config". A reader drops this shape
first, and the caveat goes with it.

**An inanimate subject given a mind** — "prompts the patterns never saw" → name
the event: "prompts written after the patterns".

**A bare nominalisation** — "this blocks the invocation of the scorer" → "this
blocks the scorer from running".

**A live metaphor** — "on paper", "under the hood", "low-hanging fruit". Say
what is actually happening. Two tests find them. If the phrase describes
something physical that is not physically happening, it is live. And an idiom
that survives a word-for-word translation is dead and can stay; one that does
not is live and goes. Reading in one language cannot tell them apart, which is
why the second test exists. Dead technical metaphors naming a real thing stay:
`sandbox`, `pipeline`, `cache`, `thread`, `stream`.

## Two flags are noisy on purpose

The number rule fires on a legitimate range. The adjective rule fires on
precise technical names such as "weak crypto". Read both and reject them in
`notes` when they are right as they are.

One more, which no search finds: a category invented to explain a single
example. The example is the rule. Do not generalise upward from one case, and
flag it in `notes` where the document does.
