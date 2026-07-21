---
name: skill-sync
description: Use when the user asks to "sync skills", "set up skill-sync", "check skill status", "validate skills", "preview skill changes", "diagnose skills", "pin a skill", "unpin a skill", "prune skills", or "promote skill changes".
version: 0.2.0
tools: Bash, Read, Write, Edit
---

# Skill Sync

Read `skill-sync.yaml` (or `.claude/skills/skill-sync.yaml`) first. It defines
sources, destination, excludes, pins, and validation. Route to the operation
guide below.

## Actions

| Action | Read |
|---|---|
| `setup` | `references/operations.md` |
| `sync` | `references/operations.md` |
| `status` | `references/operations.md` |
| `validate` | `references/operations.md` |
| `diff` | `references/operations.md` |
| `doctor` | `references/operations.md` |
| `pin` | `references/operations.md` |
| `unpin` | `references/operations.md` |
| `prune` | `references/operations.md` |
| `promote` | `references/operations.md` |
| `help` | this table |

## Rules

- Stop before sync if managed tracked files are dirty. Review and commit
  produced tracked changes before unrelated work.
- Never edit generated/materialized copies as the source of truth unless the
  config says they are authoritative.
- Global flags: `--dry-run`, `--force`, `--source NAME`, `--dest PATH`,
  `--verbose`. Use `--force` only when source/destination ownership is known.
