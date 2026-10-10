# kill-verbosity, ponytail and the Concise output style

Three ways to make an AI agent say less. They act on different things, so you
use them together, not instead of each other.

| | [`/output-style Concise`](https://code.claude.com/docs/en/output-styles) | [`/ponytail`](https://github.com/DietrichGebert/ponytail) | `/kill-verbosity` |
|---|---|---|---|
| Acts on | Claude's chat replies | the code Claude writes | files that already exist: docs, reports, agent output |
| When | every reply, as it is written | every coding task, before the code exists | on demand, after the text exists |
| What it does | leads with the result, skips narration | a "lazy senior dev" ladder: skip what isn't needed, reuse existing code, stdlib first, shortest working diff | splits the file and sends each kind of padding to its own [specialist](how-it-works.md) (noise, prose, structure, summary, …), then merges their line edits |
| Large documents | no | no | yes: works section by section, so size doesn't matter |
| Fact safety | none | none | refuses any edit that drops a number, path, identifier or rule, then [verifies the whole file](user-guide.md#what-each-command-answers) |
| Structure | no | no | puts sections in reading order, folds duplicates, adds an opening summary |
| Your file | — | — | never overwritten until you accept; all edits or none, with a backup |

In short: **Concise** keeps the chat short, **ponytail** keeps the code small,
**kill-verbosity** cleans the documents and outputs that already exist,
large ones included, without losing facts.

## Output styles do not reach subagents

An output style changes the main agent only. A
[fork](https://code.claude.com/docs/en/sub-agents#fork-the-current-conversation)
inherits it, because it inherits the parent's whole conversation and system
prompt. Every other subagent
[runs its own system prompt](https://code.claude.com/docs/en/sub-agents#what-loads-at-startup),
so the style does not change how it writes. Workflow agents are subagents too.

So setting Concise does not make your subagents' reports short. To get that,
put the instruction in the subagent's prompt or its
[definition file](https://code.claude.com/docs/en/sub-agents) in
`.claude/agents/`, or run kill-verbosity on what they produce.

## Links

- [README](../README.md): install and use kill-verbosity in Claude Code
- [User guide](user-guide.md): every command, option and agent CLI
- [How it works](how-it-works.md): the specialists and the gates
- [Known issues](known-issues.md)
- Claude Code docs: [output styles](https://code.claude.com/docs/en/output-styles), [skills](https://code.claude.com/docs/en/skills)
- [ponytail](https://github.com/DietrichGebert/ponytail)
