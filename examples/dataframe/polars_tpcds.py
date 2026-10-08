#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project.
# Licensed under the MIT License.

from __future__ import annotations

import sys
from pathlib import Path

try:
    import polars as pl

    print(f"Polars version: {pl.__version__}")
except ImportError:
    print("Error: Polars not installed. Run: pip install polars")
    sys.exit(1)


def main() -> int:
    from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES, get_tpcds_query
    from benchbox.platforms.polars_platform import PolarsAdapter

    print("=" * 60)
    print("Polars DataFrame TPC-DS Benchmark")
    print("=" * 60)

    print("\nRegistered TPC-DS queries:")
    all_queries = TPCDS_DATAFRAME_QUERIES.get_all_queries()
    for query in all_queries[:5]:
        print(f"  {query.query_id}: {query.query_name}")
    print(f"  ... and {len(all_queries) - 5} more ({len(all_queries)} total)")

    print("\nQuery complexity breakdown:")
    simple_count = sum(1 for q in all_queries if "simple" in str(q.categories).lower() or len(q.categories) <= 3)
    print(f"  Simple queries (2-3 joins): {simple_count}")
    print(f"  Moderate queries (CTEs/subqueries): {len(all_queries) - simple_count}")

    data_dir = Path("benchmark_runs/tpcds/sf1/data")
    if not data_dir.exists():
        print(f"\nWarning: Data directory not found: {data_dir}")
        print("Generate data first with:")
        print("  benchbox run --platform duckdb --benchmark tpcds --scale 1 --phases load")
        print("\nNote: TPC-DS requires scale factor >= 1")
        print("\nSkipping query execution, showing structure only.")
        return 0

    print("\nCreating Polars DataFrame context...")
    ctx = PolarsAdapter().create_connection()

    tpcds_tables = [
        "store_sales",
        "store_returns",
        "catalog_sales",
        "catalog_returns",
        "web_sales",
        "web_returns",
        "inventory",
        "store",
        "customer",
        "customer_address",
        "customer_demographics",
        "date_dim",
        "time_dim",
        "item",
        "promotion",
        "warehouse",
        "ship_mode",
        "reason",
        "income_band",
        "household_demographics",
        "call_center",
        "web_page",
        "web_site",
        "catalog_page",
    ]

    parquet_dir = data_dir / "parquet"
    if parquet_dir.exists():
        print(f"Loading tables from {parquet_dir}...")
        loaded = 0
        for table in tpcds_tables:
            table_path = parquet_dir / f"{table}.parquet"
            if table_path.exists():
                df = pl.scan_parquet(str(table_path))
                ctx.register_table(table, df)
                loaded += 1
        print(f"  Loaded {loaded} of {len(tpcds_tables)} tables")
    else:
        print(f"Parquet directory not found: {parquet_dir}")
        return 1

    print("\n" + "-" * 60)
    print("Executing Sample Queries")
    print("-" * 60)

    sample_queries = ["Q3", "Q42", "Q52", "Q55", "Q96"]
    for qid in sample_queries:
        query = get_tpcds_query(qid)
        if query is None:
            print(f"\nQuery {qid} not found")
            continue

        print(f"\n{qid}: {query.query_name}")
        print(f"  Description: {query.description}")

        try:
            result = query.execute(ctx, "expression")

            result_df = result.collect() if hasattr(result, "collect") else result

            print(f"  Result shape: {result_df.shape}")
            if len(result_df) > 0:
                print("  First 3 rows:")
                print(result_df.head(3))
        except Exception as e:
            print(f"  Error: {e}")

    print("\n" + "=" * 60)
    print("TPC-DS DataFrame Benchmark complete!")
    print("=" * 60)
    print("\nTPC-DS provides more complex analytical queries than TPC-H:")
    print("  - 24 tables (vs 8 in TPC-H)")
    print("  - 99 queries (vs 22 in TPC-H)")
    print("  - Multi-channel retail scenario (store, catalog, web)")
    print("  - Complex patterns: rollups, window functions, set operations")

    return 0


if __name__ == "__main__":
    sys.exit(main())
