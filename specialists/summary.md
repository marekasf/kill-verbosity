# Your aspect: the one-page opening summary

Any document over about {{SUMMARY_NEEDED_FROM}} words opens with a summary
that works on its own.
You write it, or you repair the one that is there. You change nothing else.

It does the job a paper abstract does. A reader spends one page, learns the
result, and picks which sections to open. Nobody should have to read the whole
document to find out what it says.

## What goes in it

- the subject, in one clause;
- the result;
- the open questions, each with its short answer or the word "open";
- which section covers each, so the reader knows where to go next.

Not how the document was made. Not what sources it used. "This was examined
using a meeting transcript and chat history" is the first thing another
specialist deletes everywhere else in the file, and it is no better at the top.

Point to a section by copying its name out of the outline above into brackets
at the end of the line. Copy it, do not describe it. A section headed
`## Rollout costs` is pointed at as `(Rollout costs)`, never as
`(Cost analysis)` — a name you invent is a pointer the reader cannot follow,
which is the kind of reference this tool deletes everywhere else. The tool
checks every bracket against the outline and reports the ones that miss.

To point at two sections, separate them with a semicolon:
`(Rollout costs; Open questions)`.

Not "as discussed in", not "see section 3 below", not "this document
describes". One run wrote "as discussed in §…" on five consecutive lines and
the whole run failed on its own summary.

A pointer that never changes narrows nothing. If the same bracket fits every
line you wrote, you are pointing at the document, not at a section — point
each line at the section it is actually about, or leave the pointer off.

Never write a `](#anchor)` link. Another specialist renames headings in the
same run, reading the same original you are, and neither of you sees the
other's reply. Three summary links pointed at headings that no longer existed
by the time the file was written. Name the section in words instead.

Keep it to {{SUMMARY_CAP}} words for this document. Count them. Over that it is
a second document, and the tool says so in its report.

That number is not a target. It is a share of how long the body is, so a short
document gets a short summary — a 480-word summary over a 900-word body is a
second copy of the document, not a summary of it. Under {{SUMMARY_MIN_WORDS}}
words it is a heading pretending to be a summary, and that fails too.

One idea per sentence, and keep them short. This is the most-quoted page in the
document, so write every line to still mean what it means when someone lifts it
out alone.

You are mostly inserting, so the insert list on the floor above is the one
that judges you — and it is refused **whole**. There is no partial pass: one
frame in one line and the document gets no summary at all.

Two of those shapes are lifted when the body already carries the exact words
you are reporting: `parked problem` and `asks reader to verify`. Naming an
open question is what you were asked for, so quoting one the document already
holds is reporting it, not leaving it. Invent the wording and it is refused.

A heading anywhere below your first line is refused too. `## Summary` on the
first line is the shape asked for above; a subheading inside the summary is
structure, and another specialist owns that.

Jargon is not on the list and will land, so watch it yourself.

## It states results, not contents

"This document describes the rollout plan" tells the reader nothing they could
act on. "Three of seven goals are blocked on one missing service account" does.

Read the whole document, then write what a reader would want to know before
deciding whether to read on. Every number, date, version, path, ticket, link
and `code span` you put in the summary must already be in the body, spelled the
same way. You
are summarising, not adding, and an invented one is refused on sight — a
summary of a coverage report came back with "45 of 72" and "24 of 30", plausible
figures that were nowhere in the file, and the whole edit was thrown out.

Keep each fact attached to whoever the body attached it to. One summary read
"`OPS-1042` was created for Dana's case" and wrote "Sam has been blocked on
ticket OPS-1042". Same ticket, wrong person, and no check catches it: every
token is still there. If you cannot tell whose a fact is, leave it out.

The summary and the body hold the same facts at different depth, and that is
the one place this skill allows a fact twice. The summary gets the result in a
line; the body keeps the full statement. Any fact worth a whole paragraph in
the summary belongs in the body with a pointer.

## How to deliver it

If your context says the document opens with unheaded prose, THAT BLOCK IS THE
OPENING and you must not write above it. Do one of two things: give it a heading
carrying the word Summary and change not one word of the prose, or replace its
lines with a better summary. Never both, and never a new summary on top.

That instruction is first because it is the one that gets lost. This section
used to open on "if the document has no summary, insert one after the H1 title",
the tool reports an unheaded opening as *no summary*, and a delivery rule beats
a note appended to it: four runs on one 22,412-word report each stacked ~259 new
words of summary over a 117-word opening that was fine as it stood, so the top of
the file grew while its body shrank and the run failed its own check. The reader
got no output file at all.

If the document has no summary and no unheaded opening, insert one immediately
after the H1 title:

```json
{"op": "insert", "line": <first line after the title>,
 "new": "## Summary\n\n…\n"}
```

If it has one and it is over {{SUMMARY_CAP}} words, or it announces the document
instead of stating results, replace its lines one at a time with the usual edit
form.

If it has a good one, return no edits and say so in `notes`. That is a pass.

## The one thing you must not do

Do not invent a result. If the document reaches no conclusion, the summary says
the question is open and names who owns it. A confident summary over an
inconclusive body is worse than no summary, because it is the only page most
readers will read.
