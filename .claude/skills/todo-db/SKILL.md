---
name: todo-db
description: Use when working tracked TODO items via the DB tracker spike - "claim a TODO", "what's ready", "defer this work", "promote a deferral", "complete the item", "todo stats". Wrapper for the database-backed tracker; the legacy `todo` skill still owns the file-tree workflow until cutover.
version: 0.1.0
tools: Bash, Read
---

# TODO Tracker (DB spike)

All TODO state lives in the tracker database. `_project/scripts/todo` is the
ONLY write path — never write tracker state to files. The CLI enforces every
lifecycle rule; when it refuses (exit 2), fix the cause, don't work around it.

## Workflow

1. `todo ready` — pick the top ready item (or the one the user names).
2. `todo claim <id>` — claims it and prints the work order: scope globs,
   must-preserves, anti-patterns, verification ladder, ready units, and open
   deferrals. Follow the work order; it is the whole briefing.
3. Per unit: `todo start <id> <wid>`, implement, then
   `todo done <id> <wid> --evidence "<command run / commit / PR>"`.
4. The moment you decide to skip something: `todo defer <id> --summary "..."
   --reason "..."` — deferring is cheap; losing work is not.
5. Before committing code: `todo check-scope <id>` (exit 1 = out of scope);
   run the ladder with `todo verify <id> --run <seq>`.
6. `todo complete <id> --pr <n>` — refuses while units are undone or
   deferrals unresolved; resolve each with `todo promote <deferral-id>
   --to-item <slug>` or `todo dismiss <deferral-id> --reason "..."`.

## Queries

`todo list`, `todo show <id> --json`, `todo stats`, `todo deps <id>`,
`todo lint <id>` (or `--all`), `todo export`.

## Notes

- Session task list is display only; the database is the record.
- Blocked? `todo block <id> --reason "..."` / `todo unblock <id>`.
  Stale claims: `todo sweep-stale`.
- `todo <cmd> --help` is the full contract; this file is deliberately short.
