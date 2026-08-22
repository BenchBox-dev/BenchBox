# Architecture Support-Tier Commitment

**Status:** Explicit deferral — 2026-08-13
**Program:** `arch-simplification`
**Source revision:** `origin/develop` at `40554b9fd6cddee26a501b60430944aaaffc5155`

## Context

The live registries are broad, but the repository has no measured demand,
installation-size, import-time, or CI-support-cost evidence that identifies a
safe product-surface cut. The current registry snapshot is:

| Registry | Total | Stable | Beta | Experimental | Deprecated | Other |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Platforms | 51 | 5 | 28 | 17 | 1 | 0 repo-only / document-only |
| Benchmark families | 23 | 5 | 12 | 5 | 0 | 1 repo-only |

Platform counts and capability totals come from
`PlatformRegistry.get_platform_count_summary()` in
`benchbox/core/platform_registry.py`. Benchmark counts come from
`get_benchmark_registry_summary()` in `benchbox/core/benchmark_registry.py`.
The `support_status` taxonomy remains the public vocabulary; `repo_only` is an
internal registry status and is not promoted into a product tier.

## Options considered

### A — Carry the current inventory

Commit to carry every current platform and benchmark registry entry in-tree.
Experimental entries remain labeled experimental. This avoids product churn,
but accepts the current breadth and its unmeasured maintenance cost.

### B — Supported product is stable plus beta

Commit to stable and beta as the supported product. Experimental and
deprecated entries remain in-tree, but become internal or extra-gated only
after a measured follow-up. This gives a clearer product boundary, but would
require evidence, migration language, and an explicit implementation decision
before changing runtime exposure.

### C — Evidence-gated deferral (selected)

Do not commit to A or B until the missing evidence exists. Keep the current
registry entries and taxonomy unchanged. A follow-up must measure, at minimum:

- default-wheel and optional-install size, including whether an extra actually
  excludes code from the wheel;
- cold import time for the default package and candidate isolated surfaces;
- CI minutes and test-lane touch points attributable to candidate surfaces;
- demand evidence such as documented user requests, adoption, or release
  usage; and
- support cost and compatibility obligations for any deprecated or
  experimental surface proposed for removal.

Until that evidence is recorded and a new product decision is accepted, no
platform or benchmark family may be deleted, have its `support_status`
changed, or be moved into a companion distribution because of this program.

## Consequences for the simplification sequence

| Downstream step | Consequence of Option C |
| --- | --- |
| Step 3b: composition and internal-boundary work | May proceed when it preserves runtime and public contracts; it cannot be used as an implicit product-surface deletion decision. |
| Step 5: family/platform isolation or support-surface work | Must preserve registry entries and labels. Any extraction, extra-gating, or retirement needs the measurements above and a separate accepted decision. |
| Step 6: benchmark-family seam and package follow-ups | A bounded internal pilot may measure extension cost, but it must not create a companion package or delete families. The future-state index must cite this record before ranking extraction as actionable. |

The `arch-composition-boundary-adr`, `arch-retire-compat-surfaces`, and
bounded SQL/SSB follow-ups may therefore improve internal structure within
their own scopes. They must not rewrite support tiers. The
`arch-future-state-index-reconciliation` item owns the corresponding index
cross-reference and must keep extraction blocked on the evidence gate.

## Explicit deferrals and preserved contracts

- Tracker deferral **#711** (MCP production publication: TLS, storage, OTLP,
  multi-host, and named approver) remains outside this program and is explicitly
  **DEFERRED_POST_RELEASE** under
  `docs/operations/mcp-production-readiness-evidence.md`. It does not block MCP
  MVP modernization; only current DuckDB package/execution evidence and pinned
  protocol conformance do.
- No registry metadata, runtime code, packaging file, or test file is changed
  by this decision.
- The public `support_status` vocabulary remains
  `stable` / `beta` / `experimental` / `deprecated` / `repo_only` /
  `document_only`. `repo_only` and `document_only` stay distinct registry
  values; this record does not promote or collapse them into one support
  claim.
