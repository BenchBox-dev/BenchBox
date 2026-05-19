# Chart Types

```{tags} intermediate, reference, visualization
```

BenchBox provides chart types optimized for benchmarking narratives, rendered as ASCII art directly in the terminal. Each chart is designed for a specific analytical purpose and can be generated via `benchbox visualize` or programmatically through the Python API. No external dependencies are required.

## Performance Bar Chart

**Purpose:** Compare execution times across platforms, runs, or configurations. The most common chart for "which platform is fastest?" questions.

**Key Features:**
- Automatic best/worst highlighting (green for fastest, red for slowest)
- Fractional-block precision (Unicode ▏▎▍▌▋▊▉█ characters)
- Automatic sorting by performance (configurable)
- Platform labels with execution time annotations

```text
Performance Comparison (ms)
──────────────────────────────────────────────────────────
DuckDB      ██████████████████                      142.3
Polars      ████████████                             98.7
SQLite      ████████████████████████████████████     285.1
Pandas      ██████████████████████████████████████   320.5

Legend: ■ Best  ■ Worst
```

*TPC-H SF1 comparison across 4 platforms showing Polars as fastest (green) and Pandas as slowest (red)*

**Data Requirements:**
- `total_time_ms` or `avg_time_ms` per result
- At least 1 result (multiple for comparison)

**Best For:**
- Platform shootouts ("DuckDB vs Snowflake")
- Before/after optimization comparisons
- Multi-benchmark summaries

---

## Power@Size Bar Chart

**Purpose:** Compare TPC Power@Size scores across platforms or versions. Power@Size is a TPC-defined throughput metric expressed in queries-per-hour at a given scale factor - higher is better.

**Key Features:**
- Automatic best/worst highlighting (highest score = green, lowest = red)
- Longer bars indicate better throughput performance (inverted vs execution time)
- Silently excluded for non-TPC benchmarks (no Power@Size in result)

```text
Power@Size Comparison (Power@Size)
──────────────────────────────────────────────────────────
DuckDB 1.5.0-dev ███████████████████████████████████████   669.3K
DuckDB 1.4.4     ██████████████████████████████████████    630.9K
DuckDB 1.3.2     ███████████████████████████████████████   614.9K
DuckDB 1.1.3     ██████████████████████████████████████    594.7K
DuckDB 1.2.2     ███████████████████████████████████       500.5K
DuckDB 1.0.0     ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓               385.8K
```

*TPC-DS SF=10 version comparison showing Power@Size progression from v1.0.0 to v1.5.0-dev*

**Data Requirements:**
- `summary.tpc_metrics.power_at_size` in result JSON (present in TPC-H and TPC-DS runs)
- At least 1 result (multiple for comparison)

**Best For:**
- TPC-H and TPC-DS version-over-version comparisons
- Tracking throughput improvement across platform upgrades
- Executive summaries of TPC benchmark results

---

## Time-Series Line Chart

**Purpose:** Track performance evolution over time, across versions, or across sequential runs. Essential for regression detection and trend analysis.

**Key Features:**
- Multi-line support for comparing platforms over time
- Least-squares regression trend overlay
- Unique marker per series (*, +, o, x, ^, v)
- Automatic legend with series names

```text
Performance Trend (ms)
──────────────────────────────────────────────────────────
     │
 350 │*
     │  *
 300 │    *
     │      *
 250 │        *         +
     │          *    +     +
 200 │            *           +
     │                           +
 150 │
     └────────────────────────────────────────────────────
      v0.8   v0.9   v1.0   v1.1   v1.2   v1.3

Legend:
  ─*─ DuckDB
  ─+─ Polars
```

*DuckDB and Polars performance over 6 releases showing improvement trends*

**Data Requirements:**
- At least 2 results with timestamps or execution IDs
- `total_time_ms` per result

**Best For:**
- Version-over-version performance tracking
- Regression detection in CI/CD
- Long-term platform evolution stories

