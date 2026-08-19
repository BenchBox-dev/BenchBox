# Bootstrap the Tracker

Use the commands shown by `todo --help`. Initialization requires a project ID
and repository URL; neither has a default.

## 1. Scaffold with `init-project` — the normal path

Run from the repository root:

```sh
todo-db init-project \
  --project-id <project-id> \
  --repository <repository-url> \
  --wrapper
```

This command sets identity and creates:

- `.todo-db/config.json`, which is committed. The tool finds it through
  `TODO_DB_CONFIG` or by walking up from the working directory. Configuration
  precedence is explicit flags, `TODO_DB_*` environment variables, then this
  file.
- `.todo-db/.gitignore`, which ignores database files but tracks `config.json`.
  Do not add `.todo-db/` to the repository `.gitignore`; that would hide the
  committed configuration. The command warns if the config is ignored.
- `_project/scripts/todo` when `--wrapper` is set. It resolves `TODO_DB_TOOL`,
  then `todo-db` on `PATH`, then `../todo-db`. It sets `TODO_DB_CONFIG`, works
  from any directory, and does not hard-code identity.

`--db` stores a local path, defaulting to `.todo-db/standalone.sqlite`, or a
`libsql://` URL. Existing scaffolding requires `--force` to overwrite. Commit
`config.json`, `.todo-db/.gitignore`, and the wrapper.

**Minimal fallback — no scaffolding (for throwaway databases):**

```sh
todo-db --db <path> init --project-id <id> --repository <url>
```

Then pass identity and database on each call or set `TODO_DB_PROJECT_ID`,
`TODO_DB_REPOSITORY`, and `TODO_DB_PATH`. The audit actor comes from `--actor`,
`TODO_ACTOR`, `CLAUDE_SESSION_ID`, `CODEX_SESSION_ID`, or `AGENT_SESSION_ID`.

## 2. Hosted backend (Turso/libSQL) — when you use `TODO_DB_URL`

Create the hosted database and mint tokens with the Turso CLI, such as
`turso db create ...`, before running `todo-db`. The tracker CLI does not create
remote databases.

Example:

```sh
TODO_DB_AUTH_TOKEN=... todo-db init-project \
  --db libsql://<db>.<region>.turso.io \
  --project-id <project-id> --repository <repository-url>
```

- Keep tokens in environment variables. `TODO_DB_AUTH_TOKEN` grants read-write
  access; `TODO_DB_RO_AUTH_TOKEN` is read-only. The CLI rejects plaintext
  `http://` URLs.
- Give each read-write worktree its own replica with
  `--replica .todo-db/replica.db`. The scaffold ignores it; never share the path
  across worktrees.
- Hosted `todo verify --run` requires `TODO_DB_ALLOW_HOSTED_VERIFY_RUN=1`
  because stored verification commands can execute other people's code.
- Use `todo doctor` to check config, identity, database access, and credential
  resolution. Use `--json` for automation. Exit code 4 means authentication
  failed: stop writes, run `todo doctor`, and rotate or provision the credential
  via `TODO_DB_CREDENTIAL_COMMAND` (see `docs/operations/hosted-credentials.md`).
- Install hosted adapters with `uv sync --extra hosted --extra audit` in the
  tool checkout.
- `scripts/turso_acceptance.sh` creates a temporary live database, runs the
  lifecycle, and destroys it. Run it deliberately because it uses real
  resources.
