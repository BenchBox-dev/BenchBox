---
name: tidy-perms
description: "Consolidate accumulated permission grants across Claude Code, Codex, and Gemini: move trusted commands into project settings, clean garbage entries, verify cross-agent consistency, commit project-level configs."
version: 0.2.0
tools: Bash, Read, Write, Edit
---

# Permissions Consolidation

Audit and consolidate agent permission settings without weakening safety.

## Actions

| Action | Trigger | Contract |
|---|---|---|
| `consolidate` | default, "tidy permissions" | Categorize Claude local permissions, move project-safe rules to project settings, validate, commit project file only |
| `audit` | "audit permissions", "review permissions" | Read-only report across Claude, Codex, Gemini |
| `help` | "help", "list actions" | Show actions |

## Permission Models

| Agent | Files | What to change |
|---|---|---|
| Claude Code | `.claude/settings.json`, `.claude/settings.local.json` | May consolidate command allowlist into project settings |
| Codex CLI | `~/.codex/config.toml` | Read-only trust/MCP parity check |
| Gemini CLI | `~/.gemini/settings.json`, `trustedFolders.json` | Read-only trust/MCP parity check |

## Categories

- **PROJECT-SAFE:** project CLIs and routine dev tools already granted locally: `git`, `uv`, `make`, `gh`, language runtimes, common shell read/inspect utilities, project MCP tools, skills present in `.claude/skills/`.
- **PERSONAL:** web fetch/search, personal paths, AI CLIs, package installs, destructive filesystem operations, unclear entries.
- **GARBAGE:** shell fragments, malformed commit heredoc fragments, duplicates, prose, entries already covered by broader safe rules.

When uncertain, keep PERSONAL and ask.

## Consolidate

1. Read Claude project/local settings. If no local settings, report and continue cross-agent checks.
2. Discover project CLIs from Makefile, MCP config, package manifests, pyproject, and agent docs.
3. Read Codex/Gemini trust and MCP state; do not edit them.
4. Categorize `settings.local.json` entries.
5. Merge PROJECT-SAFE entries into broadest already-justified patterns without expanding authority beyond observed grants.
6. Update `.claude/settings.json` `permissions.allow`, preserving hooks and all non-permission keys.
7. Rewrite `.claude/settings.local.json` with PERSONAL entries only; remove GARBAGE.
8. Validate both JSON files with `jq -e`.
9. Report cross-agent trust/MCP parity.
10. Commit only `.claude/settings.json` if changed; never commit local/global personal files.

## Audit Output

Report PROJECT-SAFE, PERSONAL, and GARBAGE tables; current `.claude/settings.json` summary; Codex/Gemini trust and MCP status; recommendation to consolidate or leave unchanged.

## Rules

- Never `git add -A`; stage explicit project config files only.
- Never commit `settings.local.json`, `~/.codex/config.toml`, or `~/.gemini/*.json`.
- Never remove hooks or unrelated settings keys.
- Never add `git push --force`, `git reset --hard`, `git clean -f`, or `rm -rf` to project allowlists.
- Codex/Gemini checks are read-only.
