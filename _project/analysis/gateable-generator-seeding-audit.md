# Gateable-benchmark generator seeding audit

Wiring a cross-surface equivalence gate for a benchmark whose generator is
**unseeded** produces a *flaky* gate: each run generates different data, so
top-N/tie-sensitive queries flip in and out of divergence (this is exactly what
happened with ClickBench — see `clickbench-cross-surface-divergences.md`). Before
wiring more gates, this audit records the data-determinism status of every
cross-surface-gateable benchmark (from `cross-surface-applicability.md`).

Method: inspect each benchmark's `generator.py` for RNG use (`random.*`, numpy)
and for a seed (`random.seed`, `default_rng`, ...). For benchmarks with no
`generator.py`, the data comes from an external/derived source whose determinism
depends on that source.

| Benchmark | RNG | Seeded? | Gate determinism |
| --- | --- | --- | --- |
| ssb | random | ✅ `random.seed(42)` | deterministic (gated) |
| coffeeshop | none (static seed-data files) | n/a | deterministic (gated) |
| clickbench | random | ✅ seeded (this campaign) | deterministic (staged gate) |
| amplab | random | ✅ seeded | deterministic |
| h2odb | random | ✅ seeded | deterministic |
| tpch_skew | random | ✅ seeded | deterministic |
| tsbs_devops | random | ✅ seeded | deterministic |
| joinorder_synthetic | random | ✅ **seeded in this change** | deterministic (verified) |
| read_primitives | none | n/a | deterministic |
| datavault | (no generator.py) | — | verify source before gating |
| flightdata | (no generator.py — real data) | — | verify source before gating |
| joinorder | (no generator.py — canonical IMDb) | — | likely deterministic (fixed source) |
| nyctaxi | (no generator.py — real data) | — | verify source before gating |
| tpcds_obt | (no generator.py — derived from TPC-DS) | — | inherits TPC-DS determinism |

## Fix applied here

`joinorder_synthetic` used `random.*` (synthetic titles/names/ids) with **no
seed** — it would have produced a flaky gate. Added `random.seed(42)` at the start
of `_generate_data_local` (mirrors SSB/ClickBench). Verified: two generations now
produce **byte-identical data tables** (the residual file-byte difference is only
the manifest's embedded timestamp, which the gate does not read).

## Notes / follow-ups

- **Manifest timestamps**: generated `manifest`/`*.json` files embed a generation
  timestamp, so raw-file-byte comparisons are not a reliable determinism signal —
  compare *data tables* (the gate reads those, not the manifest).
- The five external/derived-data benchmarks (datavault, flightdata, joinorder,
  nyctaxi, tpcds_obt) have no synthetic RNG; their gate determinism depends on a
  fixed data source. Confirm the bounded data source is stable when wiring each.
- Next gate to wire is `joinorder_synthetic` (now deterministic) or another
  id-overlapping benchmark (flightdata/h2odb/read_primitives), per
  `cross-surface-applicability.md`.
