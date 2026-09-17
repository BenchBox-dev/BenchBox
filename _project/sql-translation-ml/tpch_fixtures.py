"""Small TPC-H-schema witnesses, not compliant TPC-H benchmark data."""

from __future__ import annotations

import random
import sqlite3

import duckdb

from benchbox.core.tpch.schema import TABLES, DataType

SEEDS = (701, 809, 907, 1009, 1105)
SCHEMA = {t.name: {c.name: c.get_sql_type() for c in t.columns} for t in TABLES}


def rows(seed: int) -> dict:
    rng = random.Random(seed)
    result = {}
    for table in TABLES:
        records = []
        for index in range(1, 9):
            record = []
            for column in table.columns:
                if column.primary_key:
                    value = index
                elif column.foreign_key:
                    value = (index - 1) % 4 + 1
                elif column.nullable and index in (1, 5):
                    value = None
                elif column.data_type in (DataType.INTEGER, DataType.DECIMAL):
                    value = rng.choice([-3, 0, 2, 2, 7])
                elif column.data_type == DataType.DATE:
                    value = rng.choice(["1993-12-31", "1994-06-01", "1995-01-01", "2000-02-29", "2024-12-31"])
                elif column.name == "o_orderstatus":
                    value = rng.choice(["F", "O", "P"])
                else:
                    value = rng.choice(["a", "a ", "", "雪", "A_%'", "e\u0301", "a\nb"])
                    value = value[: column.size] if column.size else value
                record.append(value)
            records.append(tuple(record))
        rng.shuffle(records)
        result[table.name] = [] if table.name == "lineitem" and seed == SEEDS[-1] else records
    return result


def connection(dialect: str, seed: int):
    conn = (
        duckdb.connect(config={"enable_external_access": "false", "threads": "1", "memory_limit": "128MB"})
        if dialect == "duckdb"
        else sqlite3.connect(":memory:")
    )
    if dialect == "duckdb":
        conn.execute("SET TimeZone='UTC'")
    fixture = rows(seed)
    for name, columns in SCHEMA.items():
        declarations = ",".join(
            f'"{c}" {"TEXT" if dialect == "sqlite" and t == "DATE" else t}' for c, t in columns.items()
        )
        conn.execute(f'CREATE TABLE "{name}" ({declarations})')
        values = fixture[name]
        if values:
            placeholders = ",".join("?" for _ in columns)
            conn.executemany(f'INSERT INTO "{name}" VALUES ({placeholders})', values)
    if dialect == "sqlite":
        conn.set_authorizer(
            lambda action, *args: (
                sqlite3.SQLITE_OK
                if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
                else sqlite3.SQLITE_DENY
            )
        )
    return conn
