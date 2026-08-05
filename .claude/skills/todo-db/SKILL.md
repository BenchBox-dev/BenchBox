---
name: todo-db
description: Use when the user asks to "create a TODO", "show TODO items", "manage TODOs", "prioritize TODOs", "top N most important todos", "rank the backlog", "what should we work on", "implement a TODO", "implement a batch of TODOs", "batch implement TODOs", "complete a TODO", "cleanup TODOs", "review TODO quality", "claim a TODO", "what's ready" / "ready queue", "defer this work", "promote a deferral", "dismiss a deferral", "block"/"unblock a TODO", "create TODOs from a spec", or "todo stats". The production database-backed tracker; all tracker state lives in the shared DB and flows through the `todo` CLI (except skill-only analysis actions such as prioritize).
version: 0.4.0
tools: Bash, Read, Edit, Write, Task
---

# TODO Tracker

Route the request to its guide before acting. The DB is the record; most
actions are CLI subcommands, a few (skill-only) are analysis workflows.
Resolve the `todo` command for CLI actions, not by file presence alone:

1. If `_project/scripts/todo` exists, inspect its top-level `--help`.
2. Use that wrapper only when it advertises the requested subcommand.
3. Else use standalone todo-db >= 0.3 (`todo-db` / `todo`) only when help
   advertises the action and db/project identity come from config, env, or flags.
4. If neither supports the action, report the gap and stop; never send a
   standalone-only action to a legacy wrapper.
5. Skill-only actions (currently `prioritize`) have no CLI verb — follow their
   guide and use only the inspect verbs it names.

Exit 2 is generic failure. Exit 4 is hosted auth failure only when the selected
command documents that contract: stop writes, run supported `doctor`, surface
the alert. Auto-remint is only for todo-db >= 0.3 wrappers. Global `--db` /
`--actor` go before the subcommand.

## Actions

| Action | Read |
|---|---|
| `bootstrap` / `init` / `doctor` | `references/bootstrap.md` |
| `ready` / `claim` / `start` / `done` / `defer` / `check-scope` / `verify` / `complete` / `promote` / `dismiss` | `references/implement.md` |
| `create` / `update` / `list` / `show` / `stats` / `deps` / `export` / `block` / `unblock` / `release` / `sweep-stale` / `drop` | `references/queries.md` |
| `prioritize` (skill-only; no CLI verb) | `references/prioritize.md` |
| `lint` | `references/review.md` |
| `finding candidates` / `finding triage` / `finding sync` / `finding promote` | `references/implement.md` |
| `batch` | `references/batch.md` |

`ready`/`stats` emit a one-line stderr banner when untriaged findings exist
(open findings or unsynced drafts); run `todo finding candidates` to triage.
Banner is stderr-only and zero-suppressed, so stdout stays machine-readable.

Standalone-only actions are declared in the skill sidecar as
`standalone_only_commands` (currently none for this wrapper); rule 4 applies
when a future verb is declared.

## Rules

- Follow the selected guide; commit only through `SHARED/change-framework/SKILL.md`.
- The selected command's `--help` is the full CLI contract. Never hand-write
  tracker state into repo files. `TODO_DB_URL` may set the hosted DB; the CLI
  never echoes its DSN.
