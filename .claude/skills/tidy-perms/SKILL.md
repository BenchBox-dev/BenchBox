---
name: tidy-perms
description: "Consolidate accumulated permission grants across Claude Code, Codex, and Gemini: move trusted commands into project settings, clean garbage entries, verify cross-agent consistency, commit project-level configs."
version: 0.2.0
tools: Bash, Read, Write, Edit
---

# Permissions Consolidation

Route to `consolidate` or `audit`. Keep unclear entries PERSONAL and never
weaken safety.

## Actions

| Action | Trigger | Read |
|---|---|---|
| `consolidate` | default/tidy permissions | `references/consolidate.md` |
| `audit` | audit/review permissions | `references/audit.md` |
| `help` | help/list actions | this table |

## Rules

- Never `git add -A`; stage explicit project config paths only.
- Never commit `settings.local.json`, `~/.codex/config.toml`, or
  `~/.gemini/*.json`.
- Never remove hooks or unrelated keys, or add force-push/reset/clean/rm rules
  to allowlists.
