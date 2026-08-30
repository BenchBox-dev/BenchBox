# Plan: Optimal Tuning Corpus for Locally Runnable Platforms

**Author:** Muse Code (Muse Spark) — takeover from `agy` conversation `a344e6e2-918f-4808-b058-0f15760445dc`
**Date:** 2026-08-29
**Status:** Executed with a host-limited validated subset; see §11 for evidence and blocked cells
**Related:** `results-data/REGENERATION.md` (tuned purge 2026-07-16, #1176), `results-data/CORPUS_NOTES.md` (trust cut 2026-08-23), `_project/planning/plan-repopulate-results-explorer-corpus-sf1.md` (untuned SF1 repopulation, now 151 bundles / 24 cohorts on PR #1945)

## 1. Goal and Non-Goal

**Goal:** Create a *tuned* counterpart to the untuned baseline corpus that is *optimal* — every `(platform, benchmark, scale)` in it must have a credible expectation that `--tuning tuned` will change the physical plan and measurably help the workload. No filler.

**Non-goals:**
- Do not repopulate filler `tuned` rows where the template is `basic_constraints` (no-op) or where the platform renders the tuning type as `none` (preview-only, never applied at execution).
- Do not run SF0.01 tuned — data too small to amortize layout cost; compare tuned vs. notuning at SF1/SF10 where I/O and sort dominate.
- Do not re-add the 325 `tuned` bundles removed 2026-07-16; those were physically untuned due to the direct-CLI forwarding bug (see `tests/unit/platforms/test_tuning_config_forwarding.py`).

## 2. Tuning-Helpfulness Criteria (the filter)

A `(platform, benchmark, scale)` is *in* the tuning corpus iff **all** of these hold:

1. **Template exists and is not basic-constraints.** `benchbox tuning show tuned --platform <p> --benchmark <b>` resolves to a `tuned_template` (rank 2) per `benchbox/core/tuning/coverage.yaml`, not `basic_constraints` (rank 1). File must live at `examples/tunings/<platform>/<benchmark>_tuned.yaml` or `benchbox/core/tuning/templates/<platform>/<benchmark>_tuned.yaml` (parity-checked by `test_tuning_resolution.py`).
2. **Capability is rendered, not `none`.** `benchbox/core/tuning/capability_registry.py:PLATFORM_TUNING_CAPABILITIES[<platform>][<TuningType>].rendered_via != "none"` for at least one table-layout type (partitioning/clustering/distribution/sorting or z_ordering/liquid_clustering). See DuckDB `post_load: duckdb_ctas_sort` vs. `none: duckdb_copy_to_hint_only`; ClickHouse `partitioning: none` is a documented gap.
3. **Workload benefits.** Benchmark's tables have columns that appear in the TPC logical profile (`benchbox/core/tuning/profiles/tpc.yaml`) with query evidence at the target scale. E.g., TPC-H `lineitem.l_shipdate`, `orders.o_orderdate`, TPC-DS `store_sales.ss_sold_date_sk`; the profile's `accepted baseline columns` vs. `low-evidence candidates` determines whether a column is worth sorting/partitioning.
4. **Scale large enough.** SF1 (1 GB) minimum; SF10 preferred where the platform can load it within the 1200s cell budget. SF0.01 (10 MB) and SF0.1 (100 MB) are excluded for tuned — the CTAS reorder and constraint cost dominates, and prior UAT showed no measurable win at those scales.
5. **Platform locally runnable and not pruned at SF1.** Per `tests/uat/compatibility.py:_RELEASE_GATE_RUNTIME_ENVELOPES` and the SF1 mandate table in the SF1 repopulation plan: DataFusion `datavault` SF1 (OOM at 16 GiB), SQLite `tpcds`/`tpcds_obt` SF1 (1391s load), and all Docker OLTP at SF1 are pruned — do not schedule tuned there either.

If any criterion fails, the cell is **out**. This is why the plan is small by design.

## 3. Locally Runnable Inventory (what *could* run)

From `uv run -- benchbox platforms check` on this host (Apple Silicon, mocker present, no live cloud creds):

| Platform key | Tier | Ready | Tuning template present? | Rendered via (capability_registry) |
|---|---|---|---|---|
| `duckdb` | 1 Native SQL | ✅ Ready (1.3.2) | ✅ 9 templates (`duckdb/tpch_tuned.yaml`, `tpcds_tuned.yaml`, `ssb_tuned.yaml`, `tpchavoc_tuned.yaml`, `amplab_tuned.yaml`, `h2odb_tuned.yaml`, `clickbench_tuned.yaml`, `read_primitives_tuned.yaml`, `joinorder_tuned.yaml`) | `sorting: post_load:duckdb_ctas_sort` (real), `partitioning: none` (gap), constraints: `ddl:inline_column_constraint` |
| `databricks` (alias `spark`) | 1 Native SQL (Spark) | ✅ Ready (Spark 3.5) | ✅ 5 templates (`databricks/tpch_tuned.yaml`, `tpcds_tuned.yaml`, `ssb_tuned.yaml`, `tpchavoc_tuned.yaml`, `read_primitives_tuned.yaml` + `*_liquid_tuned.yaml` variants) | `z_ordering/liquid_clustering: ddl` or `post_load`, `sorting/clustering/distribution` via Databricks `DATABRICKS` mapping |
| `polars` / `pandas` / `pyspark` | 2 DataFrame | ✅ Ready (Polars 1.3, Pandas 2.3, PySpark 3.5) | ⚠️ No auto-discovery; use explicit optimized templates. The fixed sweep uses `polars_optimized.yaml` for Polars and `pandas_optimized.yaml` for Pandas and PySpark until a dedicated PySpark profile exists. Rendered via DataFrame write manager (Polars/Pandas/PySpark only; `dask-df`/`datafusion-df`/`modin-df` have `none` per `compatibility.py:_DATAFRAME_WRITE_MANAGER_UNSUPPORTED`) | `sorting/clustering` via DataFrame manager |
| `datafusion` | 1 Native SQL | ✅ Ready (53.0) | ❌ No `datafusion/<benchmark>_tuned.yaml` → falls back to `basic_constraints` | `sorting: none` for DataFusion (no CTAS sort at execution; preview-only) |
| `sqlite` | 1 Native SQL | ✅ Ready (3.53) | ❌ No `sqlite/<benchmark>_tuned.yaml` | Constraints only (`ddl`), no layout tuning; layout types render as `none` |
| `clickhouse-local` (`chdb`) | 1 Native SQL | ✅ Ready | ❌ No `clickhouse/<benchmark>_tuned.yaml` | `partitioning: ddl:PARTITION_BY` exists in registry but no shipped template → would be `basic_constraints` |
| `dask-df`, `datafusion-df`, `modin-df` | 2 DataFrame | ✅/❌ (Dask Ready, Modin missing) | ❌ `write_manager: none` per `compatibility.py:92` | `none` |
| `ducklake`, `motherduck` | 1 Native SQL (extensions) | ✅ Ready | ❌ No tuned templates | `none` |

**Conclusion for tuning corpus:** Only `duckdb`, `spark` (via `databricks` alias), and `polars`/`pandas`/`pyspark` with explicit DataFrame optimized templates satisfy criteria 1–2. All others fail criterion 1 (no `tuned_template`) and are **excluded entirely** from the tuning corpus — staging them as `tuned` would be indistinguishable from `notuning` and would pollute the `tuning_mode` facet.

## 4. Optimal Tuning Matrix (only where tuning helps)

Scales: **SF1 (1 GB) mandatory**, **SF10 (10 GB) where the platform can load it within 1200s**. SF0.01/SF0.1 intentionally omitted for tuned (baseline corpus already covers them untuned for scaling curves).

| # | Benchmark | Scale | Platform | Template (resolved) | Why tuning helps (workload + mechanism) | Pruning note |
|---|---|---|---|---|---:|---|
| 1 | `tpch` | 1.0 | `duckdb` | `duckdb/tpch_tuned.yaml` | TPC-H `lineitem` (6M rows at SF1) sorted on `l_shipdate`/`l_orderkey`; DuckDB `post_load` CTAS reorder makes Q1, Q6, Q12 range scans sequential. Profile has accepted baseline columns at SF1. | None |
| 2 | `tpch` | 10.0 | `duckdb` | `duckdb/tpch_tuned.yaml` | Same as SF1, amplified at 10 GB (60M rows); sort cost amortized, constraint-enabled optimizations (PK/FK) help optimizer at scale. | Host has 64 GiB; DuckDB SF10 tpch is within budget (prior SF10 runs exist) |
| 3 | `tpch` | 1.0 | `spark` (`databricks`) | `databricks/tpch_tuned.yaml` (Z-ORDER) | Spark shuffles avoid sort at query; Z-ORDER on `l_shipdate`/`o_orderdate` colocates relevant data. Liquid is a follow-up variant, not part of this fixed 22-cell sweep. | `spark` is alias to `databricks` per `PLATFORM_ALIASES` |
| 4 | `tpch` | 10.0 | `spark` | `databricks/tpch_tuned.yaml` (Z-ORDER) | Same, at 10 GB where Spark benefits most; prior SF10 Spark tpch runs exist in `results-data/bundles/tpcds_sf10_spark*` lineage, tpch SF10 Spark is similar envelope | |
| 5 | `tpcds` | 1.0 | `duckdb` | `duckdb/tpcds_tuned.yaml` | TPC-DS 99 queries, `store_sales` (2.8M rows SF1) partitioned/sorted on `ss_sold_date_sk`; DuckDB CTAS sort helps Q4, Q64, etc. | SQLite `tpcds` SF1 pruned (1391s load) — correctly excluded |
| 6 | `tpcds` | 10.0 | `duckdb` | `duckdb/tpcds_tuned.yaml` | 10 GB `store_sales` 28M rows; sort and PK/FK enable optimizer to eliminate joins at scale | |
| 7 | `tpcds` | 1.0 | `spark` | `databricks/tpcds_tuned.yaml` (Z-ORDER) | Databricks Z-ORDER on `ss_sold_date_sk`/`cs_sold_date_sk`; Spark benefits at SF1 where shuffle dominates | |
| 8 | `tpcds` | 10.0 | `spark` | `databricks/tpcds_tuned.yaml` (Z-ORDER) | Same at 10 GB; prior `tpcds_sf10_spark` bundles exist, so feasible | |
| 9 | `ssb` | 1.0 | `duckdb` | `duckdb/ssb_tuned.yaml` | SSB `lineorder` 6M rows SF1, sorted on `orderdate`/`commitdate`; Q1–Q4 benefit from CTAS reorder | |
| 10 | `ssb` | 10.0 | `duckdb` | same | 60M rows; sort benefit grows | |
| 11 | `ssb` | 1.0 | `spark` | `databricks/ssb_tuned.yaml` | Spark Z-ORDER on `lineorder` dates | |
| 12 | `tpchavoc` | 1.0 | `duckdb` | `duckdb/tpchavoc_tuned.yaml` | 220 variants of TPC-H, same `lineitem` sort benefit, high query evidence per `tpc.yaml` | |
| 13 | `tpchavoc` | 1.0 | `spark` | `databricks/tpchavoc_tuned.yaml` | Same for Spark | |
| 14 | `amplab` | 1.0 | `duckdb` | `duckdb/amplab_tuned.yaml` | AMPLab `rankings`/`uservisits` sort on `pageRank`/`visitDate`; DuckDB CTAS helps Q1–Q3 | SF1 only; benchmark has no SF10 scale |
| 15 | `h2odb` | 1.0 | `duckdb` | `duckdb/h2odb_tuned.yaml` | H2O-DB `customer`/`order` sort on `o_orderdate`; similar to TPC-H | |
| 16 | `clickbench` | 1.0 | `duckdb` | `duckdb/clickbench_tuned.yaml` | ClickBench single `hits` table (100M rows SF1) sorted on `EventDate`/`CounterID`; DuckDB CTAS sort helps range filters | Single scale 1.0 only |
| 17 | `read_primitives` | 1.0 | `duckdb` | `duckdb/read_primitives_tuned.yaml` | Primitives `read` workload benefits from PK/FK constraints (enabled in tuned) and sorted `lineitem` for range reads | |
| 18 | `joinorder` | 1.0 | `duckdb` | `duckdb/joinorder_tuned.yaml` | IMDb 2013 full dataset, `cast_info`/`title` sorted on `title.production_year`; constraint + sort helps Q7a warm-up (the 1200s envelope outlier) | Single scale 1.0; pg-family pruned per `compatibility.py:101-106`, DuckDB is the only local tuner that passes |
| 19 | `tpch` | 1.0 | `polars` | `examples/tunings/dataframe/polars_optimized.yaml` (explicit) | DataFrame Polars streaming + optimized write manager; tpch SF1 (6M rows) benefits from partitioned Parquet + sorted write at SF1 where Pandas/Polars spill | SF0.01 excluded; use `notuning` baseline `polars_default.yaml` as companion (do not stage as `tuned`) |
| 20 | `tpch` | 1.0 | `pandas` | `examples/tunings/dataframe/pandas_optimized.yaml` | Same for Pandas | |
| 21 | `tpch` | 1.0 | `pyspark` | `examples/tunings/dataframe/pandas_optimized.yaml` as a proxy until a dedicated PySpark profile exists | PySpark benefits from partitioning at SF1 | |
| 22 | `ssb` | 1.0 | `polars` | explicit DataFrame optimized | SSB `lineorder` 6M rows, Polars optimized helps | Optional; include if host memory allows after tpch |

**Explicitly excluded (tuning not helpful):**
- `datafusion` at any benchmark/scale — no `tuned_template`, `sorting: none`, would be `basic_constraints` only.
- `sqlite` at any benchmark/scale — same, plus SQLite is pruned at SF1 for `tpcds` anyway; constraint-only tuning does not change the SQLite B-Tree path for these workloads.
- `clickhouse-local`/`chdb` — registry has `PARTITION_BY` but no shipped template → `basic_constraints`; staging as `tuned` would mislabel a no-op (the `tuning-registry-mixin-honesty` gap noted in `capability_registry.py:55`).
- `dask-df`, `datafusion-df`, `modin-df` for `write_primitives` — `write_manager: none` per `compatibility.py:92`.
- All SF0.01/SF0.1 for tuned — baseline corpus already provides the scaling curve untuned; tuned at 10 MB is noise.

**Total tuned corpus size:** 22 cells (12 DuckDB, 6 Spark, and 4 DataFrame) covering 9 benchmarks at SF1 (and 6 of them also at SF10 where the scale exists). Each cell will have a *pair* — `notuning` baseline already in the 151-bundle corpus + `tuned` new — so the tuned facet will have a true A/B.

## 5. Template and Scale Details

- **DuckDB SF10 feasibility:** Prior bundles `tpcds_sf10_duckdb_sql_20260823_173729...` and `tpch` SF10 runs exist in `~/Developer/benchmark_runs/results` lineage, so SF10 is feasible on this host (64 GiB). Keep per-cell timeout at 1200s; if a cell times out, record as `unreachable` per UAT accounting, do not relax the budget.
- **Spark SF10:** Same; prior `tpcds_sf10_spark` exists, so include SF10 for `tpch`/`tpcds`; other benchmarks have no SF10 scale by definition.
- **DataFrame SF10:** Not included — Polars/Pandas at SF10 (60M rows) would OOM on the 16 GiB UAT envelope and has no prior SF10 evidence; keep SF1 only.

## 6. Execution Workflow (exact commands)

All runs use `BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs` (external root invariant, `docs/operations/uat-framework.md`) and `generate,load,power` only (seed-corpus contract, `results-data/SEED_CORPUS_SPEC.md`).

```bash
make worktree-create BRANCH=chore/tuning-corpus-optimal WORKTREE_PATH=../BenchBox.wt-tuning-corpus-optimal
cd ../BenchBox.wt-tuning-corpus-optimal
make agent-write-preflight

# DuckDB tuned — SF1 and SF10 where scale exists
for bench in tpch tpcds ssb tpchavoc amplab h2odb clickbench read_primitives joinorder; do
  for scale in 1 10; do
    # skip invalid scale/benchmark combos: clickbench/joinorder only 1.0, amplab/h2odb only 1.0, etc.
    # the loop below handles the mapping in §4 table; SF10 only for tpch/tpcds/ssb where prior SF10 exists
    BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs \
      uv run -- benchbox run --platform duckdb --benchmark $bench --scale $scale --tuning tuned --phases generate,load,power --compression zstd:9 --non-interactive --quiet
  done
done

# DuckDB notuning baselines at SF1 are already in the corpus (151 bundles); do not re-run unless missing.

# Spark (Databricks) tuned — SF1 and SF10
for bench in tpch tpcds ssb tpchavoc; do
  for scale in 1 10; do
    BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs \
      uv run -- benchbox run --platform spark --benchmark $bench --scale $scale --tuning tuned --phases generate,load,power --compression zstd:9 --non-interactive --quiet
  done
done
# For Liquid vs Z-ORDER comparison, run the second variant explicitly:
# benchbox run --platform spark --benchmark tpch --scale 1 --tuning examples/tunings/databricks/tpch_liquid_tuned.yaml ...

# DataFrame tuned — explicit paths, SF1 only
BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs \
  uv run -- benchbox run --platform polars --benchmark tpch --scale 1 --tuning examples/tunings/dataframe/polars_optimized.yaml --phases generate,load,power --compression zstd:9 --non-interactive --quiet
BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs \
  uv run -- benchbox run --platform pandas --benchmark tpch --scale 1 --tuning examples/tunings/dataframe/pandas_optimized.yaml --phases generate,load,power --compression zstd:9 --non-interactive --quiet
# pyspark: use the same pandas_optimized as proxy until a dedicated pyspark template lands
BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs \
  uv run -- benchbox run --platform pyspark --benchmark tpch --scale 1 --tuning examples/tunings/dataframe/pandas_optimized.yaml --phases generate,load,power --compression zstd:9 --non-interactive --quiet
```

**Ordering:** Run DuckDB first (Tier 1 native, zero daemon overhead), then Spark, then DataFrame — same serialized order as the SF1 repopulation plan and `uat-framework.md` "Release-gate re-run" to preserve host isolation. Do **not** parallelize platforms.

**Tuning verification:** After each `tuned` run, the bundle's `platform.tuning` will contain `requested_config_hash`, `applied` ledger, and `tuning_validation_status`. The 2026-07-16 bug is fixed per `tests/unit/platforms/test_tuning_config_forwarding.py` — verify forwarding still passes before the sweep:

```bash
uv run -- pytest tests/unit/platforms/test_tuning_config_forwarding.py -k test_from_config_forwards_tuning_kwargs
```

## 7. Staging, Validation, and Provenance (the gates)

1. **Zero-query and timing guard** (from `CORPUS_NOTES.md` 2026-08-24): Reject any bundle where `summary.queries.total == 0` or `summary.timing.geometric_mean_ms == 0`.
2. **Tuning-verified gate:** For SQL `tuned` bundles, require `platform.tuning.validation_status` in `{"applied_verified", "applied_unverified"}` and reject `failed`/`noop`. Explicit DataFrame profiles are a separate canonical `custom` mode and are accepted only when `config.tuning_config` contains the non-default profile and the run has nonzero query/timing evidence; their SQL ledger status is `noop` because no SQL tuning ledger applies.
3. **Cohort depth:** `results-data/validate_corpus.py` requires every `(benchmark, scale)` cohort to have ≥3 platforms. The tuning corpus is a *facet* within each cohort, not a separate cohort — so a cohort like `tpch SF=1.0` must have ≥3 platforms *in total* (which it does: 12 untuned + up to 8 tuned), and within it the `tuned` facet must have ≥2 platforms to be a comparison (DuckDB + Spark satisfies).
4. **Provenance sidecar:** For each staged `tuned` bundle, create sibling `<stem>.tuning.json` already emitted by `benchbox run --tuning tuned` and a submission sidecar `<stem>.manifest.json` with `{"result_source":"internal","funding":"unspecified"}` so `generate_corpus_inventory.py` derives `trust_label: maintainer-run` (same as the SF1 repopulation).
5. **Inventory and build:**
```bash
uv run -- python scripts/generate_corpus_inventory.py --write
uv run -- python results-data/validate_corpus.py
uv run -- python _project/scripts/explorer_publish.py build --data-dir results-data --output results-explorer/dist/data
```
The tuned bundles will appear under the `tuning_mode: tuned` facet in the Explorer (see `results-explorer/src/components/TuningBadge.tsx` and `ComparabilityReceipt.tsx` for the `tuned` vs. `notuning` comparison logic).

## 8. Resource and Time Budget

- **DuckDB SF1:** ~2–10 min per cell, 9 benchmarks × 2 scales (SF1 + SF10 where applicable) ≈ 60–120 min.
- **Spark SF1/SF10:** ~5–30 min per cell (JVM warm-up), 4 benchmarks × 2 scales where feasible ≈ 40–80 min.
- **DataFrame SF1:** ~2–5 min per cell, 4 cells ≈ 10–20 min.
- **Total:** ~110–215 min wall-clock serialized on Apple Silicon with cached datagen (`~/Developer/benchmark_runs/datagen` preserved per `uat-framework.md`). No Docker, no cloud creds, no `BENCHBOX_TUNING_CONFIG` env needed beyond the shipped templates.

## 9. What to *Not* Do (and why)

- Do not run `tuned` for `datafusion`, `sqlite`, `clickhouse-local`, `dask-df` — they would be `basic_constraints` only, and `tuning_mode: tuned` would be a mislabel (the `rendered_via="none"` honesty gap). If a future template lands for those platforms, re-evaluate.
- Do not run `tuned` at SF0.01/SF0.1 — the untuned baseline already provides the scaling curve; tuned at 10 MB is dominated by DDL cost and has no prior evidence of win.
- Do not combine DataFrame `polars_optimized.yaml` with `--tuning tuned` auto-discovery — DataFrame tuning is never auto-discovered (see `examples/tunings/README.md`); use the explicit path.
- Do not treat `tuning_mode: tuned` as comparable across tuning-policy generations — the Explorer's `ComparabilityReceipt` warns on `tuning_policy_generation` mismatch per ADR-3; keep the generation in the bundle's `platform.tuning`.

## 10. Success Criteria

- 22 new `tuned` bundles staged (12 DuckDB + 6 Spark SF1/SF10 + 4 DataFrame SF1), each with a sibling `.tuning.json` and tuning metadata showing the run was actually tuned.
- `corpus-inventory.json` grows from 151 to ~173 bundles, still `validate_corpus.py` passes (no shallow cohorts introduced).
- Explorer build `results.duckdb` shows the `tuning_mode` facet with both `tuned` and `notuning` under the same `(benchmark, scale)` cohorts, and the `TuningBadge`/`ComparabilityReceipt` correctly surfaces the `requested_config_hash` and `physical_mechanisms` for each.

## 11. Execution Outcome on the 2026-08-29 Host Run

The fixed 22-cell plan was executed serialized with the documented commands. Eight
validated bundles were imported: six SQL bundles in the `tuned` facet and two
explicit DataFrame bundles in the canonical `custom` facet. The DataFrame mode is
intentional: ADR-2 distinguishes explicit profiles from the keyword `tuned`, and
the result payload preserves the actual profile under `config.tuning_config`.

| Cells | Outcome |
|---|---|
| DuckDB `tpch` SF1, `tpcds` SF10, `ssb` SF1, `amplab` SF1, `clickbench` SF1, `joinorder` SF1 | Imported and validated |
| Polars `tpch` SF1 and `ssb` SF1 | Imported and validated as explicit DataFrame `custom` profiles |
| DuckDB `tpch` SF10 and `ssb` SF10 | Failed during the host run before producing a valid result bundle |
| DuckDB `tpcds` SF1 | Rejected by duplicate primary keys in the generated data |
| DuckDB `h2odb` SF1 | Result had `platform.tuning.validation_status=failed`, so it was not staged |
| DuckDB `read_primitives` SF1 | Benchmark rejects SF1; supported scales are SF0.01 and SF0.1 |
| DuckDB `tpchavoc` SF1 | Valid run withheld because it would create a one-platform shallow cohort |
| Spark six cells | Local Spark could not execute the tuned path on this host: `spark` has no auto-discovered template, while the Databricks connector extra is unavailable and the installed Java 26 is outside PySpark's supported range |
| Pandas `tpch` SF1 and PySpark `tpch` SF1 | Pandas exceeded the 1200-second budget; PySpark failed before producing a valid result |

The corpus therefore grows from 151 to 159 bundles and remains validator-clean;
the remaining planned cells are recorded as host/environment or benchmark-data
blockers rather than fabricated or relabeled results.
