"""Canonical logical row-content hashing for the JoinOrder dataset.

Byte-level Parquet SHA-256 is not reproducible: the JoinOrder build is
non-deterministic, so a rebuilt archive never matches the pinned per-table byte
hashes even though it carries identical logical content. This module defines a
*logical* content hash — canonical rows in ``id`` order with type-tagged,
encoding-independent cell rendering — that a rebuild reproduces exactly. It is
the dataset's stable identity (see
``_project/decisions/joinorder-logical-verification-2026-07-08.md``).

This is the single source of truth for the algorithm: the runtime loader
(``manifest.py``), the runtime verifier (``manager.py``), and the offline build
script (``_project/scripts/build_joinorder_data.py``) all import it, so build
and runtime cannot compute the hash differently. The version tag
``joinorder-logical-content-v1`` is mixed into every table hash; bump it only on
a deliberate, breaking algorithm change.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Mixed into every per-table hash so an algorithm change is self-identifying.
LOGICAL_CONTENT_VERSION = "joinorder-logical-content-v1"

# PostgreSQL integer type families. Integer columns are canonicalised through
# ``int()`` so a CSV "123" and a Parquet int64 123 render identically; every
# other type renders as its string form. Determining integer-ness from the
# PostgreSQL type (which the manifest pins per column) keeps build and runtime
# in agreement without either re-deriving a DuckDB type.
_INTEGER_POSTGRES_TYPES = frozenset({"smallint", "integer", "bigint", "int", "int2", "int4", "int8"})


def is_integer_postgres_type(postgres_type: str) -> bool:
    """True if *postgres_type* is an integer family type."""
    return postgres_type.strip().lower() in _INTEGER_POSTGRES_TYPES


@dataclass(frozen=True)
class LogicalColumn:
    """A column projected into the logical hash: its name and integer-ness."""

    name: str
    is_integer: bool


@dataclass(frozen=True)
class LogicalTableHash:
    """Canonical row-content hash for one table."""

    table: str
    row_count: int
    sha256: str


def logical_columns_from_schema(schema: Mapping[str, str]) -> list[LogicalColumn]:
    """Build ordered LogicalColumns from a manifest ``schema`` map.

    *schema* maps column name -> PostgreSQL type in column (ordinal) order;
    ordinary dict iteration preserves that order, which must match the order the
    build used when it wrote the manifest.
    """
    return [LogicalColumn(name=name, is_integer=is_integer_postgres_type(pg_type)) for name, pg_type in schema.items()]


def quote_ident(identifier: str) -> str:
    """Quote a SQL identifier, rejecting anything not a bare identifier."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def duckdb_literal(value: str | Path) -> str:
    """Render a value as a single-quoted DuckDB string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def update_sized_hash_part(hasher: Any, tag: str, payload: bytes) -> None:
    """Feed a length-prefixed, tag-delimited part so parts can't collide."""
    hasher.update(tag.encode("ascii"))
    hasher.update(str(len(payload)).encode("ascii"))
    hasher.update(b":")
    hasher.update(payload)
    hasher.update(b";")


def canonical_logical_value(value: Any, column: LogicalColumn) -> tuple[str, bytes]:
    """Return a type-tagged value payload independent of CSV/Parquet encoding.

    ``None`` -> null; integer columns -> ``int()``-normalised digits; everything
    else -> its UTF-8 string form. Callers that carry source-specific NULL
    sentinels (e.g. the build's CSV reader) must convert them to ``None`` first.
    """
    if value is None:
        return ("N", b"")
    if column.is_integer:
        return ("I", str(int(value)).encode("ascii"))
    return ("S", str(value).encode("utf-8"))


def update_logical_row_hash(hasher: Any, columns: Sequence[LogicalColumn], row_values: Sequence[Any]) -> None:
    """Feed one row (column names + canonical values) into *hasher*."""
    if len(row_values) != len(columns):
        raise ValueError(f"Logical hash row has {len(row_values)} values for {len(columns)} columns")
    hasher.update(b"row{")
    for column, value in zip(columns, row_values, strict=True):
        update_sized_hash_part(hasher, "C", column.name.encode("utf-8"))
        tag, payload = canonical_logical_value(value, column)
        update_sized_hash_part(hasher, tag, payload)
    hasher.update(b"}\n")


def aggregate_logical_content_hash(table_hashes: Sequence[LogicalTableHash]) -> str:
    """Stable dataset hash over per-table logical hashes, order-independent."""
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
    """Hash canonical Parquet rows in ``id`` order, ignoring file layout.

    *con* is any DuckDB connection. Rows are read ``ORDER BY id`` so the hash is
    a content contract, not an accidental file-byte or row-group-order contract.
    """
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