---

## Cost-Performance Scatter Plot

**Purpose:** Visualize the price/performance tradeoff with Pareto frontier highlighting. Critical for cloud platform ROI analysis.

**Key Features:**
- Pareto frontier highlighting (optimal cost-performance points marked with ◆)
- Platform labels positioned at data points
- Performance score calculation (queries/hour or inverse latency)
- Auto-scaled axes with padding

```text
Cost vs Performance
──────────────────────────────────────────────────────────
Perf │
(qph)│                                    * Redshift
 400 │
     │                          ◆ DuckDB
 300 │                    ◆ Polars
     │              ──────────────────── Pareto frontier
 200 │        * Pandas
     │
 100 │  * SQLite
     │
   0 └────────────────────────────────────────────────────
     $0       $50      $100     $150     $200     $250
                     Cost (USD)
```

*Platform comparison showing Pareto frontier highlighting cost-efficient options*

**Data Requirements:**
- `cost_summary.total_cost` per result
- Performance metric (`avg_time_ms` or `total_time_ms`)

**Best For:**
- Cloud platform cost comparisons
- ROI analysis for platform selection
- "Bang for your buck" narratives

---

## Query Variance Heatmap

**Purpose:** Show per-query performance patterns across platforms. Reveals which queries each platform handles well or poorly.

**Key Features:**
- Query (rows) × Platform (columns) grid
- 5-level intensity scale (░ ▒ ▓ █) from fast to slow
- Color gradient: green (fast) → yellow (medium) → red (slow)
- Automatic sorting by query ID

```text
Query Execution Heatmap (ms)
──────────────────────────────────────────────────────────
            DuckDB    Polars    Pandas
Q1    │     ░░ 12.3   ▒▒ 15.2   ▓▓ 45.8
Q2    │     ░░  8.5   ░░  9.1   ▒▒ 22.4
Q3    │     ▒▒ 25.1   ░░ 18.3   ██ 85.2
Q4    │     ░░ 11.2   ▓▓ 40.5   ██120.1
Q5    │     ▒▒ 30.8   ▒▒ 28.9   ▓▓ 52.3
Q6    │     ░░  5.1   ░░  4.8   ░░  8.2

Scale: ░ ▒ ▓ █ (fast → slow)
Range: 4.8 - 120.1 ms
```

*TPC-H per-query heatmap showing performance patterns across platforms*

**Data Requirements:**
- At least 2 platforms with per-query `execution_time_ms`
- Query results with `query_id` identifiers

**Best For:**
- Identifying problematic queries per platform
- TPC-H/TPC-DS per-query analysis
- Query optimization targeting

---

## Distribution Box Plot

**Purpose:** Show latency distributions to understand variance, outliers, and consistency beyond simple averages.

**Key Features:**
- Box plot with quartiles (Q1, median, Q3)
- Whiskers at min/max with cap characters (╷ ╵)
- Outlier markers (o) at actual scaled positions
- Statistics summary below plot

```text
Latency Distribution (ms)
──────────────────────────────────────────────────────────
            ╷     ┌──────┬──────┐           ╷
DuckDB      ├─────┤      │      ├───────────┤
            ╵     └──────┴──────┘           ╵
            ╷   ┌────┬────────┐       ╷
Polars      ├───┤    │        ├───────┤
            ╵   └────┴────────┘       ╵
            ╷          ┌──────────┬─────────────┐     ╷
Pandas      ├──────────┤          │             ├─────┤  o
            ╵          └──────────┴─────────────┘     ╵
────────────┼──────────┼──────────┼──────────┼────────┼──
            0         100        200        300      400  ms

Statistics:
  DuckDB: median=120.5, mean=125.3, std=45.2
  Polars: median=85.2, mean=90.1, std=32.8
  Pandas: median=210.8, mean=225.4, std=78.5
```

