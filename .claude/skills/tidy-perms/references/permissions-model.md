# Permission Models

| Agent | Files | Change |
|---|---|---|
| Claude Code | `.claude/settings.json`, `.claude/settings.local.json` | May consolidate command allowlists into project settings |
| Codex CLI | `~/.codex/config.toml` | Read-only trust/MCP parity check |
| Gemini CLI | `~/.gemini/settings.json`, `trustedFolders.json` | Read-only trust/MCP parity check |

Classify entries as:

- **PROJECT-SAFE:** observed project CLIs, routine dev tools, MCP tools, and
  skills in `.claude/skills/`.
- **PERSONAL:** web/personal paths, AI CLIs, package installs, destructive
  operations, or unclear entries.
- **GARBAGE:** shell fragments, malformed heredoc fragments, duplicates,
  prose, or entries already covered by broader safe rules.
