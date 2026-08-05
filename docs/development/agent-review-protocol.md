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

Audit records bind numbers to the tree that produced them through distinct SHA
fields. `make audit-sha-check` enforces it; the conventions are documented in
`docs/development/audit-evidence-provenance.md`.
