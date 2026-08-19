# todo-db 0.3.2-to-0.4.2 rollout and migration 007 (2026-08-19)

## Scope

Upgrade BenchBox from the vendored `todo-db` 0.3.2 wheel to the checksum-
verified 0.4.2 wheel, preserve the completed schema-6-to-schema-7 migration,
and retain the hosted audit chain, project identity, and rollback evidence.

## Release provenance

- Canonical release: `v0.4.2` at todo-db commit
  `7ae9fda4aab9aeb9d265b403c8bb9ecda844b3a5`.
- Wheel: `todo_db-0.4.2-py3-none-any.whl`.
- Wheel SHA-256:
  `c9f1b97f04f1bc9bd92647abbeb1b2ef1ef8665d6b0db8dc1dfda9f1a06731b7`.
- The downloaded wheel digest matched both the release `SHA256SUMS` entry and
  the GitHub release asset digest.
- Pi adapter remains version 0.1.1.

## Pre-upgrade state

- BenchBox's pinned runtime was still `_project/scripts/vendor/todo_db-0.3.2-py3-none-any.whl`.
- The hosted tracker had already advanced to schema 6 (`claim_coordination`),
  so the pinned 0.3.2 runtime was behind the live database and could no longer
  be trusted for migration-sensitive operations.
- Read-only low-level verification with the checksum-verified 0.4.1 wheel
  against the live schema-6 database produced:
  - schema revisions `1..6`
  - audit algorithm `sha256-chain-v2`
  - event count `9755`
  - head sequence `9755`
  - head hash
    `5d4bb33cd95743656900db588f52e56e597a9e11ae903718f45a53965a29fa10`
- Two 30-second read-only probes before and after the backup matched that same
  `(head_seq, head_hash)` pair, so no concurrent writer was observed during the
  backup window.

## Backup evidence

Because the live schema-6 package asset was unavailable as a released wheel,
BenchBox took the normal lossless export/restore rehearsal with the verified
0.4.1 code path temporarily pinned to schema 6 for read-only export and scratch
restore only. That preserved the todo-db export format and audit verifier while
avoiding writes to the hosted database before migration.

Backup artifact set:

- lossless envelope:
  `/tmp/benchbox-todo-db-preupgrade.GjnZiy/lossless/todo-db.json`
- compatibility views:
  `/tmp/benchbox-todo-db-preupgrade.GjnZiy/views/`
- scratch restore rehearsal DB:
  `/tmp/benchbox-todo-db-preupgrade.GjnZiy/restore-rehearsal.sqlite`
- lossless SHA-256:
  `8421becd4bdb89828e46225384b007c40dd1c72aef25218b3ff625acf8d68054`

The scratch restore rehearsal round-tripped byte-identically and preserved the
same audit head:

- event count `9755`
- head sequence `9755`
- head hash
  `5d4bb33cd95743656900db588f52e56e597a9e11ae903718f45a53965a29fa10`

## Migration semantics

BenchBox's rollout from 0.3.2 crosses migration 007. Migration 007 is additive
and adds verification workspace attestations through the
`verifications.workspace_fingerprint` column. It was applied during the staged
0.4.1 portion of this rollout; the hosted database is now at schema 7 and must
not be reopened with an older binary.

Canonical todo-db 0.4.2 introduces **no schema migration**. It is a package-only
follow-up over the schema-7 state, adding hosted authentication contract
unification, safe v2 auth exit negotiation, generated-wrapper path hardening,
and expanded endpoint redaction.

## Post-upgrade state

- The locked scripts runtime resolves `todo-db 0.4.2` from the vendored wheel
  and exact digest recorded above.
- `_project/scripts/todo` remains a manual `# todo-db-wrapper: v2` wrapper. It
  sets `TODO_DB_AUTH_CONTRACT=v2`, accepts externally supplied credentials, and
  never mints, parses, logs, stores, refreshes, or retries credentials.
- The adapter preserves read-only/read-write credential selection in the
  canonical package and routes mutating `agent` subcommands through BenchBox's
  maintenance-freeze guard.
- Public compatibility exports omit claim-generation tokens; the separate
  private lossless recovery envelope remains complete.
- The hosted database remains at schema 7, and the completed migration audit
  verification retained the pre-upgrade chain head:
  - event count `9755`
  - head sequence `9755`
  - head hash
    `5d4bb33cd95743656900db588f52e56e597a9e11ae903718f45a53965a29fa10`

## Rollback

If the package rollout or post-upgrade verification fails before new tracker
writes are accepted, restore from the retained pre-upgrade lossless backup into
a scratch database first, verify its audit chain and byte-identical export, and
replay it to the hosted target only through an explicitly approved recovery
procedure. Do not downgrade the migrated schema-7 database to the 0.3.2 binary.
