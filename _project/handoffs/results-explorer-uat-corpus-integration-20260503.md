# Results Explorer UAT-20260502 Corpus Integration — 2026-05-03

Audit and curation handoff for `results-explorer-uat-corpus-integrate-validated-bundles`.

Source data: `~/Developer/benchmark_runs/submissions/uat_20260502/` (376 bundles staged)
and `~/Developer/benchmark_runs/submissions/uat_20260502_valid/` (205-bundle
validator-clean subset).

## W1 — Re-validation finding

`uv run -- python scripts/validate_submission.py ~/Developer/benchmark_runs/submissions/uat_20260502/`

Output: **`Validated 376 bundle(s): 188 error(s), 212 warning(s)`** — identical
to the original W5 log (`submission_validation_20260502.log`).

Full re-validation log:
`~/Developer/benchmark_runs/logs/uat_20260502/submission_validation_revalidate_20260503.log`.

### Why the totals are unchanged

The TODO description expected post-fix re-validation to improve the failure
counts because PRs #141, #142, #143, #145 closed the dominant defect clusters.
Those fixes are emitter-side: they change `benchbox/core/results/schema.py`
and platform adapters so future captures comply. The bundle JSONs on disk
were serialized before those fixes landed and are frozen — re-running the
validator against frozen captures cannot improve the result.

This is not a regression. The 14 defect TODOs all map to fixes that prevent
*new* bundles from carrying the defect; they do not (and were not designed to)
retroactively repair captured artefacts.

### Cluster cross-reference

| Cluster | Count | Defect TODO | PR | Status |
| --- | --- | --- | --- | --- |
| `cost.total_usd cannot accompany cost_status 'unavailable'` | 134 errors | `results-explorer-uat-defect-normalized-cost-unavailable-bundles` | #141 | Closed (emitter fixed) |
| `All query timings are 0ms - likely invalid data` | 54 errors | `results-explorer-uat-defect-zero-query-timing-bundles` | #143 | Closed (emitter fixed) |
| `summary.queries.total is 0` (warn) | 106 warns | n/a — DataFrame mode without per-query timing surface | n/a | Acceptable |
| `queries array is empty` (warn) | 106 warns | same | n/a | Acceptable |

No still-open defect cluster regressed. The 188 errors / 212 warnings come
entirely from frozen pre-fix captures.

### Implication for the open question

> Should the integration prefer the validator-clean 205-bundle subset
> (already on disk) or rebuild from the full 376-bundle set after re-validation?

**The 205-bundle subset *is* the rebuild result.** Re-validating the full 376
package surfaces the same 205 PASS / 171 FAIL split as the original W5 log.
The integration candidate set is the existing `uat_20260502_valid/bundle/`
directory, with the per-cohort exclusions in W2 applied on top.

## W2 — Coverage and curation audit (205 valid bundles)

### Platform totals

| Platform | Bundle count |
| --- | --- |
| DataFusion | 68 |
| Polars | 41 |
| PySpark | 34 |
| SQLite | 28 |
| Spark | 25 |
| DuckDB | 9 |

DataFusion's high count includes paired SQL-mode and DataFrame-mode bundles
for most (benchmark, scale) cells (see "Per-cell duplicates" below).

### Benchmark and scale totals

| Benchmark | Bundles | | Scale | Bundles |
| --- | --- | --- | --- | --- |
| tpch_skew | 19 | | SF=0.01 | 70 |
| amplab | 16 | | SF=0.1 | 63 |
| h2odb | 16 | | SF=1.0 | 72 |
| ssb | 16 | | | |
| tpch | 16 | | | |
| write_primitives | 14 | | | |
| coffeeshop | 13 | | | |
| tpchavoc | 13 | | | |
| read_primitives | 12 | | | |
| tsbs_devops | 12 | | | |
| datavault | 9 | | | |
| nyctaxi | 9 | | | |
| tpcdi | 9 | | | |
| clickbench | 6 | | | |
| flightdata | 6 | | | |
| tpcds | 6 | | | |
| tpcds_obt | 5 | | | |
| ai_primitives | 3 | | | |
| metadata_primitives | 3 | | | |
| joinorder | 2 | | | |

Twenty distinct benchmarks; reasonably balanced across SF rungs.

### Cross-scale comparison surface

