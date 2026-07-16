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


def get_fk_ordered_table_names(tables: list[Any]) -> list[str]:
    """Return table names ordered so FK-referenced tables load before dependents.

    Performs a stable topological sort (a simplified Kahn's algorithm) using
    each table's ``get_foreign_keys()`` metadata: a table becomes eligible
    once every table it references (via a foreign key) has already been
    placed. Ties are broken by the tables' original relative order, so the
    result is deterministic and, for schemas with no FK dependencies,
    identical to the input order.

    A self-referencing FK (a table whose foreign key points at itself) is
    dropped from its dependency set before the sort runs, so it never blocks
    that table from being placed. A cycle spanning two or more distinct
    tables cannot be fully ordered, though; any tables left over once no
    further progress can be made are appended in their original relative
    order rather than raising, so callers always get a usable ordering back.

    Args:
        tables: Benchmark table definitions exposing ``.name`` and
            ``get_foreign_keys()`` (i.e. ``BaseSchemaTable`` subclasses).

    Returns:
        Table names in dependency-safe load order.
    """
    names = [table.name for table in tables]
    name_set = set(names)
    deps: dict[str, set[str]] = {
        table.name: {
            ref_table
            for ref_table, _ref_col in table.get_foreign_keys().values()
            if ref_table in name_set and ref_table != table.name
        }
        for table in tables
    }
    return _stable_topological_order(names, deps)


def _stable_topological_order(names: list[str], deps: dict[str, set[str]]) -> list[str]:
    """Shared Kahn's-algorithm core behind ``get_fk_ordered_table_names`` and
    ``get_fk_ordered_table_names_from_column_specs``.

    Args:
        names: All table names to order.
        deps: ``{table_name: {names of tables it must load after}}``.

    Returns:
        ``names`` reordered so every dependency precedes its dependent,
        falling back to input order (see module-level notes above) for any
        table names not present as keys in ``deps``, and to input order for
        the leftovers of an unresolvable multi-table cycle.
    """
    ordered: list[str] = []
    placed: set[str] = set()
    remaining = list(names)

    while remaining:
        progressed = False
        for name in list(remaining):
            if deps.get(name, set()) <= placed:
                ordered.append(name)
                placed.add(name)
                remaining.remove(name)
                progressed = True
        if not progressed:
            # Cycle spanning two or more tables: preserve input order for
            # the leftovers instead of raising.
            ordered.extend(remaining)
            break

    return ordered


class _DottedForeignKeyTable:
    """Adapts a raw dict-based table spec to the interface
    ``get_fk_ordered_table_names`` expects.

    Some benchmarks (SSB, CoffeeShop) define their schema as plain dicts
    loaded from a ``schema_specs.yaml``, where a column's foreign key is a
    single ``"referenced_table.referenced_column"`` string rather than a
    ``BaseSchemaTable`` column's ``(table, column)`` tuple. This wraps one
    such table spec so it can go through the same ordering helper as the
    ``BaseSchemaTable``-based benchmarks (e.g. TPC-H) without duplicating
    the topological sort.
    """

    def __init__(self, name: str, table_spec: dict[str, Any]) -> None:
        self.name = name
        self._columns = table_spec.get("columns", [])

    def get_foreign_keys(self) -> dict[str, tuple[str, str]]:
        """Return ``{column_name: (ref_table, ref_column)}`` for FK columns."""
        result: dict[str, tuple[str, str]] = {}
        for column in self._columns:
            foreign_key = column.get("foreign_key")
            if foreign_key:
                ref_table, ref_column = foreign_key.split(".", 1)
                result[column["name"]] = (ref_table, ref_column)
        return result


def get_fk_ordered_table_names_from_column_specs(tables: dict[str, dict[str, Any]]) -> list[str]:
    """``get_fk_ordered_table_names``, for dict/YAML-based schemas.

    For benchmarks (SSB, CoffeeShop) whose FK metadata is a dotted
    ``"table.column"`` string on each column spec rather than a
    ``BaseSchemaTable`` column's ``(table, column)`` tuple.

    Args:
        tables: Mapping of table key to table spec dict, in the shape each
            benchmark's ``schema_specs.yaml`` produces (e.g. ``TABLES`` in
            ``benchbox.core.ssb.schema`` / ``benchbox.core.coffeeshop.schema``):
            ``{"columns": [{"name": ..., "foreign_key": "ref_table.ref_col"}, ...]}``.

    Returns:
        Table names (the dict's keys) in dependency-safe load order.
    """
    adapters = [_DottedForeignKeyTable(name, spec) for name, spec in tables.items()]
    return get_fk_ordered_table_names(adapters)
