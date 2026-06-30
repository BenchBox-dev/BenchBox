# Query Plan Analysis

```{tags} advanced, guide, performance
```

BenchBox supports capturing, analyzing, and comparing query execution plans across different database platforms. This feature enables:

- **Cross-platform comparison**: Understand how different databases optimize the same query
- **Regression detection**: Track plan changes between software versions
- **Optimization analysis**: Identify query optimization opportunities

## Table of Contents

- [Quick Start](#quick-start)
- [Capturing Query Plans](#capturing-query-plans)
- [Viewing Plans](#viewing-plans)
- [Comparing Plans](#comparing-plans)
- [Understanding Plan Differences](#understanding-plan-differences)
- [Programmatic Usage](#programmatic-usage)
- [Troubleshooting](#troubleshooting)

## Quick Start

```bash
# 1. Run benchmark with plan capture
benchbox run --platform duckdb --benchmark tpch --scale 1 --capture-plans

# 2. View a specific plan
benchbox show-plan --run benchmark_runs/latest/results.json --query-id q05

# 3. Compare plans between two runs
benchbox compare-plans \
  --run1 run_before.json \
  --run2 run_after.json \
  --query-id q05
```

## Capturing Query Plans

### Basic Capture

Add the `--capture-plans` flag to any benchmark run:

```bash
benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --scale 1 \
  --capture-plans
```

This captures the logical query plan for each query executed during the benchmark.

### Supported Platforms

Plan capture is the default for every EXPLAIN-based engine (see "Capture Isolation" below); the
table lists the platforms with the most mature parsers. BigQuery is the one side-effect engine that
harvests its plan from the executed job rather than via `EXPLAIN`.

| Platform    | Parser Status | EXPLAIN Format                          | Notes                                                    |
|-------------|---------------|-----------------------------------------|----------------------------------------------------------|
| DuckDB      | ✓ Stable      | JSON (`EXPLAIN (ANALYZE, FORMAT JSON)`) | Actual per-operator timing; ~1× query cost overhead      |
| SQLite      | ✓ Stable      | Text (tree)                             | Simple tree format                                       |
| PostgreSQL  | ✓ Stable      | JSON                                    | SELECT: `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`; DML: `EXPLAIN (FORMAT JSON)` only |
| Redshift    | ✓ Beta        | Text                                    | Supports XN prefixed operators                           |
| DataFusion  | ✓ Beta        | Text (indent)                           | Physical plan operators                                  |

Plans are captured using platform-specific `EXPLAIN` commands and parsed into a unified logical representation.

### Performance Impact

Plan capture overhead depends on the platform:

- **DuckDB** (default): uses `EXPLAIN (ANALYZE, FORMAT JSON)`, which re-executes the query to collect
  actual per-operator timing and cardinality. Overhead is approximately **1× query cost** per captured
  plan — a 2-second query costs ~2 extra seconds. Disable re-execution with
  `--no-analyze-plans` to use estimated plans only (~1-5 ms overhead). The capture re-run happens
  in the isolated post-measurement phase, so it never inflates the measured query time.
- **PostgreSQL** (SELECT queries): uses `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, which also
  re-executes the query. Overhead is approximately **1× query cost** per captured plan.
- **PostgreSQL** (DML — INSERT/UPDATE/DELETE/MERGE): uses `EXPLAIN (FORMAT JSON)` without
  ANALYZE to prevent double-execution of writes. Overhead is low (~1-5 ms, estimated plan only).
  Note: PostgreSQL `EXPLAIN` does not accept `COPY`, so COPY statements are not plan-captured.
- **Redshift, DataFusion, SQLite**: estimated plans only (no ANALYZE), adds ~1-5 ms per query.

In all cases:
- Benchmark timing measurements are unaffected (plan capture runs after the timed execution)
- Failed plan captures are logged but don't halt execution

### Capture Isolation (the canonical post-measurement phase)

Query plan capture is a **fully separate, fully isolated** concern from the timed measurement run.
There is exactly **one capture path** for every EXPLAIN-based engine: a single post-measurement
phase that runs after all timed queries of *every* test type (power, throughput, maintenance,
combined) complete. After measurement, BenchBox issues one `EXPLAIN` pass over the
successfully-executed queries on the measurement connection and merges the resulting
`plan_fingerprint` / `query_plan` back into each query result. This means:

- **Default-ON for every EXPLAIN engine.** Plan capture via the isolated phase is the default for
  all engines whose plan a standalone `EXPLAIN` reproduces — DuckDB, MotherDuck, PostgreSQL,
  Redshift, SQLite, DataFusion, ClickHouse, Athena, Presto/Trino/Starburst, Spark, Databricks,
  Snowflake, Firebolt, Doris, SingleStore, Databend, Azure Synapse, Fabric, and others. There is
  no per-adapter opt-in.
- **No EXPLAIN on the measurement path.** Capture never interleaves with a timed query or holds the
  connection between measured queries — the `EXPLAIN` pass runs strictly after the timed loop, so
  measured per-query execution times are never inflated by capture cost, for any test type.
- **`analyze_plans` is the one and only capture-detail knob.** It is a first-class flag:
  `--analyze-plans` (the default) re-runs each SELECT once with `EXPLAIN (ANALYZE)` *after*
  measurement, so captured plans carry actual per-operator timing and cardinality (~1× extra query
  cost, outside the measured window); `--no-analyze-plans` uses a static (non-`ANALYZE`) `EXPLAIN`,
  giving estimated plans only with no re-execution cost (~1-5 ms). The structural `plan_fingerprint`
  is identical either way (it excludes timing/cardinality by design); the measured execution times
  in the result bundle remain the authoritative timings.
  **Note:** only engines whose `EXPLAIN` has an ANALYZE mode (DuckDB, MotherDuck, PostgreSQL) honour
  the knob. SQLite (`EXPLAIN QUERY PLAN`), DataFusion, and Redshift (plain `EXPLAIN`) have no ANALYZE
  mode: they always capture a static, estimated plan and `analyze_plans` is a no-op for them (no
  per-operator timing is available).
- **DML runs exactly once.** Even with `--analyze-plans`, an INSERT/UPDATE/DELETE/MERGE/COPY (or
  CTAS / `SELECT ... INTO`) query is downgraded to a non-`ANALYZE` `EXPLAIN` by the shared
  `is_dml_query` write guard, so writes are captured without being re-executed a second time.
- **Capture once per query.** Each distinct executed query is captured exactly once — a plan is a
  property of `(query, schema, engine)`, not of an execution. `--plan-config queries:<ids>`
  restricts *which* queries are captured. The old per-iteration / per-stream sampling options
  (`sample:` / `first:`) have been retired: under capture-once-per-query they had no meaning.

The single genuine exception is **BigQuery**: it has no `EXPLAIN` statement (the real plan and
stage timing are only available from the executed `QueryJob`), so it sets
`plan_capture_phase_eligible = False` and harvests its plan from the completed job rather than
through the isolated phase. `analyze_plans` is a no-op for it.

#### Mid-run data mutation: capture before the mutation

The isolated `EXPLAIN` pass runs *after* the timed loop, so for a **read-only** workload it sees the
exact data state every query was measured against — captured plans and their cardinality estimates
match what the optimizer chose during measurement. Standard TPC-H/TPC-DS **power** and **throughput**
sets are `SELECT`-only, so this is always true for them.

A workload that **mutates data mid-run** would otherwise break that guarantee. In **combined mode**
the order is *power → throughput → maintenance*: the maintenance step (TPC-H RF1/RF2 inserts+deletes,
TPC-DS data maintenance) changes table cardinalities, so a single capture pass at the very end would
`EXPLAIN` the power/throughput read queries against the **post-maintenance** data — describing a plan
the optimizer never chose during measurement.

BenchBox resolves this by capturing **before the mutation**. A capture *checkpoint* runs at the start
of the maintenance phase — after the read phases, before any maintenance write — so the
power/throughput plans are EXPLAINed against the pre-maintenance state they were measured against.
The maintenance writes themselves are then captured in the final post-measurement pass (downgraded to
a non-`ANALYZE` `EXPLAIN`, so they are never re-executed). Each query is still captured exactly once,
and plans are attached to result rows once, at the end. The checkpoint runs strictly between phases —
never inside a timed query or a concurrent throughput stream — so measured timings are unaffected.

Capture is driven by the recorded-query buffer (every distinct query that succeeded during the timed
run), and each captured plan is attached to its result row by the exact recorded query, or — for the
TPC power/throughput drivers, whose result rows carry only the query id — by that query id when it
maps to a single executed SQL variant.

> **Seed-varied throughput streams and bespoke DML query sets.** When one query id runs as *several*
> distinct SQL variants in the same run (e.g. throughput streams rendered with different seeds), a
> result row that carries only the query id cannot be matched to the specific variant it ran, so its
> plan is left unattached rather than risk pairing it with another variant's plan (literal-normalized
> fingerprints, tracked separately, make these variants structurally equal). Likewise, a *bespoke*
> query set that runs an `INSERT`/`UPDATE`/`DELETE` partway through and then more `SELECT`s has no
> maintenance phase boundary, so the isolated model captures those later reads against the end-of-run
> state. Keep data-mutating steps in a maintenance phase (or a separate run) when you need read-query
> fingerprints to reflect their measured data state.

### Captured Fields

Each query result includes three plan-related fields when `--capture-plans` is active:

| Field | Type | Description |
|-------|------|-------------|
| `query_plan` | `QueryPlan \| None` | Parsed logical plan tree; `None` if capture failed or was skipped |
| `plan_fingerprint` | `str \| None` | SHA256 of the plan's logical structure; `None` when `query_plan` is `None` |
| `plan_capture_time_ms` | `float \| None` | Wall-clock milliseconds spent on plan capture (excludes the *timed* benchmark execution; see note below) |

`plan_fingerprint` is `None` when `query_plan` is `None`. Both are `None` when `--capture-plans` is
not set or when the query was excluded by `--plan-config`.

> **`plan_capture_time_ms` is the full capture overhead, including EXPLAIN execution — not parse-only.**
> Plan capture runs in a separate post-measurement phase, so it never affects the timed benchmark
> result. But the metric does include the cost of running `EXPLAIN` itself. On DuckDB the default
> `EXPLAIN (ANALYZE, FORMAT JSON)` **re-executes the query**, so `plan_capture_time_ms` there is
> roughly the query's own runtime plus parsing (~1× query cost), not a few milliseconds of parsing.
> Engines that capture estimated plans only (Redshift, DataFusion, SQLite, PostgreSQL DML) add just
> ~1-5 ms because no re-execution occurs.

## Viewing Plans

### Tree View (Default)

Display a plan as an ASCII tree:

```bash
benchbox show-plan \
  --run results.json \
  --query-id q05
```

Output example:
```
Query Plan: q05
Platform: duckdb
Cost: 500.25 | Rows: 50

└── Aggregate (aggs=[COUNT(*), SUM(o_totalprice)])
    └── Join (type=inner)
        ├── Filter (filter='o_orderdate > '2023-01-01'')
        │   └── Scan (table=orders)
        └── Scan (table=customer)
```

### Summary View

Show statistics without the full tree:

```bash
benchbox show-plan \
  --run results.json \
  --query-id q05 \
  --format summary
```

Output example:
```
Query: q05 (duckdb)
Total Operators: 5
Max Depth: 3
Estimated Cost: 500.25
Estimated Rows: 50

Operator Breakdown:
  Scan: 2
  Filter: 1
  Join: 1
  Aggregate: 1
```

### JSON Export

Export plan for programmatic analysis:

```bash
benchbox show-plan \
  --run results.json \
  --query-id q05 \
  --format json > plan_q05.json
```

### Visualization Options

Control tree display:

```bash
# Compact view without operator properties
benchbox show-plan --run results.json --query-id q05 --compact --no-properties

# Limit tree depth for very complex plans
benchbox show-plan --run results.json --query-id q05 --max-depth 3
```

## Comparing Plans

### Compare Single Query

Compare the same query between two benchmark runs:

```bash
benchbox compare-plans \
  --run1 results_duckdb.json \
  --run2 results_datafusion.json \
  --query-id q05
```

Output example:
```
================================================================================
QUERY PLAN COMPARISON
================================================================================

Left:  q05 (duckdb)
Right: q05 (datafusion)

Plans are very similar (85.3% similarity)

Similarity Metrics:
  Overall:     85.3%
  Structural:  100.0%
  Operator:    100.0%
  Property:     66.7%

Operators: 5 (left) vs 5 (right)
  Matching:   4
  Property mismatches: 1

Property Differences (1):
  • Join type: inner ≠ hash_join

================================================================================
```

### Compare All Queries

Compare all queries from two runs:

```bash
benchbox compare-plans \
  --run1 before_optimization.json \
  --run2 after_optimization.json
```

Output example:
```
┌───────┬────────────┬──────────┬──────────┬─────────────┬─────────────────────┐
│ Query │ Similarity │ Type Diff│ Prop Diff│ Struct Diff │ Status              │
├───────┼────────────┼──────────┼──────────┼─────────────┼─────────────────────┤
│ q01   │     98.5%  │    -     │    1     │      -      │ ✓ Nearly Identical  │
│ q02   │    100.0%  │    -     │    -     │      -      │ ✓ Nearly Identical  │
│ q03   │     87.2%  │    1     │    2     │      -      │ ≈ Very Similar      │
│ q05   │     45.8%  │    5     │    3     │      2      │ ✗ Different         │
└───────┴────────────┴──────────┴──────────┴─────────────┴─────────────────────┘

Summary: 4 queries compared
  Nearly Identical (≥95%): 2
  Very Similar (75-95%):   1
  Different (<50%):        1
```

### Regression Detection

Show only queries with significant plan changes:

```bash
benchbox compare-plans \
  --run1 version_1.2.json \
  --run2 version_1.3.json \
  --threshold 0.9
```

This shows only queries with <90% similarity, helping identify potential regressions.

### JSON Export

Export comparison results for further analysis:

```bash
benchbox compare-plans \
  --run1 run_a.json \
  --run2 run_b.json \
  --output json > comparison_results.json
```

## Understanding Plan Differences

### Similarity Metrics

The comparison engine provides four similarity scores:

1. **Overall Similarity (0-100%)**
   - Weighted average of all metrics
   - Formula: 40% structural + 40% operator + 20% property
   - Best indicator of plan similarity

2. **Structural Similarity**
   - Measures tree structure matching
   - Counts operators at each level
   - 100% = same number of operators at each level

3. **Operator Similarity**
   - Measures operator type matching
   - Compares Scan, Join, Filter, Aggregate, etc.
   - 100% = all operators have matching types

4. **Property Similarity**
   - Measures property matching when types match
   - Compares table names, join types, filters, etc.
   - 100% = all properties identical

### Difference Types

**Type Mismatches**
- Different operator types at same position
- Example: `Scan` vs `IndexScan`
- Often indicates algorithmic differences

**Property Mismatches**
- Same operator type, different properties
- Example: `INNER JOIN` vs `LEFT JOIN`
- Usually indicates optimizer choices

**Structure Mismatches**
- Different tree structure
- Example: Different number of children
- Indicates major plan reorganization

### Interpretation Guide

| Similarity | Interpretation | Common Causes |
|------------|----------------|---------------|
| ≥95% | Nearly Identical | Minor property changes, equivalent optimizations |
| 75-95% | Very Similar | Different join orders, equivalent algorithms |
| 50-75% | Somewhat Similar | Different optimization strategies, same query |
| <50% | Different | Major algorithmic differences, possibly different queries |

## Programmatic Usage

### Python API

Use query plan models and comparison programmatically:

```python
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.query_plans.comparison import compare_query_plans
from benchbox.core.query_plans.visualization import render_plan

# Load results
with open('results.json') as f:
    results = BenchmarkResults.from_dict(json.load(f))

# Get a query execution
query_exec = results.phases['power'].queries[0]
plan = query_exec.query_plan

# Render plan
print(render_plan(plan))

# Compare two plans
comparison = compare_query_plans(plan1, plan2)
print(f"Similarity: {comparison.similarity.overall_similarity:.1%}")
print(f"Type mismatches: {comparison.similarity.type_mismatches}")
```

### Custom Analysis

Traverse plan trees programmatically:

```python
def count_scans(plan):
    """Count total scan operations in plan."""
    def count_in_operator(op):
        count = 1 if op.operator_type == LogicalOperatorType.SCAN else 0
        if op.children:
            for child in op.children:
                count += count_in_operator(child)
        return count

    return count_in_operator(plan.logical_root)

# Analyze plans
num_scans = count_scans(query_exec.query_plan)
print(f"Total scans: {num_scans}")
```

### Plan Fingerprints

Use fingerprints for fast plan comparison:

```python
# Check if plans are identical
if plan1.plan_fingerprint == plan2.plan_fingerprint:
    print("Plans are identical")
else:
    print("Plans differ")

# Group queries by plan
plans_by_fingerprint = {}
for query_exec in all_queries:
    fp = query_exec.query_plan.plan_fingerprint
    if fp not in plans_by_fingerprint:
        plans_by_fingerprint[fp] = []
    plans_by_fingerprint[fp].append(query_exec.query_id)

# Find queries with same plan
for fp, query_ids in plans_by_fingerprint.items():
    if len(query_ids) > 1:
        print(f"Queries {query_ids} share same plan")
```

## Troubleshooting

### Plan Not Captured

**Symptom**: Warning message "No query plan captured for query"

**Causes**:
1. Forgot `--capture-plans` flag during benchmark
2. Platform doesn't support plan capture
3. Parser error (check logs for details)

**Solution**:
```bash
# Ensure --capture-plans is included
benchbox run --platform duckdb --benchmark tpch --scale 1 --capture-plans

# Check which platforms support capture
benchbox platforms
```

### Parser Errors

**Symptom**: Plan capture succeeds but plan is None

**Causes**:
1. EXPLAIN output format changed in newer platform version
2. Complex query with unusual operators
3. Platform-specific EXPLAIN extensions

**Solution**:
- Check benchmark logs for detailed error messages
- File an issue with the EXPLAIN output for investigation
- Plan capture failures don't halt benchmark execution

### Performance Issues

**Symptom**: Benchmark runs noticeably slower with `--capture-plans`

**Expected Impact**:
- DuckDB (default): ~1× query cost per plan (re-executes via `EXPLAIN (ANALYZE, FORMAT JSON)`)
- PostgreSQL SELECT queries: ~1× query cost per plan (re-executes via `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`)
- PostgreSQL DML queries: ~1-5 ms (no re-execution; uses `EXPLAIN (FORMAT JSON)` only)
- Redshift, DataFusion, SQLite: ~1-5 ms per query (estimated plans, no re-execution)

**If DuckDB overhead is too high**:
1. Use `--no-analyze-plans` to switch to estimated plans (~1-5 ms, no re-execution)
2. Use `--plan-config queries:<ids>` to capture plans for a subset of queries during development

**If PostgreSQL overhead is too high**:
1. PostgreSQL SELECT capture re-executes each query; consider capturing a subset with `--queries`
2. DML queries are already low-overhead by design (no ANALYZE)

**If overhead exceeds 10ms per query on Redshift/DataFusion/SQLite**:
1. Check if disk I/O is bottleneck (plan serialization)
2. Verify platform EXPLAIN performance

### Memory Usage

**Symptom**: High memory usage with plan capture

**Typical Plan Size**: 1-10 KB per query in memory, 10-100 KB serialized

**For large benchmarks (TPC-DS 99 queries)**:
- Memory: ~10 MB for all plans
- Disk: ~10 MB added to results JSON

If memory is constrained, consider running with `--phases power` to capture fewer queries.

### Comparison Shows No Differences

**Symptom**: Plans appear different visually but comparison shows 100% similarity

**Cause**: Comparison ignores non-structural properties like:
- Operator IDs (internal identifiers)
- Cost estimates (platform-specific)
- Row count estimates

**This is intentional** - comparison focuses on logical plan structure, not execution details.

To compare costs/estimates, examine the JSON export directly.

## Best Practices

### Development Workflow

1. **Capture baseline**: Run benchmark with `--capture-plans` and save results
2. **Make changes**: Modify queries, update database, change configuration
3. **Capture new run**: Run same benchmark again with `--capture-plans`
4. **Compare**: Use `benchbox compare-plans` to identify changes
5. **Investigate**: For significant differences, use `show-plan` to inspect details

### Cross-Platform Analysis

```bash
# Run same benchmark on different platforms
benchbox run --platform duckdb --benchmark tpch --scale 1 --capture-plans
benchbox run --platform datafusion --benchmark tpch --scale 1 --capture-plans

# Compare plans
benchbox compare-plans \
  --run1 benchmark_runs/duckdb_*/results.json \
  --run2 benchmark_runs/datafusion_*/results.json

# Focus on interesting queries
benchbox compare-plans \
  --run1 benchmark_runs/duckdb_*/results.json \
  --run2 benchmark_runs/datafusion_*/results.json \
  --query-id q05
```

### Regression Testing

```bash
# Automated regression check
benchbox compare-plans \
  --run1 baseline.json \
  --run2 current.json \
  --threshold 0.95 \
  --output json > regression_report.json

# Check exit code
if [ $? -ne 0 ]; then
    echo "Plan regressions detected!"
    exit 1
fi
```

## Advanced Topics

### Plan Fingerprints

Plans are fingerprinted using SHA256 of the logical structure:
- **Included**: Operator types, table names, join types, filter expressions, aggregations
- **Excluded**: Operator IDs, costs, row estimates, timing, cardinality, physical operator details

#### Stability contract

`plan_fingerprint` is designed for **structural comparison**, not cost comparison:

| Change | Fingerprint effect |
|--------|--------------------|
| Same query, same schema, same engine version | **Same fingerprint** |
| Stats refresh / `VACUUM ANALYZE` (no plan change) | **Same fingerprint** |
| Adding an index that is not used by the query | **Same fingerprint** |
| Adding an index the planner starts using | **May differ** — only when it changes the *logical* structure (e.g. an index join replacing a hash join). A pure scan-method switch (Seq Scan → Index Scan on the same table) keeps the **same fingerprint**, because scan variants normalize to a logical `Scan` and physical operator details are excluded from the hash. Use `compare-plans` or the physical-plan details to detect scan-method changes. |
| Engine minor version upgrade with no plan change | **Usually same** — not guaranteed across major versions |
| `analyze_plans=true` vs `analyze_plans=false` (DuckDB) | **Same fingerprint** — timing/cardinality excluded from hash |
| Same query, **different benchmark seed** (data-driven filter literal) | **Differs by default** — filter/join/projection *literals* are part of the hash, so a seed-varied threshold (`l_quantity < 1234.56` vs `< 2345.67`) changes the fingerprint even though the plan shape is identical. Use literal normalization (below) for seed-independent comparison. |

**What fingerprint equality does NOT guarantee:**
- That query performance is the same (costs may differ with identical logical structure)
- That the plan is optimal for the current data distribution
- Stability across major engine version upgrades

> **Cross-run comparison requires identical seeds (or literal normalization).**
> Because the default fingerprint embeds filter expression literals, comparing
> fingerprints across two runs that used *different* benchmark seeds produces false
> positives: a query whose only change is a seed-driven filter value (e.g.
> `customer_acctbal < 1234.56` → `< 2345.67`) appears "changed" when the plan shape
> did not. Either hold the seed constant across the runs you compare, or use the
> literal-normalized fingerprint below.

#### Literal normalization (seed-independent fingerprints)

Literal normalization is an **opt-in** structural fingerprint that masks numeric and
single-quoted string literals in the filter, join, and projection predicates to
`<NUM>` / `<STR>` before hashing. Two structurally identical plans whose only
difference is a seed-varied literal then share a fingerprint, so cross-run
regression detection stops flagging seed changes as plan changes. Identifier fields
— table names, group-by / sort keys, aggregation functions, operator and join types
— are **never** masked, so a genuine structural change still changes the fingerprint.

Normalization is opt-in and never alters the default `plan_fingerprint` (which stays
literal-sensitive, for users who intentionally track filter-threshold changes):

- **API:** `QueryPlanDAG.normalized_fingerprint` (a lazily-computed, cached property)
  or `compute_plan_fingerprint(normalize_literals=True)` returns the masked hash;
  `LogicalOperator.get_structural_signature(normalize_literals=True)` exposes the
  underlying signature.
- **Cross-run metadata:** `create_plan_metadata_from_results(..., normalize_literals=True)`
  records the normalized fingerprint per query for seed-independent comparison.

A `benchbox run --normalize-plan-literals` flag to surface the normalized fingerprint
directly in the result bundle is planned; today the normalized fingerprint is
available through the API above and the metadata helper.

**Recommended use:**
- Within a single run: deduplicate identical plans across concurrent streams
- Cross-run regression detection: flag queries where the fingerprint changed between runs on the same engine version
- Cross-platform comparison: use `compare-plans` for structural similarity; fingerprints will differ across platforms

### Literal-Normalized Fingerprints

By default the fingerprint includes literal constants (filter values, limits, etc.),
so two queries that differ only in their parameter substitutions produce different
fingerprints. Pass `--normalize-plan-literals` (together with `--capture-plans`) to
*also* record a literal-normalized fingerprint that collapses such queries to the
same value:

```bash
benchbox run --platform duckdb --benchmark tpch --capture-plans --normalize-plan-literals
```

When enabled, each captured plan in the `*.plans.json` companion file gains a
`fingerprint_normalized` key alongside the default `fingerprint`. The default
fingerprint is never changed. Literal normalization replaces string/date literals
and standalone numeric literals (and `LIMIT`/`OFFSET` counts) with a placeholder
while preserving identifiers, so structurally identical queries with different
constants share a normalized fingerprint.

The capability is also available programmatically:

```python
plan.plan_fingerprint          # literal-sensitive (default)
plan.normalized_fingerprint    # literal-normalized
plan.compute_plan_fingerprint(normalize_literals=True)
```

### Comparison Algorithm

The comparison engine uses:
1. **Fast path**: SHA256 fingerprint comparison (O(1))
2. **Full comparison**: BFS tree traversal (O(n×m) where n, m = tree sizes)
3. **Similarity scoring**: Multi-dimensional metrics based on operator matching

### Platform-Specific Notes

**DuckDB**:
- Uses `EXPLAIN (ANALYZE, FORMAT JSON)` by default - machine-readable JSON with actual per-operator
  timing (`operator_timing`) and cardinality (`operator_cardinality`) from real execution
- Captures logical and physical operators; parser handles both ANALYZE and estimated-plan schemas
- Re-executes the query at capture time (~1× query cost, in the isolated post-measurement phase);
  use `--no-analyze-plans` to opt out and capture estimated plans only
- DML statements (INSERT/UPDATE/DELETE/MERGE/COPY) use `FORMAT JSON` without `ANALYZE` to
  prevent double-execution side effects
- Fingerprints exclude timing/cardinality - structural comparisons are unaffected by this setting

**SQLite**:
- Uses `EXPLAIN QUERY PLAN` (text format)
- Simpler output than DuckDB
- Limited cost information

**PostgreSQL**:
- SELECT queries use `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` — re-executes the query to collect
  actual timing and I/O statistics (~1× query cost overhead)
- DML queries (INSERT, UPDATE, DELETE, MERGE) use `EXPLAIN (FORMAT JSON)` without ANALYZE
  to prevent writing data twice (~1-5 ms overhead, estimated plan only). `COPY` is not
  plan-captured: PostgreSQL `EXPLAIN` does not accept `COPY` statements.
- Provides detailed cost estimates, row counts, and operator properties
- Supports all PostgreSQL node types (Seq Scan, Index Scan, Hash Join, etc.)
- Requires PostgreSQL 12+ for full JSON format support
- Note: adding an index can change the fingerprint for PostgreSQL plans (Seq Scan uses
  `Filter` nodes captured in the signature; Index Scan uses `Index Cond` which is not
  captured). Do not compare fingerprints across index additions on PostgreSQL.

**Redshift**:
- Uses text-based `EXPLAIN` output
- Operators prefixed with "XN" (e.g., XN Seq Scan, XN Hash Join)
- Includes distribution operators (DS_DIST_INNER, DS_BCAST_INNER, etc.)
- Cost and row estimates parsed from output

**DataFusion**:
- Uses indentation-based text format from `EXPLAIN`
- Prefers physical plan (operators ending in "Exec") over logical plan
- Supports EXPLAIN ANALYZE metrics (output_rows, elapsed_compute, etc.)
- Common operators: ProjectionExec, FilterExec, HashJoinExec, AggregateExec

## Further Reading

- [API Documentation](../api/query-plan-models.md) - Programmatic usage
- [Platform Guide](../platforms/) - Platform-specific details
- [TPC-H Benchmark Guide](../benchmarks/tpch.md) - Query plan analysis examples

## Support

For issues or questions:
- [GitHub Issues](https://github.com/joeharris76/benchbox/issues)
- Check logs in `benchmark_runs/` for detailed error messages
