<!-- PROVENANCE
generated: 2026-06-23
revision: 049d1c5abd154b3168dae6663176a63916615d67
This header is drift-IGNORED by `--check` (see _strip_provenance); it records when
this generated artifact was last written so a reviewer can tell if it predates
current develop. Do not rely on it for diffs.
-->
# Benchmark correctness-oracle coverage map

**Generated** by `_project/scripts/generate_oracle_coverage_map.py` from the benchmark registry, the expected-results provider registry, and the equivalence-gate registries. Do not edit by hand — run the generator and commit. `tests/unit/test_oracle_coverage_map.py` fails if this drifts.

**Summary:** 23 shipped benchmarks — 8 guarded, 15 UNGUARDED (13 reachable by the cross-surface gate, 2 single-surface needing a fallback oracle).

**Strength + scale disclosure:** a guarded cell is not a uniform guarantee. The **Strength** column says what the oracle proves — `value-level` (full result values compared) vs `cardinality-only` (row counts only) vs `value+cardinality` (both) — and the **Scale** column says at which scale it actually holds. Both are derived from live sources (the provider's stored answers/digests and the equivalence gate's bounded scale), not hand-labelled. No expected-results oracle exists above SF=1 (the loader raises for other scales), so `tpch`/`tpcds` values are unguarded above SF=1.

| Benchmark | Surfaces | Oracle | Strength | Scale | Notes |
| --- | --- | --- | --- | --- | --- |
| ai_primitives | sql | NONE | — | — | single-surface → needs fallback oracle (w2) |
| amplab | sql+dataframe | cross-surface | value-level | SF=0.1 | cross-surface |
| clickbench | sql+dataframe | cross-surface | value-level | SF=0.1 | cross-surface |
| coffeeshop | sql+dataframe | cross-surface | value-level | SF=0.1 | cross-surface |
| datavault | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| flightdata | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| h2odb | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| joinorder | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| joinorder_synthetic | sql+dataframe | cross-surface | value-level | SF=0.1 | cross-surface |
| metadata_primitives | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| nyctaxi | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| read_primitives | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| ssb | sql+dataframe | cross-surface | value-level | SF=0.1 | cross-surface |
| tpcdi | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| tpcds | sql+dataframe | expected-results | cardinality-only | SF=1 | expected-results |
| tpcds_obt | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| tpch | sql+dataframe | expected-results | value+cardinality | SF=1 | expected-results |
| tpch_skew | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| tpchavoc | sql+dataframe | variant-equivalence | value-level | SF=0.1 | variant-equivalence, cross-surface-variant |
| transaction_primitives | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| tsbs_devops | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| vector_search | sql | NONE | — | — | single-surface → needs fallback oracle (w2) |
| write_primitives | sql+dataframe | NONE | — | — | dual-surface → dispatch to cross-surface gate (w1) |

## UNGUARDED benchmarks

These ship with no automated correctness oracle today. Dual-surface ones are dispatched to `benchmark-cross-surface-equivalence-gate` (w1); single-surface ones need a per-benchmark fallback — differential vs a second engine, a small curated expected-results subset, or a documented structural invariant (w2).

> Caveat (w2 oracle choice): write/DML/nondeterministic benchmarks (`write_primitives`, `transaction_primitives`, `metadata_primitives`, `tpcdi`) are listed as dual-surface, but their two surfaces may not be result-comparable; prefer structural-invariant oracles (row counts, post-state assertions) over cross-surface equality for those.

- Dual-surface (cross-surface candidates): datavault, flightdata, h2odb, joinorder, metadata_primitives, nyctaxi, read_primitives, tpcdi, tpcds_obt, tpch_skew, transaction_primitives, tsbs_devops, write_primitives
- Single-surface (fallback-oracle needed): ai_primitives, vector_search
