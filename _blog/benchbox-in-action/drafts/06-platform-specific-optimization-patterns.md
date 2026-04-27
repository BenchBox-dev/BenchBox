# BenchBox in action: when the same query needs different code

> Two DataFrame patterns, three platforms, and a 5x performance gap that revealed an uncomfortable truth about cross-platform code.

**TL;DR**: While implementing TPC-DS queries in BenchBox, we discovered that the same logical operation (finding orders shipped from multiple warehouses) runs 3-5x faster with different code on Polars vs DataFusion. Our investigation across three platforms and six data scales revealed that the "right" DataFrame pattern depends entirely on which query planner executes it. The root cause: Polars optimizes for streaming aggregations, DataFusion optimizes for hash joins, and PySpark optimizes for shuffle reduction.

---

## Introduction

We wrote what seemed like obvious code: a self-join to find orders shipped from multiple warehouses. Polars ran it 3x slower than expected.

That observation kicked off a multi-day investigation that revealed an uncomfortable truth about cross-platform DataFrame code: the "right" pattern depends entirely on which engine runs it.

The answer, backed by testing across Polars, DataFusion, and PySpark at six data scales (10K to 1M rows), is unambiguous. And the differences are not marginal. We measured speedups of 2-5x depending on the platform, with opposite winners: Polars and PySpark prefer one pattern, while DataFusion prefers another.

This post walks through our investigation from initial observation to root cause analysis to platform-specific solution. The finding has implications beyond BenchBox, for anyone building cross-platform DataFrame libraries or writing code that needs to run efficiently on multiple engines.

---

## The problem: TPC-DS multi-warehouse detection

TPC-DS queries Q16 and Q95 share a common pattern: finding orders that were shipped from multiple warehouses. The business logic is straightforward. A retail operation wants to identify orders that, for whatever reason, required fulfillment from more than one warehouse location.

The standard TPC-DS SQL uses a correlated subquery with an inequality filter[^1]:

```sql
EXISTS(
  SELECT * FROM catalog_sales cs2
  WHERE cs1.cs_order_number = cs2.cs_order_number
  AND cs1.cs_warehouse_sk <> cs2.cs_warehouse_sk
)
```

When translating this to DataFrame operations, there are two natural approaches. Both produce identical results, but they represent fundamentally different execution strategies.

**Pattern A: Self-join (mirrors the SQL structure)**

```python
# Get unique order-warehouse pairs, join to find different warehouses
order_wh = df.select(["order_number", "warehouse_sk"]).unique()
multi_warehouse = (
    order_wh.join(order_wh.rename({"warehouse_sk": "wh2"}), on="order_number")
    .filter(col("warehouse_sk") != col("wh2"))
    .select("order_number").unique()
)
```

**Pattern B: Aggregation with n_unique**

```python
# Count unique warehouses per order, filter for > 1
multi_warehouse = (
    df.group_by("order_number")
    .agg(col("warehouse_sk").n_unique().alias("n"))
    .filter(col("n") > 1)
    .select("order_number")
)
```

The first pattern is a direct translation of the SQL. The second pattern reformulates the problem: instead of finding orders with different warehouses, count the unique warehouses per order and keep those with more than one.

Both approaches are logically correct. Which is faster?

---

## Hypothesis and test design

Our initial observation on Polars suggested the aggregation pattern was 3-5x faster. But we wanted to know: is this universal, or does it depend on the platform?

**Hypothesis**: Pattern performance might vary by platform due to different query planner optimizations.

**Test design**: We generated synthetic order-warehouse data at six scales (10K to 1M orders), ran both patterns on three platforms, and measured execution time. Each scale included approximately 10% multi-warehouse orders to simulate realistic data distribution.

**Platforms tested**:
- Polars 1.37.1
- DataFusion 51.0.0 (via Python bindings)
- PySpark 4.1.1

**Controls**:
- Same data at each scale
- Same hardware (Apple M1 Mac Mini, 16GB RAM)
- Same iteration count (5 runs after 2 warmup runs)
- Median timing used for comparison

