# Post outline: BenchBox in action, when the same query needs different code

**Series**: BenchBox in Action | **Post #6**
**Target length**: 2,400-2,800 words
**Status**: OUTLINED

---

## Metadata

```yaml
title: "BenchBox in action: when the same query needs different code"
slug: platform-specific-optimization-patterns
series: benchbox-in-action
post_number: 6
date: 2026-02-XX
tags: [benchmarking, benchbox, polars, datafusion, pyspark, tpcds, dataframe, query-optimization]
meta_description: "We investigated why a TPC-DS multi-warehouse detection pattern runs 5x faster with different code on Polars vs DataFusion, and what this means for cross-platform DataFrame libraries."
```

---

## Thesis

> While building BenchBox's TPC-DS DataFrame implementations, we discovered that the same logical operation (finding orders shipped from multiple warehouses) requires fundamentally different code paths on Polars vs DataFusion. Our investigation across three platforms and six data scales revealed that Polars prefers n_unique() aggregation (3-4x faster), while DataFusion prefers self-join patterns (5x faster). The root cause lies in how each engine's query planner handles COUNT(DISTINCT) vs hash joins.

**Core focus**: The methodology insight about cross-platform DataFrame code, not which platform "wins."

---

## Outline

### 1. The question (~250 words)

**Opening**: BenchBox aims to run the same benchmark across multiple DataFrame platforms. While implementing TPC-DS Q16 and Q95 (multi-warehouse order detection), we wrote what seemed like the obvious code, a self-join to find orders with different warehouses. Initial testing on Polars showed the self-join running 3-5x slower than alternatives, leading us to wonder: does the "right" DataFrame pattern depend on which engine runs it?

**This post walks through**: Our systematic investigation across Polars, DataFusion, and PySpark, from initial observation to root cause analysis to platform-specific solution.

### 2. The problem: TPC-DS multi-warehouse detection (~300 words)

Explain the business logic:
- TPC-DS Q16/Q95 need to find orders shipped from multiple warehouses
- SQL uses a self-join pattern with inequality filter
- Initial DataFrame translation: `unique() -> self-join -> filter != -> unique()`

Show the two implementation patterns:

```python
# Pattern A: Self-join (mirrors SQL)
order_wh = df.select(["order_number", "warehouse_sk"]).unique()
multi_warehouse = (
    order_wh.join(order_wh.rename({"warehouse_sk": "wh2"}), on="order_number")
    .filter(col("warehouse_sk") != col("wh2"))
    .select("order_number").unique()
)

# Pattern B: n_unique aggregation
multi_warehouse = (
    df.group_by("order_number")
    .agg(col("warehouse_sk").n_unique().alias("n"))
    .filter(col("n") > 1)
    .select("order_number")
)
```

Both produce identical results. Which is faster?

### 3. Hypothesis and test design (~200 words)

- **Hypothesis**: Pattern performance might vary by platform due to different query planner optimizations
- **Test design**: Generate synthetic order-warehouse data at 6 scales (10K to 1M orders), run both patterns on three platforms, measure execution time
- **Platforms tested**: Polars 1.37, DataFusion 51.0, PySpark 4.1
- **Controls**: Same data, same hardware, same iteration count (5 runs after 2 warmup)

### 4. Results: opposite behavior across platforms (~400 words)

Present the benchmark results as a table:

```
Scale      Polars          DataFusion      PySpark
-------------------------------------------------------
10K          2.4x ✓         2.1x ✗         1.7x ✓
50K          2.7x ✓         4.5x ✗         2.2x ✓
100K         3.2x ✓         4.9x ✗         1.3x ✓
250K         3.0x ✓         4.3x ✗         1.4x ✓
500K         3.8x ✓         5.2x ✗         1.4x ✓
1M           3.9x ✓         5.4x ✗         1.6x ✓

✓ = n_unique faster, ✗ = self-join faster
```

