# Audit Permissions

Read global, project, and local scopes to resolve each executable rule's owner
and precedence. Report PROJECT-SAFE, PERSONAL, GARBAGE, and POLICY-CONFLICT
tables; project settings; Codex and Gemini trust and MCP state; and whether to
consolidate.

Treat hooks as executable policy. Check for stale repositories or remotes,
duplicate commands, broad or destructive
permissions, bare tool invocations that bypass project tooling, swallowed
errors, mutation during edit hooks, and MCP commands coupled to another
project's environment. Keep Codex/Gemini checks read-only unless the current
task explicitly authorizes personal configuration changes.
