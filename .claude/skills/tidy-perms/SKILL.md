---
name: tidy-perms
description: "Consolidate accumulated permission grants across Claude Code, Codex, and Gemini: move trusted commands into project settings, clean garbage entries, verify cross-agent consistency, commit project-level configs."
version: 0.2.0
tools: Bash, Read, Write, Edit
---

# Permissions Consolidation

Route to `consolidate` or `audit`; read the file in the Read column before
acting. Keep unclear entries PERSONAL and ask; never weaken safety.

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
- Never remove unrelated hooks or keys, or add force-push/reset/clean/rm rules
  to allowlists. A stale or conflicting executable hook may be removed only
  when the active owner, conflict, and replacement safety path are evidenced
  and the current task explicitly authorizes personal configuration changes.
