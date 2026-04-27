#!/usr/bin/env python3
"""Benchmark heap-to-columnstore migration for pg_mooncake.

Measures the overhead of converting existing PostgreSQL heap tables to
pg_mooncake's columnstore format, including:
- Conversion time per table (ALTER TABLE ... SET ACCESS METHOD columnstore)
- Storage size before and after conversion (via pg_total_relation_size)
- Query performance delta: heap baseline vs columnstore comparison

Outputs results in BenchmarkResults v2.0 JSON format compatible with
PlatformComparison.from_files() for cross-run analysis.

Exit codes:
  0 - Benchmark completed successfully
  1 - Connection error or other failure

Usage:
  # Run against a local pg_mooncake instance with TPC-H SF=0.01
  uv run -- python scripts/benchmark_mooncake_migration.py \\
    --host localhost --port 5432

  # Custom scale factor and queries
  uv run -- python scripts/benchmark_mooncake_migration.py \\
    --scale-factor 1.0 --queries Q1,Q6,Q14

  # Use pre-existing result files (skip live run)
  uv run -- python scripts/benchmark_mooncake_migration.py \\
    --heap-results heap_run.json --columnstore-results cs_run.json

  # Dry run (show execution plan)
  uv run -- python scripts/benchmark_mooncake_migration.py --dry-run

Requires: psycopg (pip install psycopg[binary])
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

# Default TPC-H tables to migrate
TPCH_TABLES = ["nation", "region", "customer", "orders", "lineitem", "part", "partsupp", "supplier"]

# Simple TPC-H queries for heap vs columnstore comparison
DEFAULT_QUERIES: dict[str, str] = {
    "Q1": """
        SELECT l_returnflag, l_linestatus,
               SUM(l_quantity) AS sum_qty,
               SUM(l_extendedprice) AS sum_base_price
        FROM lineitem
        WHERE l_shipdate <= DATE '1998-12-01' - INTERVAL '90' DAY
        GROUP BY l_returnflag, l_linestatus
        ORDER BY l_returnflag, l_linestatus
    """,
    "Q6": """
        SELECT SUM(l_extendedprice * l_discount) AS revenue
        FROM lineitem
        WHERE l_shipdate >= DATE '1994-01-01'
          AND l_shipdate < DATE '1994-01-01' + INTERVAL '1' YEAR
          AND l_discount BETWEEN 0.06 - 0.01 AND 0.06 + 0.01
          AND l_quantity < 24
    """,
    "Q14": """
        SELECT 100.00 * SUM(CASE WHEN p_type LIKE 'PROMO%%' THEN l_extendedprice * (1 - l_discount) ELSE 0 END) /
               SUM(l_extendedprice * (1 - l_discount)) AS promo_revenue
        FROM lineitem, part
        WHERE l_partkey = p_partkey
          AND l_shipdate >= DATE '1995-09-01'
          AND l_shipdate < DATE '1995-09-01' + INTERVAL '1' MONTH
    """,
}


@dataclass
class TableMigrationResult:
    """Result of migrating a single table."""

    table_name: str
    heap_size_bytes: int
    columnstore_size_bytes: int
    conversion_time_ms: float
    size_ratio: float  # columnstore/heap (< 1 means compression)


@dataclass
class QueryTimingResult:
    """Timing for a single query execution."""

    query_id: str
    execution_time_ms: float
    rows_returned: int
    status: str = "SUCCESS"


@dataclass
class MigrationBenchmarkResult:
    """Complete migration benchmark result."""

    scale_factor: float
    pg_mooncake_version: str
    postgresql_version: str
    timestamp: str
    table_migrations: list[TableMigrationResult] = field(default_factory=list)
    heap_query_results: list[QueryTimingResult] = field(default_factory=list)
    columnstore_query_results: list[QueryTimingResult] = field(default_factory=list)
    total_conversion_time_ms: float = 0.0
    total_heap_size_bytes: int = 0
    total_columnstore_size_bytes: int = 0


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------


def _get_versions(cursor) -> tuple[str, str]:
    """Get pg_mooncake and PostgreSQL versions."""
    cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_mooncake'")
    row = cursor.fetchone()
    mooncake_version = row[0] if row else "unknown"

    cursor.execute("SHOW server_version")
    pg_version = cursor.fetchone()[0]

    return mooncake_version, pg_version


def _get_table_size(cursor, table_name: str) -> int:
    """Get total relation size in bytes."""
    cursor.execute("SELECT pg_total_relation_size(%s)", (table_name,))
    row = cursor.fetchone()
    return row[0] if row else 0


def _run_query(cursor, query_id: str, sql: str) -> QueryTimingResult:
    """Execute a query and return timing."""
    start = time.monotonic()
    try:
        cursor.execute(sql)
        rows = cursor.fetchall()
        elapsed_ms = (time.monotonic() - start) * 1000
        return QueryTimingResult(
            query_id=query_id,
            execution_time_ms=round(elapsed_ms, 3),
            rows_returned=len(rows),
            status="SUCCESS",
        )
    except Exception as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return QueryTimingResult(
            query_id=query_id,
            execution_time_ms=round(elapsed_ms, 3),
            rows_returned=0,
            status=f"FAILED: {e}",
        )


_SAFE_TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_table_name(table_name: str) -> str:
    """Validate table name is a safe SQL identifier (alphanumeric + underscore only)."""
    if not _SAFE_TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name!r} - must be alphanumeric/underscore only")
    return table_name


def _convert_table_to_columnstore(cursor, conn, table_name: str) -> TableMigrationResult:
    """Convert a single table from heap to columnstore and measure overhead."""
    table_name = _validate_table_name(table_name)

    # Measure heap size before conversion
    heap_size = _get_table_size(cursor, table_name)

    # Convert to columnstore - table_name is validated above as a safe identifier
    start = time.monotonic()
    from psycopg import sql

    cursor.execute(sql.SQL("ALTER TABLE {} SET ACCESS METHOD columnstore").format(sql.Identifier(table_name)))
    conn.commit()
    conversion_time_ms = (time.monotonic() - start) * 1000

    # Measure columnstore size after conversion
    columnstore_size = _get_table_size(cursor, table_name)

    size_ratio = columnstore_size / heap_size if heap_size > 0 else 0.0

    return TableMigrationResult(
        table_name=table_name,
        heap_size_bytes=heap_size,
        columnstore_size_bytes=columnstore_size,
        conversion_time_ms=round(conversion_time_ms, 3),
        size_ratio=round(size_ratio, 4),
    )


def run_migration_benchmark(
    conn,
    tables: list[str],
    queries: dict[str, str],
    scale_factor: float,
) -> MigrationBenchmarkResult:
    """Run the full migration benchmark.

    Assumes tables are already loaded as heap tables (standard PostgreSQL).
    Steps:
      1. Measure heap table sizes
      2. Run queries on heap tables (baseline)
      3. Convert each table to columnstore
      4. Run queries on columnstore tables (comparison)
    """
    cursor = conn.cursor()
    mooncake_ver, pg_ver = _get_versions(cursor)

    result = MigrationBenchmarkResult(
        scale_factor=scale_factor,
        pg_mooncake_version=mooncake_ver,
        postgresql_version=pg_ver,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # Phase 1: Run queries on heap tables
    print("Phase 1: Running queries on heap tables...", file=sys.stderr)
    for qid, sql in queries.items():
        timing = _run_query(cursor, qid, sql)
        result.heap_query_results.append(timing)
        print(f"  {qid}: {timing.execution_time_ms:.1f}ms ({timing.rows_returned} rows)", file=sys.stderr)

    # Phase 2: Convert tables to columnstore
    print("\nPhase 2: Converting tables to columnstore...", file=sys.stderr)
    for table_name in tables:
        try:
            migration = _convert_table_to_columnstore(cursor, conn, table_name)
            result.table_migrations.append(migration)
            result.total_conversion_time_ms += migration.conversion_time_ms
            result.total_heap_size_bytes += migration.heap_size_bytes
            result.total_columnstore_size_bytes += migration.columnstore_size_bytes
            compression = f"{migration.size_ratio:.2f}x"
            print(
                f"  {table_name}: {migration.conversion_time_ms:.1f}ms "
                f"({migration.heap_size_bytes:,} -> {migration.columnstore_size_bytes:,} bytes, {compression})",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"  {table_name}: FAILED ({e})", file=sys.stderr)

    # Phase 3: Run queries on columnstore tables
    print("\nPhase 3: Running queries on columnstore tables...", file=sys.stderr)
    for qid, sql in queries.items():
        timing = _run_query(cursor, qid, sql)
        result.columnstore_query_results.append(timing)
        print(f"  {qid}: {timing.execution_time_ms:.1f}ms ({timing.rows_returned} rows)", file=sys.stderr)

    cursor.close()
    return result


# ---------------------------------------------------------------------------
# BenchmarkResults v2.0 output
# ---------------------------------------------------------------------------


def to_benchmark_results_v2(
    result: MigrationBenchmarkResult,
    phase: str,
    platform_name: str,
) -> dict:
    """Convert migration results to BenchmarkResults v2.0 JSON schema.

    Creates a separate result file for heap and columnstore phases so
    PlatformComparison.from_files() can compare them directly.

    Args:
        result: Migration benchmark result
        phase: "heap" or "columnstore"
        platform_name: Platform name for the result file
    """
    query_results = result.heap_query_results if phase == "heap" else result.columnstore_query_results

    queries_list = []
    query_times_ms = []
    for qr in query_results:
        queries_list.append(
            {
                "id": qr.query_id,
                "ms": qr.execution_time_ms,
                "rows": qr.rows_returned,
                "status": "SUCCESS" if qr.status == "SUCCESS" else "FAILED",
                "run_type": "measurement",
            }
        )
        if qr.status == "SUCCESS":
            query_times_ms.append(qr.execution_time_ms)

    total_ms = sum(query_times_ms) if query_times_ms else 0
    successful = len([q for q in query_results if q.status == "SUCCESS"])
    failed = len(query_results) - successful

    payload = {
        "version": "2.0",
        "run": {
            "id": str(uuid.uuid4()),
            "timestamp": result.timestamp,
            "total_duration_ms": round(total_ms),
            "query_time_ms": round(total_ms),
        },
        "benchmark": {
            "id": "tpch",
            "name": "TPC-H",
            "scale_factor": result.scale_factor,
        },
        "platform": {
            "name": platform_name,
        },
        "summary": {
            "queries": {
                "total": len(query_results),
                "passed": successful,
                "failed": failed,
            },
            "timing": {
                "total_ms": round(total_ms, 1),
                "avg_ms": round(total_ms / len(query_results), 1) if query_results else 0,
                "min_ms": round(min(query_times_ms), 1) if query_times_ms else 0,
                "max_ms": round(max(query_times_ms), 1) if query_times_ms else 0,
            },
        },
        "queries": queries_list,
    }

    # Add migration metadata for columnstore phase
    if phase == "columnstore":
        payload["migration"] = {
            "total_conversion_time_ms": round(result.total_conversion_time_ms, 1),
            "total_heap_size_bytes": result.total_heap_size_bytes,
            "total_columnstore_size_bytes": result.total_columnstore_size_bytes,
            "compression_ratio": round(result.total_columnstore_size_bytes / result.total_heap_size_bytes, 4)
            if result.total_heap_size_bytes > 0
            else 0,
            "per_table": [asdict(m) for m in result.table_migrations],
        }

    return payload


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def format_summary_report(result: MigrationBenchmarkResult) -> str:
    """Format a human-readable summary report."""
    lines = [
        "pg_mooncake Heap-to-Columnstore Migration Benchmark",
        f"  pg_mooncake version: {result.pg_mooncake_version}",
        f"  PostgreSQL version:  {result.postgresql_version}",
        f"  Scale factor:        {result.scale_factor}",
        f"  Timestamp:           {result.timestamp}",
        "",
        "Table Migration Results:",
        f"  {'Table':<20} {'Heap Size':>12} {'CS Size':>12} {'Ratio':>8} {'Time (ms)':>10}",
        f"  {'-' * 20} {'-' * 12} {'-' * 12} {'-' * 8} {'-' * 10}",
    ]

    for m in result.table_migrations:
        lines.append(
            f"  {m.table_name:<20} {m.heap_size_bytes:>12,} {m.columnstore_size_bytes:>12,} "
            f"{m.size_ratio:>8.2f} {m.conversion_time_ms:>10.1f}"
        )

    overall_ratio = (
        result.total_columnstore_size_bytes / result.total_heap_size_bytes if result.total_heap_size_bytes > 0 else 0
    )
    lines.extend(
        [
            f"  {'-' * 20} {'-' * 12} {'-' * 12} {'-' * 8} {'-' * 10}",
            f"  {'TOTAL':<20} {result.total_heap_size_bytes:>12,} {result.total_columnstore_size_bytes:>12,} "
            f"{overall_ratio:>8.2f} {result.total_conversion_time_ms:>10.1f}",
            "",
            "Query Performance Comparison:",
            f"  {'Query':<8} {'Heap (ms)':>12} {'CS (ms)':>12} {'Speedup':>10}",
            f"  {'-' * 8} {'-' * 12} {'-' * 12} {'-' * 10}",
        ]
    )

    heap_by_id = {q.query_id: q for q in result.heap_query_results}
    for cs_q in result.columnstore_query_results:
        heap_q = heap_by_id.get(cs_q.query_id)
        if heap_q and heap_q.execution_time_ms > 0:
            speedup = heap_q.execution_time_ms / cs_q.execution_time_ms
            lines.append(
                f"  {cs_q.query_id:<8} {heap_q.execution_time_ms:>12.1f} {cs_q.execution_time_ms:>12.1f} "
                f"{speedup:>9.2f}x"
            )

    return "\n".join(lines)


def format_dry_run(tables: list[str], queries: dict[str, str], scale_factor: float) -> str:
    """Show execution plan without running."""
    lines = [
        "Migration Benchmark Dry Run",
        f"  Scale factor: {scale_factor}",
        "",
        "Tables to migrate:",
    ]
    for t in tables:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append("Queries to run (heap + columnstore):")
    for qid in queries:
        lines.append(f"  - {qid}")
    lines.append("")
    lines.append("Execution plan:")
    lines.append("  1. Run queries on heap tables (baseline)")
    lines.append("  2. ALTER TABLE ... SET ACCESS METHOD columnstore (per table)")
    lines.append("  3. Measure storage sizes before/after")
    lines.append("  4. Run queries on columnstore tables (comparison)")
    lines.append("  5. Output BenchmarkResults v2.0 JSON files")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark heap-to-columnstore migration for pg_mooncake.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  # Run against local pg_mooncake
  %(prog)s --host localhost --port 5432

  # Custom queries and output directory
  %(prog)s --queries Q1,Q6 --output-dir ./results

  # Compare pre-existing result files
  %(prog)s --heap-results heap.json --columnstore-results cs.json

  # Dry run
  %(prog)s --dry-run
""",
    )
    parser.add_argument(
        "--host", default=os.environ.get("PGHOST", "localhost"), help="PostgreSQL host (default: $PGHOST or localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PGPORT", "5432")),
        help="PostgreSQL port (default: $PGPORT or 5432)",
    )
    parser.add_argument(
        "--user", default=os.environ.get("PGUSER", "postgres"), help="PostgreSQL user (default: $PGUSER or postgres)"
    )
    parser.add_argument(
        "--password", default=os.environ.get("PGPASSWORD"), help="PostgreSQL password (default: $PGPASSWORD)"
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("PGDATABASE", "benchbox_tpch"),
        help="PostgreSQL database with TPC-H data loaded as heap tables",
    )
    parser.add_argument(
        "--scale-factor", type=float, default=0.01, help="TPC-H scale factor of the loaded data (default: 0.01)"
    )
    parser.add_argument(
        "--queries",
        default=None,
        help="Comma-separated query IDs to run (default: Q1,Q6,Q14)",
    )
    parser.add_argument(
        "--tables",
        default=None,
        help=f"Comma-separated table names to migrate (default: {','.join(TPCH_TABLES)})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for result JSON files (default: current directory)",
    )
    parser.add_argument(
        "--heap-results",
        type=Path,
        default=None,
        help="Pre-existing heap result file (skip live benchmark, compare only)",
    )
    parser.add_argument(
        "--columnstore-results",
        type=Path,
        default=None,
        help="Pre-existing columnstore result file (skip live benchmark, compare only)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show execution plan without running")
    return parser.parse_args(argv)