---

## How BenchBox surfaced this

BenchBox's multi-platform support made this investigation possible. We used the MCP server to explore the question systematically.

First, we ran TPC-DS on multiple DataFrame platforms using the CLI:

```bash
benchbox run --platform polars-df --benchmark tpcds --scale 0.1 --phases power
benchbox run --platform datafusion-df --benchmark tpcds --scale 0.1 --phases power
```

Then we used the MCP `analyze_results` tool to compare runs. The comparison flagged Q16 and Q95 as significant outliers, with performance ratios far outside the normal range. That per-query visibility, rather than aggregate metrics, is what triggered the deeper investigation.

Using `get_query_details`, we retrieved the DataFrame implementations for both queries and noticed they shared the same multi-warehouse detection pattern. This led us to isolate the pattern and test it independently across platforms.

---

## Results: opposite behavior across platforms

The results were striking. Not only did the optimal pattern differ by platform, but the preference was consistent across all scales and substantial in magnitude.

| Scale | Rows | Polars | DataFusion | PySpark |
|-------|------|--------|------------|---------|
| 10K | 11,952 | 2.4x n_unique | 2.1x self-join | 1.7x n_unique |
| 50K | 60,038 | 2.7x n_unique | 4.5x self-join | 2.2x n_unique |
| 100K | 120,215 | 3.2x n_unique | 4.9x self-join | 1.3x n_unique |
| 250K | 300,611 | 3.0x n_unique | 4.3x self-join | 1.4x n_unique |
| 500K | 600,980 | 3.8x n_unique | 5.2x self-join | 1.4x n_unique |
| 1M | 1,200,738 | 3.9x n_unique | 5.4x self-join | 1.6x n_unique |

**Key observations**:

1. **The pattern holds consistently across all scales (10K to 1M)**. This is not a small-data vs. large-data effect.

2. **Polars prefers n_unique by 2.4-3.9x**. The advantage grows slightly with scale.

3. **DataFusion prefers self-join by 2.1-5.4x**. The advantage also grows with scale.

4. **PySpark aligns with Polars, preferring n_unique by 1.3-2.2x**. The effect is more modest but consistent.

5. **No crossover point exists**. The pattern preference is architectural, not data-dependent. We never found a scale where the relationship reversed.

---

## Root cause investigation: query plans

Performance numbers tell us what happened, but not why. To understand the root cause, we examined the query plans generated by each engine.

### Polars: optimized for streaming aggregation

The n_unique pattern generates a simple, efficient plan:

```
simple π 1/1 ["order_number"]
  FILTER [(col("n")) > (1)]
  FROM
    AGGREGATE[maintain_order: false]
      [col("warehouse_sk").n_unique().alias("n")] BY [col("order_number")]
```

This is a single-pass streaming aggregation with vectorized hash counting[^2]. Polars processes data in batches without intermediate materialization.

The self-join pattern, in contrast, requires multiple passes:

```
UNIQUE[maintain_order: false, keep_strategy: Any] BY None
  simple π 1/1 ["order_number"]
    FILTER [(col("warehouse_sk")) != (col("wh2"))]
    FROM
      INNER JOIN:
      LEFT PLAN ON: [col("order_number")]
        CACHE[id: ...]  -- Materialization required
      RIGHT PLAN ON: [col("order_number")]
        SELECT [col("order_number"), col("warehouse_sk").alias("wh2")]
          CACHE[id: ...]  -- Same materialization
```

The CACHE nodes indicate materialization. The self-join pattern forces Polars to break its streaming model, requiring multiple passes over the data. This architectural mismatch explains the 2-4x performance gap.

### DataFusion: optimized for hash joins

DataFusion shows the opposite pattern. The self-join generates an efficient plan:

```
HashJoinExec: mode=CollectLeft, join_type=Inner
  AggregateExec: mode=FinalPartitioned, gby=[order_number, warehouse_sk]
```

