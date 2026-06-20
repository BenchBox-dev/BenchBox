# Benchmark correctness-oracle coverage map

**Generated** by `_project/scripts/generate_oracle_coverage_map.py` from the benchmark registry, the expected-results provider registry, and the equivalence-gate registries. Do not edit by hand — run the generator and commit. `tests/unit/test_oracle_coverage_map.py` fails if this drifts.

**Summary:** 23 shipped benchmarks — 4 guarded, 19 UNGUARDED (17 reachable by the cross-surface gate, 2 single-surface needing a fallback oracle).

| Benchmark | Surfaces | Oracle | Notes |
| --- | --- | --- | --- |
| ai_primitives | sql | NONE | single-surface → needs fallback oracle (w2) |
| amplab | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| clickbench | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| coffeeshop | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| datavault | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| flightdata | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| h2odb | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| joinorder | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| joinorder_synthetic | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| metadata_primitives | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| nyctaxi | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| read_primitives | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| ssb | sql+dataframe | cross-surface | cross-surface |
| tpcdi | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| tpcds | sql+dataframe | expected-results | expected-results |
| tpcds_obt | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| tpch | sql+dataframe | expected-results | expected-results |
| tpch_skew | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| tpchavoc | sql+dataframe | variant-equivalence | variant-equivalence, cross-surface-variant |
| transaction_primitives | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| tsbs_devops | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |
| vector_search | sql | NONE | single-surface → needs fallback oracle (w2) |
| write_primitives | sql+dataframe | NONE | dual-surface → dispatch to cross-surface gate (w1) |

## UNGUARDED benchmarks

These ship with no automated correctness oracle today. Dual-surface ones are dispatched to `benchmark-cross-surface-equivalence-gate` (w1); single-surface ones need a per-benchmark fallback — differential vs a second engine, a small curated expected-results subset, or a documented structural invariant (w2).

> Caveat (w2 oracle choice): write/DML/nondeterministic benchmarks (`write_primitives`, `transaction_primitives`, `metadata_primitives`, `tpcdi`) are listed as dual-surface, but their two surfaces may not be result-comparable; prefer structural-invariant oracles (row counts, post-state assertions) over cross-surface equality for those.

- Dual-surface (cross-surface candidates): amplab, clickbench, coffeeshop, datavault, flightdata, h2odb, joinorder, joinorder_synthetic, metadata_primitives, nyctaxi, read_primitives, tpcdi, tpcds_obt, tpch_skew, transaction_primitives, tsbs_devops, write_primitives
- Single-surface (fallback-oracle needed): ai_primitives, vector_search
