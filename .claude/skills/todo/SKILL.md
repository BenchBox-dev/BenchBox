---
name: todo
description: Use when the user asks to "ideate on an idea", "refine an idea", "brainstorm", "write a spec", "create a specification", "create a TODO", "show TODO items", "manage TODOs", "prioritize TODOs", "top N most important todos", "rank the backlog", "what should we work on", "implement a TODO", "implement a batch of TODOs", "complete a TODO", "cleanup TODOs", "review TODO quality", "claim a TODO", "what's ready" / "ready queue", "defer this work", "promote a deferral", "dismiss a deferral", "block"/"unblock a TODO", "create TODOs from a spec", or "todo stats". Covers the lifecycle from idea to specification, implementation, and completion.
version: 0.8.0
tools: Bash, Read, Edit, Write, Task
---

# Todo — Idea to Done

## Purpose

Use this skill to turn a rough idea into a clear specification and manage its
TODO items through the full lifecycle: idea, specification, creation,
implementation, and completion.

## Critical rules

Use `_project/scripts/todo`. Check that the wrapper supports the command you need:

* Run `_project/scripts/todo --help` and confirm the subcommand appears.
* If the subcommand is missing, report the gap and stop.

`prioritize` has no CLI command. It is a skill-only analysis. Follow `references/prioritize.md` and use only the inspect commands it lists.

Put global flags before the subcommand: `todo --db <path> --actor <name> <command>`.

Exit code 2 means a general failure. Exit code 4 means the hosted database rejected your credentials. When you get exit code 4, stop all writes, run `todo doctor`, and show the error. Some wrappers try once to refresh the token before they return exit code 4.

The `--help` output for the command you chose is the full contract.

* Read the selected action guide before acting.
* When the user agrees to a specification, create its item with `todo create`
  or the supported create-from-spec command.
* Store tracker state only in the database. Do not write it to files by hand.
* Commit only through `SHARED/change-framework/SKILL.md`.
* `TODO_DB_URL` may select the hosted database. The CLI never prints its
  connection string.

## Actions

| Action | When to use it | Guide |
|---|---|---|
| `ideate` | You need to refine or brainstorm an idea | `references/ideate.md` |
| `spec` | You need to write a specification | `references/spec.md` |
| `bootstrap`, `init`, `doctor` | You set up or check the tracker | `references/bootstrap.md` |
| `ready`, `claim`, `start`, `done`, `defer`, `check-scope`, `verify`, `complete`, `promote`, `dismiss` | You implement a TODO | `references/implement.md` |
| `create`, `update`, `list`, `show`, `stats`, `deps`, `export`, `block`, `unblock`, `release`, `sweep-stale`, `drop` | You query or change items | `references/queries.md` |
| `prioritize` — skill-only, no CLI command | You rank open items and group by topic | `references/prioritize.md` |
| `lint` | You review an item | `references/review.md` |
| `finding candidates`, `finding triage`, `finding sync`, `finding promote` | You triage findings | `references/implement.md` |
| `batch` — a set of related TODOs | You implement several TODOs in order | `references/batch.md` |
| `help` | You need the action list | This table |

`todo ready` and `todo stats` may print a one-line warning on stderr when there are untriaged findings (open findings or unsynced drafts). The warning does not affect stdout. When you see it, run `todo finding candidates` to triage. The warning is silent when there are no findings.
