---
title: "BenchBox v0.2.0: Alpha to Beta"
series: building-benchbox
post_number: 8
type: release-notes
tags: [benchbox, release, changelog, beta, redshift, cloud-testing, coverage, hardening]
status: OUTLINE
---

# Outline: BenchBox v0.2.0 release summary

---

## Theme

v0.2.0 is the **Beta promotion release**. The project status moves from `Development Status ::
3 - Alpha` to `4 - Beta`. This is less about new features and more about finishing what we
started: closing reliability gaps in cloud platforms, raising the coverage bar, cleaning up dead
code, and making the install story work in air-gapped environments.

The headline changes are:
1. Release-quality hardening (coverage threshold 80%, dead code removal)
2. On-demand TPC answer file downloads (offline-friendly install)
3. Cloud platform hardening (Redshift, BigQuery, Dask DataFrame fixes)
4. Live integration tests for 5 cloud platforms
5. Redshift Read Primitives coverage (0 to 40+ queries)
6. Two platforms removed (Snowpark Connect, Onehouse Quanton: 31 to 29 SQL platforms)
7. Legacy `plot` command removed

---

## TL;DR (draft bullets)

- **Project status promoted to Beta.** BenchBox is now `Development Status :: 4 - Beta` in
  package metadata. APIs are stabilizing; production use is closer but not yet recommended.
- **Coverage threshold raised to 80%** with behavioral coverage across adapters, CLI, credentials,
  and lifecycle. Dead code removed (9 unused imports, 12 prefixed parameters).
- **On-demand TPC answer file downloads.** Wheel installs fetch missing TPC-H/TPC-DS answer
  files automatically for validation. Offline environments can pre-populate with
  `benchbox download-answers`.
- **Redshift reliability overhaul.** Fixed S3 upload retry failures, `DROP DATABASE` timeouts,
  multi-format manifest errors, stale datagen reuse, and Serverless-compatible system queries.
  Adaptive connection timeout adjusts to cluster state.
- **Cloud platform live tests.** Added smoke tests for Firebolt, Starburst Galaxy, MotherDuck,
  pg_duckdb, and pg_mooncake with Docker Compose harness for PostgreSQL extensions.
- **Read Primitives Redshift coverage** expanded from 0 to 40+ queries with dialect-specific
  rewrites for window functions, fulltext, array operations, and statistical functions.
- **Dask DataFrame `.isin()` fix.** 11 TPC-H/TPC-DS queries fixed where lazy Dask Series caused
  runtime errors.
- **BigQuery loading correctness.** Standardized text file defaults for SQL platforms, enabled
  parquet-first native loads on BigQuery, fixed GCS blob naming.
- Two platforms removed (Snowpark Connect, Onehouse Quanton). Legacy `plot` command removed.

---

## At a glance table

| Area | What changed in v0.2.0 | Why it matters |
| --- | --- | --- |
| Beta status | `Development Status :: 4 - Beta` | Signal that APIs are stabilizing |
| Coverage hardening | Threshold raised to 80%; behavioral tests added across adapters/CLI | Higher confidence in release quality |
| TPC answer downloads | Auto-fetch for wheel installs; `benchbox download-answers` for offline | Validation works out of the box; air-gapped installs supported |
| Redshift reliability | S3 retry, DROP DATABASE timeout, Serverless system queries, adaptive timeout | Redshift benchmarks complete without manual intervention |
| Cloud live tests | Firebolt, Starburst Galaxy, MotherDuck, pg_duckdb, pg_mooncake | Regressions caught before release on real cloud platforms |
| Read Primitives Redshift | 0 to 40+ queries with dialect rewrites | Redshift users get meaningful primitive benchmark coverage |
| Dask DataFrame | `.isin()` computed before use in 11 queries | Dask TPC-H/TPC-DS runs clear a specific TypeError failure mode |
| BigQuery loading | Text-file defaults for SQL; parquet-first native on BigQuery | Correct format selection without manual overrides |
| Data-source resolution | Shared-data benchmarks resolve source database correctly | Multi-benchmark workflows don't silently fail |
| Platform removals | Snowpark Connect, Onehouse Quanton removed (31 to 29) | Platform list reflects what's actually testable |
| `plot` command removed | `benchbox plot` removed; use `benchbox visualize` | Eliminates undeclared matplotlib dependency |

