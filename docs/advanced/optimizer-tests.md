# Optimizer Sniff Test Queries

```{tags} advanced, guide, performance
```

<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

## Overview

The BenchBox Read Primitives benchmark now includes 13 systematic "optimizer sniff test" queries designed to evaluate how well database query optimizers handle common optimization patterns. These queries are based on the TPC-H schema and test specific optimizer capabilities without requiring database-specific code.

## Test Queries

The BenchBox Read Primitives benchmark includes 13 optimizer test queries that thoroughly evaluate database query optimizer capabilities:

### 1. EXISTS to Semijoin Decorrelation Test

**Query ID**: `optimizer_exists_to_semijoin`

**Purpose**: Tests whether the query optimizer can convert correlated EXISTS subqueries to more efficient semijoin operations.

**What it tests**:
- Subquery decorrelation capabilities
- Semijoin optimization recognition
- Performance impact of EXISTS vs JOIN transformations

**Expected behavior**: Advanced-level optimizers should automatically convert the EXISTS subquery to a semijoin, resulting in faster execution (typically 10x or more vs. naive nested loop).

**Query pattern**:
```sql
SELECT c_custkey, c_name, c_mktsegment, c_nationkey
FROM customer c
WHERE EXISTS (
    SELECT 1 FROM orders o
    WHERE o.o_custkey = c.c_custkey
      AND o.o_orderdate >= DATE '1995-01-01'
      AND o.o_orderdate < DATE '1996-01-01'
      AND o.o_totalprice > 100000
)
```

### 2. DISTINCT Elimination Test

**Query ID**: `optimizer_distinct_elimination`

**Purpose**: Tests whether the query optimizer can eliminate redundant DISTINCT clauses when they're not needed due to primary key constraints.

**What it tests**:
- Primary key constraint awareness
- Redundant DISTINCT detection
- Logical optimization capabilities

**Expected behavior**: Since the query selects the primary key (`o_orderkey`) and other columns from the same table, the DISTINCT is redundant and should be eliminated by the optimizer.

**Query pattern**:
```sql
SELECT DISTINCT o_orderkey, o_custkey, o_orderdate, o_totalprice
FROM orders o
WHERE o_orderdate >= DATE '1995-01-01'
  AND o_orderdate < DATE '1996-01-01'
  AND o_totalprice > 50000
```

### 3. Common Subexpression Elimination Test

**Query ID**: `optimizer_common_subexpression`

**Purpose**: Tests whether the query optimizer can identify and eliminate common subexpressions, computing complex expressions only once.

**What it tests**:
- Common subexpression recognition
- Expression optimization
- Computational efficiency optimization

**Expected behavior**: The complex expression `l_quantity * l_extendedprice * (1 - l_discount) * (1 + l_tax)` appears multiple times and should be computed only once, then reused.

**Query pattern**:
```sql
SELECT
    l_orderkey, l_partkey, l_suppkey, l_linenumber,
    l_quantity * l_extendedprice * (1 - l_discount) * (1 + l_tax) as revenue_with_tax,
    CASE
        WHEN l_quantity * l_extendedprice * (1 - l_discount) * (1 + l_tax) > 50000 THEN 'High Value'
        WHEN l_quantity * l_extendedprice * (1 - l_discount) * (1 + l_tax) > 10000 THEN 'Medium Value'
        ELSE 'Low Value'
    END as value_category,
    ROUND(l_quantity * l_extendedprice * (1 - l_discount) * (1 + l_tax), 2) as rounded_revenue
FROM lineitem
WHERE l_shipdate >= DATE '1995-01-01'
  AND l_shipdate < DATE '1996-01-01'
  AND l_quantity * l_extendedprice * (1 - l_discount) * (1 + l_tax) > 1000
ORDER BY l_quantity * l_extendedprice * (1 - l_discount) * (1 + l_tax) DESC
```

### 4. Predicate Pushdown Through Joins Test

**Query ID**: `optimizer_predicate_pushdown`

**Purpose**: Tests whether the query optimizer can push predicates down past joins to reduce intermediate result sizes.

**What it tests**:
- Predicate pushdown optimization
- Join selectivity optimization
- Filter placement strategies

**Expected behavior**: Predicates on `c_nationkey` and `c_mktsegment` should be pushed down to the customer table before the join, and date predicates should be pushed down to the orders table.

### 5. Join Reordering Optimization Test

