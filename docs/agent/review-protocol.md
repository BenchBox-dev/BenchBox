# Agent review protocol

BenchBox binding for `SHARED/review-protocol`. Supersedes
`docs/agent/review-protocol-legacy.md`. IDs are auditable.

## Authority boundary

- `[REVIEW-AUTH-001]`: reviews are read-only except local capture. Remediation,
  hosted writes, commits, pushes, PRs, and auto-merge need authorization in a
  later user turn; bundling review and remediation does not. Findings only: zero tracked
  worktree-content changes; do not review and then edit.
- `[AUTH-PROVENANCE-001]`: label task, repository, mechanical, or
  recommendation. A prior task's author identity is not policy.
- `[COMMIT-IDENTITY-001]`: resolve human Git identity and its origin. Reject
  stale agent/service authors unless this task names that identity.

## Finding routing

- `[REVIEW-DEFECT-001]`: correctness, security, or performance failures stay
  owned review actions, not blind spots.
- `[REVIEW-L2-001]`: L2 is a missed dimension, not a found defect.
- `[REVIEW-CAPTURE-001]`: append-only under `~/.benchbox/finding-drafts/`.
  Hosted sync, commits, pushes, and PRs need separate authorization.

## Project binding

Do not write the TODO database just because it exists. Use
`_project/scripts/todo` only after authorized tracker writes.
`[REVIEW-PARITY-001]`: IDs and semantics stay aligned with the canonical
skill; contradiction is drift.

## Audit evidence provenance

Numbers bind to their measurement tree. `make audit-sha-check` enforces it;
see `docs/agent/audit-evidence-provenance.md`.

## Architecture and plan review axes

Do not relocate a defect into L2 (`[REVIEW-L2-001]`).

- **Operational corpus.** Inventory the operational corpus: test:source
  ratio, parsed Make API, overlapping docs, explorer/Python contracts, and
  agent-instruction surface before judging complexity. Simplification plans
  must name those surfaces.
- **Extension-cost.** Primary extension-cost metric: files/contracts to add one SQL
  platform, one DataFrame platform, and one benchmark family. McCabe/cloc
  are hygiene (`docs/development/quality-gate-policy.md`).
- **Prior-decision.** `[REVIEW-PLAN-RECON-001]`: Enumerate recorded decision
  surfaces (future-state index/tiers, migration gates, readiness docs, open
  tracker items). Cite or supersede each. Unexplained demotion or a dropped open
  gate is a defect.
- **CI synchronize fan-out.** For savings/skip/path-filter plans, list every
  same-event workflow, split runner vs wall minutes, and change siblings or
  lower the target. See `docs/operations/repo-admin-settings.md`.
