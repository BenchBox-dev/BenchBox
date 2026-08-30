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

## Legacy validation-claim normalization (2026-08-25)

The 136-bundle develop corpus contained 52 legacy bundles whose
`phases.validation.status` was `NOT_RUN` while `summary.validation` claimed
`passed` (23 bundles) or `partial` (29 bundles). These are historical claims,
not rerun evidence. Their summary status is now `not_run`; their query timing
and failure records remain unchanged.

This preserves truthful partial measurements as non-ranking capability
evidence. It does not promote failed queries or infer validation results. A
future rerun may replace the `not_run` claim only when the validation phase
records actual evidence. Submission admission also rejects a `passed` or
`partial` summary claim paired with an unrun validation phase.

## Pre-2026-08-23 results withdrawn (2026-08-28)

All 130 bundles run before 2026-08-23 were removed from the develop corpus,
together with their 114 `.manifest.json` sidecars (244 files). What remains is
9 bundles across 3 cohorts.

**This was a trust decision, not a soundness finding.** Unlike the 2026-07-16
tuned drop (#1176 proved the tuning config never reached platform adapters) and
the 2026-08-24 zero-query withdrawal (bundles claimed `passed` after executing
nothing), no defect was found in the removed results. The maintainer no longer
trusts measurements taken before 2026-08-23 and asked for them to be withdrawn.
Do not go looking for a bug report; there isn't one.

What went:

- 12 bundles from the original 2026-04-03/04 corpus generation
- 111 bundles from the 2026-05-02 maintainer UAT sweep (committed in #164)
- 3 JoinOrder bundles from the 2026-05-12 canonical UAT
- 4 SSB seed-lane bundles from 2026-07-30

Removing them would have left TPC-H SF1 holding only Polars and PySpark, below
the three-platform floor in `validate_corpus.py`. A fresh maintainer DuckDB run
at TPC-H SF1 (DuckDB 1.3.2, 66 queries, 0 failed, validation PASSED) was added
in the preceding commit to hold the cohort. It also gives that cohort a SQL
reference point against two DataFrame-mode results.

The three migration manifests in `bundles/` were deliberately kept:
`path-privacy-migration.manifest.json` is the `DEFAULT_MANIFEST` in
`_project/scripts/results_explorer_corpus_migrate.py` and is name-referenced by
`sync-results-data-to-published.yml`. They are tooling audit records, excluded
from bundle discovery by `COMPANION_SUFFIXES`.

Restoring any withdrawn cohort means fresh runs, not reverting this commit.
`REGENERATION.md` is the precedent for how to document what a restore needs.
The removal commit carries the exact 244-path list.

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


## CPU identity backfill (2026-08-29) — OPERATOR ATTESTATION, NOT MEASURED

Every bundle in this corpus now carries `cpu_model: "Apple M4"` and
`cpu_vendor: "Apple"`, which the Explorer read model normalizes to the family
`apple_silicon`. **These values were not measured. They are an operator
attestation.**

### Why no measured value exists

The capture path was defective, in three independent ways:

1. `get_system_info` sourced `cpu_model` from `platform.processor()`, which on
   Darwin returns the bare architecture `"arm"`. `normalize_cpu_family("arm")`
   is `"unknown"`, so even where a value was recorded it said nothing.
2. `SystemInfo.to_dict` emitted `cpu_cores` / `total_memory_gb` / `os_version`
   while `ClientHostEnvironment.from_system_profile` reads `cpu_count` /
   `memory_gb` / `os_release`, so those three were silently dropped from every
   bundle, and `cpu_vendor` was never produced at all.
3. The DataFrame adapters descend from a hierarchy that never runs the SQL
   path's environment capture, so 43 of these 151 bundles recorded no client
   host whatsoever.

Defects 1 and 2 are fixed in `fix/cpu-identity-capture-source`. Defect 3 is
tracked as `dataframe-client-host-capture-gap`. Across the 3,845 raw local
results only 4 carry a CPU, and all four post-date those fixes — so there was
nothing in the archive to recover.

### The attestation

The project maintainer attests that every run in this corpus executed on a
single machine — natively, or driving Apple container Linux images whose
engines share that host's CPU. No other machine has been used in the project's
development.

Recorded evidence is consistent with it but does not by itself establish the
model: every bundle that records a client host records `Darwin`/`arm64`, and
the raw local archive shows a single `machine_id`. `arm64` + `Darwin` implies
Apple Silicon; it does not distinguish an M1 from an M4. The specific model
rests on the attestation alone.

### What was and was not written

Only `cpu_model` and `cpu_vendor` were written. For the 43 DataFrame bundles
that had no client host, `os`, `arch` and `python` were **not** synthesized:
the attestation covers which machine ran the corpus, not a given run's OS
release or interpreter version. That gap closes forward, not retroactively.

### Result IDs were renumbered

`result_id` embeds a SHA-256 prefix of the raw bundle bytes, so all 151 were
renumbered. Precedent: `path-privacy-migration` and `unread-identifier-field-drop`
each renumbered all 207 entries of the corpus of their day. Every old → new
mapping is recorded in `results-data/bundles/cpu-identity-attestation.manifest.json`,
which is also where a reader distinguishes attested values from measured ones.

Reproduce with:

    uv run -- python _project/scripts/results_explorer_cpu_attestation_backfill.py
    # add --write to apply
