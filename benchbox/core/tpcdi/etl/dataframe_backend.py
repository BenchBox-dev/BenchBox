"""DataFrame-maintenance-backed TPC-DI ETL backend implementation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from benchbox.core.dataframe.maintenance_interface import DataFrameMaintenanceOperations


def _render_literal(value: Any) -> str:
    """Render a Python scalar as a SQL literal for maintenance predicates."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"Unsupported literal value for SCD2 operation: {value!r}")


def _condition_to_sql(condition: str | Any) -> str:
    """Normalize an SCD2 expire condition to a SQL predicate string.

    Maintenance operations accept SQL predicate strings (polars SQL, Delta
    predicates); dict conditions are rendered to ``"col" = <literal>`` Equality
    clauses mirroring the SQL backend's parameterized where-clause builder.
    """
    if isinstance(condition, str):
        if not condition.strip():
            raise ValueError("SCD2 expire condition cannot be empty")
        return condition
    if isinstance(condition, dict):
        if not condition:
            raise ValueError("SCD2 expire condition dictionary cannot be empty")
        clauses: list[str] = []
        for raw_column, value in condition.items():
            column = str(raw_column)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column):
                raise ValueError(f"Unsafe column name in SCD2 expire condition: {column!r}")
            if value is None:
                clauses.append(f'"{column}" IS NULL')
            else:
                clauses.append(f'"{column}" = {_render_literal(value)}')
        return " AND ".join(clauses)
    raise TypeError("SCD2 expire condition must be a SQL expression string or dict[str, Any]")


class DataFrameETLBackend:
    """TPC-DI ETL backend delegating writes to maintenance operations."""

    def __init__(
        self,
        *,
        maintenance_ops: DataFrameMaintenanceOperations,
        platform_name: str,
        table_root: Path | str | None = None,
    ) -> None:
        self.maintenance_ops = maintenance_ops
        self.platform_name = platform_name
        self.table_root = Path(table_root) if table_root is not None else None

    def _resolve_table_path(self, table_name: str) -> Path | str:
        """Resolve a logical table name to a maintenance-ops table path.

        Without a configured root the bare table name is passed through,
        preserving historical behavior. With a root, tables stay under it
        instead of scattering relative directories into the caller CWD.
        """
        if self.table_root is None:
            return table_name
        return self.table_root / table_name

    def create_schema(self) -> None:
        """No-op for DataFrame platforms where table paths are materialized lazily."""
        return

    def load_dataframes(self, staged_data: dict[str, pd.DataFrame], batch_type: str) -> dict[str, Any]:
        """Load DataFrames using maintenance INSERT operations.

        ``batch_type`` is currently reserved for backend-specific partitioning
        or lineage metadata and is intentionally unused in this implementation.
        """
        _ = batch_type
        load_results: dict[str, Any] = {"records_loaded": 0, "tables_updated": []}
        for table_name, dataframe in staged_data.items():
            if dataframe is None or dataframe.empty:
                continue
            result = self.maintenance_ops.insert_rows(self._resolve_table_path(table_name), dataframe, mode="append")
            if not result.success:
                raise RuntimeError(result.error_message or f"Failed to insert rows for table {table_name}")
            load_results["records_loaded"] += int(result.rows_affected)
            if int(result.rows_affected) > 0 and table_name not in load_results["tables_updated"]:
                load_results["tables_updated"].append(table_name)
        return load_results

    def validate_results(self) -> dict[str, Any]:
        """Return DataFrame-mode validation metadata.

        DataFrame ETL currently reports validation as not executed rather than
        inferring a synthetic quality score from SQL-only checks.
        """
        return {
            "validation_queries": {},
            "data_quality_issues": [],
            "data_quality_score": 0.0,
            "completeness_checks": {},
            "consistency_checks": {},
            "accuracy_checks": {},
            "validation_level": "not_executed",
            "notes": f"Validation executed in DataFrame mode for platform '{self.platform_name}'",
        }

    def _adapter_accepts_sql_predicates(self) -> bool:
        """Whether the maintenance adapter consumes SQL predicate text.

        Adapters declaring ``accepts_sql_predicates=False`` (e.g. Iceberg,
        whose parser handles single unquoted comparisons only) receive native
        dict conditions and native update values instead. Unknown adapters
        default to the SQL path, preserving current behavior.
        """
        get_capabilities = getattr(self.maintenance_ops, "get_capabilities", None)
        if get_capabilities is None:
            return True
        try:
            return bool(get_capabilities().accepts_sql_predicates)
        except Exception:
            return True

    def execute_scd2_expire(self, table_name: str, condition: str | Any, updates: dict[str, Any]) -> dict[str, Any]:
        """Expire current rows using UPDATE maintenance operation."""
        if not updates:
            return {"success": True, "rows_affected": 0}
        if isinstance(condition, dict) and not self._adapter_accepts_sql_predicates():
            predicate: str | Any = condition
            rendered_updates = {str(column): value for column, value in updates.items()}
        else:
            predicate = _condition_to_sql(condition)
            rendered_updates = {str(column): _render_literal(value) for column, value in updates.items()}
        result = self.maintenance_ops.update_rows(self._resolve_table_path(table_name), predicate, rendered_updates)
        if not result.success:
            raise RuntimeError(result.error_message or f"Failed to expire rows for table {table_name}")
        return {"success": True, "rows_affected": int(result.rows_affected)}

    def execute_scd2_insert(self, table_name: str, dataframe: pd.DataFrame) -> dict[str, Any]:
        """Insert new SCD2 rows using INSERT maintenance operation."""
        result = self.maintenance_ops.insert_rows(self._resolve_table_path(table_name), dataframe, mode="append")
        if not result.success:
            raise RuntimeError(result.error_message or f"Failed to insert SCD2 rows for table {table_name}")
        return {"success": True, "rows_affected": int(result.rows_affected)}

    def read_current_dimension(self, table_name: str) -> pd.DataFrame | None:
        """Return current dimension rows when backend has native read support."""
        _ = table_name
        return None
