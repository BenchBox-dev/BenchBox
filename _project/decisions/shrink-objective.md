# ADR: Shrink Campaign Objective

**Status:** Accepted — 2026-05-24
**Supersedes:** the implicit "reduce `benchbox/` Python by 66%" target.
**Evidence:** `_project/analysis/shrink-feasibility.md`
**Operative doc:** `_project/goal-shrink-core-code.md`

## Context

The shrink campaign carried a 66% line-reduction target (234,211 → ~79,632 cloc) with:

- **No documented provenance** — no `_project` record states why 66%, or what problem it solves.
- **A history of metric-gaming** — prior "shrink" PRs created raw `cloc` movement that is
  not credited unless a merged ledger fragment classifies it as maintained-Python reduction
  (this branch measures 206,854 Python code lines against the 234,211 reference denominator).
- **A feasibility analysis** (two independent reviews) showing the honest autonomous ceiling
  is single-digit %, and that even deleting all experimental surface + architectural rewrites
  reaches only ~30–45% — never 66% without gaming or product-surface loss.
- **Low intrinsic complexity** — radon avg cyclomatic "A" (3.77). The codebase is broad, not
  complex; line count is a poor proxy for its real maintenance cost (the platform × benchmark
  × mode matrix).

## Decision

1. **Retarget** the campaign to a **safe autonomous reduction of 12,000–19,000 credited
   maintained-Python lines (~5–9% of the 234,211 baseline)** — committed floor 12k, stretch 19k.
2. **Move the big levers out of the autonomous loop.** Deleting whole benchmarks/platforms,
   the `benchbox.experimental` package, deprecated/beta-public surfaces, and codegen/god-class
   rewrites are **product/architecture decisions**, recorded in `_project/decisions/`, keyed to
   `benchmark_registry.yaml` / `platform_registry.py` `support_status` — not campaign iterations.
3. **Add a non-regression guardrail panel** (Guardrail 7): reductions must not worsen per-unit
   cyclomatic complexity, coupling, fast-suite time, or cost-to-add-a-platform. This is a
   guardrail, not a second objective function.
4. **Add a kill criterion:** when the safe reservoir is exhausted, declare maximum-safe-reduction
   and convene human review; do not reach for out-of-scope levers to keep the number moving.

## The three objective questions (answered)

- *Is line reduction the goal or a proxy?* A proxy — and a weak one, given low complexity.
  The real end (maintainability / cost) is better served by matrix reduction via `support_status`.
- *What regressions are unacceptable even if lines drop?* Benchmark semantics, platform
  capability, public API/CLI, result integrity, beta-public contracts
  (`docs/reference/public-contracts.md`), and extensibility (cost-to-add-a-platform).
- *What tradeoffs are explicitly allowed?* Deleting unwired/experimental code and deprecated
  commands; consolidating proven boilerplate. **Not** allowed: relocation-as-removal; lossy
  abstraction of platform capability.

## Options considered and rejected

- **Keep 66% as-is.** Rejected: unreachable without gaming or breaking the product promise;
  re-creates the exact incentive the honest formula was built to remove.
- **Stop the campaign entirely.** Rejected: a real ~5–9% mechanical tail exists and is worth
  capturing safely.
- **Approve full product deletion now to chase a big number.** Deferred: legitimate, but a
  separate leadership decision with its own scope and owner — not folded into the loop.

## Consequences

- The autonomous loop pursues only the mechanical-safe tail; progress is honest and bounded.
- A larger reduction remains available **only** via an explicit, separately-approved
  product-deletion plan (see the feasibility reservoir).
- The 66% debate is now closed with a recorded rationale, so it should not recur.
