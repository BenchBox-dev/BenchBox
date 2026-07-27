# Bootstrap The Tracker In A Fresh Project

Adopt the `todo-db` tracker in a project that has none. Requires todo-db
>= 0.2.0 (installed on PATH, or a checkout — default assumption: sibling at
`<repo>/../todo-db`, invoked via `uv run --project <checkout> todo-db ...`).
Document only what `todo-db --help` confirms; the CLI contract is
authoritative. Identity is REQUIRED — there is no default `--project-id`/
`--repository`; `init` without one is an error.

## 1. Scaffold with `init-project` (primary path)

From the repo root:

```sh
todo-db init-project \
  --project-id <project-id> \
  --repository <repository-url> \
  --wrapper
```

One command binds the identity and scaffolds the repo:

- `.todo-db/config.json` — COMMITTED. Discovered git-style (walking up from
  cwd, or pinned via `TODO_DB_CONFIG`), it supplies identity and database
  target so later calls need no flags. Precedence: explicit flags >
  `TODO_DB_*` env > discovered config.
- `.todo-db/.gitignore` — ignores the databases but keeps `config.json`
  tracked. Do NOT add a bare `.todo-db/` rule to the repo `.gitignore`; that
  hides the committed config (the command warns if git ignores it).
- `_project/scripts/todo` (from `--wrapper`; optional path argument) — an
  executable wrapper resolving the tool as `TODO_DB_TOOL` env > `todo-db` on
  PATH > sibling `../todo-db` checkout, exporting `TODO_DB_CONFIG` so it
  works from any cwd. No hardcoded identity flags.

`--db` records a local path (default `.todo-db/standalone.sqlite`) or a
`libsql://` URL in the config. Existing scaffolding is never overwritten
without `--force`. Commit `config.json`, `.todo-db/.gitignore`, and the
wrapper.

Minimal fallback (no scaffolding — e.g. throwaway databases):
`todo-db --db <path> init --project-id <id> --repository <url>`, then pass
identity/db on every call or via `TODO_DB_PROJECT_ID`/`TODO_DB_REPOSITORY`/
`TODO_DB_PATH`. The audit actor comes from `--actor` or
`TODO_ACTOR`/`CLAUDE_SESSION_ID`/`CODEX_SESSION_ID`/`AGENT_SESSION_ID`.

## 2. Hosted backend (Turso/libSQL)

Provisioning happens OUTSIDE this tool: create the database and mint tokens
with the Turso tooling (`turso db create ...` plus token minting) before any
`todo-db` call. The CLI never creates the remote database — a first-use
connection to a missing database fails; it does not provision.

```sh
TODO_DB_AUTH_TOKEN=... todo-db init-project \
  --db libsql://<db>.<region>.turso.io \
  --project-id <project-id> --repository <repository-url>
```

- `TODO_DB_AUTH_TOKEN` — read-write connections; `TODO_DB_RO_AUTH_TOKEN` —
  read-only (e.g. `export`). Tokens live in env only; plaintext `http://`
  URLs are refused.
- Read-write hosted use requires a per-worktree embedded replica:
  `--replica .todo-db/replica.db` (gitignored by the scaffold; one replica
  path per worktree, never shared).
- `verify --run` against a hosted database refuses without
  `TODO_DB_ALLOW_HOSTED_VERIFY_RUN=1`: stored commands are written by other
  actors, and executing them locally is a lateral code-execution channel.
- Preflight: `todo-db doctor` (>= 0.3.0) is a side-effect-free health check
  over config, identity, database reachability, and turso CLI auth; `--json`
  for automation. Exit 4 = auth failure (see SKILL.md halt rule); the
  generated wrapper auto-remints a token and retries once before exiting 4.
- Live validation: `scripts/turso_acceptance.sh` in the todo-db checkout
  provisions a throwaway database, exercises the full lifecycle, and
  destroys it (run deliberately — real resources).
- Hosted adapters are optional extras of the todo-db package
  (`uv sync --extra hosted --extra audit` in the tool checkout).
