# Your aspect: simplify code

Not part of `kill-verbosity run`, which works on Markdown. Read this when the
thing to simplify is source.

Read the whole file and trace its callers before editing. Find the repository's
existing test command and run it for a baseline. If no test covers the code,
make smaller changes and report the missing safety net.

## 1. Reuse before adding

Look for an existing helper, type, utility or local pattern first. Then prefer
the language standard library, platform features and installed dependencies. Do
not add a helper, abstraction or dependency when the codebase already solves
the problem.

## 2. Simplify names

- Rename unclear local variables and private helpers to state what they hold or do.
- Remove empty suffixes such as `Manager`, `Helper`, `Util` and `Data` when a
  precise name is shorter.
- Use one name for each concept throughout the file.
- Keep exported names, public functions, routes, schemas and externally consumed
  identifiers unchanged unless the user explicitly requests an API change.

## 3. Flatten control flow

- Return early instead of nesting the happy path.
- Extract a named boolean when a condition is hard to read.
- Give each function one job. Split only when the new names make the flow clearer.
- Prefer a plain expression to a clever equivalent.
- Keep the order of side effects unchanged.

## 4. Remove only proven waste

- Delete unused locals, imports, unreachable branches and commented-out code.
- Fold exact duplication into an existing function or the smallest local helper.
- Do not delete a defensive guard, null check, `catch`, retry, validation or
  boundary case merely because it looks redundant.
- If callers, tests or runtime behavior do not prove code dead, leave it and
  report the uncertainty.

## 5. Fix comments

- Keep comments that explain intent, constraints, magic values or workarounds.
- Delete comments that restate the next line.
- Update or remove comments that no longer match the code.
- Cut blame and subjective digs ("Bob's hack", "stupid API"); keep the warning,
  reworded to describe the code.
- Preserve specification and ticket links that explain a constraint.

## 6. Match the codebase

- Follow the file's existing naming, errors, imports and formatting.
- Reuse the nearest established pattern instead of introducing a new one.
- Keep the diff narrow enough to review as a refactor.
- Do not mix a bug fix, redesign, dependency change or feature with
  simplification. Report it separately.

## 7. Verify behavior

Run the same test command used for the baseline. Confirm:

- the same inputs produce the same outputs and side effects;
- public APIs and externally meaningful values did not change;
- error handling, guards and boundary cases remain;
- tests pass unchanged;
- the diff contains simplification only.

If the simpler form changes behavior, do not apply it. List it as a separate
proposed change.
