from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGICAL_CONTENT_VERSION = "joinorder-logical-content-v1"

_INTEGER_POSTGRES_TYPES = frozenset({"smallint", "integer", "bigint", "int", "int2", "int4", "int8"})


def is_integer_postgres_type(postgres_type: str) -> bool:
    return postgres_type.strip().lower() in _INTEGER_POSTGRES_TYPES


@dataclass(frozen=True)
class LogicalColumn:
    name: str
    is_integer: bool


@dataclass(frozen=True)
class LogicalTableHash:
    table: str
    row_count: int
    sha256: str


def logical_columns_from_schema(schema: Mapping[str, str]) -> list[LogicalColumn]:
    return [LogicalColumn(name=name, is_integer=is_integer_postgres_type(pg_type)) for name, pg_type in schema.items()]


def quote_ident(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def duckdb_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def update_sized_hash_part(hasher: Any, tag: str, payload: bytes) -> None:
    hasher.update(tag.encode("ascii"))
    hasher.update(str(len(payload)).encode("ascii"))
    hasher.update(b":")
    hasher.update(payload)
    hasher.update(b";")


def canonical_logical_value(value: Any, column: LogicalColumn) -> tuple[str, bytes]:
    if value is None:
        return ("N", b"")
    if column.is_integer:
        return ("I", str(int(value)).encode("ascii"))
    return ("S", str(value).encode("utf-8"))


def update_logical_row_hash(hasher: Any, columns: Sequence[LogicalColumn], row_values: Sequence[Any]) -> None:
    if len(row_values) != len(columns):
        raise ValueError(f"Logical hash row has {len(row_values)} values for {len(columns)} columns")
    hasher.update(b"row{")
    for column, value in zip(columns, row_values, strict=True):
        update_sized_hash_part(hasher, "C", column.name.encode("utf-8"))
        tag, payload = canonical_logical_value(value, column)
        update_sized_hash_part(hasher, tag, payload)
    hasher.update(b"}\n")


def aggregate_logical_content_hash(table_hashes: Sequence[LogicalTableHash]) -> str:
    payload = "\n".join(
        f"{entry.table}:{entry.row_count}:{entry.sha256}" for entry in sorted(table_hashes, key=lambda f: f.table)
    )
    return hashlib.sha256((payload + "\n").encode("utf-8")).hexdigest()


def logical_table_hash_from_parquet(
    *,
    con: Any,
    parquet_path: Path,
    table: str,
    columns: Sequence[LogicalColumn],
    batch_size: int = 100_000,
) -> LogicalTableHash:
    hasher = hashlib.sha256()
    update_sized_hash_part(hasher, "V", LOGICAL_CONTENT_VERSION.encode("ascii"))
    update_sized_hash_part(hasher, "T", table.encode("utf-8"))
    select_list = ", ".join(quote_ident(column.name) for column in columns)
    cursor = con.execute(
        f"SELECT {select_list} FROM read_parquet({duckdb_literal(parquet_path)}) ORDER BY {quote_ident('id')}"
    )
    row_count = 0
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        for row in rows:
            update_logical_row_hash(hasher, columns, row)
            row_count += 1
    return LogicalTableHash(table=table, row_count=row_count, sha256=hasher.hexdigest())
