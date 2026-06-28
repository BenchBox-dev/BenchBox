---
name: skill-sync
description: Use when the user asks to "sync skills", "set up skill-sync", "check skill status", "validate skills", "preview skill changes", "diagnose skills", "pin a skill", "unpin a skill", "prune skills", or "promote skill changes".
version: 0.2.0
tools: Bash, Read, Write, Edit
---

# skill-sync Workflow

Manage local skill materialization from configured sources while preserving repo hygiene.

## Config

Read `.claude/skills/skill-sync.yaml` or `skill-sync.yaml` from repo root. Config defines sources, destination, excludes, overrides/pins, and validation. If missing, setup creates it.

## Repo Hygiene

- Stop before sync if managed tracked files are dirty; commit or explicitly set aside first.
- After sync, review and commit produced tracked changes before unrelated work.
- Never edit generated/materialized copies as the source of truth unless the config says they are authoritative.

## Actions

| Action | Trigger | Contract |
|---|---|---|
| `setup` | "set up skill-sync" | Create config and initial managed tree |
| `sync` | "sync skills" | Fetch/copy sources into destination |
| `status` | "check skill status" | Show managed paths, pins, drift, dirty state |
| `validate` | "validate skills" | Check config, frontmatter, missing references |
| `diff` | "preview changes" | Dry-run sync and show changes |
| `doctor` | "diagnose skills" | Explain config/path/source problems |
| `pin` | "pin a skill" | Lock git source to current revision |
| `unpin` | "unpin a skill" | Remove revision lock |
| `prune` | "prune skills" | Remove stale managed files |
| `promote` | "promote changes" | Push local source changes upstream |
| `help` | "help", "list actions" | Show actions |

## Action Notes

- **Setup:** discover desired destination, write config, run dry-run, then sync if approved by current task.
- **Sync:** default to dry-run when uncertain; otherwise run configured sync, then validate and report changed files.
- **Status:** include dirty managed files, untracked materialized files, missing sources, pins, and mirror drift.
- **Validate:** ensure every skill has frontmatter, name/description, valid references, and no duplicate canonical paths.
- **Diff:** no writes; show source revision, destination path, additions/removals/modifications.
- **Doctor:** check CLI availability, config parse, source reachability, destination permissions, and drift.
- **Pin/Unpin:** update config only; validate.
- **Prune:** dry-run first; delete only files known to be managed by skill-sync.
- **Promote:** inspect diff, run validation, commit/push source repo using explicit file staging.

## Global Flags

`--dry-run`, `--force`, `--source NAME`, `--dest PATH`, `--verbose`. Use `--force` only when source/destination ownership is known.
