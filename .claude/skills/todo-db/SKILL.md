---
name: todo-db
description: Use when the user asks to "create a TODO", "show TODO items", "manage TODOs", "prioritize TODOs", "implement a TODO", "implement a batch of TODOs", "batch implement TODOs", "complete a TODO", "cleanup TODOs", "review TODO quality", "claim a TODO", "what's ready" / "ready queue", "defer this work", "promote a deferral", "dismiss a deferral", "block"/"unblock a TODO", "create TODOs from a spec", or "todo stats". The production database-backed tracker; all tracker state lives in the shared DB and flows through the `todo` CLI.
version: 0.2.0
tools: Bash, Read, Edit, Write, Task
---

# TODO Tracker

Route the requested CLI subcommand to its guide and read that guide before
acting. The database is the record:
`_project/scripts/todo` is the ONLY write path, and exit 2 means fix the cause.
Global `--db` / `--actor` flags go before the subcommand.

## Actions

| Action | Read |
|---|---|
| `ready` | `references/implement.md` |
| `claim` | `references/implement.md` |
| `start` | `references/implement.md` |
| `done` | `references/implement.md` |
| `defer` | `references/implement.md` |
| `check-scope` | `references/implement.md` |
| `verify` | `references/implement.md` |
| `complete` | `references/implement.md` |
| `promote` | `references/implement.md` |
| `dismiss` | `references/implement.md` |
| `create` | `references/queries.md` |
| `list` | `references/queries.md` |
| `show` | `references/queries.md` |
| `stats` | `references/queries.md` |
| `deps` | `references/queries.md` |
| `export` | `references/queries.md` |
| `block` | `references/queries.md` |
| `unblock` | `references/queries.md` |
| `release` | `references/queries.md` |
| `sweep-stale` | `references/queries.md` |
| `drop` | `references/queries.md` |
| `lint` | `references/review.md` |
| `batch` | `references/batch.md` |

## Rules

- Follow the selected guide and commit changed files only through
  `SHARED/commit-framework/SKILL.md`.
- `todo <cmd> --help` is the full CLI contract. Never hand-write tracker state
  into repo files. `TODO_DB_URL` may provide the hosted database; the CLI never
  echoes its DSN.
