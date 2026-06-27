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

Currently supported platforms for query plan capture:

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
  `--platform-option analyze_plans=false` to use estimated plans only (~1-5 ms overhead).
- **PostgreSQL** (SELECT queries): uses `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, which also
  re-executes the query. Overhead is approximately **1× query cost** per captured plan.
- **PostgreSQL** (DML — INSERT/UPDATE/DELETE/MERGE): uses `EXPLAIN (FORMAT JSON)` without
  ANALYZE to prevent double-execution of writes. Overhead is low (~1-5 ms, estimated plan only).
  Note: PostgreSQL `EXPLAIN` does not accept `COPY`, so COPY statements are not plan-captured.
- **Redshift, DataFusion, SQLite**: estimated plans only (no ANALYZE), adds ~1-5 ms per query.

In all cases:
- Benchmark timing measurements are unaffected (plan capture runs after the timed execution)
- Failed plan captures are logged but don't halt execution

### Capture Isolation (post-measurement phase)

For EXPLAIN-based engines (DuckDB, MotherDuck, SQLite, DataFusion, PostgreSQL, Redshift),
`--capture-plans` runs as a **separate post-measurement phase** rather than inline with each
timed query. After all power iterations complete, BenchBox issues a single `EXPLAIN` pass over
the successfully-executed queries on the measurement connection and merges the resulting
`plan_fingerprint` / `query_plan` back into each query result. This means:

- **No EXPLAIN on the measurement path.** Plan capture never interleaves with a timed query or
  holds the connection between measured queries — the EXPLAIN pass runs strictly after the timed
  loop, so measured per-query execution times are never inflated by capture cost.
- **Honours `analyze_plans` on the engines that support ANALYZE.** On DuckDB,
  MotherDuck, and PostgreSQL — the engines whose `EXPLAIN` has an ANALYZE mode —
  `analyze_plans=true` (the default) re-runs each SELECT once with `EXPLAIN
  (ANALYZE)` *after* measurement, so captured plans carry actual per-operator
  timing and cardinality (~1× extra query cost, outside the measured window), and
  `--platform-option analyze_plans=false` uses a static (non-`ANALYZE`) `EXPLAIN`
  giving estimated plans only with no re-execution cost (~1-5 ms). SQLite
  (`EXPLAIN QUERY PLAN`), DataFusion, and Redshift (plain `EXPLAIN`) have no
  ANALYZE mode: they always capture a static, estimated plan and the
  `analyze_plans` toggle has no effect on those adapters (no per-operator timing
  is available). The structural `plan_fingerprint` is identical either way (it
  excludes timing/cardinality by design); the measured execution times in the
  result bundle remain the authoritative timings.
- **DML runs exactly once.** Even with `analyze_plans=true`, an
  INSERT/UPDATE/DELETE/MERGE/COPY (or CTAS / `SELECT ... INTO`) query is downgraded to a
  non-`ANALYZE` `EXPLAIN` by the shared `is_dml_query` write guard, so writes are captured
  without being re-executed a second time.
- **Sampling honoured.** `--plan-queries`, `--plan-first-n`, and `--plan-sampling-rate` apply to
  the phase exactly as before.

Platforms that obtain plans as a side effect of execution (BigQuery job statistics, Spark/event-log
based adapters) continue to capture **inline** during execution — the isolated phase is opt-in per
adapter via the `plan_capture_phase_eligible` capability flag and is not used for those platforms.

### Captured Fields

Each query result includes three plan-related fields when `--capture-plans` is active:

| Field | Type | Description |
|-------|------|-------------|
| `query_plan` | `QueryPlan \| None` | Parsed logical plan tree; `None` if capture failed or was skipped |
| `plan_fingerprint` | `str \| None` | SHA256 of the plan's logical structure; `None` when `query_plan` is `None` |
| `plan_capture_time_ms` | `float \| None` | Wall-clock milliseconds spent on plan capture (excludes query execution time) |

`plan_fingerprint` is `None` when `query_plan` is `None`. Both are `None` when `--capture-plans` is
not set or when the query was excluded by `--plan-config`.

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
1. Use `--platform-option analyze_plans=false` to switch to estimated plans (~1-5 ms, no re-execution)
2. Use `--queries` to capture plans for a subset of queries during development

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
| Adding an index the planner starts using | **Different fingerprint** (join/scan operator changes) |
| Engine minor version upgrade with no plan change | **Usually same** — not guaranteed across major versions |
| `analyze_plans=true` vs `analyze_plans=false` (DuckDB) | **Same fingerprint** — timing/cardinality excluded from hash |

**What fingerprint equality does NOT guarantee:**
- That query performance is the same (costs may differ with identical logical structure)
- That the plan is optimal for the current data distribution
- Stability across major engine version upgrades

**Recommended use:**
- Within a single run: deduplicate identical plans across concurrent streams
- Cross-run regression detection: flag queries where the fingerprint changed between runs on the same engine version
- Cross-platform comparison: use `compare-plans` for structural similarity; fingerprints will differ across platforms

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
- Re-executes the query at capture time (~1× query cost); use
  `--platform-option analyze_plans=false` to opt out and capture estimated plans only
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