---

## Section breakdown

### 1. What "Beta" means for BenchBox (~300 words)

This is the framing section. What changed, what it signals, what it doesn't promise.

**What changed**: the `Development Status` classifier in `pyproject.toml` moved from `3 - Alpha`
to `4 - Beta`. This is the package metadata that PyPI surfaces to users evaluating whether to
depend on a library.

**What it means**:
- Core APIs (CLI flags, Python API, result format) are stabilizing. We'll avoid breaking changes
  where possible and document them clearly when necessary.
- The benchmark execution pipeline, data generation, validation, and result export have been
  exercised across enough platforms and scale factors that we're confident in the core path.
- We still don't recommend BenchBox for unattended production pipelines. Beta means "the happy
  path works reliably; edge cases may still surprise you."

**What drove the decision**: the work in v0.1.2 through v0.1.5 closed most of the gaps we
identified at launch: DataFrame coverage, chart reliability, driver management, test quality,
format loading. v0.2.0 adds the cloud platform hardening and coverage threshold that let us
feel comfortable with the label.

Connect to the hardening work later in the post: coverage at 80%, dead code removed, live cloud
tests, and the Redshift reliability fixes were specifically gated on the Beta milestone.

### 2. On-demand TPC answer file downloads (~250 words)

**The problem**: TPC-H and TPC-DS answer files (used for row-count validation) are not included
in the wheel distribution due to licensing constraints. Users installing from PyPI couldn't
validate results without manually sourcing these files.

**The solution**: wheel installs now detect missing answer files at validation time and fetch
them automatically. SHA-256 verification, retries, and `BENCHBOX_NO_DOWNLOAD=1` for
environments that prohibit network access.

For air-gapped environments:
```bash
benchbox download-answers --benchmark tpch    # pre-populate cache
benchbox download-answers --benchmark all     # all benchmarks
benchbox download-answers --show-cache-dir    # show cache location
```

### 3. Redshift reliability overhaul (~350 words)

This is the largest fix cluster in the release. Group the fixes by symptom:

**S3 upload retry failures**: botocore stream rewind errors on retry. Fixed by ensuring streams
are rewindable before upload.

**`DROP DATABASE` timeouts**: extended socket timeout to 300s and pre-terminate active
connections before dropping.

**Multi-format manifest errors**: `Is a directory` errors when manifests contained mixed formats.
Platform format preferences now take priority over manifest defaults.

**Stale native datagen reuse**: cached native-format data wasn't invalidated when it should
have been.

**Serverless compatibility**: system table queries (`sys_serverless_usage` vs
`stv_cluster_configuration`) and `pg_stat_activity` column references (`procpid` vs `pid`)
now adapt to deployment type.

**Adaptive connection timeout**: paused or resuming provisioned clusters get longer timeout;
Serverless gets cold-start floor.

**Adapter-only validation**: non-admin Redshift connections no longer crash during row-count
validation.

### 4. Cloud platform live integration tests (~200 words)

**Before**: cloud platforms were tested only through mocked adapter paths. Real-platform failures
(credential issues, API changes, timeout behavior) were caught only during manual testing.

**Now**: live smoke tests for Firebolt, Starburst Galaxy, MotherDuck, pg_duckdb, and pg_mooncake.
Each platform has its own marker, fixture, and Makefile target. PostgreSQL extensions use a
Docker Compose harness for isolated testing. A multi-extension comparison orchestration layer
runs cross-extension benchmarks.

### 5. Read Primitives Redshift coverage (~200 words)

Expanded from 0 to 40+ queries. Dialect-specific rewrites for window functions, fulltext
operators, array operations, and statistical functions. Queries without semantically-exact
Redshift equivalents are skipped rather than approximated (the right call for a benchmark tool).

### 6. Release-quality hardening (~250 words)

**Coverage threshold**: raised from 60% (v0.1.5) to 80%. This required adding behavioral
coverage across adapter SQL generation, CLI paths, credential prompts, and adapter lifecycle.

**Dead code cleanup**: 9 unused platform imports removed, 12 unused function parameters
prefixed with `_`. These were found during the coverage push and Beta readiness audit.

