# Agent review protocol

This is the active BenchBox binding for the canonical generated
`SHARED/review-protocol` skill — the single behavioral authority for
review-shaped work. It supersedes `docs/development/review-protocol.md`,
retained only as non-authoritative historical rationale. Stable IDs make
the contract mechanically auditable.

## Authority boundary

- `[REVIEW-AUTH-001]`: review-shaped work is read-only. Local capture is the
  only exception explicitly described below. Remediation, hosted writes,
  commits, pushes, PRs, and auto-merge require explicit authorization in a
  later user turn; bundling review and remediation does not satisfy that gate.
- `[AUTH-PROVENANCE-001]`: label consequential instructions as task authority,
  repository policy, mechanical constraint, or recommendation. A prior task's
  requested author identity is not repository policy.
- `[COMMIT-IDENTITY-001]`: resolve the effective human Git identity and inspect
  its config origin. Reject stale agent/service identities unless the user
  explicitly requests that exact identity for the current task.

## Finding routing

- `[REVIEW-DEFECT-001]`: an observed correctness, security, or performance
  failure is a defect and remains an owned review action. It is not a blind
  spot, assumption, or scope-creep record.
- `[REVIEW-L2-001]`: L2 records a review dimension the framework failed to ask
  about. It does not relocate a concrete finding already caught by the review.
- `[REVIEW-CAPTURE-001]`: review-time finding capture is append-only and local
  under `~/.benchbox/finding-drafts/`. Hosted `todo finding sync`, commits,
  pushes, and PRs are separate actions requiring authorization.

## Project binding

The shared TODO database is the durable work tracker, but a review may not
write it merely because the database is available. Use `_project/scripts/todo`
only after the user authorizes tracker writes. The generated canonical skill
defines cross-project behavior; this file binds it to BenchBox paths and tools
without duplicating its full prose. `[REVIEW-PARITY-001]` Stable policy IDs and
their semantics must remain aligned with that canonical skill; wording may be
shorter here, but a contradiction is drift and the canonical behavior wins.

## Audit evidence provenance

`_project/audits/*.md` uses distinct SHA fields for distinct claims:

| Convention | Meaning | Numeric measurement binding |
|---|---|---|
| `develop_sha` | Develop base or lineage the audit describes | Necessary, but not sufficient for measured results |
| `checked_sha` | Exact non-base tree under test | `measured_at_sha` must match it |
| Test-result counts | Passed, failed, skipped, or timed-out totals | Require `measured_at_sha` |
| Inventory counts | Counted tests, queries, bundles, findings, comments, and similar entities | Require `measured_at_sha` |
| Dates, versions, PR/issue references | Narrative identifiers, not empirical results | Do not require fabricated measurement provenance |

`measured_at_sha` binds the original numeric evidence to the exact commit that
produced it. It equals `checked_sha` when that field exists, otherwise
`develop_sha`. A later spot replay does not replace or refresh the original
measurement: record its commit as `replay_sha` and describe exactly what was
rerun in `replay_scope`. The replay commit must descend from the measured
commit, and both must be reachable from the audit's committed tree when the
record is validated. If a replay contradicts a number, correct the claim using
new evidence instead of using `replay_sha` to bless the stale value.
