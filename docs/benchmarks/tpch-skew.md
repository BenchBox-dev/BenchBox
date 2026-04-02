<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC-H Skew Benchmark

```{tags} advanced, concept, tpch-skew, tpc-h, custom-benchmark
```

> **CLI name:** `tpch_skew` — use `benchbox run --benchmark tpch_skew`

## Overview

The TPC-H Skew benchmark extends the standard TPC-H benchmark with configurable data skew patterns to test database performance under realistic, non-uniform data distributions. Based on the research paper ["Introducing Skew into the TPC-H Benchmark"](https://www.tpc.org/tpctc/tpctc2011/slides_and_papers/introducing_skew_into_the_tpc_h_benchmark.pdf), this benchmark helps evaluate how query optimizers handle skewed data distributions that are common in real-world scenarios.

The benchmark is ideal for testing cardinality estimation accuracy, join strategy selection, and overall optimizer robustness when data doesn't follow uniform distributions.

## Key Features

- **Configurable skew levels** - From uniform (standard TPC-H) to extreme Zipfian distributions
- **Multiple distribution types** - Zipfian, normal, and exponential patterns
- **Preset configurations** - Ready-to-use skew profiles for common scenarios
- **Same 22 queries** - Uses standard TPC-H queries for direct comparison
- **Concurrent stream support** - Full TPC-H compliance testing with skewed data
- **Research-backed methodology** - Based on TPC-TC 2011 research

## Skew Presets

BenchBox provides predefined skew configurations for common testing scenarios:

| Preset | Skew Factor (z) | Description | Use Case |
|--------|-----------------|-------------|----------|
| `none` | 0.0 | Uniform distribution (standard TPC-H) | Baseline comparison |
| `light` | 0.2 | Light skew | Initial optimizer stress testing |
| `moderate` | 0.5 | Moderate skew (default) | Balanced skew testing |
| `heavy` | 0.8 | Heavy skew | Advanced optimizer testing |
| `extreme` | 1.0 | Zipf's law distribution | Edge case testing |
| `realistic` | varies | E-commerce patterns | Real-world simulation |

## Data Model

The TPC-H Skew benchmark uses the same schema as standard TPC-H:

### Tables

| Table | Purpose | Approximate Rows (SF 1) |
|-------|---------|-------------------------|
| **lineitem** | Order line items (largest table) | ~6,000,000 |
| **orders** | Customer orders | ~1,500,000 |
| **partsupp** | Part-supplier relationships | ~800,000 |
| **customer** | Customer information | ~150,000 |
| **part** | Part catalog | ~200,000 |
| **supplier** | Supplier information | ~10,000 |
| **nation** | Nation reference | 25 |
| **region** | Region reference | 5 |

### Skew Applied To

The skew distribution is applied to key columns that affect join cardinality and selectivity:

- **o_custkey** (orders → customer join)
- **l_partkey** (lineitem → part join)
- **l_suppkey** (lineitem → supplier join)
- **ps_partkey** (partsupp → part join)
- **ps_suppkey** (partsupp → supplier join)

## Query Categories

The benchmark uses the standard 22 TPC-H queries, unchanged from the base benchmark. This allows direct comparison between uniform and skewed data performance:

### Scan-Heavy Queries
- Q1, Q6: Large aggregations on lineitem
- Most affected by data volume, less by skew

### Join-Heavy Queries
- Q3, Q5, Q7, Q8, Q9, Q10, Q21: Multi-table joins
- **Most affected by skew** - cardinality estimation errors compound

### Subquery Queries
- Q2, Q4, Q11, Q15, Q17, Q18, Q20, Q22: Correlated subqueries
- Affected by both skew and optimizer strategy selection

### Complex Analytics
- Q13, Q14, Q16, Q19: Aggregation with complex predicates
- Variable impact depending on selectivity

## Usage Examples

### Basic Usage with Preset

```python
from benchbox import TPCHSkew

# Use moderate skew (default)
benchmark = TPCHSkew(scale_factor=1.0)
data_files = benchmark.generate_data()

# Get queries (same as standard TPC-H)
queries = benchmark.get_queries()

# Check skew configuration
print(benchmark.get_skew_info())
```

### Using Different Presets

```python
from benchbox import TPCHSkew

# Light skew for initial testing
light_benchmark = TPCHSkew(scale_factor=0.1, skew_preset="light")

# Heavy skew for optimizer stress testing
heavy_benchmark = TPCHSkew(scale_factor=1.0, skew_preset="heavy")

# Extreme skew for edge cases
extreme_benchmark = TPCHSkew(scale_factor=1.0, skew_preset="extreme")

# Realistic e-commerce patterns
realistic_benchmark = TPCHSkew(scale_factor=1.0, skew_preset="realistic")
```

### Custom Skew Configuration

```python
from benchbox import TPCHSkew
from benchbox.core.tpch_skew import SkewConfiguration

# Create custom configuration
custom_config = SkewConfiguration(
    skew_factor=0.7,
    distribution_type="zipfian",
    attribute_skew_enabled=True,
    join_skew_enabled=True,
    temporal_skew_enabled=False,
)

benchmark = TPCHSkew(
    scale_factor=1.0,
    skew_config=custom_config
)
data_files = benchmark.generate_data()
```

### DuckDB Integration

```python
import duckdb
from benchbox import TPCHSkew
from benchbox.platforms.duckdb import DuckDBAdapter

# Initialize benchmark with heavy skew
benchmark = TPCHSkew(scale_factor=0.1, skew_preset="heavy")

# Generate skewed data
benchmark.generate_data()

# Use DuckDB adapter
adapter = DuckDBAdapter(database=":memory:")
adapter.load_benchmark(benchmark)

# Run queries and compare with baseline
results = adapter.run_benchmark(benchmark)

# Analyze query performance
for query_id, result in results.items():
    print(f"Q{query_id}: {result['execution_time']:.3f}s")
```

### Comparing Uniform vs Skewed Performance

```python
from benchbox import TPCH, TPCHSkew
from benchbox.platforms.duckdb import DuckDBAdapter

# Baseline: Standard TPC-H (uniform)
uniform = TPCH(scale_factor=1.0)
uniform.generate_data()

# Test: TPC-H with heavy skew
skewed = TPCHSkew(scale_factor=1.0, skew_preset="heavy")
skewed.generate_data()

# Compare performance
for benchmark, name in [(uniform, "Uniform"), (skewed, "Skewed")]:
    adapter = DuckDBAdapter()
    adapter.load_benchmark(benchmark)

    # Run a join-heavy query (most affected by skew)
    query = benchmark.get_query(3)  # Q3: Shipping Priority
    result = adapter.execute_query(query)
    print(f"{name} Q3: {result['execution_time']:.3f}s")
```

## Scale Factor Guidelines

| Scale Factor | Data Size | Memory Usage | Use Case |
|--------------|-----------|--------------|----------|
| 0.01 | ~10 MB | < 100 MB | Quick testing |
| 0.1 | ~100 MB | < 500 MB | Development |
| 1.0 | ~1 GB | < 4 GB | Standard benchmark |
| 10.0 | ~10 GB | < 20 GB | Performance testing |

## Performance Characteristics

### Impact of Skew on Query Performance

**Low Impact:**
- Q1, Q6: Simple scans and aggregations
- Performance dominated by I/O, not join strategies

**Medium Impact:**
- Q2, Q4, Q11, Q15: Subqueries with moderate join complexity
- Cardinality estimation errors affect plan selection

**High Impact:**
- Q3, Q5, Q7, Q8, Q9, Q10, Q21: Complex multi-way joins
- Skew causes significant cardinality estimation errors
- Wrong join order selection common with naive optimizers

### Common Optimizer Failures

1. **Hash join overflow**: Skewed build side exceeds memory estimates
2. **Wrong join order**: Estimated cardinalities differ significantly from actual
3. **Suboptimal parallelism**: Work imbalance due to skewed partitions
4. **Index selection errors**: Skewed data changes selectivity assumptions

## Best Practices

### Testing Methodology

1. **Establish baseline** - Run standard TPC-H first for comparison
2. **Start with moderate skew** - Use `moderate` preset initially
3. **Progress to heavy skew** - Identify optimizer breaking points
4. **Monitor query plans** - Compare plans between uniform and skewed runs

### Interpreting Results

1. **Calculate slowdown ratio** - skewed_time / uniform_time
2. **Identify outliers** - Queries with >2x slowdown indicate optimizer issues
3. **Examine plans** - Look for join order changes, hash spills
4. **Check cardinality estimates** - Compare estimated vs actual row counts

### Optimization Recommendations

1. **Update statistics frequently** - Histogram-based statistics help
2. **Consider adaptive execution** - Runtime join strategy switching
3. **Use skew hints if available** - Some databases support skew-aware hints
4. **Test with realistic skew** - Use `realistic` preset for production planning

## Related Documentation

- [TPC-H Benchmark](tpc-h.md) - Standard TPC-H documentation
- [TPC-Havoc](tpc-havoc.md) - Query syntax variant testing
- [Join Order Benchmark](join-order.md) - Join optimization testing

## External Resources

- [TPC-H Official Specification](http://www.tpc.org/tpch) - TPC-H standard
- [Introducing Skew into TPC-H](https://www.tpc.org/tpctc/tpctc2011/) - Research methodology
- [Cardinality Estimation in Query Optimizers](https://www.vldb.org/pvldb/vol9/p204-leis.pdf) - Related research
