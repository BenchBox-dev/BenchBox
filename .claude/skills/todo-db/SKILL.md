---
name: todo-db
description: Use when the user asks to "create a TODO", "show TODO items", "manage TODOs", "prioritize TODOs", "implement a TODO", "implement a batch of TODOs", "batch implement TODOs", "complete a TODO", "cleanup TODOs", "review TODO quality", "claim a TODO", "what's ready" / "ready queue", "defer this work", "promote a deferral", "dismiss a deferral", "block"/"unblock a TODO", "create TODOs from a spec", or "todo stats". The production database-backed tracker; all tracker state lives in the shared DB and flows through the `todo` CLI.
version: 0.2.0
tools: Bash, Read, Edit, Write, Task
---

# TODO Tracker

The production TODO tracker. All tracker state lives in the shared database;
`_project/scripts/todo` (abbreviated `todo` below) is the ONLY write path —
never hand-write tracker state into repo files. The CLI enforces every
lifecycle rule; when it refuses (exit 2), fix the cause, don't work around it.
Global flags `--db` / `--actor` go **before** the subcommand.

## Implement flow

1. `todo ready` — pick the top ready item (or the one the user names).
2. `todo claim <id>` — claims it and prints the WORK ORDER: scope globs,
   must-preserves, anti-patterns, verification ladder, ready units, and open
   deferrals. Follow the work order; it is the whole briefing — there are no
   separate guardrail files to read.
3. Per unit: `todo start <id> <wid>` (optional — records your worktree and
   branch so another agent can resume partial work; `todo done` stamps them
   too), implement, then
   `todo done <id> <wid> --evidence "<command run / commit / PR>"`.
4. The moment you decide to skip something: `todo defer <id> --summary "..."
   --reason "..."` — deferring is cheap; losing work is not.
5. Before committing code: `todo check-scope <id>` (exit 1 = out of scope);
   run the ladder with `todo verify <id> --run [seq]`.
6. `todo complete <id> --pr <n>` — gated: refuses while units are undone or
   deferrals unresolved. Resolve each with `todo promote <deferral-id>
   --to-item <slug>` or `todo dismiss <deferral-id> --reason "..."`.

Commit changed files only, through SHARED/commit-framework/SKILL.md.

## Backlog & queries

- **Create:** `todo create --title ... --worktree ... --priority ...` (or
  `--from -` for a JSON payload) from a title, the conversation, or a finished
  spec (the `todo` skill's `spec` action authors the spec). For code items add
  guardrail rows — scope, must-preserve, anti-patterns, verification.
- **Inspect:** `todo list [filters]`, `todo show <id> [--json]`, `todo stats`,
  `todo deps <id>`, `todo export`.
- **Prioritize:** set item priority on create/edit; ideal active distribution
  is Critical 0-2, High 3-5, Medium-High 5-10.
- **Block / release / drop:** `todo block <id> --reason ...` /
  `todo unblock <id>`; `todo release <id>` drops your claim; `todo sweep-stale`
  releases expired leases; `todo drop <id> --reason ...` retires an item.

## Review quality

`todo lint <id>` (or `--all`) runs the mechanical checks — verification rows
present with a command, scope rules for code items, `prior_art` when the item
is tagged new-module/env-var/fs-convention, and re-runnable evidence when the
description pins upstream behavior. The judgment axes (clarity, premise
freshness) stay agent work: read `todo show <id>` and score them, then apply
SHARED/review-protocol/SKILL.md L2.

## Batch implement

Drive a related TODO set through implement -> verify -> complete -> `code`
review -> fix -> PR, one PR per TODO. See `references/batch.md`.

## Notes

- The harness session task list is display only; the database is the record.
- The `--db` default is a gitignored local SQLite; production sets
  `TODO_DB_URL` (hosted). The CLI never echoes the DSN.
- `todo <cmd> --help` is the full contract; this file is deliberately short.
