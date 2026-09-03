#!/usr/bin/env python3
"""Canonical content digest for explorer results.duckdb files (G2 root-neutrality gate).

Exact file bytes can never match across builds: the pipeline stamps every
build with a wall-clock ``generated_at``
(``_project/scripts/explorer_pipeline/pipeline.py``) and float aggregates
such as ``geomean_ms`` drift by 1 ULP across runners (libm/CPU), e.g.
``50.5278141562074`` vs ``50.52781415620743``. Both were observed live:
two same-input builds 60s apart hash differently while holding identical
logical content.

This script hashes canonical logical content instead: ordered tables,
schema-ordered columns, rows sorted by full content, floats rounded to
``--float-sig-digits`` significant digits, and ``--exclude-column``
build-stamp columns (default: ``generated_at``) dropped. Two databases
built from the same corpus agree on this digest even when their bytes
differ. Any added/removed table, column, row, or material value change
fails the comparison.

Usage:
  uv run python scripts/publication/compare_db_digest.py digest FILE
  uv run python scripts/publication/compare_db_digest.py compare REBUILT LIVE

Exit codes: 0 match; 1 content mismatch; 2 unusable input (missing file,
unreadable database, empty table set).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

DEFAULT_EXCLUDE_COLUMNS = ("generated_at",)
DEFAULT_FLOAT_SIG_DIGITS = 9


def _canonical_value(value: object, float_sig_digits: int) -> str:
    """Render one cell deterministically with float tolerance."""
    if isinstance(value, bool):
        return f"bool:{value!r}"
    if isinstance(value, int):
        return f"int:{value}"
    if isinstance(value, float):
        return f"float:{format(value, f'.{float_sig_digits}g')}"
    if value is None:
        return "null:"
    return f"str:{value}"


def canonical_digest(
    db_path: Path,
    exclude_columns: tuple[str, ...] = DEFAULT_EXCLUDE_COLUMNS,
    float_sig_digits: int = DEFAULT_FLOAT_SIG_DIGITS,
) -> str:
    """Hash canonical logical content of every table in ``db_path``."""
    import duckdb

    excluded = set(exclude_columns)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = [
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY 1"
            ).fetchall()
        ]
        if not tables:
            raise ValueError(f"no tables in main schema of '{db_path}'")
        digest = hashlib.sha256()
        for table in tables:
            columns = [row[1] for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()]
            kept = [name for name in columns if name not in excluded]
            if not kept:
                raise ValueError(f"table '{table}' has no comparable columns after exclusions")
            collist = ", ".join(f'"{name}"' for name in kept)
            rows = con.execute(f'SELECT {collist} FROM "{table}" ORDER BY {collist}').fetchall()
            digest.update(f"table:{table}\ncolumns:{','.join(kept)}\nrows:{len(rows)}\n".encode())
            for row in rows:
                digest.update("|".join(_canonical_value(value, float_sig_digits) for value in row).encode())
                digest.update(b"\n")
        return digest.hexdigest()
    finally:
        con.close()


def compare_databases(
    rebuilt: Path,
    live: Path,
    exclude_columns: tuple[str, ...] = DEFAULT_EXCLUDE_COLUMNS,
    float_sig_digits: int = DEFAULT_FLOAT_SIG_DIGITS,
) -> list[str]:
    """Diff two databases; empty list means digest-equivalent."""
    for label, path in (("rebuilt", rebuilt), ("live", live)):
        if not path.is_file():
            return [f"{label} database missing: '{path}' (refusing comparison)"]
    try:
        rebuilt_digest = canonical_digest(rebuilt, exclude_columns, float_sig_digits)
    except Exception as exc:
        return [f"rebuilt database unreadable: {exc}"]
    try:
        live_digest = canonical_digest(live, exclude_columns, float_sig_digits)
    except Exception as exc:
        return [f"live database unreadable: {exc}"]
    if rebuilt_digest != live_digest:
        return [f"canonical content digests differ: rebuilt={rebuilt_digest} live={live_digest}; refusing deploy"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Canonical digest comparison for results.duckdb")
    sub = parser.add_subparsers(dest="command", required=True)
    digest_cmd = sub.add_parser("digest", help="print the canonical digest of one database")
    digest_cmd.add_argument("db", type=Path)
    compare_cmd = sub.add_parser("compare", help="fail unless two databases are digest-equivalent")
    compare_cmd.add_argument("rebuilt", type=Path)
    compare_cmd.add_argument("live", type=Path)
    for cmd in (digest_cmd, compare_cmd):
        cmd.add_argument("--exclude-column", action="append", default=list(DEFAULT_EXCLUDE_COLUMNS))
        cmd.add_argument("--float-sig-digits", type=int, default=DEFAULT_FLOAT_SIG_DIGITS)
    args = parser.parse_args(argv)

    if args.command == "digest":
        if not args.db.is_file():
            print(f"::error::database missing: '{args.db}'", file=sys.stderr)
            return 2
        try:
            print(canonical_digest(args.db, tuple(args.exclude_column), args.float_sig_digits))
        except Exception as exc:
            print(f"::error::database unreadable: {exc}", file=sys.stderr)
            return 2
        return 0

    findings = compare_databases(args.rebuilt, args.live, tuple(args.exclude_column), args.float_sig_digits)
    if findings:
        for finding in findings:
            print(f"::error::{finding}")
        return 1
    print(
        f"Digest-equivalent (excluding {', '.join(args.exclude_column)}; "
        f"floats at {args.float_sig_digits} significant digits)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
