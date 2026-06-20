# Cross-surface applicability sweep

**Generated** by `_project/scripts/cross_surface_applicability_sweep.py`. Drills into the dual-surface UNGUARDED benchmarks from the oracle coverage map and asks the production DataFrame resolver how many DataFrame *queries* each actually ships. `supports_dataframe` (the coverage map's signal) is a DataFrame *loading* flag and over-counts cross-surface candidates.

**Summary:** 17 dual-surface unguarded candidates — 2 GATEABLE (ship DataFrame queries), 15 have no DataFrame query surface (need a w2 fallback oracle), 0 blocked.

| Benchmark | Status | SQL queries | DataFrame queries | Note |
| --- | --- | --- | --- | --- |
| amplab | no-df-query-surface | 8 | 0 | → w2 fallback oracle |
| clickbench | gateable | 43 | 43 | → cross-surface gate (w3) |
| coffeeshop | no-df-query-surface | 11 | 0 | → w2 fallback oracle |
| datavault | no-df-query-surface | 22 | 0 | → w2 fallback oracle |
| flightdata | no-df-query-surface | 20 | 0 | → w2 fallback oracle |
| h2odb | no-df-query-surface | 10 | 0 | → w2 fallback oracle |
| joinorder | no-df-query-surface | 113 | 0 | → w2 fallback oracle |
| joinorder_synthetic | gateable | 13 | 13 | → cross-surface gate (w3) |
| metadata_primitives | no-df-query-surface | 62 | 0 | → w2 fallback oracle |
| nyctaxi | no-df-query-surface | 25 | 0 | → w2 fallback oracle |
| read_primitives | no-df-query-surface | 157 | 0 | → w2 fallback oracle |
| tpcdi | no-df-query-surface | 38 | 0 | → w2 fallback oracle |
| tpcds_obt | no-df-query-surface | 89 | 0 | → w2 fallback oracle |
| tpch_skew | no-df-query-surface | 22 | 0 | → w2 fallback oracle |
| transaction_primitives | no-df-query-surface | 23 | 0 | → w2 fallback oracle |
| tsbs_devops | no-df-query-surface | 18 | 0 | → w2 fallback oracle |
| write_primitives | no-df-query-surface | 109 | 0 | → w2 fallback oracle |

## Campaign dispatch

- **Cross-surface gate (w3)** — ships DataFrame queries, 1:1 with SQL: clickbench, joinorder_synthetic. These need a load-faithful per-benchmark builder (see the SSB builder in `benchbox.core.equivalence.cross_surface`) before the gate can enumerate real divergences; a generic build is not load-faithful.
- **w2 fallback oracle** — no comparable DataFrame query surface, so the cross-surface gate cannot reach them; they need a differential second-engine check or a curated expected-results subset: amplab, coffeeshop, datavault, flightdata, h2odb, joinorder, metadata_primitives, nyctaxi, read_primitives, tpcdi, tpcds_obt, tpch_skew, transaction_primitives, tsbs_devops, write_primitives.
