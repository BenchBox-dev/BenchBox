# Bootstrap the tracker

Set up tracker state for a repository. State lives on a dedicated Git
branch, outside the code worktree.

## Create the state branch

A human runs, from anywhere with Git access to the remote:

```sh
todo-db bootstrap --state-remote <git-url-or-path> [--state-branch todo-state] --write-config
```

`--write-config` writes `.todo-db/config.json` (state remote + branch)
in the repo root for server discovery. Bootstrap refuses to overwrite an
existing state branch.

## Migrate from a 0.6.x export

To carry an existing SQLite-era tracker onto the new state branch:

1. With the old `todo-db`, write a lossless export:
   `todo-db --db <old>.sqlite export --output <export>.json` (the envelope
   must be `format_version` 2).
2. `todo-db bootstrap ...` to create the empty state branch.
3. `todo-db migrate --from-export <export>.json --dry-run` and read the
   mapping report: item count, status breakdown, dropped-claim warnings,
   and preserved row counts.
4. `todo-db migrate --from-export <export>.json --backup-dir <dir> --actor
   <name>` for the real run. `--backup-dir` is required — the export is the
   only archive of events, findings, and audit history, none of which
   migrate.
5. `todo-db validate`, then spot-check a few items with `todo-db show <id>`.

The migration refuses a non-empty state branch and refuses cutover while
any claim lease is still live. To roll back before any consumer adopts the
new tracker, delete the state branch and re-bootstrap; the old database is
untouched.

## Point the agent at it

- MCP server: `--state-remote` / `--state-branch` / `--cache-dir` flags,
  `TODO_DB_STATE_REMOTE` / `TODO_DB_STATE_BRANCH` / `TODO_DB_CACHE_DIR`
  env, or the discovered `.todo-db/config.json` — in that order.
- One server instance is one worker identity (`--actor`, else
  `TODO_DB_ACTOR`, else the client name from the MCP handshake).

## Preflight verification

1. Run `todo-db validate` (human/CI) or `list_items` (agent).
2. A missing branch means bootstrap has not run yet — say so, do not
   improvise state.
3. The state branch shares its repository's access and visibility. Never
   publish credentials to it and never assume it is private.
