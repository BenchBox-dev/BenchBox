# Bootstrap the Tracker

Use this guide to add the `todo-db` tracker to a project that does not yet have it. The CLI contract is authoritative — only use what `todo --help` shows. You must provide a project id and a repository URL. There is no default. If you run `init` without them, it fails.

## 1. Scaffold with `init-project` — the normal path

Run from the repository root:

```sh
todo-db init-project \
  --project-id <project-id> \
  --repository <repository-url> \
  --wrapper
```

This one command sets the identity and creates the scaffolding:

* `.todo-db/config.json` — committed. The tool finds it by walking up from your working directory, or from `TODO_DB_CONFIG` if you set it. It holds the identity and the database location so later commands need no flags. Priority: explicit flags first, then `TODO_DB_*` env vars, then the config file.
* `.todo-db/.gitignore` — keeps the database files untracked but keeps `config.json` tracked. Do not add a bare `.todo-db/` line to the repository `.gitignore`. It would hide the committed config. The command warns you if the config is ignored.
* `_project/scripts/todo` (created by `--wrapper`) — a wrapper that finds the tool as `TODO_DB_TOOL` env var, then `todo-db` on PATH, then a sibling `../todo-db` checkout. It sets `TODO_DB_CONFIG` so it works from any directory. It does not hard-code an identity.

`--db` stores a local path (default `.todo-db/standalone.sqlite`) or a `libsql://` URL in the config. The command never overwrites existing scaffolding unless you pass `--force`. Commit `config.json`, `.todo-db/.gitignore`, and the wrapper.

**Minimal fallback — no scaffolding (for throwaway databases):**

```sh
todo-db --db <path> init --project-id <id> --repository <url>
```

Then pass the identity and database on every call, or through `TODO_DB_PROJECT_ID`, `TODO_DB_REPOSITORY`, and `TODO_DB_PATH`. The audit actor comes from `--actor` or from `TODO_ACTOR`, `CLAUDE_SESSION_ID`, `CODEX_SESSION_ID`, or `AGENT_SESSION_ID`.

## 2. Hosted backend (Turso/libSQL) — when you use `TODO_DB_URL`

This section is part of the main guide. Use it when you store the tracker in a hosted database.

You must create the hosted database before you run `todo-db`. Create it and mint tokens with the Turso CLI (`turso db create ...` and token minting). The tracker CLI never creates the remote database. If the database does not exist, the first connection fails.

Example:

```sh
TODO_DB_AUTH_TOKEN=... todo-db init-project \
  --db libsql://<db>.<region>.turso.io \
  --project-id <project-id> --repository <repository-url>
```

What you need to know:

* Tokens live only in env vars. `TODO_DB_AUTH_TOKEN` is for read-write. `TODO_DB_RO_AUTH_TOKEN` is for read-only use (for example, `export`). The CLI refuses plaintext `http://` URLs.
* Hosted read-write use needs a per-worktree replica: `--replica .todo-db/replica.db`. The scaffold git-ignores it. Do not share one replica path across worktrees.
* `todo verify --run` on a hosted database refuses to run unless you set `TODO_DB_ALLOW_HOSTED_VERIFY_RUN=1`. Stored verification commands were written by other people. Running them is a code-execution risk.
* Preflight check: `todo doctor` is a safe health check. It checks config, identity, database reachability, and Turso CLI auth. Use `--json` for automation. Exit code 4 means auth failed — stop writes, refresh the token, and show the error. Wrappers from `todo-db` try once to refresh the token before they return exit code 4.
* Hosted adapters are optional extras of the `todo-db` package. Install them in the tool checkout with `uv sync --extra hosted --extra audit`.
* Live validation: `scripts/turso_acceptance.sh` in the `todo-db` checkout creates a temporary database, runs the full lifecycle, and destroys it. It uses real resources, so run it on purpose only.
