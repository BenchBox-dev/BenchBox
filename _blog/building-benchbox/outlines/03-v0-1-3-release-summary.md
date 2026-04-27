# Outline: BenchBox v0.1.3 release summary

**Series**: Building BenchBox
**Post type**: Release Notes
**Status**: PLANNING
**Target file**: `docs/blog/2026-02-23-v0-1-3-release-summary.md`
**Mirrors**: `docs/blog/2026-02-15-v0-1-2-release-summary.md`

---

## Thesis

v0.1.3 deepens the ASCII chart system (more types, no-color fallbacks, auto-display after runs),
introduces driver flexibility (version pinning, optional extras for a leaner install), and
ships a faster bulk-loading path for multi-shard data. Reliability fixes address a DataFrame
cache mismatch, a ClickHouse decompression bug, and platform display-name inconsistencies.

---

## Headline themes

| Theme | v0.1.3 changes |
|-------|---------------|
| Charts | 5+ new types, no-color fallbacks, auto post-run display, 3 new templates |
| Driver flexibility | `driver_version` pinning, 4 drivers moved to optional extras |
| Performance | Bulk multi-shard loading for DuckDB and ClickHouse |
| Reliability | DataFrame cache fix, ClickHouse decompression fix, display-name cleanup |

---

## Front matter

```yaml
blogpost: true
date: Feb 23, 2026
author: Joe Harris
tags: benchbox, release, changelog, charts, drivers, performance
```

---

## Post structure (mirrors v0.1.2)

### Opening (2-3 sentences)

- Release date: February 23, 2026
- One-sentence framing of what this release is about

### Image

- Placeholder: post-run chart auto-display output (screenshot or ASCII inline)
- Suggested filename: `images/post_run_chart_v013.png`

### TL;DR (bullet list)

- ASCII charts: 5 new types, no-color fallbacks, and auto-display after every run
- Charts are now automatically shown in the terminal at the end of each benchmark run
- Drivers for DuckDB, Polars, ClickHouse Connect, and PostgreSQL are now optional extras for leaner installs
- New `driver_version` pinning: lock any platform driver to a specific version
- Bulk multi-shard loading speeds up TPC-DS runs on DuckDB and ClickHouse
- Key reliability fixes: DataFrame cache path, ClickHouse decompression, platform display names

### At a glance (table)

| Area | What changed in v0.1.3 | Why it matters |
|------|------------------------|----------------|
| Charts - new types | Percentile ladder, stacked bar, sparkline, CDF, rank table, normalized speedup | More analysis options without leaving the terminal |
| Charts - no-color | Fill-pattern/glyph fallbacks for CI, NO_COLOR, piped output | Charts are readable in any environment |
| Charts - auto-run | Post-run summaries generated and displayed automatically | Immediate feedback without a separate visualize step |
| Chart templates | 3 new bundles: latency_deep_dive, regression_triage, executive_summary | Pre-composed chart sets for common analysis flows |
| Driver pinning | `--platform-option driver_version=X.Y.Z` + `driver_auto_install=true` | Reproducible benchmarks across different driver releases |
| Optional extras | DuckDB, Polars, ClickHouse Connect, psycopg2 no longer hard deps | Leaner installs; easier to pin drivers independently |
| Bulk loading | `load_table_bulk()` for DuckDB and ClickHouse | Measurably faster TPC-DS ingestion with sharded data |
| Reliability | Cache path fix, decompression fix, display-name corrections | Fewer silent failures during data generation and load |

### What changed for typical workflows (numbered sections, Before/Now)

#### 1. Charts appear after every benchmark run

**Before**: Charts were generated on demand via a separate `benchbox visualize` command.
**Now**: Post-run summaries are automatically generated and displayed at the end of every
`benchbox run` invocation, and included in MCP `run_benchmark` responses.

Bullets:
- No separate step required to see query time distributions
- MCP callers get chart content inline in the response
- Auto-generated using the default chart template for the benchmark type

#### 2. More ASCII chart types and no-color environments

**Before**: Seven chart types; all relied on ANSI color codes for differentiation.
**Now**: Twelve chart types; all have greyscale/no-color fallbacks using Unicode fill patterns.

Bullets:
- New chart types: percentile ladder, stacked bar, sparkline table, CDF, rank table, log2-scaled speedup
- Three new template bundles map to common analysis workflows (latency, regressions, executive)
- CI environments, `NO_COLOR`, and piped output now render legible charts

#### 3. Driver version pinning and optional extras

**Before**: Drivers bundled as hard dependencies at fixed versions; no way to test a different driver without modifying the environment manually.
**Now**: `--platform-option driver_version=X.Y.Z` pins the driver for a specific run; `driver_auto_install=true` handles the install automatically.

