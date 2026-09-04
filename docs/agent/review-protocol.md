# Agent review protocol

BenchBox bindings for `shared-review-protocol`. The canonical skill governs
behavior; this file records project-specific storage, evidence, and review axes.
It supersedes `docs/agent/review-protocol-legacy.md`.

## Project bindings

- `[REVIEW-AUTH-001]`, `[REVIEW-DEFECT-001]`, `[REVIEW-DEPTH-001]` and
  `[REVIEW-L2-001]` are governed verbatim by the canonical skill. Named here to
  satisfy `[REVIEW-PARITY-001]` without restating behavior, which
  `shared-review-protocol` section 5 forbids this file from doing.
- `[REVIEW-CAPTURE-001]` Finding drafts live under `~/.todo-db/finding-drafts/<project>/`;
  tracker operations use the `todo-db-mcp` server.
- `[REVIEW-PARITY-001]` The canonical skill governs behavior; this file contains
  only BenchBox-specific bindings.

## Audit evidence provenance

Numbers bind to their measurement tree. `make audit-sha-check` enforces it;
see `docs/agent/audit-evidence-provenance.md`.

## Architecture and plan review axes

- **Operational corpus.** Inventory the operational corpus: test:source
  ratio, parsed Make API, overlapping docs, explorer/Python contracts, and
  agent-instruction surface before judging complexity. Simplification plans
  must name those surfaces.
- **Extension-cost.** Primary extension-cost metric: files/contracts to add one SQL
  platform, one DataFrame platform, and one benchmark family. McCabe/cloc
  are hygiene (`docs/development/quality-gate-policy.md`).
- **Prior-decision.** `[REVIEW-PLAN-RECON-001]` BenchBox decision surfaces are
  the future-state index/tiers, migration gates, readiness docs, and open tracker items.
- **CI synchronize fan-out.** For savings/skip/path-filter plans, list every
  same-event workflow, split runner vs wall minutes, and change siblings or
  lower the target. See `docs/operations/repo-admin-settings.md`.