The key detail is `HashJoinExec: mode=CollectLeft`[^3]. DataFusion's hash join implementation collects the left (build) side into an in-memory hash table, then streams the right (probe) side through it. When the order-warehouse pairs are deduplicated first (a small set), this creates an efficient lookup structure.

The n_unique pattern generates a more complex aggregation:

```
AggregateExec: mode=Partial, gby=[order_number], aggr=[count(DISTINCT warehouse_sk)]
  AggregateExec: mode=FinalPartitioned
```

The `count(DISTINCT)` aggregate requires maintaining per-group hash sets to track unique values[^4]. This has memory overhead of O(groups x unique_values_per_group) and requires two-phase aggregation (Partial then FinalPartitioned). Simple DISTINCT (groupBy without aggregation) is much cheaper than `count(DISTINCT)` because it maintains state globally rather than per group.

### PySpark: shuffle cost dominates

PySpark's behavior is explained by shuffle operations. In Spark, "wide transformations" require moving data across the cluster (or in local mode, between shuffle partitions)[^5].

- **n_unique pattern**: Requires 1 shuffle (group by order_number)
- **Self-join pattern**: Requires 2 shuffles (distinct, then join)

At scale, shuffle cost dominates. Each shuffle requires serialization, partition exchange, and deserialization. Avoiding one shuffle is a significant win.

We also tested whether broadcast join hints could help the self-join pattern:

| Pattern | Time | Notes |
|---------|------|-------|
| Self-join (no broadcast) | 243ms | Baseline |
| Self-join (with broadcast) | 237ms | Only 1.03x speedup |
| n_unique (countDistinct) | 184ms | Still 1.3x faster |

Broadcast hints have negligible effect because both sides of the self-join are the same data (unique order-warehouse pairs). There is no "small side" to broadcast. The recommendation stands: use n_unique for PySpark regardless of scale or broadcast configuration.

---

## The solution: platform-specific code paths

Given the consistent 2-5x performance differences, we implemented platform detection in BenchBox's TPC-DS DataFrame queries:

```python
platform = getattr(ctx, "platform", "polars")
if platform == "datafusion":
    # Self-join pattern (5x faster on DataFusion)
    order_wh = df.select(["cs_order_number", "cs_warehouse_sk"]).unique()
    multi_warehouse_orders = (
        order_wh.join(
            order_wh.rename({"cs_warehouse_sk": "cs_warehouse_sk_2"}),
            on="cs_order_number",
        )
        .filter(col("cs_warehouse_sk") != col("cs_warehouse_sk_2"))
        .select(["cs_order_number"])
        .unique()
    )
else:
    # n_unique pattern (3-4x faster on Polars/PySpark)
    multi_warehouse_orders = (
        df.group_by("cs_order_number")
        .agg(col("cs_warehouse_sk").n_unique().alias("num_warehouses"))
        .filter(col("num_warehouses") > lit(1))
        .select("cs_order_number")
    )
```

**Trade-off acknowledged**: This adds complexity. Single-source DataFrame code is cleaner. But a 5x performance difference is too large to ignore for benchmark tooling where query execution time is the primary measurement.

---

## Methodology insight

This investigation revealed several insights about benchmarking and cross-platform DataFrame code:

### 1. "Write once, run anywhere" has performance limits

Logical equivalence does not guarantee performance equivalence. Both patterns produce identical results, but query planners make fundamentally different optimization decisions. The DataFrame API abstracts the "what" but not the "how."

### 2. Aggregate metrics would have hidden this

If we had only measured geometric mean across all TPC-DS queries, Q16 and Q95 would have been noise in the overall result. Per-query analysis was essential to identifying the pattern-specific behavior.

### 3. Root cause analysis requires query plans

Performance numbers tell us that something is slow, not why. Understanding planner behavior required examining execution plans, which revealed the architectural differences: Polars' streaming model vs. DataFusion's optimized hash joins vs. PySpark's shuffle sensitivity.

### 4. Platform-specific tuning may be necessary

Libraries like Ibis and Narwhals aim for cross-platform DataFrame compatibility. Our findings suggest these libraries may need to expose "hints" or platform-specific optimizations for patterns where the performance gap is substantial.

