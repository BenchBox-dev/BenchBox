---
name: skill-sync
description: Use when the user asks to sync, set up, inspect, validate, verify, pin, prune, promote, or configure skills managed by skill-sync.
---

# Skill Sync

Read the project-root `skill-sync.yaml`, then read
`references/operations.md` before acting.

## Critical rules

- Resolve the authoritative source before any write: use `source_name` when set;
  otherwise use the first configured source containing the skill.
- Never edit a generated target as the source of truth.
- The `skill-sync` product repository owns its bundled `skills/skill-sync`
  operator skill. Installed and catalog copies are generated consumers.
- Stop before sync when managed tracked files are dirty. Review and commit
  produced tracked changes before unrelated work.

## Actions

| Action | Read |
|---|---|
| `setup`, `sync`, `status`, `validate`, `verify`, `diff`, `doctor` | `references/operations.md` |
| `pin`, `unpin`, `prune`, `promote`, `settings` | `references/operations.md` |
| `agent-config` | `references/operations.md` |
| `help` | this table |

## Flags

- Global: `--json`/`-j`, `--project`/`-p`, `--help`/`-h`.
- Sync: `--dry-run`/`-n`, `--force`/`-f`.
- Validate: `--exit-code`. Settings: `--agent`. Prune: `--dry-run`.
- Agent config: `capture`, `validate`, or `restore`; supports `--dry-run`,
  `--force` for restore, and `--json`.
- Use `--force` only when source and target ownership is known.