**Key observations**:
- Pattern holds consistently across ALL scales (10K to 1M)
- Polars: n_unique 2.4-3.9x faster
- DataFusion: self-join 2.1-5.4x faster
- PySpark: n_unique 1.3-2.2x faster (consistent with Polars, tested at all 6 scales)
- No crossover point, the pattern preference is architectural, not data-dependent
- Broadcast join hints do not change PySpark recommendation (both sides are same size)

### 5. Root cause investigation: query plans (~600 words)

#### Polars query plans

Show the optimized plans:

**n_unique pattern (single pass)**:
```
AGGREGATE [n_unique()] BY [order_number]
  → TableScan
```

**Self-join pattern (multiple passes)**:
```
UNIQUE → FILTER → INNER JOIN (CACHE) → UNIQUE pairs × 2
```

**Why n_unique wins in Polars**: Single-pass streaming aggregation with vectorized hash counting. No intermediate materialization.

#### DataFusion query plans

**Self-join pattern**:
```
HashJoinExec: mode=CollectLeft (efficient!)
  → AggregateExec: gby=[order_number, warehouse_sk] (simple dedup)
```

**n_unique pattern**:
```
AggregateExec: mode=Partial, gby=[order_number], aggr=[count(DISTINCT ...)]
  → AggregateExec: mode=FinalPartitioned
```

**Why self-join wins in DataFusion**:
- `HashJoinExec: mode=CollectLeft` is highly optimized for in-memory joins
- `count(DISTINCT)` requires maintaining per-group hash sets with O(groups x unique_values) memory overhead
- Simple `DISTINCT` (groupBy without aggregation) is much cheaper than `count(DISTINCT)`

#### PySpark analysis

- n_unique requires 1 shuffle (group by order_number)
- Self-join requires 2 shuffles (distinct, then join)
- Shuffle cost dominates at scale, so n_unique wins
- Pattern holds consistently from 10K to 1M rows (1.3-2.2x speedup)

**Broadcast join hint tested**: Does forcing a broadcast join help the self-join pattern?

```
Pattern                      Time    Notes
-------------------------------------------------
Self-join (no broadcast)     243ms   Baseline
Self-join (with broadcast)   237ms   Only 1.03x speedup
n_unique (countDistinct)     184ms   Still 1.3x faster
```

**Why broadcast doesn't help**: Both sides of the self-join are the same data (unique order-warehouse pairs), so there's no "small side" to broadcast. Broadcast optimization helps when one table is much smaller than the other. The recommendation stands: use n_unique pattern for PySpark regardless of scale or broadcast hints.

### 6. The solution: platform-specific code paths (~300 words)

BenchBox now detects the platform and uses the optimal pattern:

```python
platform = getattr(ctx, "platform", "polars")
if platform == "datafusion":
    # Self-join pattern (5x faster on DataFusion)
    order_wh = df.select([...]).unique()
    result = order_wh.join(...).filter(...).unique()
else:
    # n_unique pattern (3-7x faster on Polars/PySpark)
    result = df.group_by(...).agg(n_unique()).filter(...)
```

**Trade-off acknowledged**: This adds complexity. Single-source DataFrame code is cleaner. But a 5x performance difference is too large to ignore for benchmark tooling.

### 7. Methodology insight (~400 words)

What this reveals about benchmarking and cross-platform DataFrame libraries:

1. **"Write once, run anywhere" has limits**: Logical equivalence doesn't guarantee performance equivalence. Query planners make different trade-offs.

2. **Aggregate metrics would have hidden this**: If we'd only measured geometric mean, we might not have noticed Q16/Q95 were outliers.

3. **Root cause analysis requires query plans**: Performance numbers alone don't explain "why." Understanding planner behavior required examining execution plans.

4. **Platform-specific tuning may be necessary**: Libraries like Ibis and Narwhals aim for cross-platform compatibility, but some patterns may need platform-specific fast paths.

5. **This isn't about which platform is "better"**: Polars optimizes for streaming aggregation. DataFusion optimizes for join operations. Both are valid engineering choices.

### 8. Test environment (~200 words)