**Query ID**: `optimizer_join_reordering`

**Purpose**: Tests whether the query optimizer can reorder joins based on cardinality and selectivity.

**What it tests**:
- Join order optimization
- Cardinality-based optimization
- Cost-based join planning

**Expected behavior**: Despite the written order (orders → customer → nation), the optimizer should reorder to start with the smallest, most selective table (nation) first.

### 6. Limit Pushdown Through Operations Test

**Query ID**: `optimizer_limit_pushdown`

**Purpose**: Tests whether the query optimizer can push LIMIT clauses down to reduce work in upstream operations.

**What it tests**:
- Limit pushdown optimization
- Top-N optimization
- Early termination strategies

**Expected behavior**: The LIMIT 100 should influence the join execution to avoid processing unnecessary rows.

### 7. Aggregate Pushdown Through Joins Test

**Query ID**: `optimizer_aggregate_pushdown`

**Purpose**: Tests whether the query optimizer can partially compute aggregates before joins when possible.

**What it tests**:
- Aggregate placement optimization
- Pre-aggregation strategies
- HAVING clause optimization

**Expected behavior**: Aggregates should be partially computed on the orders table before joining with customer when beneficial.

### 8. Scalar Subquery Flattening Test

**Query ID**: `optimizer_scalar_subquery_flattening`

**Purpose**: Tests whether the query optimizer can convert scalar subqueries to joins for improved execution efficiency.

**What it tests**:
- Subquery flattening optimization
- Join conversion strategies
- Correlated subquery elimination

**Expected behavior**: The scalar subqueries should be converted to LEFT JOINs or similar more efficient join operations.

### 9. Constant Folding and Expression Simplification Test

**Query ID**: `optimizer_constant_folding`

**Purpose**: Tests whether the query optimizer can pre-compute constants and simplify expressions at compile time.

**What it tests**:
- Constant folding optimization
- Expression simplification
- Algebraic optimization

**Expected behavior**: Expressions like `l_quantity * (1.0 + 0.0)` should be simplified to `l_quantity`, and `(2 * 3 + 4)` should be folded to `10`.

### 10. Column Pruning (Projection Pushdown) Test

**Query ID**: `optimizer_column_pruning`

**Purpose**: Tests whether the query optimizer can eliminate unnecessary column reads to reduce I/O.

**What it tests**:
- Column pruning optimization
- Projection pushdown
- I/O reduction strategies

**Expected behavior**: Only columns needed for the final result, joins, and filtering should be read from each table.

### 11. IN-to-EXISTS Transformation Test

**Query ID**: `optimizer_in_to_exists`

**Purpose**: Tests whether the query optimizer can transform IN subqueries to EXISTS when beneficial.

**What it tests**:
- IN subquery optimization
- EXISTS transformation
- Subquery execution strategies

**Expected behavior**: The IN subquery should be transformed to an EXISTS or semijoin operation for improved execution efficiency.

### 12. Union/Set Operation Optimization Test

**Query ID**: `optimizer_union_optimization`

**Purpose**: Tests whether the query optimizer can optimize UNION operations and eliminate redundant operations.

**What it tests**:
- UNION optimization
- Set operation efficiency
- Redundant sort elimination

**Expected behavior**: UNION ALL operations should be configured, and redundant sorting should be eliminated.

### 13. Runtime Filter Generation Test

**Query ID**: `optimizer_runtime_filter`

**Purpose**: Tests whether the query optimizer can generate runtime filters (bloom filters, hash filters) for selective joins.

**What it tests**:
- Runtime filter generation
- Bloom filter optimization
- Dynamic join optimization

**Expected behavior**: The selective predicate on `p_type` should generate a runtime filter that gets pushed down to the lineitem table to reduce join input size.

## Implementation Details

### Database Compatibility
- **Schema**: Uses standard TPC-H tables (customer, orders, lineitem)
- **SQL Features**: Standard SQL constructs supported by all major databases
- **Dialects**: Compatible with DuckDB, PostgreSQL, SQLite, MySQL, and others via SQLGlot translation

### Performance Characteristics
- **Scale Factor Dependency**: Query performance scales with TPC-H scale factor
- **Execution Complexity**: Simple queries at small scale factors; complexity increases with scale
- **Resource Usage**: Memory usage depends on intermediate result sizes

### Usage Example

