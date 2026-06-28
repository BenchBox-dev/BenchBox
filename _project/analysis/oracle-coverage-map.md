<!-- PROVENANCE
generated: 2026-06-28
content-revision: sha256:fc04c4548a8f38f9
This header is drift-IGNORED by `--check` (see _strip_provenance). content-revision
is a hash of the generated body (markdown + json), NOT a git SHA: a PR-branch SHA is
orphaned by squash-merge, so to verify this artifact, regenerate it with
`make oracle-coverage-map` on develop and confirm the body matches (the drift check
does this). Do not rely on this header for diffs.
-->
# Benchmark correctness-oracle coverage map

**Generated** by `_project/scripts/generate_oracle_coverage_map.py` from the benchmark registry, the expected-results provider registry, and the equivalence-gate registries. Do not edit by hand — run the generator and commit. `tests/unit/test_oracle_coverage_map.py` fails if this drifts.

**What an oracle here means.** A benchmark is listed as *guarded* when an oracle is REGISTERED for it — it is **not** a claim that the oracle is currently green. The distinction matters most for cross-surface gates: only a gate in the enforced `GATES` registry is run as a CI-blocking step (so it is green or CI fails); a gate in `STAGED_GATES` is registered but not run in CI, so its registration proves nothing about correctness. The **Enforced** column reports this *cross-surface* enforcement status: `enforced (CI-blocking)`, `staged (NOT CI-enforced)`, or `—` for any benchmark that is not cross-surface-gated. A `—` therefore says nothing about whether a *non*-cross-surface oracle is enforced: the expected-results (tpch, tpcds) and TPC-Havoc variant oracles are CI-enforced via their own test suites despite showing `—` here.

**Summary:** 23 shipped benchmarks — 9 guarded (oracle registered), 14 UNGUARDED (12 reachable by the cross-surface gate, 2 single-surface needing a fallback oracle). Cross-surface gates: 6 CI-enforced, 0 staged (not CI-enforced).

**Strength + scale disclosure:** a guarded cell is not a uniform guarantee. The **Strength** column says what the oracle proves — `value-level` (full result values compared) vs `cardinality-only` (row counts only) vs `value+cardinality` (both) — and the **Scale** column says at which scale it actually holds. Both are derived from live sources (the provider's stored answers/digests and the equivalence gate's bounded scale), not hand-labelled. No expected-results oracle exists above SF=1 (the loader raises for other scales), so `tpch`/`tpcds` values are unguarded above SF=1 — the tpch **Strength** cell states this inline so the row is self-contained.

**Reference-independence disclosure:** the **Independence** column says whether a guarded cell compares against a reference INDEPENDENT of the system under test, or against ITSELF — orthogonal to Strength (a `value-level` oracle can be either). `self-referential` = compared against a shared spec or a frozen self-snapshot (the cross-surface gates compare a benchmark's DataFrame surface to its OWN SQL surface; the tpch value digest is a frozen benchbox-on-DuckDB snapshot, a regression tripwire, not an authority). `semi-independent` = an external authority on CARDINALITY only (tpch/tpcds row counts come from the published TPC answer sets, but the values are not checked there). `independent` = full values checked against an external authority (no shipped oracle reaches this today). So a green `value-level`/`value+cardinality` cell that reads `self-referential` proves *unchanged from a shared/frozen reference*, NOT *values proven correct against an authority* — do not skip manual inspection on the strength of it. Derived from the oracle kind + digest provenance, not hand-labelled.

| Benchmark | Surfaces | Oracle | Strength | Scale | Independence | Enforced | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ai_primitives | sql | NONE | — | — | — | — | single-surface → needs fallback oracle (w2) |
| amplab | sql+dataframe | cross-surface | value-level | SF=0.1 | self-referential | enforced (CI-blocking) | cross-surface |
| clickbench | sql+dataframe | cross-surface | value-level | SF=0.1 | self-referential | enforced (CI-blocking) | cross-surface |
| coffeeshop | sql+dataframe | cross-surface | value-level | SF=0.1 | self-referential | enforced (CI-blocking) | cross-surface |
| datavault | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| flightdata | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| h2odb | sql+dataframe | cross-surface | value-level | SF=0.01 | self-referential | enforced (CI-blocking) | cross-surface |
| joinorder | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| joinorder_synthetic | sql+dataframe | cross-surface | value-level | SF=0.1 | self-referential | enforced (CI-blocking) | cross-surface |
| metadata_primitives | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| nyctaxi | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| read_primitives | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| ssb | sql+dataframe | cross-surface | value-level | SF=0.1 | self-referential | enforced (CI-blocking) | cross-surface |
| tpcdi | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| tpcds | sql+dataframe | expected-results | cardinality-only | SF=1 | semi-independent | — | expected-results |
| tpcds_obt | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| tpch | sql+dataframe | expected-results | value+cardinality (SF=1 only; values UNGUARDED above SF=1) | SF=1 | self-referential | — | expected-results |
| tpch_skew | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| tpchavoc | sql+dataframe | variant-equivalence | value-level | SF=0.1 | self-referential | — | variant-equivalence, cross-surface-variant |
| transaction_primitives | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| tsbs_devops | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |
| vector_search | sql | NONE | — | — | — | — | single-surface → needs fallback oracle (w2) |
| write_primitives | sql+dataframe | NONE | — | — | — | — | dual-surface → dispatch to cross-surface gate (w1) |

## UNGUARDED benchmarks

These ship with no automated correctness oracle today. Dual-surface ones are dispatched to `benchmark-cross-surface-equivalence-gate` (w1); single-surface ones need a per-benchmark fallback — differential vs a second engine, a small curated expected-results subset, or a documented structural invariant (w2).

> Caveat (w2 oracle choice): write/DML/nondeterministic benchmarks (`write_primitives`, `transaction_primitives`, `metadata_primitives`, `tpcdi`) are listed as dual-surface, but their two surfaces may not be result-comparable; prefer structural-invariant oracles (row counts, post-state assertions) over cross-surface equality for those.

- Dual-surface (cross-surface candidates): datavault, flightdata, joinorder, metadata_primitives, nyctaxi, read_primitives, tpcdi, tpcds_obt, tpch_skew, transaction_primitives, tsbs_devops, write_primitives
- Single-surface (fallback-oracle needed): ai_primitives, vector_search