Bullets:
- Driver version is shown in the run announcement line for clear audit trails
- DuckDB, Polars, ClickHouse Connect, and psycopg2 are now `benchbox[duckdb]` etc. extras
- `pip install benchbox[all]` restores the previous all-inclusive behavior

### Major additions (detailed subsections)

#### ASCII chart system: new types

List and briefly describe each new type:
- **Percentile ladder**: p50/p95/p99 distribution across queries in a vertical ladder layout
- **Stacked bar**: compare multiple metrics or categories per query side-by-side
- **Sparkline table**: compact per-query trend lines in a table
- **CDF (cumulative distribution)**: visualize query time distributions across percentiles
- **Rank table**: rank queries by performance metric with delta indicators
- **Normalized speedup**: log2-scaled comparison to a baseline platform or run

#### ASCII chart system: no-color fallbacks

Explain the problem (CI, piped output, accessibility) and the solution (Unicode fill blocks,
hatch patterns, cell shading). Note standardized `no_color` detection path shared across all
chart renderers.

#### Post-run chart auto-display

Explain how this integrates into the run pipeline and MCP. Short code example showing what the
terminal output looks like after a run (use a representative ASCII chart block or screenshot reference).

#### Chart template bundles

Describe the three new bundles:
- `latency_deep_dive`: percentile ladder + CDF + query time breakdown
- `regression_triage`: comparison bar + rank table + sparkline for trend analysis
- `executive_summary`: high-level summary charts suitable for reporting

#### Driver version pinning

Show the usage pattern:
```bash
benchbox run --platform duckdb --benchmark tpch \
  --platform-option driver_version=1.1.3 \
  --platform-option driver_auto_install=true
```
Note that the active driver version is displayed in the run announcement.

#### Bulk multi-shard loading

Explain the `load_table_bulk()` interface and which handlers implement it (DuckDB CSV/Parquet,
ClickHouse Native). Note measurably faster TPC-DS ingestion for sharded data.

### Major fixes and stability work

#### DataFrame cache path fix

Before: SQL and DataFrame modes used different directory structures, forcing re-generation
when switching modes at the same scale factor.
After: Both modes share a flat layout; cached data is reused correctly.

#### ClickHouse decompression fix

Before: `ClickHouseNativeHandler` applied manual zstd decompression on top of the driver's
built-in decompression, corrupting bulk load data.
After: Double-decompression eliminated.

#### Platform display names

Corrected display names:
- Amazon Athena (was "AWS Athena")
- Google Cloud Dataproc (was "GCP Dataproc")
- Microsoft Azure platforms
- Databricks (now "Databricks SQL")

`adapter.get_platform_info()` propagated to match.

#### Other fixes

- CLI warning when a platform option's default value is not in the declared choices list
- Ranking normalization crash when all metric values are negative finite numbers
- PySpark SIGINT handler hanging `pytest-xdist` workers
- `--validation-mode` CLI prompt crash when `spec.default` is not a string
- Driver auto-install version switching: module cache now invalidated after version swap

### Changed behavior to be aware of

- DuckDB, Polars, ClickHouse Connect, and psycopg2 are no longer installed by default.
  Run `pip install benchbox[duckdb]` (or `benchbox[all]`) to restore previous behavior.
- Existing installs that relied on these packages being present may need to add the relevant extras.
- All terminal output now flows through `emit()`. If you capture BenchBox output programmatically,
  `--quiet` and non-interactive mode behavior is now consistent across all pipeline stages.

### Quick upgrade checks

Steps (numbered), mirroring v0.1.2 format:
1. Check version: `benchbox --version`
2. Install extras if needed: `pip install benchbox[duckdb] benchbox[polars]`  (or `benchbox[all]`)
3. Run a smoke benchmark and confirm post-run charts appear automatically
4. If using driver version pinning, test with `--platform-option driver_version=X.Y.Z`
5. If running TPC-DS with sharded data, note load time improvement

### Bottom line

v0.1.3 is focused on making benchmark output more useful out of the box:
- terminal-native charts appear automatically after every run,
- more chart types and fallbacks mean results are readable everywhere,
- and driver pinning gives teams reproducibility across releases.

Frame as: v0.1.2 laid the ASCII chart foundation; v0.1.3 makes it complete and production-ready.

### Reference

- Changelog entry: `CHANGELOG.md` (`[0.1.3] - 2026-02-23`)

---

## Word count target

600-900 words (release notes type per style guide: 500-1,000 words)

---

## Writing notes

- No em-dashes or en-dashes (ASCII hyphen only)
- Sentence-case headings
- Use "we" not "I"
- For the driver extras section, note trade-off: leaner default, extra install step required
- Avoid superlatives; let the change list speak for itself
- Image: if a screenshot of post-run chart auto-display is available, include it under the
  opening (same slot as `query_histogram.png` in v0.1.2)
