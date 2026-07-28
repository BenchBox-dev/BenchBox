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
- **POLICY-CONFLICT:** an executable hook, permission, trust record, or MCP
  command whose effective behavior contradicts current repository policy,
  assumes a retired repository/remote, hides failures, mutates incomplete
  edits, or launches through another project's environment. Do not consolidate
  it. Remove or repair it only with explicit authority for the owning scope.

For every executable entry, record its source scope, matcher, command family,
effective precedence, failure behavior, and the policy or workflow it claims
to enforce. Identical commands in multiple scopes are duplicates even when
their JSON text differs only because one parser reads stdin.
