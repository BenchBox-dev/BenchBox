---
name: skill-sync
description: Use when the user asks to "sync skills", "set up skill-sync", "check skill status", "validate skills", "preview skill changes", "diagnose skills", "verify skills", "pin a skill", "unpin a skill", "prune skills", "promote skill changes", or "configure skill settings".
version: 0.2.0
tools: Bash, Read, Write, Edit
---

# Skill Sync

Read `skill-sync.yaml` at the project root first. It defines sources, skills, targets, and pins. Route to the operation guide below and read the file in the Read column before acting.

## Actions

| Action | Read |
|---|---|
| `setup` | `references/operations.md` |
| `sync` | `references/operations.md` |
| `status` | `references/operations.md` |
| `validate` | `references/operations.md` |
| `verify` | `references/operations.md` |
| `diff` | `references/operations.md` |
| `doctor` | `references/operations.md` |
| `pin` | `references/operations.md` |
| `unpin` | `references/operations.md` |
| `prune` | `references/operations.md` |
| `promote` | `references/operations.md` |
| `settings` | `references/operations.md` |
| `help` | this table |

## Rules

- Stop before sync if managed tracked files are dirty. Review and commit produced tracked changes before unrelated work.
- Never edit generated/materialized copies as the source of truth unless the config says they are authoritative.
- Global flags: `--json`/`-j`, `--project`/`-p`, `--help`/`-h`. Per-command flags: `--dry-run`/`-n` and `--force`/`-f` for sync, `--exit-code` for validate, `--agent` for settings, `--dry-run` for prune. Use `--force` only when source/destination ownership is known.
