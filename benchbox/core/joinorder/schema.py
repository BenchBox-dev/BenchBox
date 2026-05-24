"""Join Order Benchmark schema definitions."""

from pathlib import Path
from typing import Any

import yaml

from benchbox.sql_compat.local_exemptions import compat_local


def _load_schema_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("schema_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class JoinOrderSchema:
    """Schema manager for the Join Order Benchmark."""

    def __init__(self) -> None:
        """Initialize the Join Order schema manager."""
        specs = _load_schema_specs()
        self._tables = specs["tables"]
        self._table_order = list(specs["table_order"])
        self._relationship_tables = list(specs["relationship_tables"])
        self._dimension_tables = list(specs["dimension_tables"])

    @compat_local(
        kind="type_mapping",
        platform_specific=True,
        reason=(
            "Substitutes dialect-specific type tokens: VARCHAR→CHARACTER VARYING for postgres, "
            "TEXT→TEXT CHARACTER SET utf8mb4 for mysql. "
            "Pure column-type translation - no engine/layout policy."
        ),
    )
    def get_create_table_sql(
        self,
        table_name: str,
        dialect: str = "sqlite",
        *,
        include_foreign_keys: bool = False,
    ) -> str:
        """Generate CREATE TABLE SQL for a specific table.

        Args:
            table_name: Name of the table
            dialect: SQL dialect ('sqlite', 'postgres', 'mysql', 'duckdb')

        Returns:
            SQL CREATE TABLE statement
        """
        if table_name not in self._tables:
            raise ValueError(f"Table {table_name} not found in schema")

        table = self._tables[table_name]
        columns = table["columns"]

        # Adjust column definitions for different dialects
        if dialect == "postgres":
            columns = [col.replace("VARCHAR", "CHARACTER VARYING") for col in columns]
        elif dialect == "mysql":
            columns = [col.replace("TEXT", "TEXT CHARACTER SET utf8mb4") for col in columns]

        sql = f"CREATE TABLE {table_name} (\n"
        sql += ",\n".join(f"    {col}" for col in columns)

        # The canonical IMDb dataset contains dangling references, so foreign
        # keys are opt-in metadata rather than default load-time constraints.
        if include_foreign_keys and dialect in ["postgres", "mysql"] and "foreign_keys" in table:
            for fk in table["foreign_keys"]:
                sql += f",\n    {fk}"

        sql += "\n);"
        return sql

    def get_create_tables_sql(self, dialect: str = "sqlite", *, include_foreign_keys: bool = False) -> str:
        """Generate CREATE TABLE SQL for all tables.

        Args:
            dialect: SQL dialect ('sqlite', 'postgres', 'mysql', 'duckdb')

        Returns:
            SQL CREATE TABLE statements for all tables
        """
        sql_statements = []
        for table_name in self._table_order:
            sql_statements.append(
                self.get_create_table_sql(table_name, dialect, include_foreign_keys=include_foreign_keys)
            )

        return "\n\n".join(sql_statements)

    def get_table_names(self) -> list[str]:
        """Get list of all table names.

        Returns:
            List of table names
        """
        return list(self._tables.keys())

    def get_table_info(self, table_name: str) -> dict:
        """Get information about a specific table.

        Args:
            table_name: Name of the table

        Returns:
            Dictionary with table column and foreign key information
        """
        if table_name not in self._tables:
            raise ValueError(f"Table {table_name} not found in schema")

        return self._tables[table_name].copy()

    def get_relationship_tables(self) -> list[str]:
        """Get list of relationship/junction tables.

        Returns:
            List of relationship table names
        """
        return list(self._relationship_tables)

    def get_dimension_tables(self) -> list[str]:
        """Get list of main dimension tables.

        Returns:
            List of dimension table names
        """
        return list(self._dimension_tables)