**51 (platform, benchmark) pairs have all three SF rungs (0.01, 0.1, 1.0)
present** — this is the surface the explorer's cross-scale view needs and
the original UAT under-tested (blind-spot
`2026-05-03-081920-uat-cross-scale-deliverable-not-guarded.md`).

By platform:

| Platform | (platform, benchmark) pairs with all 3 SF rungs |
| --- | --- |
| DataFusion | 14 — amplab, coffeeshop, datavault, h2odb, nyctaxi, read_primitives, ssb, tpcdi, tpcds, tpch, tpch_skew, tpchavoc, tsbs_devops, write_primitives |
| Polars | 12 — amplab, coffeeshop, h2odb, nyctaxi, read_primitives, ssb, tpcds, tpch, tpch_skew, tpchavoc, tsbs_devops, write_primitives |
| PySpark | 9 — amplab, datavault, h2odb, nyctaxi, ssb, tpch, tpch_skew, tsbs_devops, write_primitives |
| SQLite | 7 — ai_primitives, amplab, coffeeshop, h2odb, ssb, tpcdi, tsbs_devops |
| Spark | 7 — amplab, coffeeshop, h2odb, ssb, tpcdi, tpch, tpch_skew |
| DuckDB | 2 — datavault, tpch_skew |

For W5 verification, the three (platform, benchmark) pairs to exercise the
explorer cross-scale view against will be picked from the DataFusion or
Polars rows (deepest cross-scale coverage).

### Cohort merge gate (`results-data/validate_corpus.py` → ≥3 platforms per cohort)

51 cohorts total. **42 mergeable, 9 blocked.**

Blocked cohorts (must be excluded from this PR or the gate must be relaxed):

| Cohort | Platforms present | Bundles |
| --- | --- | --- |
| ai_primitives × 0.01 | SQLite | 1 |
| ai_primitives × 0.1 | SQLite | 1 |
| ai_primitives × 1.0 | SQLite | 1 |
| joinorder × 1.0 | SQLite, Spark | 2 |
| read_primitives × 1.0 | DataFusion, Polars | 3 (DataFusion has SQL+DF modes) |
| tpcds × 0.01 | DataFusion, Polars | 2 (DF mode only) |
| tpcds × 0.1 | DataFusion, Polars | 2 (DF mode only) |
| tpcds × 1.0 | DataFusion, Polars | 2 (DF mode only) |
| tpchavoc × 1.0 | DataFusion, Polars | 3 (DataFusion has SQL+DF modes) |

**Decision: exclude all 9 blocked cohorts from this PR.** Total exclusion =
**17 bundles** (3 ai_primitives + 2 joinorder + 3 read_primitives_SF1
+ 6 tpcds + 3 tpchavoc_SF1).

These cohorts will be carried forward as a follow-up TODO once a third
platform is available — they are *not* defects, just below the depth gate.
The corpus validator gate is intentionally not changed in this PR (changing
a corpus-quality policy is a separate decision that does not belong in a
curation PR).

### Per-cell duplicates: DataFusion SQL + DataFrame modes

21 cells have two bundles for the same (platform, benchmark, scale).
**All 21 are DataFusion**, paired as `_sql_*.json` (SQL execution mode) and
`_df_*.json` (DataFrame execution mode). DataFusion is the only platform in
the corpus that exposes both modes.

These are not duplicates in the corpus-quality sense — they capture distinct
execution paths through the same platform and the explorer can compare them.
**Decision: keep both modes for every duplicate cell.** This matches the
existing curated convention (e.g. `tpch_sf01_polars_df_*` and
`tpch_sf01_polars_*` already coexist for Polars).

### Empty `queries[]` warnings (63 bundles)

63 bundles passed the validator with the `summary.queries.total is 0` /
`queries array is empty` warning pair. Distribution:

| Platform | Bundles with empty queries[] |
| --- | --- |
| DataFusion | 21 (all `_df_` DataFrame-mode captures) |
| Polars | 21 |
| PySpark | 18 |
| SQLite | 3 |

These are DataFrame-mode bundles whose adapters do not yet emit per-query
timing surfaces — the same pattern the existing curated
`tpch_sf01_polars_df_20260404_191727_mcp_b897c572.json` exhibits, which is
already shipping in the corpus. The bundles still carry valid load / phase /
environment / cost data.

**Decision: keep these bundles.** They are warnings, not errors, and the
per-query timing surface is platform-mode-level missing data, not a defect
in this capture. The explorer already short-circuits empty `queries[]` —
see `results-explorer/src/components/DivergingBarChart.tsx:32`,
`NormalizedSpeedupChart.tsx:44`, and `pages/ResultDetail.tsx:334,382`.

