"""Sorted-ingestion + CTAS-sort helpers for PlatformAdapter.

Extracted from `benchbox.platforms.base.adapter` per the refactor map
(`docs/development/adapter-refactor-map.md` Slice 2). Covers the
sorted-ingestion capability matrix, strategy resolution, metadata
reporting, and the default CTAS-sort execution pipeline.

Platform adapters opt into CTAS sorting by overriding `_build_ctas_sort_sql`;
default returns None so unsupported platforms are safely skipped.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.input_validation import validate_sql_identifier

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import TuningColumn

try:
    from benchbox.core.tuning.interface import TuningType
except ImportError:
    TuningType = None


class SortedIngestionMixin:
    """Mixin providing sorted-ingestion + CTAS-sort plumbing for `PlatformAdapter`.

    Expects the host class to expose `platform_name`, `logger`, `dry_run_mode`,
    `capture_sql`, `log_verbose`, and `get_effective_tuning_configuration`
    (the last lives on `PlatformAdapter` itself for now; see Slice 2b).
    """

    platform_name: str
    logger: logging.Logger

    def get_sorted_ingestion_capability(self) -> dict[str, Any]:
        """Return sorted-ingestion capability metadata for the current platform."""
        cloud_method_matrix = {
            "snowflake": ["ctas"],
            "databricks": ["ctas", "z_order", "liquid_clustering"],
            "bigquery": ["ctas"],
            "redshift": ["ctas", "vacuum_sort"],
            "athena": ["ctas"],
            "azure synapse": ["ctas"],
            "clickhouse cloud": [],
        }

        platform_key = self.platform_name.strip().lower()
        methods = cloud_method_matrix.get(platform_key, ["ctas"])
        is_cloud = platform_key in cloud_method_matrix
        return {
            "platform": self.platform_name,
            "is_cloud_platform": is_cloud,
            "supports_sorted_ingestion": bool(methods),
            "supported_methods": methods,
        }

    def resolve_sorted_ingestion_strategy(self) -> tuple[str, str]:
        """Resolve sorted-ingestion mode/method with capability guardrails."""
        capability = self.get_sorted_ingestion_capability()
        supported_methods = capability["supported_methods"]

        effective_config = self.get_effective_tuning_configuration()
        platform_optimizations = getattr(effective_config, "platform_optimizations", None)

        mode = getattr(platform_optimizations, "sorted_ingestion_mode", "off")
        method = getattr(platform_optimizations, "sorted_ingestion_method", "auto")

        if mode == "off":
            return "off", "auto"

        if method != "auto" and method not in supported_methods:
            raise ValueError(
                f"Sorted ingestion method '{method}' is not supported for platform '{self.platform_name}'."
            )

        if not supported_methods:
            if mode == "force":
                raise ValueError(f"Sorted ingestion mode 'force' is not supported for platform '{self.platform_name}'.")
            return "off", "none"

        resolved_method = method if method != "auto" else supported_methods[0]
        return mode, resolved_method

    def get_sorted_ingestion_metadata(self) -> dict[str, Any]:
        """Return configured/resolved sorted-ingestion metadata for result reporting."""
        effective_config = self.get_effective_tuning_configuration()
        platform_optimizations = getattr(effective_config, "platform_optimizations", None)
        configured_mode = getattr(platform_optimizations, "sorted_ingestion_mode", "off")
        configured_method = getattr(platform_optimizations, "sorted_ingestion_method", "auto")

        resolved_mode: str | None = None
        resolved_method: str | None = None
        resolution_error: str | None = None
        try:
            resolved_mode, resolved_method = self.resolve_sorted_ingestion_strategy()
        except Exception as exc:  # pragma: no cover - defensive metadata path
            resolution_error = str(exc)

        applied_tables = getattr(self, "_sorted_ingestion_applied_tables", [])
        total_apply_seconds = getattr(self, "_sorted_ingestion_total_apply_seconds", 0.0)
        unique_tables = sorted(set(applied_tables))
        return {
            "configured_mode": configured_mode,
            "configured_method": configured_method,
            "resolved_mode": resolved_mode,
            "resolved_method": resolved_method,
            "capability": self.get_sorted_ingestion_capability(),
            "applied_tables": unique_tables,
            "applied_table_count": len(unique_tables),
            "total_apply_seconds": total_apply_seconds,
            "resolution_error": resolution_error,
        }

    def apply_ctas_sort(self, table_name: str, tuning_config: Any, connection: Any) -> bool:
        """Apply CTAS-based sorting after a table load when sorting is configured.

        This shared implementation performs table-tuning lookup, sort-column extraction,
        identifier validation, dry-run SQL capture, and execution. Platform adapters
        enable CTAS sorting by overriding _build_ctas_sort_sql(); adapters that return
        ``None`` are treated as unsupported and safely skipped.
        """
        sort_columns = self._resolve_ctas_sort_columns(table_name, tuning_config)
        if sort_columns is None:
            return False

        validated_table = validate_sql_identifier(table_name, "table name")
        sorted_columns = sorted(sort_columns, key=lambda column: column.order)
        for column in sorted_columns:
            validate_sql_identifier(column.name, "sort column")
        ctas_sort_sql = self._build_ctas_sort_sql(validated_table, sorted_columns)

        if ctas_sort_sql is None:
            self.logger.debug(f"{self.platform_name} does not support CTAS sort for {table_name}; skipping")
            return False

        statements = ctas_sort_sql if isinstance(ctas_sort_sql, list) else [ctas_sort_sql]
        return self._execute_ctas_sort(table_name, validated_table, sorted_columns, statements, connection)

    def _resolve_ctas_sort_columns(self, table_name: str, tuning_config: Any) -> list | None:
        """Resolve sort columns for CTAS sort, returning None if not applicable."""
        if not tuning_config:
            self.logger.debug(f"No tuning config provided for {table_name}; skipping CTAS sort")
            return None

        table_tunings = getattr(tuning_config, "table_tunings", None)
        if not table_tunings:
            self.logger.debug(f"No table tunings configured for {table_name}; skipping CTAS sort")
            return None

        table_tuning = None
        for configured_name, configured_tuning in table_tunings.items():
            if configured_name.lower() == table_name.lower():
                table_tuning = configured_tuning
                break

        if not table_tuning:
            self.logger.debug(f"Table {table_name} not present in tuning config; skipping CTAS sort")
            return None

        if TuningType is None:
            self.logger.debug("TuningType unavailable; skipping CTAS sort")
            return None

        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if not sort_columns:
            self.logger.debug(f"No sort columns for {table_name}; skipping CTAS sort")
            return None

        return sort_columns

    def _execute_ctas_sort(
        self, table_name: str, validated_table: str, sorted_columns: list, statements: list[str], connection: Any
    ) -> bool:
        """Execute CTAS sort statements or capture them in dry-run mode."""
        apply_start = mono_time()
        if not hasattr(self, "_sorted_ingestion_applied_tables"):
            self._sorted_ingestion_applied_tables = []
        if not hasattr(self, "_sorted_ingestion_total_apply_seconds"):
            self._sorted_ingestion_total_apply_seconds = 0.0
        if self.dry_run_mode:
            for statement in statements:
                self.capture_sql(statement, "ctas_sort", validated_table)
            self._sorted_ingestion_applied_tables.append(validated_table)
            return True

        for statement in statements:
            self._execute_sql_statement(connection, statement)
        self._sorted_ingestion_applied_tables.append(validated_table)
        self._sorted_ingestion_total_apply_seconds += elapsed_seconds(apply_start)
        sorted_col_names = ", ".join(column.name for column in sorted_columns)
        self.log_verbose(f"Applied CTAS sorting to {table_name}: {sorted_col_names}")
        return True

    @staticmethod
    def _execute_sql_statement(connection: Any, statement: str) -> None:
        """Execute a SQL statement against execute()-style or cursor()-style connections."""
        execute_method = getattr(connection, "execute", None)
        if callable(execute_method):
            execute_method(statement)
            return

        cursor_method = getattr(connection, "cursor", None)
        if callable(cursor_method):
            cursor = cursor_method()
            try:
                cursor.execute(statement)
            finally:
                close_method = getattr(cursor, "close", None)
                if callable(close_method):
                    close_method()
            return

        raise TypeError("Connection must provide execute() or cursor().execute() for CTAS sort")

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | list[str] | None:
        """Build CTAS SQL used by apply_ctas_sort for this platform.

        Platforms opt in by overriding this hook and returning SQL that rewrites
        ``table_name`` ordered by ``sort_columns``. The default implementation
        returns ``None``, which indicates CTAS sorting is unsupported. Adapters
        may return either a single SQL statement or a list of statements.

        ``sort_columns`` is pre-sorted by ``apply_ctas_sort`` (ascending by
        ``column.order``). Implementations must not sort again.
        """
        return None
