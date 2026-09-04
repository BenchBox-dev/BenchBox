# Bootstrap the Tracker

Initialization requires a project ID and repository URL; neither has a default.

## 1. Scaffold with `init-project`

Run from the repository root:

```sh
todo-db init-project \
  --project-id <project-id> \
  --repository <repository-url>
```

This command sets identity and creates:

- `.todo-db/config.json`, which is committed. Tools find it through
  `TODO_DB_CONFIG` or by walking up from the working directory.
- `.todo-db/.gitignore`, which ignores database files but tracks `config.json`.
  Do not add `.todo-db/` to the repository `.gitignore`; that would hide the
  committed configuration.

`--db` stores a local path, defaulting to `.todo-db/standalone.sqlite`. Existing
scaffolding requires `--force` to overwrite. Commit `config.json` and
`.todo-db/.gitignore`.

Run the preflight check to verify setup:
- Inside an MCP session: call the MCP `doctor` tool.
- From the floor CLI: run `todo-db doctor`.

## 2. Register the MCP Server

Ensure `todo-db-mcp` (installed via `todo-db[mcp]`) is registered in your agent client:
- **Claude Code:** `.mcp.json` at project root with command `todo-db-mcp`.
- **Codex:** `~/.codex/config.toml` with command `todo-db-mcp`.
- **Cursor / Windsurf / Zed:** Add `todo-db-mcp` with `--actor <client>:${USER}@${HOSTNAME}`.

## 3. Hosted backend (Turso/libSQL) — when you use `TODO_DB_URL`

The `todo-db-mcp` server is local-SQLite-first. Connecting to a hosted Turso
target requires passing `--allow-hosted` to the server or floor CLI. Authentication
tokens are provided via `TODO_DB_AUTH_TOKEN` (read-write) and `TODO_DB_RO_AUTH_TOKEN`
(read-only). If the server returns `E_AUTH_REJECTED`, provision or rotate credentials
via `TODO_DB_CREDENTIAL_COMMAND`.

