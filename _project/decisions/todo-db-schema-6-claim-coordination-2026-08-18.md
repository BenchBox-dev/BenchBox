# Schema 6 rollout: claim-coordination columns (todo-db 0.4.0)

**Date**: 2026-08-18
**Status**: wrapper and inventory bumped to 6; hosted primary migrated to
schema 6 on 2026-08-18.
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

The local embedded replica `.todo-db/standalone-replica.db` was checked before
migration on 2026-08-18: `meta.schema_version = '5'`, and `items` had none of
the five revision-6 columns. A Turso snapshot was exported outside the
repository before the migration.

The migration was then applied with the locked `todo-db 0.4.0` client using
`todo-db ... migrate` and a short-lived RW token minted by the Turso CLI. A
post-migration `todo doctor` read-only probe confirmed the hosted primary at
schema v6. No credential was written to the repository.

## Deployment order

Propagate the 0.4.0 runtime to every active clone/worktree before the first
0.4.0 client opens the hosted primary:

1. Land this change on `develop`.
2. Every active clone/worktree pulls and runs `uv sync --project _project/scripts`.
3. Confirm `todo doctor` reports schema OK v6 from each active worktree.
4. Open the hosted primary with a 0.4.0 client; migration 006 then applies.

This rollout applied step 4 on 2026-08-18 after the pre-migration snapshot and
post-migration probe. Any active clone still on 0.3.2 now fails closed with
`E_SCHEMA_DIVERGED`, including read-only commands; those clones must complete
step 2 before using the tracker again. The behavior is the same stale-clone
protection accepted in D2 and does not mutate the stale clone.

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
