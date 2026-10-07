#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import decimal
import hashlib
import json
import sys
from pathlib import Path


def short_ids(db_path: Path) -> dict[str, str]:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute("select result_id, short_id from short_ids").fetchall()
    return dict(rows)


def summary(db_path: Path) -> dict:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    platforms_per_cohort = con.execute(
        """
    SELECT benchmark, scale_factor,
           COALESCE(NULLIF(LOWER(TRIM(test_type)), ''), 'unknown') AS phase,
           COUNT(DISTINCT platform_id)
    FROM results
    WHERE platform_id IN ('cedardb', 'datafusion', 'duckdb', 'pandas', 'polars', 'spark')
    GROUP BY 1, 2, 3
    """
    ).fetchall()
    benchmarks = [row[0] for row in con.execute("SELECT DISTINCT benchmark FROM results ORDER BY 1").fetchall()]
    trust_labels = {row[0] for row in con.execute("SELECT DISTINCT trust_label FROM results").fetchall()}
    tuning_rows = con.execute(
        """
    SELECT
        benchmark,
        scale_factor,
        COALESCE(NULLIF(LOWER(TRIM(test_type)), ''), 'unknown') AS phase,
        platform_id,
        COALESCE(tuning_mode, '') AS tuning_mode,
        has_tuning
    FROM results
    ORDER BY 1, 2, 3, 4
    """
    ).fetchall()
    environment_values = {}
    for column in (
        "deployment_class",
        "cloud_provider",
        "cloud_region",
        "instance_or_warehouse",
        "storage_format",
    ):
        environment_values[column] = [
            row[0]
            for row in con.execute(
                f"SELECT DISTINCT {column} FROM results WHERE {column} IS NOT NULL ORDER BY 1"
            ).fetchall()
        ]
    cloud_rows = con.execute(
        """
    SELECT
        result_id,
        platform,
        cloud_provider,
        cloud_region,
        instance_or_warehouse,
        storage_format,
        trust_label
    FROM results
    WHERE deployment_class = 'cloud'
    ORDER BY result_id
    """
    ).fetchall()
    container_rows = con.execute(
        """
    SELECT
        result_id,
        platform,
        deployment_class,
        instance_or_warehouse,
        storage_format,
        trust_label
    FROM results
    WHERE platform = 'Fixture Container SQL'
    ORDER BY result_id
    """
    ).fetchall()
    return {
        "result_count": con.execute("SELECT COUNT(*) FROM results").fetchone()[0],
        "platforms_per_cohort": platforms_per_cohort,
        "benchmarks": benchmarks,
        "trust_labels": sorted(trust_labels),
        "tuning_rows": tuning_rows,
        "environment_values": environment_values,
        "cloud_rows": cloud_rows,
        "container_rows": container_rows,
    }


def _normalize(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize(val) for key, val in sorted(value.items())}
    return value


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def digest(db_path: Path) -> dict:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    tables = sorted(row[0] for row in con.execute("SHOW TABLES").fetchall())
    payload = {}
    for table in tables:
        result = con.execute(f"SELECT * FROM {_quote_ident(table)} ORDER BY ALL")
        columns = [description[0] for description in result.description]
        rows = [[_normalize(value) for value in row] for row in result.fetchall()]
        payload[table] = {"columns": columns, "rows": rows}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {"sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "tables": tables}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Browser fixture queries for the site-inputs bundle")
    parser.add_argument("command", choices=("short-ids", "summary", "digest"))
    parser.add_argument("db", type=Path)
    args = parser.parse_args(argv)
    if args.command == "short-ids":
        sys.stdout.write(json.dumps(short_ids(args.db)))
    elif args.command == "summary":
        print(json.dumps(summary(args.db)))
    else:
        print(json.dumps(digest(args.db)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
