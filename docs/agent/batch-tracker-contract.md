# Batch tracker contract (BenchBox side)

BenchBox uses todo-db as the canonical tracker. This document records the
consumer boundary for serial and prepared feature batches; the implementation
and API contract live in todo-db, not in BenchBox or its generated skill
mirrors.

## Serial workflow

- A batch is one named delivery with an ordered member list recorded by the
  frozen `feature_batch_preregistration` baseline and the integration worktree
  configuration (`scripts/batch_integration.py start`).
- The integrator performs `take` → scoped implementation → `check_scope` →
  commit → `progress` with file and test evidence → `finish` on one shared
  branch. Claims remain exclusive per principal.
- Tracker dependencies remain tracker-managed. A shared branch supplies a
  common base; it never bypasses dependency order.
- `.todo-batch/` is a local ignored ledger and is never committed.

## Prepared delivery contract

Prepared delivery is now implemented canonically by todo-db PR #39, merged to
`main` at `74631c83f74b7f184abbd49001f032943b720774`. The source exposes schema
3, the `prepared_work_v1` receipt schema, and the MCP verbs `register_batch`,
`prepare`, `bind_batch_pr`, and `abort_batch`. A prepared receipt records the
registered batch and member identity, owner generation, exact clean source
worktree and revision, accepted and integration heads, changed files, scope
hash, and passed bounded-suite evidence.

Only an explicitly registered same-batch implementation edge may consume a
valid prepared receipt. Ordinary, cross-repository, review, approval, merge,
deployment, and soak dependencies remain done-only. Prepared is evidence of
delivery readiness, not completion: final member verification runs on the
combined integration tree, one final PR binds all members, and closeout must
retain exact-tree and attribution evidence. Abort is owner-authorized and
resumable; it invalidates prepared/final evidence without fabricating done
members.

The source checkout and behavioral evidence for this consumer are recorded in
[`batch-source-delivery.json`](../../_project/analysis/batch-source-delivery.json).
That receipt is a source-integrity record, not a tracker mutation or an
activation permit.

## Catalog delivery boundary

The corresponding canonical `todo` skill documentation is merged in
skill-sync-skills PR #80 at `c8473708b5c7809700e8449ecde0dabcdc8e9892`, and
BenchBox pins that revision in `skill-sync.conf`. The tracked `.claude/skills`
mirror and the ignored `.agents/skills` materialization were regenerated from
that pin. Generated mirrors are never hand-edited; `make skill-sync-check`
verifies their parity when the ignored local materialization is present.

## Rollback and safety

No prepared mode is activated by this BenchBox receipt because the active
runtime still lacks the registered-batch capability. The source rollback is
an authorized revert of todo-db merge `74631c83f74b7f184abbd49001f032943b720774`.
If the catalog delivery is rolled back, restore the BenchBox pin to
`d55ac93b9c35f63077b948e4183b4ff960012069` and regenerate through the normal
skill-sync workflow. Do not downgrade a live schema-3 state branch in place;
restore from an accepted snapshot under todo-db's migration and recovery
contract.
