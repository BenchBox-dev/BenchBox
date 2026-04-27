"""Shared schema primitives for benchmark table definitions.

``BaseSchemaTable`` provides the common ``get_primary_key``,
``get_foreign_keys``, and ``get_create_table_sql`` logic that every
benchmark's ``Table`` class reimplemented identically. Each benchmark
still defines its own ``DataType`` enum and ``Column`` NamedTuple because
the enum values and any column-level quirks (e.g. Data Vault HASHKEY
handling) are benchmark-specific. The shared base only depends on columns
being duck-typed to expose ``name``, ``nullable``, ``primary_key``,
``foreign_key``, and ``get_sql_type()``.
"""

from __future__ import annotations

from typing import Any


class BaseSchemaTable:
    """Base class for benchmark table definitions.

    Subclasses may add benchmark-specific fields (e.g. Data Vault's
    ``table_type``) by overriding ``__init__`` and calling ``super().__init__``.
    """

    def __init__(self, name: str, columns: list[Any]) -> None:
        self.name = name
        self.columns = columns

    def get_primary_key(self) -> list[str]:
        """Return the primary-key column names for this table."""
        return [col.name for col in self.columns if col.primary_key]

    def get_foreign_keys(self) -> dict[str, tuple[str, str]]:
        """Return ``{column_name: (ref_table, ref_column)}`` for FK columns."""
        return {col.name: col.foreign_key for col in self.columns if col.foreign_key is not None}

    def get_create_table_sql(
        self,
        enable_primary_keys: bool = True,
        enable_foreign_keys: bool = True,
    ) -> str:
        """Generate ``CREATE TABLE`` SQL for this table.

        Args:
            enable_primary_keys: Include ``PRIMARY KEY`` constraint.
            enable_foreign_keys: Include ``FOREIGN KEY`` constraints.
        """
        column_defs: list[str] = []
        pk_columns: list[str] = []
        fk_defs: list[str] = []

        for col in self.columns:
            col_def = f"{col.name} {col.get_sql_type()}"

            if not col.nullable:
                col_def += " NOT NULL"

            if col.primary_key and enable_primary_keys:
                pk_columns.append(col.name)

            if col.foreign_key and enable_foreign_keys:
                ref_table, ref_col = col.foreign_key
                fk_defs.append(f"FOREIGN KEY ({col.name}) REFERENCES {ref_table}({ref_col})")

            column_defs.append(col_def)

        if pk_columns and enable_primary_keys:
            column_defs.append(f"PRIMARY KEY ({', '.join(pk_columns)})")

        if enable_foreign_keys:
            column_defs.extend(fk_defs)

        sql = f"CREATE TABLE {self.name} (\n    "
        sql += ",\n    ".join(column_defs)
        sql += "\n);"

        return sql
