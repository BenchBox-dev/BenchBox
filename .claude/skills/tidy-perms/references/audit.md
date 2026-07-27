# Audit Permissions

Read user-global, project, and local scopes so the effective owner and
precedence of each executable rule are known. Report PROJECT-SAFE, PERSONAL,
GARBAGE, and POLICY-CONFLICT tables; the project settings summary;
Codex/Gemini trust and MCP state; and whether consolidation is recommended or
should be left unchanged.

Audit hooks as executable policy, not inert configuration. Check for stale
repository/remotes, duplicate commands across scopes, broad or destructive
permissions, bare tool invocations that bypass project tooling, swallowed
errors, mutation during edit hooks, and MCP commands coupled to another
project's environment. Keep Codex/Gemini checks read-only unless the current
task explicitly authorizes personal configuration changes.