The Ibis project has documented similar challenges[^6], finding that certain TPC-H queries performed very differently across their supported backends.

### 5. This finding is not about which platform is "better"

Polars optimizes for streaming aggregation. DataFusion optimizes for join operations (its SQL heritage shows in HashJoinExec). PySpark optimizes for distributed execution with shuffle minimization. These are all valid engineering choices for their target use cases. The "right" pattern depends on the context.

---

## Test environment

- **Hardware**: Apple M1 Mac Mini, 16GB RAM
- **Software**: Polars 1.37.1, DataFusion 51.0.0, PySpark 4.1.1
- **Data**: Synthetic order-warehouse data, 10% multi-warehouse orders
- **Methodology**: 5 iterations after 2 warmup runs, median timing reported
- **Code**: [Investigation scripts](https://github.com/benchbox/benchbox/tree/main/examples/platform-optimization-patterns) in the BenchBox repository

**Limitations**:
- Single-node testing only. Distributed Spark clusters may show different characteristics, though shuffle cost would likely remain the dominant factor.
- We tested one specific pattern (multi-warehouse detection). Other patterns may show different platform preferences.
- Hardware is Apple Silicon. x86 systems may show different relative performance.

---

## Conclusions

A single slow query during TPC-DS implementation led to three platforms, six data scales, and one clear conclusion: the "right" DataFrame pattern depends entirely on which query planner executes it.

**What we learned about cross-platform DataFrame code**:

- Same API, same logic, dramatically different performance
- The "right" code depends on which query planner executes it
- For benchmark tooling where performance matters, platform-specific paths are justified
- For application code, consider whether the performance difference matters for your use case

**What we learned about benchmarking methodology**:

- Per-query analysis catches patterns that aggregate metrics miss
- Query plans explain "why," not just "what"
- Testing across multiple scales validates that findings are architectural, not data-dependent

**How BenchBox enabled this investigation**:

BenchBox's multi-platform support and per-query analysis tools made this investigation possible. The `analyze_results` comparison flagged Q16 and Q95 as outliers. The `get_query_details` tool let us inspect the shared implementation pattern. Without per-query visibility, this 5x performance gap would have been noise in the aggregate metrics.

BenchBox now uses platform detection to choose the optimal pattern for Q16 and Q95. We are continuing to investigate whether other TPC-DS queries show similar platform-specific optimization opportunities.

---

## References

[^1]: [TPC-DS Standard Specification v3.2.0](https://www.tpc.org/tpc_documents_current_versions/pdf/tpc-ds_v3.2.0.pdf) - Official Q16 specification with EXISTS subquery pattern

[^2]: [Polars User Guide: Aggregation and Parallelization](https://docs.pola.rs/user-guide/expressions/aggregation/) - Documents Polars' parallel aggregation strategy: "Polars will try to parallelize the computation of the aggregating functions over the groups"

[^3]: [DataFusion HashJoinExec Documentation](https://docs.rs/datafusion/latest/datafusion/physical_plan/joins/struct.HashJoinExec.html) - CollectLeft mode collects the build side into memory for efficient lookup

[^4]: [DataFusion Aggregate Functions](https://datafusion.apache.org/user-guide/sql/aggregate_functions.html) - COUNT(DISTINCT) implementation details

[^5]: [Spark Shuffle Optimization](https://www.sparkcodehub.com/pyspark/performance/shuffle-optimization) - "Joins often trigger data shuffling, which can be a performance bottleneck"

[^6]: [Ibis Benchmark: DuckDB, DataFusion, Polars](https://ibis-project.org/posts/ibis-bench/) - Cross-platform DataFrame comparison showing similar query-specific performance variations

---

*Questions or feedback? [Open an issue](https://github.com/benchbox/benchbox/issues) or join the discussion.*

---

**Status**: Revised Draft
**Word Count**: ~2,800
**Draft Date**: 2026-02-04
**Revised**: 2026-02-04
