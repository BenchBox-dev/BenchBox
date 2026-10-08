#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TYPE_CATALOG: dict[str, list[tuple[str, str]]] = {
    "numeric": [
        ("SMALLINT", "col SMALLINT"),
        ("INTEGER", "col INTEGER"),
        ("BIGINT", "col BIGINT"),
        ("DECIMAL(10,2)", "col DECIMAL(10,2)"),
        ("NUMERIC(12,4)", "col NUMERIC(12,4)"),
        ("REAL", "col REAL"),
        ("DOUBLE PRECISION", "col DOUBLE PRECISION"),
        ("SERIAL", "col SERIAL"),
        ("BIGSERIAL", "col BIGSERIAL"),
    ],
    "character": [
        ("CHAR(10)", "col CHAR(10)"),
        ("VARCHAR(255)", "col VARCHAR(255)"),
        ("TEXT", "col TEXT"),
    ],
    "binary": [
        ("BYTEA", "col BYTEA"),
    ],
    "datetime": [
        ("DATE", "col DATE"),
        ("TIME", "col TIME"),
        ("TIME WITH TIME ZONE", "col TIME WITH TIME ZONE"),
        ("TIMESTAMP", "col TIMESTAMP"),
        ("TIMESTAMP WITH TIME ZONE", "col TIMESTAMP WITH TIME ZONE"),
        ("INTERVAL", "col INTERVAL"),
    ],
    "boolean": [
        ("BOOLEAN", "col BOOLEAN"),
    ],
    "uuid": [
        ("UUID", "col UUID"),
    ],
    "json": [
        ("JSON", "col JSON"),
        ("JSONB", "col JSONB"),
    ],
    "array": [
        ("INTEGER[]", "col INTEGER[]"),
        ("TEXT[]", "col TEXT[]"),
    ],
    "geometric": [
        ("POINT", "col POINT"),
        ("LINE", "col LINE"),
        ("BOX", "col BOX"),
    ],
    "network": [
        ("INET", "col INET"),
        ("CIDR", "col CIDR"),
        ("MACADDR", "col MACADDR"),
    ],
    "monetary": [
        ("MONEY", "col MONEY"),
    ],
    "bit": [
        ("BIT(8)", "col BIT(8)"),
        ("BIT VARYING(64)", "col BIT VARYING(64)"),
    ],
    "range": [
        ("INT4RANGE", "col INT4RANGE"),
        ("DATERANGE", "col DATERANGE"),
    ],
}


REFERENCE_TYPE_SUPPORT: dict[str, bool] = {
    "SMALLINT": True,
    "INTEGER": True,
    "BIGINT": True,
    "DECIMAL(10,2)": True,
    "NUMERIC(12,4)": True,
    "REAL": True,
    "DOUBLE PRECISION": True,
    "SERIAL": True,
    "BIGSERIAL": True,
    "CHAR(10)": True,
    "VARCHAR(255)": True,
    "TEXT": True,
    "BYTEA": True,
    "DATE": True,
    "TIME": True,
    "TIME WITH TIME ZONE": False,
    "TIMESTAMP": True,
    "TIMESTAMP WITH TIME ZONE": True,
    "INTERVAL": False,
    "BOOLEAN": True,
    "UUID": True,
    "JSON": False,
    "JSONB": True,
    "INTEGER[]": False,
    "TEXT[]": False,
    "POINT": False,
    "LINE": False,
    "BOX": False,
    "INET": False,
    "CIDR": False,
    "MACADDR": False,
    "MONEY": False,
    "BIT(8)": False,
    "BIT VARYING(64)": False,
    "INT4RANGE": False,
    "DATERANGE": False,
}


@dataclass
class TypeProbeResult:
    type_name: str
    category: str
    supported: bool
    error_message: str | None = None


@dataclass
class CompatibilityMatrix:
    pg_mooncake_version: str
    postgresql_version: str
    probe_timestamp: str
    total_types: int = 0
    supported_count: int = 0
    unsupported_count: int = 0
    results: list[TypeProbeResult] = field(default_factory=list)


TEST_TABLE_NAME = "_benchbox_type_probe"


def _get_versions(cursor) -> tuple[str, str]:
    cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_mooncake'")
    row = cursor.fetchone()
    mooncake_version = row[0] if row else "unknown"

    cursor.execute("SHOW server_version")
    pg_version = cursor.fetchone()[0]

    return mooncake_version, pg_version


def _probe_type(cursor, conn, type_name: str, ddl_fragment: str) -> tuple[bool, str | None]:
    ddl = f"CREATE TABLE {TEST_TABLE_NAME} ({ddl_fragment}) USING columnstore"
    drop = f"DROP TABLE IF EXISTS {TEST_TABLE_NAME}"

    try:
        cursor.execute(drop)
        conn.commit()
        cursor.execute(ddl)
        conn.commit()
        cursor.execute(drop)
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        try:
            cursor.execute(drop)
            conn.commit()
        except Exception:
            conn.rollback()
        return False, str(e).strip().split("\n")[0]


