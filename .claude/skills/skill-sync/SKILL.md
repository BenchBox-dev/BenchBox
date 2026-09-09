---
name: skill-sync
description: Use when the user asks to sync, preview, check, or configure skills managed by skill-sync.
---

# Skill Sync

`skill-sync` copies selected skill packages from Git-managed catalogs into a
project. rsync copies the payload; Git supplies history, review, and rollback.

Read the project-root `skill-sync.conf`, then read `references/operations.md`
before acting.

## Critical rules

- The catalog checkout named in `skill-sync.conf` is the only place to edit a
  managed skill. Files under a `target` directory are generated copies; editing
  them is lost work.
- Bytes always come from the `rev` recorded in the config, never from the
  catalog's working tree. To ship an edit, commit it in the catalog and bump
  `rev`.
- Run `preview` before `apply`. `apply` refuses to overwrite uncommitted
  changes to the files it would rewrite; commit or discard them first.
- `apply` does not commit or push. Review the resulting Git diff and commit it
  through the project's normal workflow.
- The product repository owns its bundled `skills/skill-sync` operator skill.
  Installed copies are generated consumers.

## Actions

| Action | Command |
|---|---|
| Show what a sync would change | `skill-sync preview` |
| Fail if a sync is pending | `skill-sync check` (exit 3 when changes are pending) |
| Copy the payload into the project | `skill-sync apply` |
| Gate a committed payload offline | `skill-sync verify` |

All four take `-C DIR` (project root, default `.`) and `-f FILE` (config,
default `PROJECT/skill-sync.conf`). `preview`, `check`, and `apply` need the
catalog checkout; `verify` reads only committed project files.

## Retired commands

`sync`, `status`, `validate`, `diff`, `doctor`, `pin`, `unpin`, `prune`,
`promote`, `settings`, `align-agents`, and `agent-config` belonged to the
TypeScript implementation. The CLI rejects them with a pointer to
`MIGRATION.md`. Do not reintroduce them; read `references/operations.md` for
what replaced each one.
