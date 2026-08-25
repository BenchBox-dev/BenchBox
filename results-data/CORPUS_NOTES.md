# Corpus Generation Notes - 2026-04-03

## Platforms Run

### TPC-H (SF 0.01)
- **DuckDB 1.4.3** - PASSED, 22 queries, 3 measurement runs
- **DataFusion 51.0.0** - PASSED, 22 queries, 3 measurement runs
- **Polars 1.37.1** - PASSED, 22 queries, 3 measurement runs (DataFrame mode)

### SSB / Star Schema (SF 0.01)
- **DuckDB 1.4.3** - PASSED, 13 queries, 3 measurement runs
- **DataFusion 51.0.0** - PASSED, 13 queries, 3 measurement runs
- **SQLite 3.50.4** - PASSED, 13 queries, 3 measurement runs

## Skips and Notes

### Polars-df SSB - Skipped (0 queries)
`polars-df` with SSB benchmark emitted 0 queries during execution ("No queries
found for execution"). SSB DataFrame queries are not implemented for the Polars
platform. SQLite was used as the third platform for SSB instead.

### Export bug fix
The `benchbox export` command failed with `TypeError: type NoneType doesn't
define __round__ method` when `load_time_ms` was `None` in `table_statistics`.
Fixed in `benchbox/core/results/schema.py` by guarding `round()` calls with
`is not None` checks.

### Export --last filter caveat
`benchbox export --last --benchmark ssb --platform duckdb` did not find SSB
results because the schema v2 `benchmark.id` field is `star_schema` (not `ssb`).
The `--last --benchmark` filter compares against the JSON `benchmark.id`, so
results were exported directly by filename.

## Cohort Depth
Both cohorts meet the >=3-platform depth criterion required for the Compare view:
- `tpch SF=0.01`: DuckDB, DataFusion, Polars
- `star_schema SF=0.01`: DuckDB, DataFusion, SQLite

## Zero-query DataFrame withdrawal (2026-08-24)

Sixty legacy DataFrame bundles were withdrawn because they reported
`summary.validation=passed` after executing zero queries. They are
non-measurements, not truthful partial results. Each bundle's manifest was
removed with it.

Removing only those bundles would have left ten represented cohorts below the
three-platform corpus floor. Because truthful replacements were not yet
available, the remaining 17 SQL bundles in those cohorts were temporarily
withdrawn too; those 17 were not classified as invalid. This preserves the
cohort invariant without counting empty results as coverage:

- AMPLab SF 0.1 and 1.0
- CoffeeShop SF 0.1 and 1.0
- H2O-DB SF 0.1 and 1.0
- SSB SF 1.0
- TSBS DevOps SF 0.01, 0.1, and 1.0

The removal commit contains the exact 77-bundle and 77-manifest path list.
Restore a cohort only with at least three truthful platform results. Fresh
DataFrame results additionally require real validation evidence; execution
success alone is not a validation pass. NYC Taxi and TSBS DevOps regeneration
also waits for their native temporal-literal fix.

## Public-path single-pass status (2026-08-05)

Verified with `results_explorer_corpus_migrate.py` dry-run: 0/207 bundles changed under the current public anonymization pass. The `test_rederiv_fresh_public_pass_equals_curated_for_all_fields` gate pins the fixed point.

---

# Regeneration - strip residual empty `client_host` (2026-08-05 / 2026-08-06)

**Related PR:** #1614 (`fix/strip-empty-client-host-corpus`)
**Date:** 2026-08-05 (local) / 2026-08-06 (UTC commit)

## Reason

After `machine_id` was dropped from public environment maps, some already
public-shaped primary bundles retained residual empty `client_host: {}`
objects. Those hollow maps were identifier-only leftovers, not real host
profiles. Anonymization policy now **always omits empty optional environment
maps** (including already-empty `{}` residuals) so the public shape has no
hollow blocks.

## What landed together

Code change and corpus re-derive shipped in one fixed-point commit so stored
bytes match the fresh public shape:

1. **Policy** (`benchbox/core/results/anonymization.py`): omit empty optional
   maps under `_PUBLIC_EMPTY_OPTIONAL_MAP_KEYS` even when the stored input was
   already `{}` (not only when non-empty content was stripped to empty).
2. **Corpus**: re-derived **105** primary bundles under
   `results-data/bundles/` (plus inventory refresh) so checked-in bytes match
   re-anonymization output. Count verified as the primary-bundle delta vs
   `origin/develop` on this branch (105 `results-data/bundles/*.json` primaries;
   not plans/tuning/manifest sidecars).

No full corpus rewrite beyond those residual hollow maps; non-empty
`client_host` profiles and unrelated fields were left alone. Anonymization
policy was not expanded beyond empty optional map omission.

## How to verify

- Unit: `tests/unit/core/results/test_anonymization.py` —
  `test_already_empty_client_host_is_omitted` (and related public-unread
  identifier drop cases).
- Corpus fixed point: re-anonymize primary bundles and assert byte-identical
  publication (existing re-derived / fixed-point corpus gates; no empty
  `client_host` objects remain in primary bundles).
- Spot check: `rg -n '"client_host": \{\}' results-data/bundles` should not
  match residual hollow maps in primary result JSON.