def run_probe(conn) -> CompatibilityMatrix:
    cursor = conn.cursor()

    mooncake_version, pg_version = _get_versions(cursor)
    matrix = CompatibilityMatrix(
        pg_mooncake_version=mooncake_version,
        postgresql_version=pg_version,
        probe_timestamp=datetime.now(timezone.utc).isoformat(),
    )

    for category, types in TYPE_CATALOG.items():
        for type_name, ddl_fragment in types:
            supported, error = _probe_type(cursor, conn, type_name, ddl_fragment)
            result = TypeProbeResult(
                type_name=type_name,
                category=category,
                supported=supported,
                error_message=error,
            )
            matrix.results.append(result)
            matrix.total_types += 1
            if supported:
                matrix.supported_count += 1
            else:
                matrix.unsupported_count += 1

    cursor.close()
    return matrix


def format_matrix_json(matrix: CompatibilityMatrix) -> str:
    return json.dumps(asdict(matrix), indent=2)


def format_matrix_yaml(matrix: CompatibilityMatrix) -> str:
    lines = [
        f'pg_mooncake_version: "{matrix.pg_mooncake_version}"',
        f'postgresql_version: "{matrix.postgresql_version}"',
        f'probe_timestamp: "{matrix.probe_timestamp}"',
        f"total_types: {matrix.total_types}",
        f"supported_count: {matrix.supported_count}",
        f"unsupported_count: {matrix.unsupported_count}",
        "",
        "results:",
    ]
    for r in matrix.results:
        lines.append(f'  - type_name: "{r.type_name}"')
        lines.append(f'    category: "{r.category}"')
        lines.append(f"    supported: {str(r.supported).lower()}")
        if r.error_message:
            escaped = r.error_message.replace('"', '\\"')
            lines.append(f'    error_message: "{escaped}"')
    return "\n".join(lines) + "\n"


def format_matrix_table(matrix: CompatibilityMatrix) -> str:
    lines = [
        "pg_mooncake Type Compatibility Matrix",
        f"  pg_mooncake version: {matrix.pg_mooncake_version}",
        f"  PostgreSQL version:  {matrix.postgresql_version}",
        f"  Probed at:           {matrix.probe_timestamp}",
        f"  Supported: {matrix.supported_count}/{matrix.total_types}",
        "",
        f"{'Type':<30} {'Category':<15} {'Status':<12} {'Error'}",
        f"{'-' * 30} {'-' * 15} {'-' * 12} {'-' * 40}",
    ]
    for r in matrix.results:
        status = "OK" if r.supported else "UNSUPPORTED"
        error = r.error_message or ""
        if len(error) > 40:
            error = error[:37] + "..."
        lines.append(f"{r.type_name:<30} {r.category:<15} {status:<12} {error}")

    return "\n".join(lines)


def build_reference_matrix() -> CompatibilityMatrix:
    matrix = CompatibilityMatrix(
        pg_mooncake_version="reference",
        postgresql_version="reference",
        probe_timestamp=datetime.now(timezone.utc).isoformat(),
    )

    for category, types in TYPE_CATALOG.items():
        for type_name, _ in types:
            supported = REFERENCE_TYPE_SUPPORT.get(type_name, False)
            error = None if supported else "Not supported by Parquet/DuckDB engine (reference)"
            result = TypeProbeResult(
                type_name=type_name,
                category=category,
                supported=supported,
                error_message=error,
            )
            matrix.results.append(result)
            matrix.total_types += 1
            if supported:
                matrix.supported_count += 1
            else:
                matrix.unsupported_count += 1

    return matrix


def dry_run_output() -> str:
    lines = ["Types that would be probed:", ""]
    for category, types in TYPE_CATALOG.items():
        lines.append(f"  {category}:")
        for type_name, _ in types:
            lines.append(f"    - {type_name}")
    total = sum(len(types) for types in TYPE_CATALOG.values())
    lines.append(f"\nTotal: {total} types across {len(TYPE_CATALOG)} categories")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe pg_mooncake columnstore data type compatibility.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  # Probe local pg_mooncake and print table
  %(prog)s --host localhost --port 5432

  # Output JSON matrix
  %(prog)s --format json --output mooncake_types.json

  # Dry run (no connection needed)
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
        default=os.environ.get("PGDATABASE", "postgres"),
        help="PostgreSQL database (default: $PGDATABASE or postgres)",
    )
    parser.add_argument(
        "--format", choices=["table", "json", "yaml"], default="table", help="Output format (default: table)"
    )
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output file path (default: stdout)")
    parser.add_argument("--dry-run", action="store_true", help="Show types to probe without connecting")
    parser.add_argument(
        "--generate-reference",
        action="store_true",
        help="Generate a reference matrix from hardcoded type support data (no connection needed)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.dry_run:
        output = dry_run_output()
        if args.output:
            args.output.write_text(output)
            print(f"Wrote dry-run output to {args.output}", file=sys.stderr)
        else:
            print(output)
        return 0

    if args.generate_reference:
        matrix = build_reference_matrix()
        if args.format == "json":
            output = format_matrix_json(matrix)
        elif args.format == "yaml":
            output = format_matrix_yaml(matrix)
        else:
            output = format_matrix_table(matrix)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output)
            print(f"Wrote reference matrix to {args.output}", file=sys.stderr)
        else:
            print(output)
        return 0

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
    except Exception as e:
        print(f"Error: Failed to connect to PostgreSQL: {e}", file=sys.stderr)
        return 1

    try:
        matrix = run_probe(conn)
    finally:
        conn.close()

    if args.format == "json":
        output = format_matrix_json(matrix)
    elif args.format == "yaml":
        output = format_matrix_yaml(matrix)
    else:
        output = format_matrix_table(matrix)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
        print(f"Wrote {args.format} output to {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
