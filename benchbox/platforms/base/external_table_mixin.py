from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from benchbox.utils.clock import elapsed_seconds, mono_time

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")


class HiveExternalTableMixin:
    def validate_external_table_requirements(self) -> None:
        if not getattr(self, "staging_root", None):
            platform = getattr(self, "platform_name", type(self).__name__)
            raise ValueError(
                f"{platform} external mode requires --platform-option staging_root=<cloud-uri> "
                "(for example s3://bucket/path or gs://bucket/path)."
            )

    @staticmethod
    def _map_external_column_type(column_type: str) -> str:
        normalized = str(column_type).strip().upper()
        if not normalized:
            return "VARCHAR"
        if normalized.startswith(("DECIMAL", "NUMERIC", "VARCHAR", "CHAR", "TIMESTAMP")):
            return normalized
        if "BIGINT" in normalized:
            return "BIGINT"
        if "SMALLINT" in normalized:
            return "SMALLINT"
        if "INT" in normalized:
            return "INTEGER"
        if "DOUBLE" in normalized:
            return "DOUBLE"
        if "REAL" in normalized or "FLOAT" in normalized:
            return "REAL"
        if "DATE" in normalized:
            return "DATE"
        if "BOOLEAN" in normalized or normalized == "BOOL":
            return "BOOLEAN"
        return "VARCHAR"

    def _build_external_column_definitions(self, benchmark: Any, table_name: str) -> str:
        platform = getattr(self, "platform_name", type(self).__name__)
        if not hasattr(benchmark, "get_schema"):
            raise ValueError(
                f"Benchmark schema metadata unavailable for '{table_name}'. "
                f"{platform} external mode requires benchmark.get_schema()."
            )

        schema = benchmark.get_schema() or {}
        table_schema = schema.get(table_name) or schema.get(table_name.lower()) or schema.get(table_name.upper())
        if not table_schema:
            raise ValueError(f"No schema definition found for table '{table_name}'.")

        columns = table_schema.get("columns", [])
        if not columns:
            raise ValueError(f"No columns found in schema definition for table '{table_name}'.")

        column_defs = []
        for column in columns:
            column_name = str(column.get("name", "")).strip().lower()
            if not column_name:
                raise ValueError(f"Column with empty name found in schema for table '{table_name}'.")
            if not _IDENTIFIER_RE.match(column_name):
                raise ValueError(
                    f"Column name '{column_name}' in table '{table_name}' is not a valid SQL "
                    f"identifier (must match {_IDENTIFIER_RE.pattern}). Quote or rename the column."
                )
            mapped_type = self._map_external_column_type(str(column.get("type", "")))
            column_defs.append(f"{column_name} {mapped_type}")

        if not column_defs:
            raise ValueError(f"No valid column definitions were generated for table '{table_name}'.")

        return ", ".join(column_defs)

    def _build_external_location(self, table_name: str) -> str:
        staging_root = getattr(self, "staging_root", None)
        assert staging_root is not None
        escaped = staging_root.rstrip("/").replace("'", "''")
        return f"{escaped}/{table_name.lower()}/"

    def create_external_tables(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        self.validate_external_table_requirements()

        target_catalog = getattr(self, "catalog", "")
        target_schema = getattr(self, "schema", "")
        validate_id = getattr(self, "_validate_identifier", None)
        if callable(validate_id):
            if not validate_id(target_catalog) or not validate_id(target_schema):
                raise ValueError(f"Invalid catalog or schema for external mode: {target_catalog}.{target_schema}")

        start_time = mono_time()
        table_stats: dict[str, int] = {}
        cursor = connection.cursor()

        try:
            resolve_fn = self._resolve_data_files
            data_files = resolve_fn(benchmark, data_dir)
            for table_name in data_files:
                table_name_lower = table_name.lower()
                if callable(validate_id) and not validate_id(table_name_lower):
                    raise ValueError(f"Invalid table identifier for external mode: {table_name}")

                qualified_table = f"{target_catalog}.{target_schema}.{table_name_lower}"
                location = self._build_external_location(table_name_lower)
                column_defs = self._build_external_column_definitions(benchmark, table_name_lower)

                cursor.execute(f"DROP TABLE IF EXISTS {qualified_table}")
                cursor.execute(
                    f"""
                    CREATE TABLE {qualified_table} ({column_defs})
                    WITH (
                        external_location = '{location}',
                        format = 'PARQUET'
                    )
                    """
                )
                cursor.execute(f"SELECT COUNT(*) FROM {qualified_table}")
                result = cursor.fetchone()
                table_stats[table_name_lower] = int(result[0]) if result else 0

        finally:
            cursor.close()

        total_time = elapsed_seconds(start_time)
        return table_stats, total_time, None
