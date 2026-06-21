# Cross-surface applicability sweep

**Generated** by `_project/scripts/cross_surface_applicability_sweep.py`. Drills into the dual-surface UNGUARDED benchmarks from the oracle coverage map and detects which ship a DataFrame query `QueryRegistry` (the registry the cross-surface gate builders consume). `supports_dataframe` (the coverage map's signal) is a DataFrame *loading* flag and over-counts candidates; the production query *resolver* under-counts (it misses per-benchmark `<BENCH>_DATAFRAME_QUERIES` registries). Registry detection is the authoritative gate-applicability signal.

**Summary:** 16 dual-surface unguarded candidates — 12 cross-surface gateable (ship a DataFrame query registry), 4 have no DataFrame query surface (need a w2 fallback oracle), 0 blocked.

| Benchmark | Status | SQL queries | DataFrame queries | Raw id overlap | Note |
| --- | --- | --- | --- | --- | --- |
| amplab | gateable-needs-id-mapping | 8 | 8 | 0 | → cross-surface gate after id normalization (w3) |
| clickbench | gateable | 43 | 43 | 43 | → cross-surface gate (w3) |
| datavault | gateable-needs-id-mapping | 22 | 22 | 0 | → cross-surface gate after id normalization (w3) |
| flightdata | gateable | 20 | 20 | 20 | → cross-surface gate (w3) |
| h2odb | gateable | 10 | 10 | 10 | → cross-surface gate (w3) |
| joinorder | gateable | 113 | 113 | 113 | → cross-surface gate (w3) |
| joinorder_synthetic | gateable | 13 | 13 | 13 | → cross-surface gate (w3) |
| metadata_primitives | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |
| nyctaxi | gateable-needs-id-mapping | 25 | 25 | 0 | → cross-surface gate after id normalization (w3) |
| read_primitives | gateable | 157 | 152 | 152 | → cross-surface gate (w3) |
| tpcdi | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |
| tpcds_obt | gateable-needs-id-mapping | 89 | 3 | 0 | → cross-surface gate after id normalization (w3) |
| tpch_skew | gateable-needs-id-mapping | 22 | 22 | 0 | → cross-surface gate after id normalization (w3) |
| transaction_primitives | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |
| tsbs_devops | gateable-needs-id-mapping | 18 | 18 | 0 | → cross-surface gate after id normalization (w3) |
| write_primitives | no-df-query-surface | — | 0 | — | → w2 fallback oracle (no DataFrame query registry) |

## Campaign dispatch

- **Cross-surface gate, ids overlap as-is (w3):** clickbench, flightdata, h2odb, joinorder, joinorder_synthetic, read_primitives.
- **Cross-surface gate, needs id normalization first (w3):** amplab, datavault, nyctaxi, tpcds_obt, tpch_skew, tsbs_devops — a DataFrame query registry exists but its ids differ from the SQL ids by a naming convention (e.g. `1` vs `Q1`); normalize in the builder.
- **w2 fallback oracle** — no DataFrame query registry, so the cross-surface gate cannot reach them; they need a differential second-engine check or a curated expected-results subset: metadata_primitives, tpcdi, transaction_primitives, write_primitives.
