#!/usr/bin/env python3
"""
SQL vs DataFrame Comparison Example

Demonstrates comparing the same TPC-H queries executed via:
1. SQL mode (DuckDB SQL interface)
2. DataFrame mode (Polars expression API)

This highlights how BenchBox enables fair comparison between query paradigms.

Copyright 2026 Joe Harris / BenchBox Project.
Licensed under the MIT License.

Usage:
    python examples/dataframe/sql_vs_dataframe.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Check availability
has_duckdb = False
has_polars = False

try:
    import duckdb

    has_duckdb = True
    print(f"DuckDB: {duckdb.__version__}")
except ImportError:
    print("DuckDB: not installed")

try:
    import polars as pl

    has_polars = True
    print(f"Polars: {pl.__version__}")
except ImportError:
    print("Polars: not installed")


def run_sql_query(conn, sql: str) -> tuple[float, int]:
    """Execute SQL query and return time and row count."""
    start = time.perf_counter()
    result = conn.execute(sql).fetchdf()
    elapsed = time.perf_counter() - start
    return elapsed, len(result)


def run_dataframe_query(query, ctx) -> tuple[float, int]:
    """Execute DataFrame query and return time and row count."""
    start = time.perf_counter()
    result = query.execute(ctx, "expression")
    if hasattr(result, "collect"):
        result = result.collect()
    elapsed = time.perf_counter() - start
    return elapsed, len(result)


TPCH_TABLES = ["lineitem", "orders", "customer", "supplier", "part", "partsupp", "nation", "region"]

Q1_SQL = """
SELECT
    l_returnflag,
    l_linestatus,
    SUM(l_quantity) AS sum_qty,
    SUM(l_extendedprice) AS sum_base_price,
    SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
    SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,
    AVG(l_quantity) AS avg_qty,
    AVG(l_extendedprice) AS avg_price,
    AVG(l_discount) AS avg_disc,
    COUNT(*) AS count_order
FROM lineitem
WHERE l_shipdate <= DATE '1998-09-02'
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag, l_linestatus
"""

Q6_SQL = """
SELECT SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_shipdate >= DATE '1994-01-01'
  AND l_shipdate < DATE '1995-01-01'
  AND l_discount BETWEEN 0.05 AND 0.07
  AND l_quantity < 24
"""


def _run_sql_mode(parquet_dir: Path, results: dict) -> None:
    print("\n" + "-" * 70)
    print("SQL Mode (DuckDB)")
    print("-" * 70)

    conn = duckdb.connect()
    for table in TPCH_TABLES:
        table_path = parquet_dir / f"{table}.parquet"
        if table_path.exists():
            conn.execute(f"CREATE VIEW {table} AS SELECT * FROM '{table_path}'")

    for qid, sql in {"Q1": Q1_SQL, "Q6": Q6_SQL}.items():
        try:
            elapsed, row_count = run_sql_query(conn, sql)
            results[f"SQL-{qid}"] = {"time": elapsed, "rows": row_count}
            print(f"  {qid}: {elapsed:.4f}s ({row_count} rows)")
        except Exception as e:
            print(f"  {qid}: Error - {e}")

    conn.close()


def _run_dataframe_mode(parquet_dir: Path, results: dict) -> None:
    from benchbox.core.dataframe.context import PolarsDataFrameContext
    from benchbox.core.tpch.dataframe_queries import get_tpch_query

    print("\n" + "-" * 70)
    print("DataFrame Mode (Polars)")
    print("-" * 70)

    ctx = PolarsDataFrameContext()
    for table in TPCH_TABLES:
        table_path = parquet_dir / f"{table}.parquet"
        if table_path.exists():
            df = pl.scan_parquet(str(table_path))
            ctx.register_table(table, df)

    for qid in ["Q1", "Q6"]:
        query = get_tpch_query(qid)
        if query is None:
            print(f"  {qid}: Query not found")
            continue
        try:
            elapsed, row_count = run_dataframe_query(query, ctx)
            results[f"DF-{qid}"] = {"time": elapsed, "rows": row_count}
            print(f"  {qid}: {elapsed:.4f}s ({row_count} rows)")
        except Exception as e:
            print(f"  {qid}: Error - {e}")


def _print_results_summary(results: dict) -> None:
    print("\n" + "=" * 70)
    print("Comparison Summary")
    print("=" * 70)

    print(f"\n{'Query':<12}{'Mode':<12}{'Time (s)':<12}{'Rows':<10}")
    print("-" * 46)

    for key, data in sorted(results.items()):
        mode, qid = key.split("-")
        mode_name = "SQL" if mode == "SQL" else "DataFrame"
        print(f"{qid:<12}{mode_name:<12}{data['time']:<12.4f}{data['rows']:<10}")

    if has_duckdb and has_polars:
        print("\n" + "-" * 46)
        print("Performance Comparison:")
        for qid in ["Q1", "Q6"]:
            sql_key = f"SQL-{qid}"
            df_key = f"DF-{qid}"
            if sql_key in results and df_key in results:
                sql_time = results[sql_key]["time"]
                df_time = results[df_key]["time"]
                if df_time > 0:
                    ratio = sql_time / df_time
                    faster = "SQL" if ratio > 1 else "DataFrame"
                    speedup = ratio if ratio > 1 else 1 / ratio
                    print(f"  {qid}: {faster} is {speedup:.2f}x faster")

    print("\n" + "=" * 70)
    print("Key Insight: Both paradigms execute equivalent analytical logic,")
    print("but with different APIs (SQL strings vs method chains).")
    print("=" * 70)


def main() -> int:
    """Run SQL vs DataFrame comparison."""
    print("=" * 70)
    print("SQL vs DataFrame Comparison")
    print("=" * 70)

    if not has_duckdb and not has_polars:
        print("\nError: Need at least DuckDB or Polars installed.")
        print("Run: pip install duckdb polars")
        return 1

    parquet_dir = Path("benchmark_runs/tpch/sf0.01/data") / "parquet"
    if not parquet_dir.exists():
        print(f"\nWarning: Data directory not found: {parquet_dir}")
        print("Generate data first with:")
        print("  benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases load")
        return 1

    results: dict = {}
    if has_duckdb:
        _run_sql_mode(parquet_dir, results)
    if has_polars:
        _run_dataframe_mode(parquet_dir, results)

    _print_results_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
