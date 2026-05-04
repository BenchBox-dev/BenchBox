"""Minimal reproducers for SQLGlot defects observed by BenchBox.

Pinned to ``sqlglot==30.6.0`` (the version resolved by the BenchBox lockfile
at the time the issues were drafted). Run with:

    uv run --with sqlglot==30.6.0 python _project/sqlglot-upstream/repros/repro_all.py

Each repro prints PASS / FAIL with the offending output. Tier A items are
defects we plan to file. Tier B items must reproduce as FAIL on this version
before we file; if they PASS on 30.6.0 the workaround is obsolete and we
should remove it from BenchBox instead of filing upstream.
"""

from __future__ import annotations

import sys

import sqlglot
from sqlglot.dialects.dialect import Dialect


def _section(title: str) -> None:
    print()
    print(f"=== {title} ===")


def _result(label: str, passed: bool, detail: str) -> bool:
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {label}")
    print(f"        {detail}")
    return passed


def repro_1_duckdb_all_keyword() -> bool:
    _section("Tier B #1: DuckDB GROUP/ORDER BY ALL quoted under identify=True")
    sql = "SELECT col1, col2, SUM(col3) FROM tbl GROUP BY ALL"
    out = sqlglot.transpile(sql, read="duckdb", write="duckdb", identify=True)[0]
    print(f"  input : {sql}")
    print(f"  output: {out}")
    quoted = '"ALL"' in out or "`ALL`" in out
    return _result(
        "GROUP BY ALL preserved as bare keyword (no identifier quoting)",
        passed=not quoted,
        detail=f"detected double-quoted ALL in clause: {quoted}",
    )


def repro_2_sqlite_interval_arithmetic() -> bool:
    _section("Tier A #2: SQLite INTERVAL date arithmetic")
    sql = "SELECT DATE '2025-01-01' + INTERVAL '5' DAY"
    out = sqlglot.transpile(sql, read="postgres", write="sqlite")[0]
    print(f"  input : {sql}")
    print(f"  output: {out}")
    has_interval = "INTERVAL" in out.upper()
    return _result(
        "INTERVAL lowered to SQLite date modifier form",
        passed=not has_interval,
        detail=f"SQLite has no INTERVAL keyword. literal INTERVAL still present: {has_interval}",
    )


def repro_3_sqlite_extract() -> bool:
    _section("Tier B #3: SQLite EXTRACT not lowered to STRFTIME")
    sql = "SELECT EXTRACT(YEAR FROM d) FROM t"
    out = sqlglot.transpile(sql, read="postgres", write="sqlite")[0]
    print(f"  input : {sql}")
    print(f"  output: {out}")
    has_extract = "EXTRACT" in out.upper()
    return _result(
        "EXTRACT lowered to STRFTIME (or equivalent SQLite expression)",
        passed=not has_extract,
        detail=f"SQLite has no EXTRACT. literal EXTRACT still present: {has_extract}",
    )


def repro_5_mysql_percentile_cont_decorator() -> bool:
    _section("Tier A #5: MySQL PERCENTILE_CONT decorated with extra CASE/NULL")
    sql = "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY x) FROM t"
    out = sqlglot.transpile(sql, read="postgres", write="mysql")[0]
    print(f"  input : {sql}")
    print(f"  output: {out}")
    upper = out.upper()
    has_case = "CASE" in upper
    has_null = "NULL" in upper
    decorated = has_case and has_null
    return _result(
        "PERCENTILE_CONT round-trips without synthetic CASE/NULL decorator",
        passed=not decorated,
        detail=f"unwanted CASE+NULL decorator detected: {decorated}",
    )


def repro_6_questdb_dialect_missing() -> bool:
    _section("Tier A #6: QuestDB has no SQLGlot dialect")
    try:
        Dialect.get_or_raise("questdb")
        return _result(
            "QuestDB dialect resolvable",
            passed=True,
            detail="Dialect.get_or_raise('questdb') succeeded — feature request may be obsolete",
        )
    except Exception as exc:
        return _result(
            "QuestDB dialect resolvable",
            passed=False,
            detail=f"Dialect.get_or_raise('questdb') raised: {type(exc).__name__}: {exc}",
        )


def main() -> int:
    print(f"sqlglot version: {sqlglot.__version__}")
    expected = "30.6.0"
    if sqlglot.__version__ != expected:
        print(f"WARNING: pinned to {expected}; running on {sqlglot.__version__}")

    results = [
        ("#1 duckdb-all-keyword (Tier B)", repro_1_duckdb_all_keyword()),
        ("#2 sqlite-interval-arithmetic (Tier A)", repro_2_sqlite_interval_arithmetic()),
        ("#3 sqlite-extract (Tier B)", repro_3_sqlite_extract()),
        ("#5 mysql-percentile-cont (Tier A)", repro_5_mysql_percentile_cont_decorator()),
        ("#6 questdb-dialect-missing (Tier A)", repro_6_questdb_dialect_missing()),
    ]

    _section("Summary (FAIL = defect reproduces; PASS = no longer reproduces)")
    for label, passed in results:
        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}] {label}")

    any_failed = any(not p for _, p in results)
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