```python
from benchbox.core.primitives.queries import PrimitivesQueryManager

# Initialize query manager
query_manager = PrimitivesQueryManager()

# Get all optimizer test queries
optimizer_queries = [
    "optimizer_exists_to_semijoin",
    "optimizer_distinct_elimination",
    "optimizer_common_subexpression",
    "optimizer_predicate_pushdown",
    "optimizer_join_reordering",
    "optimizer_limit_pushdown",
    "optimizer_aggregate_pushdown",
    "optimizer_scalar_subquery_flattening",
    "optimizer_constant_folding",
    "optimizer_column_pruning",
    "optimizer_in_to_exists",
    "optimizer_union_optimization",
    "optimizer_runtime_filter"
]

# Execute all optimizer queries
for query_id in optimizer_queries:
    query_sql = query_manager.get_query(query_id)
    # Execute against TPC-H database and measure performance
    # ... analyze query plans and optimization effectiveness
```

## Testing and Validation

### Automated Testing
All optimizer queries are automatically tested as part of the BenchBox test suite:
- Syntax validation against multiple SQL dialects
- Execution testing with TPC-H scale factor 0.01
- Result validation and row count verification

### Manual Testing
For manual testing of optimizer effectiveness:
1. Run queries with `EXPLAIN` or `EXPLAIN ANALYZE` to examine query plans
2. Compare execution times with and without optimizations
3. Monitor resource usage (CPU, memory) during execution
4. Test across different database engines to compare optimizer capabilities

## Expected Row Counts

Expected row counts at TPC-H scale factor 0.01 (useful for validation):
- **EXISTS to Semijoin**: ~1,000 rows returned
- **DISTINCT Elimination**: ~2,000 rows returned
- **Common Subexpression**: ~5,000 rows returned
- **Predicate Pushdown**: ~212 rows returned
- **Join Reordering**: ~83 rows returned
- **Limit Pushdown**: ~100 rows returned
- **Aggregate Pushdown**: ~50 rows returned
- **Scalar Subquery Flattening**: ~100 rows returned
- **Constant Folding**: ~1,000 rows returned
- **Column Pruning**: ~500 rows returned
- **IN-to-EXISTS**: ~200 rows returned
- **Union Optimization**: ~300 rows returned
- **Runtime Filter**: ~1,000 rows returned

**Note:** Execution times vary based on hardware, database engine, and configuration. Run benchmarks to establish baselines for your environment.

## Optimization Benefits

### Potential Performance Gains

The following are theoretical benefits from query optimizations. Actual improvements vary significantly based on data characteristics, query complexity, selectivity, hardware, and platform implementation. Use these as general guidance rather than expected results.

- **EXISTS to Semijoin**: Performance improvement depending on data size
- **DISTINCT Elimination**: Performance improvement by avoiding sort operations
- **Common Subexpression**: Performance improvement by reducing redundant calculations
- **Predicate Pushdown**: Performance improvement by reducing join input sizes
- **Join Reordering**: Performance improvement based on cardinality differences
- **Limit Pushdown**: Performance improvement by early termination
- **Aggregate Pushdown**: Performance improvement by reducing data movement
- **Scalar Subquery Flattening**: Performance improvement by eliminating nested loops
- **Constant Folding**: Performance improvement by eliminating runtime calculations
- **Column Pruning**: Performance improvement by reducing I/O
- **IN-to-EXISTS**: Performance improvement based on data distribution
- **Union Optimization**: Performance improvement by eliminating redundant operations
- **Runtime Filter**: Performance improvement by reducing join input sizes

### Measurable Indicators
- Query execution time reduction
- Lower CPU usage during execution
- Reduced intermediate result sizes
- More efficient query plan structures

## Future Enhancements

### Additional Test Patterns
- **Predicate Pushdown**: Test filter predicate optimization through joins
- **Join Reordering**: Test appropriate join order selection
- **Constant Folding**: Test compile-time constant evaluation
- **Index Usage**: Test index selection and utilization

### Advanced-level Metrics
- Query plan complexity analysis
- Optimizer decision tracking
- Performance regression detection
- Cross-database optimizer comparison

## References

- [Original Blog Post](https://buttondown.com/jaffray/archive/a-sniff-test-for-some-query-optimizers/) by Justin Jaffray: Inspiration for these optimizer tests
- [TPC-H Specification](http://www.tpc.org/tpc_documents_current_versions/current_specifications.asp): Reference for schema and data patterns
- [BenchBox Documentation](../README.md): General usage and architecture information