### Collisions with existing curated entries

Four (platform, benchmark, scale) cells overlap with the 12 existing curated
bundles in `results-data/bundles/`:

| Cell | Existing curated | New UAT bundles |
| --- | --- | --- |
| DataFusion × tpch × 0.01 | `tpch_sf001_datafusion_20260403_093731_c235e698.json` | `tpch_sf001_datafusion_df_20260502_222800_536a69c2.json`, `tpch_sf001_datafusion_sql_20260502_182433_0310462d.json` |
| DataFusion × tpch × 0.1 | `tpch_sf01_datafusion_sql_20260404_191814_890f931e.json` | `tpch_sf01_datafusion_df_20260502_222802_da96c80b.json`, `tpch_sf01_datafusion_sql_20260502_182437_40f235bb.json` |
| Polars × tpch × 0.01 | `tpch_sf001_polars_20260403_093741_e744512d.json` | `tpch_sf001_polars_df_20260502_210713_8408d471.json` |
| Polars × tpch × 0.1 | `tpch_sf01_polars_df_20260404_191727_mcp_b897c572.json` | `tpch_sf01_polars_df_20260502_210715_372f12c6.json` |

**Decision: add new bundles alongside existing curated entries, do not
overwrite.** This satisfies the must_preserve "Existing curated entries
remain in place and unmodified". Multiple bundles per cell are already the
convention (e.g. existing curated has both `tpch_sf001_polars_*` and
`tpch_sf01_polars_df_*` styles).

### Trust-label resolution

`scripts/generate_corpus_inventory.py:43-52` derives the trust label from
the presence of a `<stem>.manifest.json` sidecar (or the legacy singleton
`submission-manifest.json` fallback):

- Per-bundle sidecar present **or** legacy singleton present → `community-submission`
- Neither present → `maintainer-run`

The TODO description mentioned `maintainer-curated`, which is **not an
existing label** and would constitute "inventing" a new one (forbidden by
must_preserve). The UAT bundles were submitted via the per-bundle manifest
flow (PR #95) and so naturally land as `community-submission` once their
sidecar manifests are copied alongside them. This is the correct label for
local laptop captures that did not flow through `seed-corpus.yml`.

**Caveat for future maintainers:** the legacy `submission-manifest.json`
singleton fallback is directory-wide. If a top-level
`results-data/bundles/submission-manifest.json` were ever introduced, every
bundle in the directory would silently flip to `community-submission`,
including the existing 12 maintainer-run entries. The staging plan never
copies the singleton — only per-bundle sidecars — so this PR cannot trip
the trap, but it is worth flagging.

**Decision: copy each UAT bundle JSON together with its sibling
`<stem>.manifest.json` into `results-data/bundles/`. The inventory generator
will resolve the trust label correctly without any manual labelling.**

## Staging plan (W3)

1. Compute the include set from `uat_20260502_valid/bundle/`:
   - Start: 205 bundles.
   - Exclude: every bundle in the 9 blocked cohorts listed above (17 bundles).
   - Final include count: **188 bundles** (205 − 17), confirmed at staging time.
2. For each included bundle, copy two files into `results-data/bundles/`:
   - `<stem>.json` (the primary bundle)
   - `<stem>.manifest.json` (the sidecar from `submissions/uat_20260502/`)
3. Regenerate `results-data/corpus-inventory.json` via
   `uv run -- python scripts/generate_corpus_inventory.py --write`.
4. Re-run `uv run -- python results-data/validate_corpus.py` and
   `uv run -- python scripts/validate_submission.py results-data/bundles/` —
   both must exit 0.
5. Record the final include count, exclusion list, and validator outputs in
   this handoff doc under a "Staging log" section.

## Success-metric tracking

- "≥80% of validator-clean bundles land via merged PR" — target 164/205
  bundles minimum. Plan stages **188 bundles** (excluding only the 17
  bundles in the 9 blocked cohorts), so **91.7%** on-track.
- "Cross-scale view renders for ≥3 (platform, benchmark) pairs" — there are
  51 candidates; W5 will pick three from DataFusion or Polars.
- "Audit matrix filed under `_project/handoffs/`" — this document.
- "Hosted validator and per-bundle contract CI green" — verified at W4.
