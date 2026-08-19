# Schema 6 rollout: claim-coordination columns (todo-db 0.4.0)

**Date**: 2026-08-18
**Status**: wrapper and inventory bumped to 6; **hosted primary migration not yet
performed**.
**Related**: `_project/decisions/todo-db-cutover-write-freeze-2026-08-01.md`
(D2, D9, D10).

## Context

The `_project/scripts` runtime moved from the vendored `todo_db-0.3.2` wheel to
`https://github.com/joeharris76/todo-db@v0.4.0`, locked to commit
`da060081261dbcc297c9c1923838e993a7f79d5b`.

That release moves `todo_db.database.SCHEMA_VERSION` from 5 to 6. Revision 6
is `006_claim_coordination.sql`, with five additive `items` columns:

```sql
ALTER TABLE items ADD COLUMN claimed_session TEXT;
ALTER TABLE items ADD COLUMN claim_token TEXT;
ALTER TABLE items ADD COLUMN claimed_branch TEXT;
ALTER TABLE items ADD COLUMN claimed_worktree TEXT;
ALTER TABLE items ADD COLUMN git_baseline TEXT;
```

## Current state

The local embedded replica `.todo-db/standalone-replica.db` was checked on
2026-08-18: `meta.schema_version = '5'`, and `items` has none of the five
revision-6 columns. The hosted primary has therefore not been migrated by this
change.

`todo-db` applies revision 6 automatically when the first 0.4.0 client opens
the primary. No hosted credential was read or used here.

## Deployment order

Propagate the 0.4.0 runtime to every active clone/worktree before the first
0.4.0 client opens the hosted primary:

1. Land this change on `develop`.
2. Every active clone/worktree pulls and runs `uv sync --project _project/scripts`.
3. Confirm `todo doctor` reports schema OK v6 from each active worktree.
4. Open the hosted primary with a 0.4.0 client; migration 006 then applies
   automatically.

`_migrate()` fails closed with `E_SCHEMA_DIVERGED` when a stale 0.3.2 clone
encounters the newly applied revision. This includes read-only commands, so
step 2 must precede step 4. The behavior is the same stale-clone protection
accepted in D2 and does not mutate the stale clone.

## CI guard placement

`todo_schema_migration_check.py` previously inspected the orphaned vendored
0.3.2 wheel, so it could pass against schema 5 while the runtime was schema 6.
It now inspects todo-db as installed into `_project/scripts/.venv`. Because a
git-tag pin has no artifact to inspect before installation, the guard runs in
`lint` as `guard-todo-schema-migration`, after
`uv sync --project _project/scripts --locked`, and is mirrored by `make ci-lint`.

This leaves an accepted path-filter gap: `lint` requires code CI, while
`_project/decisions/**` is `safe-content` in `.github/path-filters.yml`. A PR
that only deletes or renames this evidence record can therefore skip the
runtime guard. Keeping the evidence path in the inventory and reviewing
path-filter changes together is the chosen trade-off; syncing the scripts
project in dependency-free `ci-paths` would tax every content-only PR.
