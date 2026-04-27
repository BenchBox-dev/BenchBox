---
title: "BenchBox v0.1.4: release summary"
series: building-benchbox
post_number: 4
type: release-notes
tags: [benchbox, release, changelog, query-plans, charts, accuracy]
status: OUTLINE
---

# Outline: BenchBox v0.1.4 release summary

> **Note**: v0.1.4 not yet tagged. This outline is planned from unreleased commits since v0.1.3.
> Finalize after tagging: confirm version number, release date, and any additional commits.

---

## Theme

v0.1.4 is about **accuracy**: the numbers BenchBox surfaces now reflect what actually happened.

- Query plan capture now collects **actual execution timing**, not estimated plans.
- ASCII charts now handle **outlier data correctly** without distorting scale for normal queries.
- Phase durations (load, datagen) and per-table timings are now **propagated correctly** through
  the result pipeline.

These aren't new capabilities - plan capture and ASCII charts shipped in v0.1.2/0.1.3. v0.1.4
is what happens when you use those features under real conditions and fix what breaks.

---

## TL;DR (draft bullets)

- Query plan capture now uses **EXPLAIN ANALYZE** by default, recording actual execution timing
  alongside the plan structure. Set `analyze_plans: false` to opt out.
- New **`power_bar` chart type** visualizes TPC Power@Size scores. Added to flagship,
  head_to_head, trends, regression_triage, and executive_summary templates.
- ASCII charts now handle **outlier queries correctly** - extreme values no longer compress the
  rest of the chart into an unreadable sliver.
- **Per-table load timings** and datagen phase duration are now recorded and exported in result
  files.
- SSB query IDs with dots (Q2.1, Q3.2) now work in `--queries` and `show-plan` / `compare-plans`.
- `--quiet` mode now emits the result filepath to stdout for scripting and CI.

---

## At a glance table

| Area                  | What changed in v0.1.4                                              | Why it matters                                                          |
| --------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Query plan capture    | EXPLAIN ANALYZE by default; actual timing in plans                  | Plan data matches what the query actually did, not what the optimizer predicted |
| Charts - power_bar    | New chart type for TPC Power@Size scores                            | Compare throughput across versions/platforms at a glance                |
| Charts - outliers     | Outlier truncation across all chart types                           | Extreme queries no longer collapse the rest of the chart                |
| Result pipeline       | Per-table load timings, datagen duration, explicit duration override | Complete timing picture across all phases in result files               |
| SSB query IDs         | Dot notation (Q2.1) in --queries and CLI plan commands              | SSB benchmarks work consistently with query selection                   |
| Quiet mode            | Result filepath emitted to stdout in --quiet                        | Easier scripting: pipe result path directly without parsing output      |
| Runtime validation    | ABI validation for isolated driver installs                         | Prevents crashes from incompatible driver binaries                      |

---

## Section breakdown

### 1. Query plan capture: EXPLAIN ANALYZE by default (~350 words)

**Before**: `--capture-plans` ran `EXPLAIN (FORMAT JSON)`, capturing the optimizer's estimated
plan: structure, estimated rows, estimated costs. Useful for understanding the plan shape, but
the timing shown was the optimizer's prediction, not measured execution time.

**Now**: `EXPLAIN (ANALYZE, FORMAT JSON)` is the default. The plan includes actual elapsed time
per node, actual row counts, and loop counts - the same data you'd see running EXPLAIN ANALYZE
manually in psql or DuckDB's shell.

This matters when diagnosing regressions: the plan shape might not have changed, but a specific
node's actual runtime can reveal where time went. Version comparisons with plan capture enabled
now show whether the optimizer changed its strategy *and* whether that changed execution time.

Opt out per-platform with `analyze_plans: false` in your tuning config if you want estimated
plans only (e.g., for platforms where ANALYZE has significant overhead):

```yaml
# tuning.yaml
analyze_plans: false
```

Cover: DuckDB FORMAT JSON handling fix (dict extra_info), plan preservation through normalize
pipeline, show-plan / compare-plans loading fix.

### 2. power_bar chart type (~250 words)

**New chart type**: `power_bar` visualizes TPC Power@Size scores as a horizontal bar chart.
Higher bars = better throughput. Contrast with `performance_bar`, where lower is better.

