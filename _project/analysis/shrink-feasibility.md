# Shrink Campaign Feasibility Analysis

**Date:** 2026-05-24
**Question:** Is the "reduce maintained Python in `benchbox/` by 66%" target honestly
reachable, or only via metric-gaming / product-surface deletion?
**Answer:** Not reachable honestly. Retarget to a safe autonomous ~5–9%. See
`_project/decisions/shrink-objective.md` for the decision; this file is the evidence.

## Method

Two **independent** stratified hand-review passes over six surfaces (not static-tool
counts), each producing five confidence bands per surface and a campaign roll-up:

- **Review A** — six parallel hand-review agents, one per surface.
- **Review B** — independent pass anchored on `benchmark_registry.yaml` /
  `platform_registry.py` `support_status`, `pyproject.toml`, and `docs/reference/public-contracts.md`.

Both reached the **same verdict**. When two blind analyses converge, confidence is high.

Rules enforced in both: "removable" = deletable/consolidatable without losing benchmark
semantics, platform capability, public API/CLI, or result integrity; Python→YAML/data
relocation is **gaming, not removal**; structural similarity ≠ removable.

## Per-surface ceilings (consensus)

| Surface | cloc | Honest ceiling | Note |
|---|--:|---|---|
| Platform adapters | ~52k | ~19% | already refactored to 9 mixins (`docs/development/adapter-refactor-map.md`); ~90% load-bearing |
| Benchmark families | ~63k | ~32% incl. deletions | mass is semantics; experimental families ~18k are the deletion lever |
| DataFrame query layers | ~25–40k | ~9–10% | heavy files are query *semantics*; further YAML = gaming (0 credit) |
| SQL compat + query plans | ~6.4k | ~19–30% | DDL boilerplate + parser consolidation; plan-capture is wired |
| CLI + result plumbing | ~28k | ~15% | deprecated commands + run-branch config; result schema is a public contract |
| Reporting/utils + sweep | ~19k+ | ~12k lines | `benchbox.experimental` is the lever; MCP/viz/cost/expected_results are wired |

## Campaign-wide confidence bands (consensus, vs 234,211 baseline; deliberately imprecise)

| Band | Range | Meaning |
|---|---|---|
| Conservative-safe | ~1–3% (5–11k) | mechanical dedup, dead code, deprecated commands |
| **Likely-safe (autonomous + tests)** | **~5–9% (12–22k)** | realistic autonomous-loop target → the new campaign band |
| Aggressive-plausible | ~11–20% (25–45k) | major refactors preserving product surface |
| Only with full product + architecture deletion | ~30–45% cumulative | delete experimental platforms/benchmarks/package + codegen rewrites |
| Unsafe / gaming-only | remaining ~40–55% | relocation, semantics-hiding, or cutting beta/stable capability |

Baseline note: the reference denominator remains 234,211. On this branch,
`cloc --include-lang=Python benchbox/` reports 206,854 Python code lines.
Raw `cloc` movement before ledger adoption is not credited unless a merged ledger
fragment records credited reduction, so credited accounting starts at ~0.

## Why the codebase resists line-cutting

Radon average cyclomatic complexity is **"A" (3.77)** — the code is *simple per unit,
broad in surface*. The cost driver is the matrix (≈14 platform groups × ~18 benchmarks
× SQL+DataFrame modes), not per-function complexity. The honest maintainability lever is
**shrinking the matrix** (a product decision, keyed to `support_status`), not compressing code.

## The product-deletion reservoir (the only honest path to a larger number)

Requires a leadership/product decision — out of scope for the autonomous loop:

| Lever (by `support_status`) | ~Lines |
|---|--:|
| `benchbox.experimental` package (shipped-but-unsupported, `pyproject.toml`) | ~5.4k |
| Experimental benchmarks: tpchavoc, tpcds_obt, datavault, ai_primitives, tpch_skew, joinorder_synthetic | ~18k |
| Experimental platforms: CedarDB, pg-duckdb/mooncake, Glue, EMR, Dataproc, Fabric Spark, Snowpark Connect, LakeSail, Velox, Quanton, Modin, cuDF | ~6.9k |
| Deprecated CLI commands + abandoned analytics tiers (cost optimizer/tco, monitoring profiler) | ~4–5k |
| **Total** | **~34–37k (~15–17%)** |

Even this, plus aggressive refactoring, tops out near ~30–45% — confirming 66% needs
gaming or breaking BenchBox's benchmark/platform promise.

## Verdict against decision thresholds

- likely-safe ≥ 66% → continue: **NO** (~5–9%).
- likely-safe 45–65% → reset/require deletions: **NO**.
- likely-safe < 45% → **stop the autonomous 66% campaign; reframe**: **YES** (even the absolute ceiling ~30–45% < 66%).
- >half of any reduction depends on human product/architecture decisions → **narrow the loop to the mechanical tail**: **YES**.
