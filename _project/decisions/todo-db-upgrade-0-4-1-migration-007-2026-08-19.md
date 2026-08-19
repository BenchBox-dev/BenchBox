# todo-db 0.4.1 upgrade and migration 007 runbook (2026-08-19)

## Scope

Upgrade BenchBox from the vendored `todo-db` 0.3.2 wheel to the checksum-
verified 0.4.1 wheel, migrate the hosted tracker from schema 6 to schema 7,
and preserve the hosted audit chain, project identity, and rollback evidence.

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
avoiding any writes to the hosted database before migration.

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

## Migration 007 intent

Migration 007 is additive and adds verification workspace attestations via the
`verifications.workspace_fingerprint` column. BenchBox must not reopen the
hosted tracker with an older binary after this migration lands.

## Post-upgrade state

- The locked scripts runtime now resolves `todo-db 0.4.1` from the vendored
  wheel SHA-256
  `a334ff36ebfb0202d4110936c6868f3603fe4f767c86eb998b10b44cd14be13f`.
- `_project/scripts/todo` is now a manual `# todo-db-wrapper: v2` wrapper with
  external credentials only; `todo doctor --json` reports wrapper/config/
  identity/database/finding-drafts PASS.
- The hosted database is now at schema 7 and `todo-db audit verify` still
  reports the same chain head as the pre-upgrade backup:
  - event count `9755`
  - head sequence `9755`
  - head hash
    `5d4bb33cd95743656900db588f52e56e597a9e11ae903718f45a53965a29fa10`
- The direct package `agent instructions` command is available after upgrade.
  The required read-only `agent next` check now fails with the live production
  guard that the current principal holds multiple active claims; this is the
  expected claim-coordination evidence, not a migration failure.

## Rollback

If the 0.4.1 migration or post-migration verification fails before any new
tracker writes are accepted, restore from the retained pre-upgrade lossless
backup into a scratch database first, verify its audit chain and byte-identical
export, then replay it to the hosted target only with an explicitly approved
recovery procedure.
