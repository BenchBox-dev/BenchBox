# Cross-surface applicability sweep

**Generated** by `_project/scripts/cross_surface_applicability_sweep.py`. Drills into the dual-surface UNGUARDED benchmarks from the oracle coverage map and detects which ship a DataFrame query `QueryRegistry` (the registry the cross-surface gate builders consume). `supports_dataframe` (the coverage map's signal) is a DataFrame *loading* flag and over-counts candidates; the production query *resolver* under-counts (it misses per-benchmark `<BENCH>_DATAFRAME_QUERIES` registries). Registry detection is the authoritative gate-applicability signal.

**Gateable means VERIFIED, not merely registered.** A benchmark is counted as `gateable` only when its DataFrame query ids overlap the SQL query ids verbatim — a confirmed SQL<->DataFrame correspondence the gate can compare. A benchmark whose registry has ZERO verbatim id overlap is `candidate-unverified`, NOT gateable: wiring a gate would require *guessing* which DataFrame query answers which SQL query, and the campaign's own TODO warns "do NOT guess". These need an independent, per-benchmark id mapping confirmed first (and some, like `tpcds_obt` at 3 DataFrame vs ~89 SQL queries, may never be a clean correspondence).

**Summary:** 13 dual-surface unguarded candidates — 4 cross-surface gateable (verified verbatim id overlap), 5 candidate-unverified (registry exists but ZERO verified id overlap — needs a confirmed id mapping first), 4 have no DataFrame query surface (need a w2 fallback oracle), 0 blocked.

| Benchmark | Status | SQL queries | DataFrame queries | Raw id overlap | Note |
| --- | --- | --- | --- | --- | --- |
| datavault | candidate-unverified | 22 | 22 | 0 | → confirm an independent SQL↔DataFrame id mapping before gating (do NOT guess) |
| flightdata | gateable | 20 | 20 | 20 | → cross-surface gate (w3) |
| h2odb | gateable | 10 | 10 | 10 | → cross-surface gate (w3) |
| joinorder | gateable | 113 | 113 | 113 | → cross-surface gate (w3) |
| metadata_primitives | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |
| nyctaxi | candidate-unverified | 25 | 25 | 0 | → confirm an independent SQL↔DataFrame id mapping before gating (do NOT guess) |
| read_primitives | gateable | 157 | 152 | 152 | → cross-surface gate (w3) |
| tpcdi | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |
| tpcds_obt | candidate-unverified | 89 | 3 | 0 | → confirm an independent SQL↔DataFrame id mapping before gating (do NOT guess) |
| tpch_skew | candidate-unverified | 22 | 22 | 0 | → confirm an independent SQL↔DataFrame id mapping before gating (do NOT guess) |
| transaction_primitives | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |
| tsbs_devops | candidate-unverified | 18 | 18 | 0 | → confirm an independent SQL↔DataFrame id mapping before gating (do NOT guess) |
| write_primitives | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |

## Campaign dispatch

- **Cross-surface gate, ids overlap as-is (w3):** flightdata, h2odb, joinorder, read_primitives.
- **Candidate-unverified (NOT gateable yet):** datavault, nyctaxi, tpcds_obt, tpch_skew, tsbs_devops — a DataFrame query registry exists but ZERO ids overlap the SQL ids verbatim, so there is no verified query correspondence. Each needs an independent, per-benchmark id mapping confirmed (the campaign TODO says "do NOT guess") before a gate can be wired; do not count these as coverage.
- **w2 fallback oracle** — no DataFrame query registry, so the cross-surface gate cannot reach them; they need a differential second-engine check or a curated expected-results subset: metadata_primitives, tpcdi, transaction_primitives, write_primitives.
