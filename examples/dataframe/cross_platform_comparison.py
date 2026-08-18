#!/usr/bin/env python3
"""
Cross-Platform DataFrame Comparison Example

Demonstrates comparing query performance across different DataFrame platforms
(Polars, Pandas) using the same TPC-H queries. This showcases how BenchBox's
family-based architecture enables fair comparisons.

Copyright 2026 Joe Harris / BenchBox Project.
Licensed under the MIT License.

Usage:
    python examples/dataframe/cross_platform_comparison.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Check platform availability
platforms_available = {"polars": False, "pandas": False}

try:
    import polars as pl

    platforms_available["polars"] = True
    print(f"Polars: {pl.__version__}")
except ImportError:
    print("Polars: not installed")

try:
    import pandas as pd

    platforms_available["pandas"] = True
    print(f"Pandas: {pd.__version__}")
except ImportError:
    print("Pandas: not installed")

if not any(platforms_available.values()):
    print("\nError: No DataFrame platforms available.")
    print("Install at least one: pip install polars pandas")
    sys.exit(1)


def load_polars_context(data_dir: Path):
    """Load data into Polars DataFrame context."""
    from benchbox.platforms.polars_platform import PolarsDataFrameContext

    ctx = PolarsDataFrameContext()
    parquet_dir = data_dir / "parquet"

    tables = ["lineitem", "orders", "customer", "supplier", "part", "partsupp", "nation", "region"]
    for table in tables:
        table_path = parquet_dir / f"{table}.parquet"
        if table_path.exists():
            df = pl.scan_parquet(str(table_path))
            ctx.register_table(table, df)

    return ctx


def load_pandas_context(data_dir: Path):
    """Load data into Pandas DataFrame context."""
    from benchbox.platforms import get_dataframe_adapter

    ctx = get_dataframe_adapter("pandas-df", working_dir=str(data_dir)).create_context()
    parquet_dir = data_dir / "parquet"

    tables = ["lineitem", "orders", "customer", "supplier", "part", "partsupp", "nation", "region"]
    for table in tables:
        table_path = parquet_dir / f"{table}.parquet"
        if table_path.exists():
            df = pd.read_parquet(str(table_path))
            ctx.register_table(table, df)

    return ctx


def run_query_timed(query, ctx, family: str) -> tuple[float, int]:
    """Run a query and return execution time and row count."""
    start = time.perf_counter()
    result = query.execute(ctx, family)

    # Collect if lazy
    if hasattr(result, "collect"):
        result = result.collect()

    elapsed = time.perf_counter() - start
    row_count = len(result)

    return elapsed, row_count


def main() -> int:
    """Run cross-platform DataFrame comparison."""
    from benchbox.core.tpch.dataframe_queries import get_query

    print("=" * 70)
    print("Cross-Platform DataFrame Comparison")
    print("=" * 70)

    # Check data availability
    data_dir = Path("benchmark_runs/tpch/sf0.01/data")
    if not data_dir.exists():
        print(f"\nWarning: Data directory not found: {data_dir}")
        print("Generate data first with:")
        print("  benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases load")
        return 1

    # Load contexts for available platforms
    contexts = {}
    families = {}

    if platforms_available["polars"]:
        print("\nLoading Polars context...")
        contexts["Polars"] = load_polars_context(data_dir)
        families["Polars"] = "expression"

    if platforms_available["pandas"]:
        print("Loading Pandas context...")
        contexts["Pandas"] = load_pandas_context(data_dir)
        families["Pandas"] = "pandas"

    # Queries to compare
    query_ids = ["Q1", "Q3", "Q6", "Q10"]

    # Results storage
    results = {qid: {} for qid in query_ids}

    # Run comparisons
    print("\n" + "-" * 70)
    print("Running Query Comparisons")
    print("-" * 70)

    for qid in query_ids:
        try:
            query = get_query(qid)
        except KeyError:
            print(f"\nQuery {qid} not found, skipping")
            continue

        print(f"\n{qid}: {query.query_name}")

        for platform, ctx in contexts.items():
            family = families[platform]

            # Check if query has implementation for this family
            impl = query.get_impl_for_family(family)
            if impl is None:
                print(f"  {platform}: No {family} implementation")
                continue

            try:
                elapsed, row_count = run_query_timed(query, ctx, family)
                results[qid][platform] = {"time": elapsed, "rows": row_count}
                print(f"  {platform}: {elapsed:.4f}s ({row_count} rows)")
            except Exception as e:
                print(f"  {platform}: Error - {e}")

    # Summary table
    print("\n" + "=" * 70)
    print("Performance Summary")
    print("=" * 70)

    # Header
    platform_names = list(contexts.keys())
    header = f"{'Query':<10}"
    for platform in platform_names:
        header += f"{platform:>15}"
    if len(platform_names) == 2:
        header += f"{'Speedup':>15}"
    print(header)
    print("-" * len(header))

    # Data rows
    for qid in query_ids:
        row = f"{qid:<10}"
        times = []
        for platform in platform_names:
            if platform in results[qid]:
                t = results[qid][platform]["time"]
                times.append(t)
                row += f"{t:>14.4f}s"
            else:
                times.append(None)
                row += f"{'N/A':>15}"

        # Calculate speedup if both platforms ran
        if len(times) == 2 and all(t is not None for t in times):
            if times[0] > 0:
                speedup = times[1] / times[0]  # Pandas / Polars
                row += f"{speedup:>14.2f}x"
            else:
                row += f"{'N/A':>15}"

        print(row)

    print("\n" + "=" * 70)
    print("Comparison complete!")
    if len(platform_names) == 2:
        print("Speedup = Pandas time / Polars time (higher means Polars is faster)")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