*Latency distribution comparison showing Polars as most consistent (tightest box)*

**Data Requirements:**
- Per-query `execution_time_ms` values
- Multiple queries per platform for meaningful distribution

**Best For:**
- Consistency analysis (low variance = predictable performance)
- Outlier detection
- SLA compliance stories (P95/P99 analysis)

---

## Query Latency Histogram

**Purpose:** Display per-query execution latency with one bar per query. Short query IDs render as vertical bars; long descriptive query names render as horizontal bars so labels remain readable. Provides immediate visual insight into which queries are fastest/slowest and the overall latency distribution pattern.

**Key Features:**
- One bar per query showing execution time
- Horizontal layout for long labels such as Primitives query names
- Automatic best/worst highlighting (green for fastest, orange for slowest)
- Mean reference line for quick comparison
- Natural query ID sorting (Q1, Q2, Q10 - not Q1, Q10, Q2)
- **Auto-splits large query sets** - when queries exceed 33, automatically generates multiple charts (e.g., TPC-DS 99 queries → 3 charts)
- Multi-platform grouped bar support for comparisons

```text
Query Latency Histogram (Execution Time (ms))
──────────────────────────────────────────────────────────
     150 │                              ██
         │                              ██
     100 │          ██                  ██    ██
         │    ██    ██    ██            ██    ██
      50 │    ██    ██    ██    ██      ██    ██    ██
         │    ██    ██    ██    ██      ██    ██    ██
       0 └────────────────────────────────────────────────
           Q1   Q2   Q3   Q4   Q5   Q6   Q7   Q8

····· Mean: 87.5 ms

Legend: ■ Best  ■ Worst
```

**Data Requirements:**
- Per-query `execution_time_ms` values
- Query results with `query_id` identifiers
- Aggregates multiple iterations per query (mean latency)

**Best For:**
- Quick identification of slow/fast queries
- TPC-DS (99 queries) and ClickBench (43 queries) analysis
- Spotting outlier queries that need optimization
- Per-query comparison across platforms

**Chart Splitting:**
For large benchmarks, the histogram automatically splits into readable chunks:

| Benchmark | Queries | Charts Generated |
|-----------|---------|------------------|
| TPC-H | 22 | 1 chart |
| SSB | 13 | 1 chart |
| ClickBench | 43 | 2 charts (1-33, 34-43) |
| TPC-DS | 99 | 3 charts (1-33, 34-66, 67-99) |

---

## Comparison Bar Chart

**Purpose:** Side-by-side paired bars per query showing baseline vs comparison performance. Essential for before/after analysis.

**Key Features:**
- Paired rows per query: baseline bar + comparison bar
- Inline percentage change (green for improvement, red for regression)
- Scale note showing value per block character
- Handles outlier truncation with overflow indicator

```text
SQL vs DataFrame Comparison (ms)
──────────────────────────────────────────────────────────
Q1   SQL  ████████████████████████  240.5
     DF   ██████████████████        180.2       -25.1%
Q2   SQL  ████████████████          160.0
     DF   ████████████████████████  240.8       +50.5%
Q3   SQL  ████████████████████      200.0
     DF   ████████████████          160.0       -20.0%
──────────────────────────────────────────────────────────
each █ ≈ 10.0ms
  improvement (negative %)   regression (positive %)
```

**Data Requirements:**
- Two result files (baseline + comparison)
- Per-query `execution_time_ms` values

**Best For:**
- Before/after optimization comparisons
- SQL vs DataFrame API performance
- Version-over-version per-query analysis

---

## Diverging Bar Chart

**Purpose:** Percentage change bars centered on zero, showing improvements to the left and regressions to the right. Sorted by magnitude for quick triage.

**Key Features:**
- Left side (green): improvements; right side (red): regressions
- Fill intensity based on magnitude (░ weak, ▒ medium, ▓ strong)
- Overflow arrows (──►) for extreme outliers beyond clipping threshold
- Summary line with improvement/stable/regression counts

