---
id: 2026-05-05-154307-uat-tpcds-obt-reuse-graph-asymmetry
date: 2026-05-05
status: open
finding_kind: assumption
review_context: "principal-engineer review of UAT framework PR #205 (post-merge simplification audit)"
related_paths:
  - tests/uat/cleanup.py
  - benchbox/core/tpcds_obt/benchmark.py
  - benchbox/core/read_primitives/benchmark.py
  - benchbox/core/ai_primitives/benchmark.py
  - benchbox/write_primitives.py
  - benchbox/core/transactional/benchmark_base.py
suggested_sweep: "verify the tpcds_obt → tpcds reuse claim is actually true in production data flow. If true, surface it via a get_data_source_benchmark() method on TPCDSOBTBenchmark to match the pattern; if false, fix the cleanup graph."
todo_id: uat-framework-review-followups
---

# `tpcds_obt → tpcds` is in cleanup's reuse graph but no `get_data_source_benchmark()` declares it

## Finding
`tests/uat/cleanup.py:23-32` declares `SOURCE_REUSE_GRAPH = { "tpch": (...),
"tpcds": ("tpcds", "tpcds_obt") }` — a hand-maintained map naming
benchmarks that share generated data with a "source" benchmark.

The same relationship is also encoded in production code, but as the
reverse direction: each benchmark instance carries
`get_data_source_benchmark() -> Optional[str]` returning the upstream
source it reuses.

- `read_primitives` returns `"tpch"` (`benchbox/core/read_primitives/benchmark.py:92-94`).
- `ai_primitives` returns `"tpch"` (`benchbox/core/ai_primitives/benchmark.py:168-170`).
- `write_primitives` and transactional benchmarks return `"tpch"` via the
  base class (`benchbox/write_primitives.py:65-71`,
  `benchbox/core/transactional/benchmark_base.py:77`).

These four cover the `tpch` consumers in cleanup's graph. **But the
`tpcds_obt → tpcds` claim has no symmetric production declaration** that
I could find. `benchbox/core/tpcds_obt/benchmark.py:123` says in a
docstring "Source data: Uses standard TPC-DS data" and the file imports
`TPCDSDataGenerator` (line 12), but there is no `get_data_source_benchmark`
method overriding the default.

Two possibilities:
- The reuse claim is correct but undeclared. Production cleanup logic
  consulting `get_data_source_benchmark()` would not know that
  `tpcds_obt` reuses `tpcds` data; UAT cleanup would. Asymmetric
  authority.
- The reuse claim is incorrect. UAT cleanup over-preserves `tpcds` data
  for an unrelated benchmark.

I do not know which without inspecting the actual data layout for
tpcds_obt — left as a sweep step.

## Why this matters
Cleanup behaviour during a UAT sweep affects subsequent cells. If the
reuse claim is wrong, a sweep that runs `tpcds → tpcds_obt → tpch` would
preserve `tpcds` data while running tpcds_obt (correct cleanup deferral),
but the `tpcds_obt` benchmark itself may regenerate or expect different
data. If the claim is right, production code's lack of declaration means
any future cleanup utility built on the production registry pattern
would miss the relationship.

## Suggested next steps
- [ ] Read `benchbox/core/tpcds_obt/benchmark.py` end-to-end and confirm
      whether the data files written by `TPCDSDataGenerator` are
      consumed by tpcds_obt or whether tpcds_obt regenerates.
- [ ] If the reuse is real, override `get_data_source_benchmark()` on
      `TPCDSOBTBenchmark` to return `"tpcds"`. This matches the pattern
      used by read/write/ai primitives.
- [ ] Once production declares the relationship, replace
      `cleanup.SOURCE_REUSE_GRAPH` with a registry-derived
      `defaultdict(list)` built at import time.
- [ ] If the reuse is NOT real, remove `tpcds_obt` from
      `SOURCE_REUSE_GRAPH["tpcds"]` and document the cleanup behaviour
      change.
