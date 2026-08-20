#!/usr/bin/env python3
"""
Polars DataFrame TPC-H Benchmark Example

Demonstrates running TPC-H queries using Polars' native DataFrame API.
This uses the Expression family implementation with lazy evaluation
and query optimization.

Copyright 2026 Joe Harris / BenchBox Project.
Licensed under the MIT License.

Usage:
    python examples/dataframe/polars_tpch.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure polars is available
try:
    import polars as pl

    print(f"Polars version: {pl.__version__}")
except ImportError:
    print("Error: Polars not installed. Run: pip install polars")
    sys.exit(1)


def main() -> int:
    """Run Polars DataFrame TPC-H benchmark demonstration."""
    from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES, get_query
    from benchbox.platforms.polars_platform import PolarsAdapter

    print("=" * 60)
    print("Polars DataFrame TPC-H Benchmark")
    print("=" * 60)

    # Show registered queries
    print("\nRegistered TPC-H queries:")
    for qid in TPCH_DATAFRAME_QUERIES.get_query_ids()[:5]:
        query = TPCH_DATAFRAME_QUERIES.get(qid)
        print(f"  {qid}: {query.query_name}")
    print(f"  ... and {len(TPCH_DATAFRAME_QUERIES) - 5} more")

    # Check data availability
    data_dir = Path("benchmark_runs/tpch/sf0.01/data")
    if not data_dir.exists():
        print(f"\nWarning: Data directory not found: {data_dir}")
        print("Generate data first with:")
        print("  benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases load")
        print("\nSkipping query execution, showing structure only.")
        return 0

    # Create context with Polars DataFrame
    print("\nCreating Polars DataFrame context...")
    ctx = PolarsAdapter().create_connection()

    # Load tables (lazy scanning from Parquet)
    parquet_dir = data_dir / "parquet"
    if parquet_dir.exists():
        print(f"Loading tables from {parquet_dir}...")
        tables = ["lineitem", "orders", "customer", "supplier", "part", "partsupp", "nation", "region"]
        for table in tables:
            table_path = parquet_dir / f"{table}.parquet"
            if table_path.exists():
                # Use lazy scanning for efficiency
                df = pl.scan_parquet(str(table_path))
                ctx.register_table(table, df)
                print(f"  Loaded {table}")
    else:
        print(f"Parquet directory not found: {parquet_dir}")
        return 1

    # Execute sample queries
    print("\n" + "-" * 60)
    print("Executing Sample Queries")
    print("-" * 60)

    sample_queries = ["Q1", "Q3", "Q6"]
    for qid in sample_queries:
        try:
            query = get_query(qid)
        except KeyError:
            print(f"\nQuery {qid} not found")
            continue

        print(f"\n{qid}: {query.query_name}")
        print(f"  Description: {query.description}")

        try:
            # Execute expression family implementation
            result = query.execute(ctx, "expression")

            # Collect results (triggers lazy evaluation)
            result_df = result.collect() if hasattr(result, "collect") else result

            print(f"  Result shape: {result_df.shape}")
            print("  First 3 rows:")
            print(result_df.head(3))
        except Exception as e:
            print(f"  Error: {e}")

    print("\n" + "=" * 60)
    print("Benchmark complete!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
