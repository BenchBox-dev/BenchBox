# Consolidate Permissions

1. Read Claude user-global, project, and local settings; if local settings are absent, report it.
2. Discover project CLIs from the Makefile, MCP config, manifests, and agent
   docs.
3. Read Codex/Gemini trust and MCP state without editing them.
4. Resolve precedence and categorize permissions and executable hooks using
   `references/permissions-model.md`.
5. Merge PROJECT-SAFE entries into the broadest justified project patterns;
   keep PERSONAL and remove only GARBAGE.
6. Update `.claude/settings.json`, preserving unrelated hooks and
   non-permission keys. Remove a POLICY-CONFLICT hook only with task authority
   and evidence of its stale assumption or contradiction.
7. Keep PERSONAL entries in `.claude/settings.local.json` only.
8. Validate both JSON files with `jq -e`.
9. Report cross-agent trust/MCP parity and commit only the project settings
   file if changed. Personal-file changes remain local and uncommitted.
