# Cross-surface applicability sweep

**Generated** by `_project/scripts/cross_surface_applicability_sweep.py`. Drills into the dual-surface unguarded-or-staged benchmarks from the oracle coverage map (staged gates are registered but NOT CI-enforced) and detects which ship a DataFrame query `QueryRegistry` (the registry the cross-surface gate builders consume). `supports_dataframe` (the coverage map's signal) is a DataFrame *loading* flag and over-counts candidates; the production query *resolver* under-counts (it misses per-benchmark `<BENCH>_DATAFRAME_QUERIES` registries). Registry detection is the authoritative gate-applicability signal.

**Gateable means VERIFIED, not merely registered.** A benchmark is counted as `gateable` only when its DataFrame query ids overlap the SQL query ids verbatim — a confirmed SQL<->DataFrame correspondence the gate can compare. A benchmark whose registry has ZERO verbatim id overlap is `candidate-unverified`, NOT gateable: wiring a gate would require *guessing* which DataFrame query answers which SQL query, and the campaign's own TODO warns "do NOT guess". These need an independent, per-benchmark id mapping confirmed first (and some, like `tpcds_obt` at 3 DataFrame vs ~89 SQL queries, may never be a clean correspondence).

**Gateable also means CHEAP, not merely overlapping.** A benchmark that rejects the bounded SF=0.01 cell or fetches a canonical dataset via `data_manifest.toml` is `not-cheaply-gateable`, NOT gateable, no matter its id overlap: wiring it would drag a full dataset fetch into routine PRs. The table reason names the scale/provenance evidence.

**Summary:** 11 dual-surface candidates (unguarded + staged, registered but not CI-enforced) — 1 cross-surface gateable (verified verbatim id overlap at a bounded scale), 4 candidate-unverified (registry exists but ZERO verified id overlap — needs a confirmed id mapping first), 2 not-cheaply-gateable (rejects a bounded scale or needs a canonical fetch), 4 have no DataFrame query surface (need a w2 fallback oracle), 0 blocked.

| Benchmark | Status | SQL queries | DataFrame queries | Raw id overlap | Note |
| --- | --- | --- | --- | --- | --- |
| datavault | candidate-unverified | 22 | 22 | 0 | → confirm an independent SQL↔DataFrame id mapping before gating (do NOT guess) [staged, not CI-enforced] |
| flightdata | gateable | 20 | 20 | 20 | → cross-surface gate (w3) [staged, not CI-enforced] |
| joinorder | not-cheaply-gateable | 113 | 113 | 113 | → NOT a routine-PR gate: rejects bounded scale SF=0.01 (ValueError: joinorder now uses canonical IMDb 2013 data and accepts only scale_factor=1.0; use joinorder_synthetic for scaled synthetic smoke-test data.); requires SF=1.0; canonical manifest fetch (data_manifest.toml); use joinorder_synthetic (already CI-enforced) for scaled smoke-test data |
| metadata_primitives | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |
| nyctaxi | candidate-unverified | 25 | 25 | 0 | → confirm an independent SQL↔DataFrame id mapping before gating (do NOT guess) |
| tpcdi | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |
| tpcds_obt | not-cheaply-gateable | 89 | 17 | 0 | → NOT a routine-PR gate: rejects bounded scale SF=0.01 (ValueError: TPC-DS-OBT requires scale_factor >= 1.0 to align with TPC-DS generation.); requires SF=1.0 |
| tpch_skew | candidate-unverified | 22 | 22 | 0 | → confirm an independent SQL↔DataFrame id mapping before gating (do NOT guess) |
| transaction_primitives | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |
| tsbs_devops | candidate-unverified | 18 | 18 | 0 | → confirm an independent SQL↔DataFrame id mapping before gating (do NOT guess) |
| write_primitives | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |

## Campaign dispatch

- **Cross-surface gate, ids overlap as-is (w3):** flightdata.
- **Candidate-unverified (NOT gateable yet):** datavault, nyctaxi, tpch_skew, tsbs_devops — a DataFrame query registry exists but ZERO ids overlap the SQL ids verbatim, so there is no verified query correspondence. Each needs an independent, per-benchmark id mapping confirmed (the campaign TODO says "do NOT guess") before a gate can be wired; do not count these as coverage.
- **Not-cheaply-gateable (NOT a routine-PR gate):** joinorder, tpcds_obt — rejects the bounded SF=0.01 cell or needs a canonical manifest fetch; do not wire as a routine-PR gate.
- **w2 fallback oracle** — no DataFrame query registry, so the cross-surface gate cannot reach them; they need a differential second-engine check or a curated expected-results subset: metadata_primitives, tpcdi, transaction_primitives, write_primitives.