**Tautological assertions and overspecified mocks removed**: tests that passed by definition
(asserting on the mock's own return value) were replaced with tests that exercise real behavior.

**`coverage-fast` runs now use parallel execution** for faster CI feedback.

### 7. Other fixes (~200 words)

Brief treatment:
- **Dask DataFrame `.isin()`**: 11 queries (6 TPC-H, 5 TPC-DS) passed lazy Series to `.isin()`.
  All now materialize via `.compute()` first.
- **BigQuery loading**: standardized text-file defaults for SQL platforms, parquet-first on
  BigQuery, fixed GCS compound suffix handling.
- **Data-source resolution**: shared-data benchmarks now resolve the correct source database.
- **TPC-H validation noise**: non-stream-0 power runs no longer emit spurious "Validation
  skipped" warnings.
- **Monitoring without extras**: graceful degradation when monitoring extra not installed.

### 8. Removals (~150 words)

- **`benchbox plot`**: removed along with its undeclared matplotlib dependency. `benchbox
  visualize` (terminal ASCII rendering) is the replacement, available since v0.1.2.
- **Snowpark Connect and Onehouse Quanton**: removed from the SQL platform list (31 to 29).
  Neither platform had active maintenance or community usage.

### 9. Quick upgrade checks (~150 words)

Standard checks following the v0.1.3-v0.1.5 template:
1. `benchbox --version`
2. Smoke benchmark run
3. Confirm validation works (answer files download automatically)
4. If using Redshift: verify connection succeeds without manual timeout tuning
5. If using `benchbox plot`: switch to `benchbox visualize`

---

## Word count target

~1,800 words (slightly longer than v0.1.4/v0.1.5 due to Beta framing section and larger fix surface)

---

## Post structure (following release post template)

```
# BenchBox v0.2.0: Alpha to Beta

{one-sentence intro}

![{image placeholder}]

## TL;DR
## At a glance
## What "Beta" means for BenchBox
## What changed for typical workflows
  ### 1. On-demand TPC answer file downloads
  ### 2. Redshift reliability overhaul
  ### 3. Cloud platform live integration tests
## Major fixes and stability work
  ### Read Primitives Redshift coverage
  ### Dask DataFrame `.isin()`
  ### BigQuery loading correctness
  ### Other fixes
## Release-quality hardening
## Removals
## Changed behavior to be aware of
## Quick upgrade checks
## Bottom line
## Reference
```

---

## Changed behavior to be aware of

- **`benchbox plot` removed**: use `benchbox visualize` instead. The `plot` command is gone,
  not deprecated.
- **Two SQL platforms removed**: Snowpark Connect and Onehouse Quanton are no longer valid
  `--platform` values. If you have scripts referencing these, they will error.
- **Redshift format selection**: Redshift-specific format overrides now apply only to native COPY
  loads. Platform-preference priority over manifest preferences may change which format is
  selected in mixed-format environments.
- **Validation now auto-downloads answer files**: if your environment blocks outbound HTTP,
  set `BENCHBOX_NO_DOWNLOAD=1` and use `benchbox download-answers` on a machine with access.

---

## Image placeholders (to generate before publishing)

- `beta_badge.png` - PyPI classifier or version badge showing Beta status
- `redshift_adaptive_timeout.png` - sequence diagram of adaptive timeout behavior (optional)
- `answer_download_flow.png` - answer file resolution flow: check cache, fetch, verify (optional)

---

## Narrative angle

This release has one overarching story: **closing the gap between "it works for us" and "it
works for you."**

The Alpha period (v0.1.0 through v0.1.5) was about building out capabilities: DataFrame
coverage, charts, driver management, format loading. The Beta transition is about proving those
capabilities work reliably across environments we don't directly control: Redshift clusters in
various states, air-gapped installs, Dask lazy evaluation, BigQuery's format preferences.

The Beta label is not a marketing milestone. It's a statement about test coverage, reliability
fixes, and confidence level. The post should make that concrete: 80% coverage, 40+ Redshift
query rewrites, 5 cloud platforms with live tests, answer files that download on demand.

The bottom line should connect the Alpha-to-Beta arc: v0.1.x built the features; v0.2.0 is where
we started verifying they hold up. We're not done, but we're past the "things break in surprising
ways" phase.

---

## Reference

- Changelog entry: `CHANGELOG.md` (`[0.2.0] - 2026-04-01`)
- Previous release posts: posts #2, #3, #4, #7 in building-benchbox series
