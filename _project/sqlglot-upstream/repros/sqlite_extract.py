"""Execute bounded SQLite date-extraction reproducers without importing BenchBox.

Run in an isolated environment with a selected SQLGlot version. Exit 1 means
at least one translation disagrees with its explicit expected result; exit 2
means the reproducer or a reference query failed. These cases are witnesses,
not a general equivalence proof. PostgreSQL is not executed by this script.
The verdict also gates on translated equivalents of the naive-lowering
counterexamples, so an incomplete upstream fix cannot pass on the
projection cases while leaving TIMESTAMP casts or integer division wrong.
"""

from __future__ import annotations

import json
import sqlite3
import sys

import sqlglot


def cases() -> list[tuple[str, str, str, list[tuple[object, ...]]]]:
    """Use DATE values with independently specified calendar components."""
    result = []
    dates = {
        "YEAR": [(2000,), (1900,), (2024,), (2024,), (None,)],
        "MONTH": [(2,), (3,), (12,), (12,), (None,)],
        "DAY": [(29,), (1,), (31,), (31,), (None,)],
    }
    for source in ("postgres", "duckdb"):
        for part, expected in dates.items():
            result.append(
                (
                    f"{source}-extract-{part.lower()}",
                    source,
                    f"SELECT EXTRACT({part} FROM d) FROM t ORDER BY id",
                    expected,
                )
            )
        result.extend(
            [
                (
                    f"{source}-cast-date",
                    source,
                    "SELECT EXTRACT(YEAR FROM CAST('2020-06-01' AS DATE))",
                    [(2020,)],
                ),
                (
                    f"{source}-nested-date",
                    source,
                    "SELECT EXTRACT(MONTH FROM COALESCE(d, DATE '2001-01-01')) FROM t ORDER BY id",
                    [(2,), (3,), (12,), (12,), (1,)],
                ),
                (
                    f"{source}-date-part",
                    source,
                    "SELECT DATE_PART('year', d) FROM t ORDER BY id",
                    dates["YEAR"],
                ),
            ]
        )
    return result


def translated_trap_cases() -> list[tuple[str, str, str, list[tuple[object, ...]]]]:
    """Source-level equivalents of the naive-lowering traps, translated at runtime.

    Each entry is (id, source dialect, source SQL, expected rows). Unlike the
    hand-written SQLite traps in main() (which pin the already-lowered shape
    and only guard the witness, never the verdict), these go through sqlglot's
    read->sqlite lowering inside main(), so a naive STRFTIME lowering that is
    still wrong on TIMESTAMP casts or integer division fails the harness
    instead of passing silently.
    """
    return [
        (
            "timestamp-cast-affinity",
            "postgres",
            "SELECT EXTRACT(YEAR FROM CAST('2020-06-01 12:00:00' AS TIMESTAMP))",
            [(2020,)],
        ),
        (
            "integer-division",
            "postgres",
            "SELECT EXTRACT(YEAR FROM DATE '2020-06-01') / 3 > 673",
            [(1,)],
        ),
    ]


def main() -> int:
    records = []
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(
            "CREATE TABLE t(id INTEGER, d TEXT);"
            "INSERT INTO t VALUES (1, '2000-02-29'), (2, '1900-03-01'),"
            "(3, '2024-12-31'), (4, '2024-12-31'), (5, NULL);"
        )
        for case_id, source, query, expected in cases():
            record: dict[str, object] = {"id": case_id, "source": source, "sql": query, "expected": expected}
            try:
                translated = sqlglot.transpile(query, read=source, write="sqlite")[0]
                record["translated"] = translated
                actual = connection.execute(translated).fetchall()
                record.update(actual=actual, matched=actual == expected)
            except (sqlglot.errors.SqlglotError, sqlite3.Error) as exc:
                record.update(matched=False, error=f"{type(exc).__name__}: {exc}")
            records.append(record)

        # The simple replacement must not be accepted from a bare YEAR example.
        # SQLite TIMESTAMP casts have numeric affinity, not temporal semantics.
        traps = [
            (
                "timestamp-cast-affinity",
                "SELECT CAST(STRFTIME('%Y', CAST('2020-06-01 12:00:00' AS TIMESTAMP)) AS INTEGER)",
                [(2020,)],
            ),
            (
                "integer-division",
                "SELECT CAST(STRFTIME('%Y', DATE('2020-06-01')) AS INTEGER) / 3 > 673",
                [(1,)],
            ),
        ]
        counterexamples = []
        for case_id, query, expected in traps:
            actual = connection.execute(query).fetchall()
            if actual == expected:
                raise AssertionError(f"Counterexample no longer distinguishes incorrect lowering: {case_id}")
            counterexamples.append({"id": case_id, "sql": query, "actual": actual, "expected": expected})

        reference = connection.execute("SELECT CAST(STRFTIME('%Y', d) AS INTEGER) FROM t ORDER BY id").fetchall()
        if reference != [(2000,), (1900,), (2024,), (2024,), (None,)]:
            raise AssertionError("SQLite DATE-text reference failed")

        translated_traps = []
        for case_id, source, query, expected in translated_trap_cases():
            entry: dict[str, object] = {"id": case_id, "source": source, "sql": query, "expected": expected}
            try:
                translated = sqlglot.transpile(query, read=source, write="sqlite")[0]
                entry["translated"] = translated
                actual = connection.execute(translated).fetchall()
                entry.update(actual=actual, matched=actual == expected)
            except (sqlglot.errors.SqlglotError, sqlite3.Error) as exc:
                entry.update(matched=False, error=f"{type(exc).__name__}: {exc}")
            translated_traps.append(entry)

    report = {
        "sqlglot_version": getattr(sqlglot, "__version__", "unknown"),
        "sqlglot_path": sqlglot.__file__,
        "sqlite_version": sqlite3.sqlite_version,
        "fixture_contract": "Source DATE columns represented as ISO date TEXT in SQLite; no PostgreSQL execution",
        "cases": records,
        "naive_lowering_counterexamples": counterexamples,
        "translated_counterexamples": translated_traps,
        "passed": sum(bool(record["matched"]) for record in records),
        "total": len(records),
    }
    print(json.dumps(report, indent=2))
    complete = all(record["matched"] for record in records) and all(trap["matched"] for trap in translated_traps)
    return 0 if complete else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Reproducer infrastructure failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
