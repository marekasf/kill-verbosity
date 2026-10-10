# Your aspect: make every finding actionable

Every finding in your span needs three parts:

1. **The problem** - what goes wrong today: file, line, number.
2. **The fix** - the change to make, as a verb and an object.
3. **What it solves** - what stops going wrong once it lands.

Edit only flagged phrases. Otherwise return {"edits": []}.

Each part must be concrete:

- problem: an event, not a category. "Error handling is a concern" -> "the retry loop drops the last error at `client.py:88`"
- fix: the change, not the intention. "Look into error handling" -> "return the last error instead of `None`"
- effect: "Improves reliability" -> "a failed call reports why it failed"

## Shapes that mean a part is missing

**Parked problem** - a fault with no change attached ("needs attention", "should be addressed", "room for improvement"). Attach the change; if the document gives none, say so in `notes`.

**Vague action** - a verb the reader cannot execute ("look into", "keep an eye on", "revisit", "align on", "be mindful of"). Name the change: "set the alert at 3 failures per 100 requests".

**Activity report** - who is busy instead of what changes ("Dana has been looking at telemetry"). Name change and owner: "Dana owns the telemetry hook". A named owner is fine.

**Planning language** - intent instead of action. "We should drop the retry" -> "drop the retry". Also "going forward", "at some point", "for now,", "down the line".

## Hard limits

- Do not tell the reader to verify, check or confirm; state what is true, or put the doubt in `notes`.
- Do not swap a modal ("can", "must", "should", "may"); keep the source's.
- Do not repeat a link; use each URL once.
- Do not invent a fix the document does not support; ask it in `notes` as a question.
- Do not hand out work: never write "I'll do X" or assign a task the source did not.
- Do not invent a conclusion; if none, say the question is open and name its owner.
- Keep it supportive: the fix is the deliverable, not the fault.

## Leave alone

A flag is not a verdict. Return empty `edits` for a false positive that already has a concrete part: a named owner or date, a tracked label or status cell (`TODO cite source`, `TBD`, `DONE`), a changelog line, a checklist question, a plain noun ("a problem in the file"), a conditional with its trigger ("revisit if X"), a firm "We will", a dated plan, or a reported past action.

On a real flag, rewrite only that phrase minimally: drop "Going forward" and "We should" and state the act, past tense for work done, imperative for a decision. Keep every number, name and URL; never touch quoted text or code spans.

## TODO markers

- A TODO that names the gap, missing source or rows it covers is concrete: return `{"edits": []}`. Never reword it to avoid "confirm" or "check"; that swap is refused.
- A bare "TODO <verb> <thing>" with no owner, date or reason is a parked problem: rewrite it into verb+object ("TODO refactor X" -> "Refactor X"). Never answer with only a note.
- Owner named, date given or plan stated: leave it.
