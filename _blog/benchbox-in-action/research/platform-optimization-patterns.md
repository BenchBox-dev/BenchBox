# Research: Platform-Specific DataFrame Optimization Patterns

Research notes for blog post #6: "BenchBox in action: when the same query needs different code"

---

## Primary Sources

### 1. TPC-DS Query 16 Specification

**Source**: TPC-DS Standard Specification + BenchBox query retrieval

The official TPC-DS Q16 uses an EXISTS subquery to detect multi-warehouse orders:

```sql
EXISTS(
  SELECT * FROM catalog_sales cs2
  WHERE cs1.cs_order_number = cs2.cs_order_number
  AND cs1.cs_warehouse_sk <> cs2.cs_warehouse_sk
)
```

This is a correlated subquery with an inequality filter - the pattern that needs translation for DataFrame APIs.

**Citation**: [TPC-DS Standard Specification v3.2.0](https://www.tpc.org/tpc_documents_current_versions/pdf/tpc-ds_v3.2.0.pdf)

---

### 2. DataFusion HashJoinExec Documentation

**Source**: [DataFusion Rust docs - HashJoinExec](https://docs.rs/datafusion/latest/datafusion/physical_plan/joins/struct.HashJoinExec.html)

Key findings:
- HashJoinExec evaluates equijoin predicates in parallel using a hash table
- Two phases: **Build** (create hash table from smaller side) and **Probe** (stream through larger side)
- `CollectLeft` mode collects the left (build) side into memory for efficient lookup
- "The smaller input should be placed on the build side to minimize hash table construction overhead"
- Optimal for star schema queries with small dimension tables and large fact tables

**Why self-join wins**: When the order-warehouse pairs are deduplicated first (small set), the `CollectLeft` mode creates an efficient in-memory hash table. The join becomes a simple lookup rather than a complex aggregation.

**Citation**: DataFusion documentation, Apache Software Foundation

---

### 3. DataFusion COUNT(DISTINCT) Implementation

**Source**: DataFusion source code and documentation

The `count(DISTINCT col)` aggregate requires:
1. Per-group hash sets to track unique values
2. Memory overhead of O(groups × unique_values_per_group)
3. Two-phase aggregation (Partial → FinalPartitioned)

This is more expensive than simple DISTINCT (which is just a groupBy without aggregation) because it must maintain state per group rather than globally.

**Citation**: [DataFusion Aggregate Functions](https://datafusion.apache.org/user-guide/sql/aggregate_functions.html)

---

### 4. Polars Aggregation Architecture

**Source**: [Polars User Guide - Aggregation](https://docs.pola.rs/user-guide/expressions/aggregation/)

Key findings:
- "Polars will try to parallelize the computation of the aggregating functions over the groups"
- Built on Apache Arrow columnar memory format
- Enables zero-copy operations and vectorized processing via SIMD instructions
- `n_unique()` is a native aggregation that can be computed in a single streaming pass

**Why n_unique wins**: Polars is optimized for streaming aggregations. The `n_unique()` pattern requires a single pass through the data with a hash-based counter per group - this is exactly what Polars excels at. The self-join pattern forces materialization and multiple passes.

**Citation**: Polars documentation, [polars.Expr.n_unique](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.n_unique.html)

---

### 5. PySpark Shuffle Behavior

**Source**: [PySpark Joins Optimization Guide](https://www.datacamp.com/tutorial/pyspark-joins), [Spark Shuffle Optimization](https://www.sparkcodehub.com/pyspark/performance/shuffle-optimization)

Key findings:
- Both `countDistinct` and `.distinct()` are "wide transformations" requiring full shuffle
- Self-join requires TWO shuffles: one for distinct, one for the join itself
- `countDistinct` requires ONE shuffle (group by the key)
- "Joins are a cornerstone of data processing in Apache Spark... joins often trigger data shuffling, moving data across the cluster, which can be a performance bottleneck"
- Broadcast joins can eliminate shuffle for small tables, but both tables here could be large

**Why n_unique wins**: At scale, shuffle cost dominates. The `countDistinct` pattern requires 1 shuffle while self-join requires 2 shuffles. Even though each shuffle may be similar size, avoiding one shuffle is a significant win.

**Citation**: [Shuffle Optimization in PySpark](https://www.sparkcodehub.com/pyspark/performance/shuffle-optimization)

---

## Benchmark Data (Original Research)

### Test Configuration
- **Hardware**: Apple M1 Mac Mini, 16GB RAM
- **Software**: Polars 1.37.1, DataFusion 51.0.0, PySpark 4.1.1
- **Data**: Synthetic order-warehouse data, 10% multi-warehouse orders
- **Methodology**: 5 iterations after 2 warmup, average timing

### Results Summary

| Scale | Rows | Polars (n_unique speedup) | DataFusion (self-join speedup) | PySpark (n_unique speedup) |
|-------|------|---------------------------|-------------------------------|---------------------------|
| 10K | 11,952 | 2.4x | 2.1x | 1.7x |
| 50K | 60,038 | 2.7x | 4.5x | 2.2x |
| 100K | 120,215 | 3.2x | 4.9x | 1.3x |
| 250K | 300,611 | 3.0x | 4.3x | 1.4x |
| 500K | 600,980 | 3.8x | 5.2x | 1.4x |
| 1M | 1,200,738 | 3.9x | 5.4x | 1.6x |

### Query Plans Captured

**Polars n_unique pattern**:
```
simple π 1/1 ["order_number"]
  FILTER [(col("n")) > (1)]
  FROM
    AGGREGATE[maintain_order: false]
      [col("warehouse_sk").n_unique().alias("n")] BY [col("order_number")]
```

**Polars self-join pattern**:
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

**DataFusion self-join pattern**:
```
HashJoinExec: mode=CollectLeft, join_type=Inner
  AggregateExec: mode=FinalPartitioned, gby=[order_number, warehouse_sk]  -- Simple dedup
```

**DataFusion n_unique pattern**:
```
AggregateExec: mode=Partial, gby=[order_number], aggr=[count(DISTINCT warehouse_sk)]
  AggregateExec: mode=FinalPartitioned  -- Complex aggregate
```

---

## Secondary Sources

### Cross-Platform DataFrame Libraries

**Ibis Project**: Aims for cross-platform DataFrame compatibility. Their benchmark showed similar Q21 issues with DataFusion DataFrame mode.
- [Ibis Benchmark: DuckDB, DataFusion, Polars](https://ibis-project.org/posts/ibis-bench/)

**Narwhals**: Another cross-platform abstraction layer. Faces similar challenges.

---

## Key Insights for Blog Post

### 1. Root Cause Summary

| Platform | n_unique Cost | Self-join Cost | Winner |
|----------|---------------|----------------|--------|
| Polars | Single-pass streaming aggregate | Materialization + join + dedup | n_unique |
| DataFusion | Per-group hash sets (expensive) | CollectLeft hash join (cheap) | self-join |
| PySpark | 1 shuffle | 2 shuffles | n_unique |

### 2. Architectural Explanation

**Polars**: Optimized for columnar streaming operations. Aggregations like `n_unique()` use vectorized hash counting that processes data in batches without materialization. Self-joins force the data into a shape that requires cache/materialization, breaking the streaming model.

**DataFusion**: Optimized for SQL-like query patterns. The `HashJoinExec: mode=CollectLeft` is highly tuned for situations where one side fits in memory. `COUNT(DISTINCT)` aggregations require maintaining per-group state, which has higher memory and CPU overhead than simple deduplication.

**PySpark**: Shuffle-dominated at scale. Each shuffle requires serialization, network transfer, and deserialization. Reducing shuffle count is more important than optimizing individual operations.

### 3. Implications for Cross-Platform Code

- "Write once, run anywhere" has performance limits
- Query planners make different trade-offs based on their optimization targets
- For performance-critical code, platform-specific paths may be justified
- Libraries like Ibis/Narwhals may need to expose "hints" for platform-specific optimization

---

## Gaps Resolved (2026-02-04)

### PySpark at 500K/1M Scales

**Finding**: n_unique pattern remains faster at larger scales.

| Scale | Self-join | n_unique | Speedup |
|-------|-----------|----------|---------|
| 500K | 590ms | 435ms | 1.4x |
| 1M | 640ms | 406ms | 1.6x |

The pattern is consistent - n_unique wins at all scales from 10K to 1M.

### Broadcast Join Hint Effect

**Finding**: Broadcast hint has negligible effect on self-join performance.

| Pattern | Time | Notes |
|---------|------|-------|
| Self-join (no broadcast) | 243ms | Baseline |
| Self-join (with broadcast) | 237ms | Only 1.03x speedup |
| n_unique | 184ms | Still 1.3x faster than best self-join |

**Why broadcast doesn't help**: Both sides of the self-join are the same data (unique order-warehouse pairs), so there's no "small side" to broadcast. Broadcast optimization helps when one table is much smaller than the other.

**Conclusion**: The recommendation stands - use n_unique pattern for PySpark regardless of scale or broadcast hints.

## Gaps Remaining

None - all research complete.
- [ ] Review if DataFusion has plans to optimize COUNT(DISTINCT)

---

## References for Citation

1. **TPC-DS Specification**: [TPC-DS v3.2.0](https://www.tpc.org/tpc_documents_current_versions/pdf/tpc-ds_v3.2.0.pdf)
2. **DataFusion HashJoinExec**: [docs.rs/datafusion](https://docs.rs/datafusion/latest/datafusion/physical_plan/joins/struct.HashJoinExec.html)
3. **DataFusion Aggregates**: [datafusion.apache.org](https://datafusion.apache.org/user-guide/sql/aggregate_functions.html)
4. **Polars Aggregation**: [docs.pola.rs](https://docs.pola.rs/user-guide/expressions/aggregation/)
5. **Polars n_unique**: [docs.pola.rs](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.n_unique.html)
6. **PySpark Joins**: [DataCamp Tutorial](https://www.datacamp.com/tutorial/pyspark-joins)
7. **Spark Shuffle**: [SparkCodeHub](https://www.sparkcodehub.com/pyspark/performance/shuffle-optimization)
8. **BenchBox Commits**: Links to perf(tpch) and perf(tpcds) commits

---

*Research completed: 2026-02-04*
