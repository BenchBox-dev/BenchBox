# Bootstrap the tracker

Set up and verify tracker configuration for a repository.

## Repository scaffolding

Run from the repository root to initialize a new tracker:

```sh
todo-db init-project \
  --project-id <project-id> \
  --repository <repository-url>
```

This generates:
- `.todo-db/config.json`: Committed project identity and database target.
- `.todo-db/.gitignore`: Ignores local database files while tracking `config.json`.
- `.mcp.json`: Registers the `todo-db-mcp` server. If `.mcp.json` exists,
  `init-project` merges registration safely without overwriting other servers.

## Preflight verification

Verify configuration and connectivity before beginning work:

1. Call `doctor` via MCP or run `todo-db doctor` in the shell.
2. The MCP `doctor` tool returns an `ok` envelope containing:
   - `status: "ok"`
   - `schema_version`: Current schema version number.
   - `project_id` and `repository`: Confirmed project identity.
3. If the server cannot connect due to schema divergence, tools return `E_SCHEMA`
   (or CLI doctor reports `FAIL`); a human must run `todo-db migrate`.
4. If the database belongs to another repository, tools return `E_IDENTITY`.
   Do not force writes.

## Hosted backend (Turso / libSQL)

When using a hosted database:
- Set `TODO_DB_URL=libsql://<db>.<region>.turso.io` (or `https://`). Cleartext
  `http://` and `ws://` are rejected.
- Supply credentials via `TODO_DB_AUTH_TOKEN` (read-write) and
  `TODO_DB_RO_AUTH_TOKEN` (read-only), or via `TODO_DB_CREDENTIAL_COMMAND`.
- If authentication fails (`E_AUTH_MISSING` or `E_AUTH_REJECTED`), stop.
  Credentials must be refreshed or rotated outside the agent process.
