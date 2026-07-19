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
Global flags `--db` / `--actor` go before the subcommand.

## Implement flow

1. `todo ready` — pick the top ready item (or the one the user names).
2. `todo claim <id>` — claims it and prints the work order: scope globs,
   must-preserves, anti-patterns, verification ladder, ready units, and open
   deferrals. Follow it; it is the whole briefing.
3. Per unit: `todo start <id> <wid>` (optional — records your worktree/branch
   so work can resume; `todo done` stamps them too), implement, then
   `todo done <id> <wid> --evidence "<command / commit / PR>"`.
4. The moment you decide to skip something: `todo defer <id> --summary "..."
   --reason "..."` — deferring is cheap; losing work is not.
5. Before committing code: `todo check-scope <id>` (exit 1 = out of scope);
   run the ladder with `todo verify <id> --run [seq]`, then commit via
   SHARED/commit-framework/SKILL.md.
6. `todo complete <id> --pr <n>` — gated: refuses while units are undone or
   deferrals unresolved. Resolve each with `todo promote <deferral-id>
   --to-item <slug>` or `todo dismiss <deferral-id> --reason "..."`.

## Backlog, queries, review

- Manage: `todo create --title ... --worktree ... --priority ...`,
  `todo block` / `todo unblock`, `todo release`, `todo drop`, `todo sweep-stale`.
- Inspect: `todo list`, `todo show <id> --json`, `todo stats`,
  `todo deps <id>`, `todo export`.
- Review: `todo lint <id>` runs the mechanical quality checks; judge clarity
  and premise freshness by reading `todo show <id>`.
- Batch a related set, one PR per item: see `references/batch.md`.

## Notes

- The harness session task list is display only; the database is the record.
- `todo <cmd> --help` is the full contract; this file is deliberately short.
