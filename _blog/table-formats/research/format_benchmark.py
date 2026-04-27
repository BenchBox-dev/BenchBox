#!/usr/bin/env python3
"""
format_benchmark.py - Table formats storage and query timing benchmark script.

Captures data needed for the BenchBox table-formats blog series:
  - Post 0 (Intro): storage sizes across all five formats at SF1
  - Post 1 (Parquet): compression storage sizes + write times at SF1 and SF10
  - Post 2 (Delta Lake): storage sizes at SF1 and SF10, query timing vs Parquet
  - Post 4 (Vortex): storage size and query timing at SF1 and SF10

Measurements:
  1. Export timing and storage size per format/compression combination
  2. Query timing (TPC-H representative subset) via DuckDB reading external files

Formats covered:
  - Parquet (none, snappy, lz4, zstd:3, zstd:9)
  - Delta Lake (snappy, zstd) via deltalake/delta-rs
  - DuckLake (snappy default) via DuckDB ducklake extension
  - Apache Iceberg (snappy, zstd) via pyiceberg with local SQLite catalog
  - Vortex via DuckDB vortex extension or Python vortex bindings

NOT COVERED (requires cloud access):
  - Delta Lake OPTIMIZE / Z-ORDER on Databricks

Usage:
  uv run python _blog/table-formats/research/format_benchmark.py
  uv run python _blog/table-formats/research/format_benchmark.py --sf 10
  uv run python _blog/table-formats/research/format_benchmark.py --sf 1 --sf 10
  uv run python _blog/table-formats/research/format_benchmark.py --queries Q1,Q6,Q12,Q14,Q19
  uv run python _blog/table-formats/research/format_benchmark.py --runs 5 --sf 10

Output:
  benchmark_runs/format_benchmarks/format-benchmarks-YYYY-MM-DD.json
  benchmark_runs/format_benchmarks/format-benchmarks-YYYY-MM-DD.md
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import duckdb

try:
    from deltalake import write_deltalake

    HAS_DELTALAKE = True
except ImportError:
    HAS_DELTALAKE = False
    print("Warning: 'deltalake' package not found. Delta Lake measurements will be skipped.")
    print("Install with: uv add deltalake")

try:
    from pyiceberg.catalog.sql import SqlCatalog

    HAS_PYICEBERG = True
except ImportError:
    HAS_PYICEBERG = False
    print("Warning: 'pyiceberg' package not found. Iceberg measurements will be skipped.")
    print("Install with: uv add pyiceberg[sql-sqlite,pyarrow]")

try:
    import vortex

    HAS_VORTEX = True
except ImportError:
    HAS_VORTEX = False
    print("Warning: 'vortex' package not found. Vortex measurements will be skipped.")
    print("Install with: uv add vortex-data")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]

TPCH_TABLES = [
    "customer",
    "lineitem",
    "nation",
    "orders",
    "part",
    "partsupp",
    "region",
    "supplier",
]

# Parquet compression configurations: (label, codec, level)
PARQUET_CONFIGS = [
    ("none", "none", None),
    ("snappy", "snappy", None),
    ("lz4", "lz4", None),
    ("zstd:3", "zstd", 3),
    ("zstd:9", "zstd", 9),
]

# Delta Lake configurations: (label, compression_codec)
DELTA_CONFIGS = [
    ("snappy", "snappy"),  # delta-rs default
    ("zstd", "zstd"),
]

# Representative TPC-H queries for format comparison.
# Selected to cover: I/O-heavy scan (Q1), range-filter predicate pushdown (Q6),
# join + date filter (Q12), compute-heavy aggregation (Q14), multi-predicate (Q19).
DEFAULT_QUERY_SUBSET = [1, 6, 12, 14, 19]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def dir_size_mb(path: Path) -> float:
    """Return total size of all files under path in MB."""
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024**2)


def source_db_path(sf: float) -> Optional[Path]:
    """Return the path of the loaded TPC-H DuckDB database for a scale factor."""
    sf_tag = f"sf{sf:g}".replace(".", "")
    db_dir = REPO_ROOT / "benchmark_runs" / "databases" / f"tpch_{sf_tag}"
    if not db_dir.exists():
        return None
    # Find the .duckdb file
    candidates = list(db_dir.glob("*.duckdb"))
    return candidates[0] if candidates else None


def ensure_tpch_data(sf: float) -> Path:
    """Ensure TPC-H data is generated and loaded at the given scale factor. Returns DB path."""
    db = source_db_path(sf)
    if db:
        print(f"  Found existing TPC-H SF{sf:g} database: {db}")
        return db

    print(f"  Generating TPC-H SF{sf:g} data via BenchBox...")
    result = subprocess.run(
        [
            "uv",
            "run",
            "benchbox",
            "run",
            "--platform",
            "duckdb",
            "--benchmark",
            "tpch",
            "--scale",
            str(sf),
            "--phases",
            "generate,load",
            "--non-interactive",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: BenchBox generation failed:\n{result.stderr}")
        sys.exit(1)

    db = source_db_path(sf)
    if not db:
        print("ERROR: Could not find generated database after BenchBox run.")
        sys.exit(1)
    print(f"  Generated: {db}")
    return db


def get_tpch_queries(query_ids: list[int]) -> dict[int, str]:
    """Get TPC-H query text from the DuckDB tpch extension."""
    conn = duckdb.connect()
    conn.execute("INSTALL tpch; LOAD tpch;")
    queries = {}
    for qid in query_ids:
        row = conn.execute(f"SELECT query FROM tpch_queries() WHERE query_nr = {qid}").fetchone()
        if row:
            queries[qid] = row[0]
        else:
            print(f"  Warning: query {qid} not found in tpch_queries()")
    conn.close()
    return queries


# ---------------------------------------------------------------------------
# Parquet export
# ---------------------------------------------------------------------------


def export_parquet(
    source_db: Path,
    output_dir: Path,
    codec: str,
    compression_level: Optional[int],
) -> tuple[float, float]:
    """Export TPC-H tables to Parquet. Returns (write_seconds, total_mb)."""
    import pyarrow.parquet as pq

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    src = duckdb.connect(str(source_db), read_only=True)

    parquet_kwargs: dict = {"compression": codec if codec != "none" else "NONE"}
    if compression_level is not None:
        parquet_kwargs["compression_level"] = compression_level

    t0 = time.perf_counter()
    for table in TPCH_TABLES:
        arrow_table = src.execute(f"SELECT * FROM {table}").fetch_arrow_table()
        out_path = output_dir / f"{table}.parquet"
        pq.write_table(arrow_table, str(out_path), **parquet_kwargs)
    elapsed = time.perf_counter() - t0

    src.close()
    total_mb = dir_size_mb(output_dir)
    return elapsed, total_mb


# ---------------------------------------------------------------------------
# Delta Lake export
# ---------------------------------------------------------------------------


def export_delta(
    source_db: Path,
    output_dir: Path,
    compression: str,
) -> tuple[float, float]:
    """Export TPC-H tables to Delta Lake. Returns (write_seconds, total_mb)."""
    if not HAS_DELTALAKE:
        return 0.0, 0.0

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    src = duckdb.connect(str(source_db), read_only=True)

    t0 = time.perf_counter()
    for table in TPCH_TABLES:
        arrow_table = src.execute(f"SELECT * FROM {table}").fetch_arrow_table()
        table_path = str(output_dir / table)
        write_deltalake(
            table_path,
            arrow_table,
            mode="overwrite",
            configuration={"delta.targetFileSize": "134217728"},  # 128 MB target
        )
    elapsed = time.perf_counter() - t0

    src.close()
    total_mb = dir_size_mb(output_dir)
    return elapsed, total_mb


# ---------------------------------------------------------------------------
# DuckLake export
# ---------------------------------------------------------------------------


def export_ducklake(
    source_db: Path,
    output_dir: Path,
) -> tuple[float, float]:
    """Export TPC-H tables to DuckLake. Returns (write_seconds, total_mb)."""
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    catalog_path = str(output_dir / "tpch.ducklake")
    data_path = str(output_dir / "data")

    src = duckdb.connect(str(source_db), read_only=True)

    conn = duckdb.connect()
    conn.execute("INSTALL ducklake; LOAD ducklake;")
    conn.execute(f"ATTACH '{catalog_path}' AS lake (TYPE ducklake, DATA_PATH '{data_path}');")

    t0 = time.perf_counter()
    for table in TPCH_TABLES:
        tbl_data = src.execute(f"SELECT * FROM {table}").fetch_arrow_table()  # noqa: F841
        conn.execute(f"CREATE TABLE lake.{table} AS SELECT * FROM tbl_data")
    elapsed = time.perf_counter() - t0

    src.close()
    conn.close()
    total_mb = dir_size_mb(output_dir)
    return elapsed, total_mb


# ---------------------------------------------------------------------------
# Iceberg export
# ---------------------------------------------------------------------------


def export_iceberg(
    source_db: Path,
    output_dir: Path,
    compression: str = "snappy",
) -> tuple[float, float]:
    """Export TPC-H tables to Apache Iceberg via pyiceberg. Returns (write_seconds, total_mb)."""
    if not HAS_PYICEBERG:
        return 0.0, 0.0

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    src = duckdb.connect(str(source_db), read_only=True)

    # Create a temporary SQLite-backed catalog (no external service needed)
    catalog_db = output_dir / "_catalog.db"
    catalog = SqlCatalog(
        "benchbox_bench",
        uri=f"sqlite:///{catalog_db}",
        warehouse=str(output_dir),
    )
    catalog.create_namespace_if_not_exists("benchbox")

    compression_map = {"snappy": "snappy", "zstd": "zstd", "gzip": "gzip", "none": "uncompressed"}
    codec = compression_map.get(compression, "snappy")

    t0 = time.perf_counter()
    for table in TPCH_TABLES:
        arrow_table = src.execute(f"SELECT * FROM {table}").fetch_arrow_table()
        table_id = ("benchbox", table)
        try:
            catalog.drop_table(table_id)
        except Exception:
            pass
        iceberg_table = catalog.create_table(
            identifier=table_id,
            schema=arrow_table.schema,
            location=(output_dir / table).as_uri(),
            properties={
                "format-version": "2",
                "write.parquet.compression-codec": codec,
            },
        )
        iceberg_table.overwrite(arrow_table)
    elapsed = time.perf_counter() - t0

    src.close()
    # Exclude the catalog DB from size measurement (metadata-only)
    total = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file() and f.name != "_catalog.db")
    total_mb = total / (1024**2)
    return elapsed, total_mb


# ---------------------------------------------------------------------------
# Vortex export
# ---------------------------------------------------------------------------


def export_vortex(
    source_db: Path,
    output_dir: Path,
) -> tuple[float, float]:
    """Export TPC-H tables to Vortex format. Returns (write_seconds, total_mb).

    Tries DuckDB vortex extension first, falls back to Python vortex bindings.
    """
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    src = duckdb.connect(str(source_db), read_only=True)

    # Try DuckDB vortex extension first
    use_duckdb_ext = False
    try:
        test_conn = duckdb.connect()
        test_conn.execute("INSTALL vortex; LOAD vortex;")
        test_conn.close()
        use_duckdb_ext = True
    except Exception:
        if not HAS_VORTEX:
            print("    Neither DuckDB vortex extension nor Python vortex package available")
            src.close()
            return 0.0, 0.0

    t0 = time.perf_counter()
    if use_duckdb_ext:
        conn = duckdb.connect()
        conn.execute("LOAD vortex;")
        for table in TPCH_TABLES:
            arrow_table = src.execute(f"SELECT * FROM {table}").fetch_arrow_table()
            out_path = output_dir / f"{table}.vortex"
            conn.register("_vortex_src", arrow_table)
            escaped = str(out_path).replace("'", "''")
            conn.execute(f"COPY (SELECT * FROM _vortex_src) TO '{escaped}' (FORMAT VORTEX)")
            conn.unregister("_vortex_src")
        conn.close()
    else:
        # Python vortex bindings fallback
        array_fn = getattr(vortex, "array", None)
        if not array_fn:
            encoding = getattr(vortex, "encoding", None)
            array_fn = getattr(encoding, "array", None)
        io_mod = getattr(vortex, "io", None)
        write_fn = getattr(io_mod, "write", None) if io_mod else None
        if not write_fn:
            write_fn = getattr(vortex, "write", None)

        if not callable(array_fn) or not callable(write_fn):
            print("    Vortex Python bindings do not expose compatible API")
            src.close()
            return 0.0, 0.0

        for table in TPCH_TABLES:
            arrow_table = src.execute(f"SELECT * FROM {table}").fetch_arrow_table()
            out_path = output_dir / f"{table}.vortex"
            vortex_arr = array_fn(arrow_table)
            write_fn(vortex_arr, str(out_path))

    elapsed = time.perf_counter() - t0
    src.close()
    total_mb = dir_size_mb(output_dir)
    return elapsed, total_mb


# ---------------------------------------------------------------------------
# Query timing
# ---------------------------------------------------------------------------


def run_query_timing(
    conn: duckdb.DuckDBPyConnection,
    queries: dict[int, str],
    num_runs: int,
) -> dict[int, dict]:
    """Run each query num_runs times, return timing stats in milliseconds."""
    results = {}
    for qid, sql in queries.items():
        times = []
        for _ in range(num_runs):
            t0 = time.perf_counter()
            try:
                conn.execute(sql).fetchall()
            except Exception as e:
                print(f"    Query {qid} error: {e}")
                break
            times.append((time.perf_counter() - t0) * 1000)

        if times:
            times.sort()
            results[qid] = {
                "min_ms": round(times[0], 1),
                "median_ms": round(times[len(times) // 2], 1),
                "max_ms": round(times[-1], 1),
                "runs": len(times),
            }
    return results


def create_parquet_views(conn: duckdb.DuckDBPyConnection, parquet_dir: Path):
    """Register TPC-H table views over Parquet files."""
    conn.execute("INSTALL parquet; LOAD parquet;")
    for table in TPCH_TABLES:
        path = parquet_dir / f"{table}.parquet"
        conn.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM read_parquet('{path}')")


def create_delta_views(conn: duckdb.DuckDBPyConnection, delta_dir: Path):
    """Register TPC-H table views over Delta Lake files."""
    conn.execute("INSTALL delta; LOAD delta;")
    for table in TPCH_TABLES:
        path = delta_dir / table
        conn.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM delta_scan('{path}')")


def create_ducklake_views(conn: duckdb.DuckDBPyConnection, ducklake_dir: Path):
    """Attach DuckLake catalog and expose tables as views in main schema."""
    conn.execute("INSTALL ducklake; LOAD ducklake;")
    catalog_path = ducklake_dir / "tpch.ducklake"
    data_path = ducklake_dir / "data"
    conn.execute(f"ATTACH '{catalog_path}' AS lake (TYPE ducklake, DATA_PATH '{data_path}');")
    for table in TPCH_TABLES:
        conn.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM lake.{table}")


def create_vortex_views(conn: duckdb.DuckDBPyConnection, vortex_dir: Path):
    """Register TPC-H table views over Vortex files."""
    conn.execute("INSTALL vortex; LOAD vortex;")
    for table in TPCH_TABLES:
        path = vortex_dir / f"{table}.vortex"
        conn.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM read_vortex('{path}')")


def time_format_queries(
    format_label: str,
    setup_fn,
    format_dir: Path,
    queries: dict[int, str],
    num_runs: int,
) -> dict[int, dict]:
    """Create a fresh DuckDB connection, set up views for a format, run queries."""
    print(f"    Timing queries against {format_label}...")
    conn = duckdb.connect()
    try:
        setup_fn(conn, format_dir)
        return run_query_timing(conn, queries, num_runs)
    except Exception as e:
        print(f"    Error setting up {format_label}: {e}")
        return {}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------


def geomean(values: list[float]) -> float:
    import math

    if not values:
        return 0.0
    return math.exp(sum(math.log(v) for v in values) / len(values))


def render_markdown(results: dict, sf: float, query_ids: list[int]) -> str:
    lines = [
        f"# Table Format Benchmark Results - TPC-H SF{sf:g}",
        "",
        f"Generated: {date.today().isoformat()}",
        "Hardware: Apple Silicon, 16 GB RAM, local SSD",
        f"DuckDB: {duckdb.__version__}",
        "",
    ]

    # Storage and write time table
    lines += [
        "## Storage and Write Time",
        "",
        "| Format | Size (MB) | Ratio vs None | Write Time (s) |",
        "|--------|----------:|---------------:|---------------:|",
    ]
    storage = results.get("storage", {})
    none_size = storage.get("parquet_none", {}).get("size_mb", 0)
    for label, data in storage.items():
        size_mb = data.get("size_mb", 0)
        ratio = f"{size_mb / none_size:.2f}x" if none_size else "N/A"
        write_s = data.get("write_s", 0)
        lines.append(f"| {label} | {size_mb:.0f} | {ratio} | {write_s:.1f} |")
    lines.append("")

    # Query timing table
    timing = results.get("timing", {})
    if timing:
        q_headers = " | ".join(f"Q{q} (ms)" for q in query_ids)
        lines += [
            "## Query Timing (median ms, DuckDB reading external files)",
            "",
            f"| Format | {q_headers} | Geomean (ms) |",
            "|--------|" + "-------:|" * (len(query_ids) + 1),
        ]
        for label, qtimes in timing.items():
            q_vals = [qtimes.get(q, {}).get("median_ms", 0) for q in query_ids]
            gm = geomean([v for v in q_vals if v > 0])
            q_str = " | ".join(f"{v:.1f}" if v else "N/A" for v in q_vals)
            lines.append(f"| {label} | {q_str} | {gm:.1f} |")
        lines.append("")

    lines += [
        "## Notes",
        "",
        "- Delta Lake OPTIMIZE/Z-ORDER not measured (requires Databricks)",
        "- Iceberg uses local SQLite-backed pyiceberg catalog (no external service)",
        "- Vortex uses DuckDB extension when available, Python bindings as fallback",
        "- Query timing uses DuckDB reading external files, not native DuckDB tables",
        "- Geomean computed over measured queries only",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def benchmark_sf(
    sf: float,
    query_ids: list[int],
    num_runs: int,
    output_base: Path,
) -> dict:
    """Run all format benchmarks for a single scale factor."""
    sf_tag = f"sf{sf:g}".replace(".", "")
    work_dir = output_base / sf_tag
    work_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"Scale factor: SF{sf:g}")
    print(f"{'=' * 60}")

    # Ensure source data exists
    source_db = ensure_tpch_data(sf)

    results: dict = {"sf": sf, "storage": {}, "timing": {}}

    # --- Parquet exports ---
    print("\n[Parquet exports]")
    for label, codec, level in PARQUET_CONFIGS:
        config_dir = work_dir / f"parquet_{label.replace(':', '')}"
        print(f"  Exporting parquet/{label}...")
        write_s, size_mb = export_parquet(source_db, config_dir, codec, level)
        results["storage"][f"parquet_{label}"] = {
            "format": "parquet",
            "compression": label,
            "size_mb": round(size_mb, 1),
            "write_s": round(write_s, 2),
            "path": str(config_dir),
        }
        print(f"    {size_mb:.0f} MB in {write_s:.1f}s")

    # --- Delta Lake exports ---
    if HAS_DELTALAKE:
        print("\n[Delta Lake exports]")
        for label, compression in DELTA_CONFIGS:
            config_dir = work_dir / f"delta_{label}"
            print(f"  Exporting delta/{label}...")
            write_s, size_mb = export_delta(source_db, config_dir, compression)
            results["storage"][f"delta_{label}"] = {
                "format": "delta",
                "compression": label,
                "size_mb": round(size_mb, 1),
                "write_s": round(write_s, 2),
                "path": str(config_dir),
            }
            print(f"    {size_mb:.0f} MB in {write_s:.1f}s")

    # --- DuckLake export ---
    print("\n[DuckLake export]")
    ducklake_dir = work_dir / "ducklake"
    print("  Exporting ducklake (snappy default)...")
    write_s, size_mb = export_ducklake(source_db, ducklake_dir)
    results["storage"]["ducklake"] = {
        "format": "ducklake",
        "compression": "snappy (default)",
        "size_mb": round(size_mb, 1),
        "write_s": round(write_s, 2),
        "path": str(ducklake_dir),
    }
    print(f"    {size_mb:.0f} MB in {write_s:.1f}s")

    # --- Iceberg exports ---
    if HAS_PYICEBERG:
        print("\n[Iceberg exports]")
        for label, compression in [("snappy", "snappy"), ("zstd", "zstd")]:
            config_dir = work_dir / f"iceberg_{label}"
            print(f"  Exporting iceberg/{label}...")
            write_s, size_mb = export_iceberg(source_db, config_dir, compression)
            results["storage"][f"iceberg_{label}"] = {
                "format": "iceberg",
                "compression": label,
                "size_mb": round(size_mb, 1),
                "write_s": round(write_s, 2),
                "path": str(config_dir),
            }
            print(f"    {size_mb:.0f} MB in {write_s:.1f}s")

    # --- Vortex export ---
    print("\n[Vortex export]")
    vortex_dir = work_dir / "vortex"
    print("  Exporting vortex...")
    write_s, size_mb = export_vortex(source_db, vortex_dir)
    if size_mb > 0:
        results["storage"]["vortex"] = {
            "format": "vortex",
            "compression": "default",
            "size_mb": round(size_mb, 1),
            "write_s": round(write_s, 2),
            "path": str(vortex_dir),
        }
        print(f"    {size_mb:.0f} MB in {write_s:.1f}s")
    else:
        print("    Skipped (no vortex extension or package available)")

    # --- Query timing ---
    if query_ids:
        print(f"\n[Query timing ({num_runs} runs each)]")
        queries = get_tpch_queries(query_ids)
        print(f"  Loaded {len(queries)} TPC-H queries")

        # Parquet zstd:3 (BenchBox default)
        parquet_zstd3_dir = work_dir / "parquet_zstd3"
        if parquet_zstd3_dir.exists():
            timing = time_format_queries("parquet/zstd:3", create_parquet_views, parquet_zstd3_dir, queries, num_runs)
            results["timing"]["parquet_zstd3"] = timing

        # Parquet snappy
        parquet_snappy_dir = work_dir / "parquet_snappy"
        if parquet_snappy_dir.exists():
            timing = time_format_queries("parquet/snappy", create_parquet_views, parquet_snappy_dir, queries, num_runs)
            results["timing"]["parquet_snappy"] = timing

        # Parquet none
        parquet_none_dir = work_dir / "parquet_none"
        if parquet_none_dir.exists():
            timing = time_format_queries("parquet/none", create_parquet_views, parquet_none_dir, queries, num_runs)
            results["timing"]["parquet_none"] = timing

        # Delta snappy
        if HAS_DELTALAKE:
            delta_snappy_dir = work_dir / "delta_snappy"
            if delta_snappy_dir.exists():
                timing = time_format_queries("delta/snappy", create_delta_views, delta_snappy_dir, queries, num_runs)
                results["timing"]["delta_snappy"] = timing

        # DuckLake
        if ducklake_dir.exists():
            timing = time_format_queries("ducklake", create_ducklake_views, ducklake_dir, queries, num_runs)
            results["timing"]["ducklake"] = timing

        # Vortex (requires DuckDB vortex extension for read_vortex())
        if vortex_dir.exists() and any(vortex_dir.glob("*.vortex")):
            timing = time_format_queries("vortex", create_vortex_views, vortex_dir, queries, num_runs)
            if timing:
                results["timing"]["vortex"] = timing

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Table format storage and query timing benchmark for BenchBox blog series."
    )
    parser.add_argument(
        "--sf",
        type=float,
        action="append",
        default=None,
        metavar="SCALE_FACTOR",
        help="Scale factor(s) to benchmark (e.g. --sf 1 --sf 10). Default: 1",
    )
    parser.add_argument(
        "--queries",
        type=str,
        default=None,
        metavar="Q1,Q6,Q12",
        help=f"Comma-separated TPC-H query IDs to time. Default: {','.join('Q' + str(q) for q in DEFAULT_QUERY_SUBSET)}",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of timing runs per query per format. Default: 3",
    )
    parser.add_argument(
        "--no-timing",
        action="store_true",
        help="Skip query timing, only measure storage.",
    )
    args = parser.parse_args()

    scale_factors = args.sf or [1.0]

    if args.queries:
        raw = [q.strip().upper().lstrip("Q") for q in args.queries.split(",")]
        query_ids = [int(q) for q in raw if q.isdigit()]
    else:
        query_ids = DEFAULT_QUERY_SUBSET if not args.no_timing else []

    output_base = REPO_ROOT / "benchmark_runs" / "format_benchmarks"
    output_base.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    all_results = {"date": today, "scale_factors": {}}

    for sf in scale_factors:
        sf_results = benchmark_sf(sf, query_ids, args.runs, output_base / "work")
        all_results["scale_factors"][str(sf)] = sf_results

    # Write JSON
    json_path = output_base / f"format-benchmarks-{today}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved to: {json_path}")

    # Write Markdown for each SF
    for sf in scale_factors:
        sf_results = all_results["scale_factors"][str(sf)]
        md = render_markdown(sf_results, sf, query_ids)
        md_path = output_base / f"format-benchmarks-sf{sf:g}-{today}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"Markdown saved to: {md_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