- **Hardware**: Apple M1 Mac Mini, 16GB RAM
- **Software**: Polars 1.37.1, DataFusion 51.0.0, PySpark 4.1.1
- **Data**: Synthetic order-warehouse data, 10% multi-warehouse orders
- **Methodology**: 5 iterations after 2 warmup, median timing
- **Code**: Investigation script available at [link]
- **Limitations**: Single-node only; distributed Spark may show different characteristics

### 9. Conclusions (~250 words)

**BenchBox workflow thread**:
- Started with a performance observation during TPC-DS implementation
- Systematic benchmarking across platforms and scales revealed consistent pattern
- Query plan analysis explained the root cause
- Solution: platform detection with optimized code paths

**Cross-platform DataFrame thread**:
- Same logical operation, same DataFrame API, 5x performance difference
- The "right" code depends on which query planner executes it
- For benchmark tooling where performance matters, platform-specific paths are justified
- For application code, consider whether the performance difference matters for your use case

**Next exploration**: Do other TPC-DS queries show similar platform-specific optimization opportunities?

---

## Research completed

- [x] Generated synthetic benchmark data at 6 scales
- [x] Benchmarked both patterns on Polars (all scales)
- [x] Benchmarked both patterns on DataFusion (all scales)
- [x] Benchmarked both patterns on PySpark (all 6 scales)
- [x] Analyzed Polars query plans
- [x] Analyzed DataFusion query plans
- [x] Implemented platform-specific solution in BenchBox
- [x] Verified correctness (same results, all platforms)
- [x] Gathered primary sources for all technical claims
- [x] Verified PySpark behavior at larger scales (500K, 1M)
- [x] Tested broadcast join hint effect on PySpark
- [ ] Package investigation script for reproducibility

## Research needed

None - all research complete.

## References & Resources

### Primary Sources

1. **TPC-DS Specification**: [TPC-DS v3.2.0](https://www.tpc.org/tpc_documents_current_versions/pdf/tpc-ds_v3.2.0.pdf) - Official Q16 specification with EXISTS subquery pattern
2. **DataFusion HashJoinExec**: [docs.rs/datafusion](https://docs.rs/datafusion/latest/datafusion/physical_plan/joins/struct.HashJoinExec.html) - CollectLeft mode documentation
3. **DataFusion Aggregates**: [datafusion.apache.org](https://datafusion.apache.org/user-guide/sql/aggregate_functions.html) - Aggregate function implementation
4. **Polars Aggregation Guide**: [docs.pola.rs](https://docs.pola.rs/user-guide/expressions/aggregation/) - Parallelization and vectorization
5. **Polars n_unique API**: [docs.pola.rs](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.n_unique.html) - Function documentation
6. **PySpark Joins Tutorial**: [DataCamp](https://www.datacamp.com/tutorial/pyspark-joins) - Join optimization strategies
7. **Spark Shuffle Optimization**: [SparkCodeHub](https://www.sparkcodehub.com/pyspark/performance/shuffle-optimization) - Shuffle behavior and costs

### BenchBox Implementation

8. **BenchBox commit (TPC-H Q21)**: `d59507be` - perf(tpch): optimize Q21 DataFrame implementation with filter pushdown
9. **BenchBox commit (TPC-DS Q16/Q95)**: `8726dd47` - perf(tpcds): add platform-specific multi-warehouse detection

### Related Research

10. **Ibis Benchmark**: [ibis-project.org](https://ibis-project.org/posts/ibis-bench/) - Cross-platform DataFrame comparison showing similar Q21 issues

## Research notes

See `_blog/benchbox-in-action/research/platform-optimization-patterns.md` for detailed research notes including:
- Query plan captures for all platforms
- Full benchmark results table (all 6 scales, all 3 platforms)
- Architectural explanation of performance differences
- Root cause summary
- PySpark large-scale test results (500K, 1M)
- Broadcast join hint analysis

---

*Outline created: 2026-02-04*
*Research completed: 2026-02-04*
*Status: RESEARCH COMPLETE - Ready for Draft*
