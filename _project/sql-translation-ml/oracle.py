"""Strict local execution oracle; never imported by the supported package."""

from __future__ import annotations

import datetime as dt
import math
import random
import sqlite3
import threading
from collections import Counter
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp

SCHEMA = {
    "items": {"id": "integer", "grp": "integer", "amount": "integer", "txt": "text", "day": "date"},
    "other": {"id": "integer", "grp": "integer", "amount": "integer", "txt": "text", "day": "date"},
}
SETTINGS = {"timezone": "UTC", "collation": "BINARY", "numeric_tolerance": 0}


def safe_query(sql: str, dialect: str) -> exp.Expression:
    """Restrict generated candidates to read-only expressions over fixture tables."""
    statements = sqlglot.parse(sql, read=dialect)
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
        raise ValueError("expected exactly one SELECT query")
    tree = statements[0]
    forbidden = (exp.DDL, exp.DML, exp.Command, exp.Into)
    aliases = {cte.alias for cte in tree.find_all(exp.CTE)}
    for node in tree.walk():
        if isinstance(node, exp.With) and node.args.get("recursive"):
            raise ValueError("recursive CTE excluded")
        if isinstance(node, forbidden):
            raise ValueError("non-read construct")
        if isinstance(node, exp.Table):
            if not isinstance(node.this, exp.Identifier) or node.name not in {*SCHEMA, *aliases}:
                raise ValueError("unknown table or table function")
            if node.db or node.catalog:
                raise ValueError("qualified external table")
        if isinstance(node, exp.Anonymous):
            if node.name.lower() not in {"julianday", "strftime", "date", "datetime"}:
                raise ValueError("unknown function")
        if isinstance(node, exp.Func) and any(
            word in node.sql_name().lower() for word in ("read_", "scan", "rand", "current", "uuid", "write", "load")
        ):
            raise ValueError("external or nondeterministic function")
    return tree


def fixture_rows(seed: int) -> dict[str, list[tuple[Any, ...]]]:
    """Five independently seeded witnesses, with targeted edge rows in every nonempty table."""
    rng = random.Random(seed)
    rows = [
        (1, 0, None, None, "1999-12-31"),
        (2, 0, -3, "a ", "2000-02-29"),
        (3, 1, 2, "a", "2024-12-31"),
        (4, 1, 2, "é", "2025-01-01"),
        (5, None, 0, "e\u0301", "2024-02-29"),
        (6, 2, 7, "A_%'", "2024-03-01"),
    ]
    for i in range(7, 20):
        rows.append(
            (
                i,
                rng.choice([None, 0, 1, 2]),
                rng.choice([None, -9, -1, 0, 2, 9]),
                rng.choice(["", " ", "abc", "a\nb", "雪", None]),
                rng.choice(["1999-12-31", "2000-02-29", "2025-01-01"]),
            )
        )
    other = [rows[1], rows[1], rows[3], (99, 9, -7, "unmatched", "2001-01-01")]
    rng.shuffle(rows)
    rng.shuffle(other)
    return {"items": rows, "other": [] if seed % 5 == 0 else other}


def connection(dialect: str, seed: int) -> Any:
    if dialect == "duckdb":
        conn = duckdb.connect(config={"enable_external_access": "false", "threads": "1", "memory_limit": "128MB"})
        conn.execute("SET TimeZone='UTC'")
    else:
        conn = sqlite3.connect(":memory:")
    for table, rows in fixture_rows(seed).items():
        date_type = "DATE" if dialect == "duckdb" else "TEXT"
        conn.execute(f"CREATE TABLE {table}(id BIGINT, grp BIGINT, amount BIGINT, txt TEXT, day {date_type})")
        if rows:
            conn.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?)", rows)
    if dialect == "sqlite":
        conn.set_authorizer(
            lambda action, *args: (
                sqlite3.SQLITE_OK
                if action
                in {
                    sqlite3.SQLITE_SELECT,
                    sqlite3.SQLITE_READ,
                    sqlite3.SQLITE_FUNCTION,
                }
                else sqlite3.SQLITE_DENY
            )
        )
    return conn


def execute(conn: Any, sql: str, dialect: str, timeout: float = 2.0) -> tuple[int, list[tuple[Any, ...]]]:
    safe_query(sql, dialect)
    timer = threading.Timer(timeout, conn.interrupt)
    timer.start()
    try:
        cursor = conn.execute(sql)
        rows = cursor.fetchmany(10001)
        if len(rows) > 10000:
            raise ValueError("result row limit")
        return len(cursor.description), rows
    finally:
        timer.cancel()


def cell(value: Any) -> tuple[str, Any]:
    if value is None:
        return ("null", None)
    if isinstance(value, dt.datetime):
        return ("text", value.isoformat(sep=" "))
    if isinstance(value, dt.date):
        return ("text", value.isoformat())
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("nonfinite result")
        return ("number", value)
    if isinstance(value, str):
        return ("text", value)
    raise ValueError(f"unsupported result type: {type(value).__name__}")


def equivalent(left: tuple[int, list], right: tuple[int, list], ordered: bool) -> bool:
    if left[0] != right[0]:
        return False
    a = [tuple(cell(v) for v in row) for row in left[1]]
    b = [tuple(cell(v) for v in row) for row in right[1]]
    return a == b if ordered else Counter(a) == Counter(b)


def validate(source: str, candidate: str, dialect: str, seeds: list[int]) -> dict[str, Any]:
    target = "sqlite" if dialect == "duckdb" else "duckdb"
    ordered = bool(safe_query(source, dialect).args.get("order"))
    evidence = []
    for seed in seeds:
        source_conn, target_conn = connection(dialect, seed), connection(target, seed)
        try:
            expected = execute(source_conn, source, dialect)
            actual = execute(target_conn, candidate, target)
            matches = equivalent(expected, actual, ordered)
            evidence.append({"seed": seed, "matches": matches, "source_rows": len(expected[1])})
        except Exception as exc:
            evidence.append({"seed": seed, "matches": False, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            source_conn.close()
            target_conn.close()
    return {"equivalent": all(e["matches"] for e in evidence), "fixtures": evidence}