```text
Regression / Improvement Distribution
──────────────────────────────────────────────────────────
                  Faster  |  Slower
Q6   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ |                        -57.2%
Q14  ▓▓▓▓▓▓▓▓▓▓▓         |                        -38.1%
Q3             ░░░░░░░░░░ |                         -5.2%
Q1                        | ░░░░░░░░░               +4.8%
Q17                       | ▒▒▒▒▒▒▒▒▒▒▒▒▒▒        +23.4%
Q21                       | ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒──►   +726.0%
──────────────────────────────────────────────────────────
  2 improved  1 stable  3 regressed
```

**Data Requirements:**
- Two result files (baseline + comparison)
- Per-query `execution_time_ms` values

**Best For:**
- Regression triage after upgrades
- Identifying queries that improved vs degraded
- Quick visual summary of change distribution

---

## Summary Box

**Purpose:** Key statistics in a bordered panel providing an at-a-glance overview of benchmark results or a comparison between two runs.

**Key Features:**
- Bordered box with Unicode box-drawing characters
- Comparison mode: baseline → comparison with percentage change
- Color-coded percentages (green for improvement, red for regression)
- Best/worst query callouts

```text
┌──────────────────────────────────────────────┐
│            Benchmark Summary                 │
├──────────────────────────────────────────────┤
│  Geo Mean:  142.3ms → 98.7ms         -30.6% │
│  Total:     3.2s → 2.1s              -34.4% │
│  Queries:   22                               │
├──────────────────────────────────────────────┤
│  5 improved  12 stable  5 regressed          │
├──────────────────────────────────────────────┤
│  Best:  Q6 (-57.2%), Q14 (-38.1%)           │
│  Worst: Q21 (+726%), Q17 (+23.4%)           │
└──────────────────────────────────────────────┘
```

**Data Requirements:**
- At least 1 result file (2 for comparison mode)
- `total_time_ms` and/or per-query `execution_time_ms`

**Best For:**
- Executive summaries at the top of reports
- CI/CD log output (quick pass/fail context)
- Pairing with detailed charts for full analysis

---

## Chart Selection Guide

| Scenario | Recommended Chart |
|----------|-------------------|
| "Which platform is fastest?" | Performance Bar |
| "What is the TPC throughput score?" | Power@Size Bar |
| "How has performance changed over time?" | Time-Series Line |
| "Which platform has best price/performance?" | Cost-Performance Scatter |
| "Which queries does each platform struggle with?" | Query Variance Heatmap |
| "Which individual queries are slowest?" | Query Latency Histogram |
| "How consistent is query latency?" | Distribution Box |
| "How did each query change between runs?" | Comparison Bar |
| "Which queries regressed or improved?" | Diverging Bar |
| "Give me a quick summary" | Summary Box |
| "Complete platform evaluation" | Use `--template flagship` for all |

## Data Requirements Summary

| Chart Type | Required Fields | Minimum Results |
|------------|-----------------|-----------------|
| Performance Bar | `total_time_ms` or `avg_time_ms` | 1 |
| Power@Size Bar | `summary.tpc_metrics.power_at_size` | 1 (TPC benchmarks only) |
| Time-Series Line | `total_time_ms` + timestamps | 2 |
| Cost-Performance Scatter | `cost_summary.total_cost` + timing | 1 (2+ useful) |
| Query Variance Heatmap | `queries[].execution_time_ms` | 2 platforms |
| Query Latency Histogram | `queries[].execution_time_ms` | 1 |
| Distribution Box | `queries[].execution_time_ms` | 1 |
| Comparison Bar | `queries[].execution_time_ms` | 2 (baseline + comparison) |
| Diverging Bar | `queries[].execution_time_ms` | 2 (baseline + comparison) |
| Summary Box | `total_time_ms` or `queries[]` | 1 (2 for comparison) |
