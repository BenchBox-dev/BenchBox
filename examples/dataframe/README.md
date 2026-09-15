# DataFrame Examples

This directory contains examples demonstrating BenchBox's DataFrame benchmarking capabilities.

## Overview

BenchBox supports native DataFrame benchmarking alongside traditional SQL database benchmarking. These examples show how to:

1. Run TPC-H/TPC-DS queries using Polars DataFrame API
2. Run queries using Pandas DataFrame API
3. Compare performance across platforms
4. Compare SQL vs DataFrame execution paradigms

## Prerequisites

```bash
# Install DataFrame platforms
pip install polars pandas

# Generate benchmark data (required for execution)
benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases load
benchbox run --platform duckdb --benchmark tpcds --scale 1 --phases load
```

## Examples

### Basic TPC-H Examples

**Polars TPC-H** (`polars_tpch.py`)
```bash
python examples/dataframe/polars_tpch.py
```
Demonstrates running TPC-H queries using Polars' expression API with lazy evaluation.

**Pandas TPC-H** (`pandas_tpch.py`)
```bash
python examples/dataframe/pandas_tpch.py
```
Demonstrates running TPC-H queries using Pandas' DataFrame API with eager evaluation.

### TPC-DS Example

**Polars TPC-DS** (`polars_tpcds.py`)
```bash
python examples/dataframe/polars_tpcds.py
```
Demonstrates running TPC-DS queries (more complex than TPC-H with 99 queries).

### Comparison Examples

**Cross-Platform Comparison** (`cross_platform_comparison.py`)
```bash
python examples/dataframe/cross_platform_comparison.py
```
Compares query execution time across Polars and Pandas for the same queries.

**SQL vs DataFrame** (`sql_vs_dataframe.py`)
```bash
python examples/dataframe/sql_vs_dataframe.py
```
Compares SQL execution (DuckDB) vs DataFrame execution (Polars) for equivalent queries.

## Family-Based Architecture

BenchBox uses a family-based architecture for DataFrame support:

### Expression Family (Polars, PySpark, DataFusion)
```python
# Declarative style with expression objects
result = df.filter(col("shipdate") <= lit(cutoff)).group_by("status").agg(col("quantity").sum().alias("total_qty"))
```

### Pandas Family (Pandas, cuDF, Dask)
```python
# Imperative style with string-based column access
filtered = df[df["shipdate"] <= cutoff]
result = filtered.groupby("status").agg({"quantity": "sum"})
```

## Running with CLI

For production benchmarking, use the BenchBox CLI:

```bash
# Polars DataFrame mode
benchbox run --platform polars-df --benchmark tpch --scale 0.1

# Pandas DataFrame mode
benchbox run --platform pandas-df --benchmark tpch --scale 0.01

# Compare results
benchbox compare results_polars.json results_pandas.json
```

## Related Documentation

- [DataFrame Platforms Overview](../../docs/platforms/dataframe.md)
- [Pandas DataFrame Platform](../../docs/platforms/pandas-dataframe.md)
- [TPC-H Guide](../../docs/guides/tpc/tpc-h-official-guide.md)
- [TPC-DS Guide](../../docs/guides/tpc/tpc-ds-official-guide.md)
