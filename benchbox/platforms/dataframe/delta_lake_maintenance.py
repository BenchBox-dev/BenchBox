# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.utils.clock import mono_time

try:
    from deltalake import DeltaTable, write_deltalake

    DELTA_AVAILABLE = True
except ImportError:
    DeltaTable = None
    write_deltalake = None
    DELTA_AVAILABLE = False

try:
    import pyarrow as pa

    PYARROW_AVAILABLE = True
except ImportError:
    pa = None
    PYARROW_AVAILABLE = False

from benchbox.core.dataframe.maintenance_interface import (
    DELTA_LAKE_CAPABILITIES,
    BaseDataFrameMaintenanceOperations,
    DataFrameMaintenanceCapabilities,
    MaintenanceOperationType,
    MaintenanceResult,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DeltaLakeMaintenanceOperations(BaseDataFrameMaintenanceOperations):
    def __init__(self, working_dir: str | Path | None = None) -> None:
        super().__init__()

        if not DELTA_AVAILABLE:
            raise ImportError(
                "delta-rs is not installed. Install with: pip install deltalake\n"
                "For TPC-H/TPC-DS maintenance tests with Delta Lake, install:\n"
                "pip install 'benchbox[delta]'"
            )

        if not PYARROW_AVAILABLE:
            raise ImportError(
                "PyArrow is not installed. Install with: pip install pyarrow\n"
                "PyArrow is required for Delta Lake operations."
            )

        self.working_dir = Path(working_dir) if working_dir else None
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_capabilities(self) -> DataFrameMaintenanceCapabilities:
        return DELTA_LAKE_CAPABILITIES

    def _do_insert(
        self,
        table_path: Path | str,
        dataframe: Any,
        partition_columns: list[str] | None,
        mode: str,
    ) -> int:
        table_path = str(table_path)

        arrow_table = self._convert_to_arrow(dataframe)
        row_count = arrow_table.num_rows

        if row_count == 0:
            self.logger.info("No rows to insert")
            return 0

        delta_mode = "append" if mode == "append" else "overwrite"

        write_deltalake(
            table_path,
            arrow_table,
            mode=delta_mode,
            partition_by=partition_columns,
        )

        self.logger.info(f"Inserted {row_count} rows to Delta table at {table_path}")
        return row_count

    def _do_delete(
        self,
        table_path: Path | str,
        condition: str | Any,
    ) -> int:
        table_path = str(table_path)

        try:
            dt = DeltaTable(table_path)
        except Exception as e:
            self.logger.warning(f"Could not open Delta table at {table_path}: {e}")
            return 0

        rows_before = dt.to_pyarrow_table().num_rows

        dt.delete(predicate=str(condition))

        rows_after = dt.to_pyarrow_table().num_rows
        rows_deleted = rows_before - rows_after

        self.logger.info(f"Deleted {rows_deleted} rows from Delta table at {table_path}")
        return rows_deleted

    def _do_update(
        self,
        table_path: Path | str,
        condition: str | Any,
        updates: dict[str, Any],
    ) -> int:
        table_path = str(table_path)

        try:
            dt = DeltaTable(table_path)
        except Exception as e:
            raise RuntimeError(f"Could not open Delta table at {table_path}: {e}") from e

        full_table = dt.to_pyarrow_table()
        rows_before = full_table.num_rows

        dt.update(
            predicate=str(condition),
            updates=updates,
        )

        self.logger.info(f"Updated rows in Delta table at {table_path} where {condition}")

        return rows_before

    def _do_merge(
        self,
        table_path: Path | str,
        source_dataframe: Any,
        merge_condition: str | Any,
        when_matched: dict[str, Any] | None,
        when_not_matched: dict[str, Any] | None,
    ) -> int:
        table_path = str(table_path)

        source_arrow = self._convert_to_arrow(source_dataframe)
        source_rows = source_arrow.num_rows

        try:
            dt = DeltaTable(table_path)
        except Exception as e:
            raise RuntimeError(f"Could not open Delta table at {table_path}: {e}") from e

        merge_builder = dt.merge(
            source=source_arrow,
            predicate=str(merge_condition),
            source_alias="source",
            target_alias="target",
        )

        if when_matched:
            merge_builder = merge_builder.when_matched_update(updates=when_matched)

        if when_not_matched:
            merge_builder = merge_builder.when_not_matched_insert(updates=when_not_matched)

        merge_result = merge_builder.execute()

        rows_affected = source_rows
        if merge_result and isinstance(merge_result, dict):
            rows_affected = merge_result.get("num_target_rows_updated", 0) + merge_result.get(
                "num_target_rows_inserted", 0
            )

        self.logger.info(f"Merged {rows_affected} rows into Delta table at {table_path}")
        return rows_affected

    def optimize_table(
        self,
        table_path: Path | str,
        *,
        strategy: str = "compact",
        columns: list[str] | None = None,
        partition_filter: Any | None = None,
    ) -> MaintenanceResult:
        operation = MaintenanceOperationType.OPTIMIZE
        start_time = mono_time()
        try:
            self._check_capability(operation)
            normalized = strategy.lower()
            if normalized not in ("compact", "cluster", "z_order"):
                raise NotImplementedError(
                    f"Unknown Delta optimize strategy '{strategy}'. Use 'compact' or 'cluster'/'z_order'."
                )
            if normalized in ("cluster", "z_order") and not columns:
                raise ValueError("Delta z-order optimization requires ordering columns.")
            try:
                dt = DeltaTable(str(table_path))
            except Exception as e:
                raise RuntimeError(f"Could not open Delta table at {table_path}: {e}") from e
            if normalized == "compact":
                metrics = dt.optimize.compact(partition_filters=partition_filter)
            else:
                metrics = dt.optimize.z_order(list(columns or []), partition_filters=partition_filter)
            metrics = dict(metrics or {})
            files_affected = int(metrics.get("numFilesAdded", 0)) + int(metrics.get("numFilesRemoved", 0))
            end_time = mono_time()
            self.logger.info(f"Optimized Delta table at {table_path} ({normalized}): {metrics}")
            return MaintenanceResult(
                operation_type=operation,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=files_affected,
                metrics={"strategy": normalized, **metrics},
            )
        except NotImplementedError:
            raise
        except Exception as e:
            self.logger.error(f"OPTIMIZE failed: {e}")
            end_time = mono_time()
            return MaintenanceResult(
                operation_type=operation,
                success=False,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=0,
                error_message=str(e),
            )

    def vacuum_table(
        self,
        table_path: Path | str,
        *,
        retention_hours: int | None = None,
        dry_run: bool = True,
        enforce_retention: bool = True,
    ) -> MaintenanceResult:
        operation = MaintenanceOperationType.VACUUM
        start_time = mono_time()
        try:
            self._check_capability(operation)
            try:
                dt = DeltaTable(str(table_path))
            except Exception as e:
                raise RuntimeError(f"Could not open Delta table at {table_path}: {e}") from e
            deleted = list(
                dt.vacuum(
                    retention_hours=retention_hours,
                    dry_run=dry_run,
                    enforce_retention_duration=enforce_retention,
                )
                or []
            )
            end_time = mono_time()
            self.logger.info(f"Vacuumed Delta table at {table_path} (dry_run={dry_run}): {len(deleted)} files")
            return MaintenanceResult(
                operation_type=operation,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=len(deleted),
                metrics={"dry_run": dry_run, "deleted_paths": deleted},
            )
        except NotImplementedError:
            raise
        except Exception as e:
            self.logger.error(f"VACUUM failed: {e}")
            end_time = mono_time()
            return MaintenanceResult(
                operation_type=operation,
                success=False,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=0,
                error_message=str(e),
            )


def get_delta_lake_maintenance_operations(
    working_dir: str | Path | None = None,
) -> DeltaLakeMaintenanceOperations | None:
    if not DELTA_AVAILABLE:
        logger.debug("Delta Lake maintenance not available (deltalake not installed)")
        return None

    if not PYARROW_AVAILABLE:
        logger.debug("Delta Lake maintenance not available (pyarrow not installed)")
        return None

    return DeltaLakeMaintenanceOperations(working_dir=working_dir)