def _write_result_file(output_dir: Path, filename: str, payload: dict) -> Path:
    """Write a result payload to a JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_text(json.dumps(payload, indent=2))
    return path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    tables = args.tables.split(",") if args.tables else TPCH_TABLES
    queries = {}
    if args.queries:
        for qid in args.queries.split(","):
            qid = qid.strip().upper()
            if qid in DEFAULT_QUERIES:
                queries[qid] = DEFAULT_QUERIES[qid]
            else:
                print(f"Warning: Unknown query {qid}, skipping", file=sys.stderr)
    else:
        queries = DEFAULT_QUERIES

    if args.dry_run:
        print(format_dry_run(tables, queries, args.scale_factor))
        return 0

    # Compare pre-existing results if provided
    if args.heap_results and args.columnstore_results:
        try:
            from benchbox.core.analysis.comparison import PlatformComparison

            comparison = PlatformComparison.from_files([str(args.heap_results), str(args.columnstore_results)])
            report = comparison.compare()
            print(f"Comparison winner: {report.winner}")
            for ranking in report.rankings:
                print(f"  {ranking.rank}. {ranking.platform} (geomean: {ranking.geometric_mean_time:.1f}ms)")
            for insight in report.insights[:5]:
                print(f"  - {insight}")
        except Exception as e:
            print(f"Error comparing results: {e}", file=sys.stderr)
            return 1
        return 0

    # Live benchmark run
    try:
        import psycopg
    except ImportError:
        print("Error: psycopg is required. Install with: pip install psycopg[binary]", file=sys.stderr)
        return 1

    try:
        conn = psycopg.connect(
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            dbname=args.database,
        )
        conn.autocommit = False
    except Exception as e:
        print(f"Error: Failed to connect to PostgreSQL: {e}", file=sys.stderr)
        return 1

    try:
        result = run_migration_benchmark(conn, tables, queries, args.scale_factor)
    except Exception as e:
        print(f"Error during benchmark: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    # Print summary
    print("\n" + format_summary_report(result))

    # Write BenchmarkResults v2.0 files
    output_dir = args.output_dir or Path(".")
    heap_payload = to_benchmark_results_v2(result, "heap", "pg_mooncake_heap")
    cs_payload = to_benchmark_results_v2(result, "columnstore", "pg_mooncake_columnstore")

    heap_path = _write_result_file(output_dir, "migration_heap.json", heap_payload)
    cs_path = _write_result_file(output_dir, "migration_columnstore.json", cs_payload)

    print("\nResult files written:", file=sys.stderr)
    print(f"  Heap baseline:  {heap_path}", file=sys.stderr)
    print(f"  Columnstore:    {cs_path}", file=sys.stderr)
    print("\nCompare with:", file=sys.stderr)
    print(f"  {sys.argv[0]} --heap-results {heap_path} --columnstore-results {cs_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