`power_at_size` is extracted from `summary.tpc_metrics.power_at_size` in the result JSON.
Returns `None` gracefully for non-TPC benchmarks, so it's safe to include in any template.

Added to five templates: flagship, head_to_head, trends, regression_triage, executive_summary.
The chart renders only when TPC metric data is present; non-TPC runs skip it silently.

Include code example:

```bash
benchbox visualize benchmark_runs/results/<result>.json --chart power_bar
```

### 3. Outlier handling in ASCII charts (~300 words)

**Before**: one extreme outlier (e.g., a cold-cache query taking seconds while others finished in
milliseconds, or a query with a bad plan) could compress everything else in a chart into a few
pixels at the left edge, making the chart useless for comparing the rest of the queries.

**Now**: outlier truncation is applied across all chart types. Values beyond the capping
threshold are marked with a truncation indicator; the axis scales to the non-outlier range.

Which charts: bar, histogram, stacked bar, scatter, line, CDF, percentile ladder, heatmap,
box plot (separate fix for severity marker interleaving).

Additional chart fixes in this release:
- Natural sort for query IDs (Q1, Q2, ..., Q10 instead of Q1, Q10, Q11, Q2)
- Color cycling correctness
- Width cap raised from 120 to 400 characters (better on wide terminals / MCP)

### 4. Result pipeline accuracy (~250 words)

Several result accuracy fixes that are quiet but important for users who analyze load phase
performance or pipe result files into downstream tooling.

**Per-table load timings**: each table's load time is now recorded and exported in
`table_statistics` in the result JSON. Previously, per-table timing was measured but not
propagated through the result builder.

**Datagen phase metrics**: datagen manifest stats (files generated, rows, duration) are now
surfaced in phase metadata. Previously, the datagen phase appeared with no duration.

**Load phase duration**: the load phase duration key was wrong, causing phase timing to appear
as zero. Fixed.

These changes don't require any workflow changes - result files now contain more complete timing
data.

### 5. Quick upgrade checks (~150 words)

Standard checks matching v0.1.2/0.1.3 template:
1. `benchbox --version`
2. Smoke run
3. If using `--capture-plans`: confirm EXPLAIN ANALYZE timing appears in plan output
4. If using SSB with query selection: verify dot-notation IDs work
5. If scripting with `--quiet`: update to capture result filepath from stdout

### 6. Other fixes (brief)

- SSB customer row count expectation corrected in SSBRowCountStrategy
- Runtime ABI validation for isolated driver installs (prevents SIGSEGV-class crashes on
  incompatible binaries)
- Benchmark runtime harmonization for nyctaxi and tsbs_devops (internal; no workflow changes)

---

## Word count target

~1,400 words (consistent with v0.1.2 and v0.1.3 length)

---

## Post structure (following v0.1.2 / v0.1.3 template)

```
# BenchBox v0.1.4: release summary

{one-sentence intro}

![{image placeholder}]

## TL;DR
## At a glance
## What changed for typical workflows
  ### 1. Query plan capture: actual execution timing
  ### 2. power_bar chart type
  ### 3. Outlier handling in ASCII charts
## Major additions
## Major fixes and stability work
## Changed behavior to be aware of
## Quick upgrade checks
## Bottom line
## Reference
```

---

## Changed behavior to be aware of

- `--capture-plans` now runs EXPLAIN ANALYZE by default. This adds query execution overhead
  during plan capture runs (queries execute twice: once for the benchmark result, once for the
  plan). Use `analyze_plans: false` to opt out.

---

## Image placeholders (to generate before publishing)

- `post_run_chart_v014.png` - post-run chart showing power_bar in a template
- `outlier_before.png` - chart before outlier fix (query compressing everything)
- `outlier_after.png` - same chart after outlier fix (readable scale)
- `explain_analyze_plan.png` - plan output showing actual timing nodes

---

## Reference

- Changelog entry: `CHANGELOG.md` (`[0.1.4]` - pending)
- Key commits: `40a00a968` (EXPLAIN ANALYZE default), `310f3e167` (power_bar),
  `531f00aae` (outlier/natural sort), `5cf6ef406` + series (outlier across chart types),
  `d57f0d2a3` (per-table timings), `4813110cc` (datagen metrics)
