# DataFrame Benchmarking Quickstart

```{tags} beginner, tutorial, dataframe-platform, polars
```

Run TPC-H using DataFrame APIs (Polars, Pandas) instead of SQL.

## Why DataFrame Benchmarking?

- **Compare paradigms**: SQL vs DataFrame execution on same queries
- **Data science workflows**: Benchmark tools you actually use
- **No database required**: Pure Python execution

## Quick Start with Polars

```bash
benchbox run --platform polars-df --benchmark tpch --scale 0.1
```

This runs all 22 TPC-H queries using Polars' DataFrame API.

## Available DataFrame Platforms

| Platform | CLI Name | Best For |
|----------|----------|----------|
| Polars | `polars-df` | Speed, production workloads |
| Pandas | `pandas-df` | Compatibility, reference |
| PySpark | `pyspark-df` | Distributed computing |
| DataFusion | `datafusion-df` | Arrow-native processing |

## SQL vs DataFrame Comparison

```bash
# SQL execution (DuckDB)
benchbox run --platform duckdb --benchmark tpch --scale 0.1 --output sql.json

# DataFrame execution (Polars)
benchbox run --platform polars-df --benchmark tpch --scale 0.1 --output polars.json

# Compare
benchbox compare sql.json polars.json
```

## How It Works

BenchBox translates TPC-H queries into DataFrame operations:

**SQL (TPC-H Q1):**
```sql
SELECT l_returnflag, l_linestatus,
       SUM(l_quantity), SUM(l_extendedprice)
FROM lineitem
WHERE l_shipdate <= DATE '1998-12-01' - INTERVAL 90 DAY
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag, l_linestatus
```

**DataFrame (Polars):**
```python
lineitem.filter(
    pl.col("l_shipdate") <= date(1998, 9, 2)
).group_by(
    "l_returnflag", "l_linestatus"
).agg(
    pl.col("l_quantity").sum(),
    pl.col("l_extendedprice").sum()
).sort("l_returnflag", "l_linestatus")
```

Both produce identical results.

## Performance Tuning

Enable auto-tuning for optimal performance:

```bash
benchbox run --platform polars-df --benchmark tpch --tuning auto
```

Or use a custom configuration:

```bash
# View available settings
benchbox tuning show-defaults --platform polars

# Use custom tuning
benchbox run --platform polars-df --benchmark tpch --tuning tuning.yaml
```

## Pandas Example

```bash
# Run with Pandas
benchbox run --platform pandas-df --benchmark tpch --scale 0.01

# Note: Pandas is slower than Polars for large datasets
# Use scale 0.01-0.1 for Pandas benchmarks
```

## Cross-Platform DataFrame Comparison

```bash
# Compare DataFrame platforms
benchbox run --platform polars-df --benchmark tpch --output polars.json
benchbox run --platform pandas-df --benchmark tpch --output pandas.json
benchbox run --platform datafusion-df --benchmark tpch --output datafusion.json

benchbox compare polars.json pandas.json datafusion.json
```

## TPC-DS Support

DataFrame mode also supports TPC-DS (99 queries):

```bash
benchbox run --platform polars-df --benchmark tpcds --scale 1
```

Note: TPC-DS requires scale factor >= 1 due to data generator constraints.

## Programmatic Usage

```python
from benchbox.platforms.dataframe import PolarsDataFrameAdapter
from benchbox import TPCH

adapter = PolarsDataFrameAdapter()
benchmark = TPCH(scale_factor=0.1)

# Run benchmark
results = benchmark.run_dataframe(adapter)

# Access results
for query_result in results.query_results:
    print(f"{query_result.query_id}: {query_result.execution_time_ms:.1f}ms")
```

## Next Steps

- [DataFrame Platform Guide](../platforms/dataframe.md) - Detailed configuration
- [DataFrame Migration Guide](../guides/dataframe-migration.md) - Adopting DataFrame mode
- [Tuning Reference](../platforms/dataframe.md#tuning-system) - Performance optimization
