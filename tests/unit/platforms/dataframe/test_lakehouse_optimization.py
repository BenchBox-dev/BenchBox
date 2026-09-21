"""Execution tests for lakehouse compaction, optimization, and vacuum.

Delta Lake tests run against real local Delta tables via delta-rs;
Iceberg tests run against a real SQL catalog in tmp; Hudi tests drive the
documented CALL procedures (run_compaction, run_clustering, run_clean) against
a recording Spark double. A final section pins the shared capability flags
and the opt-in protocol surface.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

try:
    import pyarrow as pa
    from deltalake import DeltaTable, write_deltalake

    from benchbox.platforms.dataframe.delta_lake_maintenance import DeltaLakeMaintenanceOperations

    DELTA_AVAILABLE = True
except ImportError:
    pa = None  # type: ignore[assignment]
    DeltaTable = None  # type: ignore[assignment]
    write_deltalake = None  # type: ignore[assignment]
    DeltaLakeMaintenanceOperations = None  # type: ignore[assignment]
    DELTA_AVAILABLE = False

try:
    import pyiceberg  # noqa: F401

    from benchbox.platforms.dataframe.iceberg_maintenance import IcebergMaintenanceOperations

    ICEBERG_AVAILABLE = True
except ImportError:
    IcebergMaintenanceOperations = None  # type: ignore[assignment]
    ICEBERG_AVAILABLE = False


def _arrow_batch(rows: list[dict[str, Any]]) -> Any:
    schema = pa.schema([("id", pa.int64()), ("v", pa.string())])
    return pa.Table.from_pylist(rows, schema=schema)


@pytest.mark.skipif(not DELTA_AVAILABLE, reason="deltalake not installed")
class TestDeltaOptimization:
    def _two_file_table(self, tmp_path: Path) -> str:
        path = str(tmp_path / "delta_tbl")
        write_deltalake(path, _arrow_batch([{"id": 1, "v": "a"}]))
        write_deltalake(path, _arrow_batch([{"id": 2, "v": "b"}]), mode="append")
        assert len(DeltaTable(path).file_uris()) == 2
        return path

    def test_compact_binpacks_files(self, tmp_path: Path) -> None:
        ops = DeltaLakeMaintenanceOperations()
        result = ops.optimize_table(self._two_file_table(tmp_path), strategy="compact")

        assert result.success is True
        assert result.operation_type.value == "optimize"
        assert result.metrics["strategy"] == "compact"
        assert result.metrics["numFilesRemoved"] == 2
        assert result.metrics["numFilesAdded"] == 1
        assert result.rows_affected == 3

    def test_z_order_requires_columns(self, tmp_path: Path) -> None:
        ops = DeltaLakeMaintenanceOperations()
        result = ops.optimize_table(self._two_file_table(tmp_path), strategy="z_order")

        assert result.success is False
        assert "ordering columns" in (result.error_message or "")

    def test_z_order_compacts_with_columns(self, tmp_path: Path) -> None:
        ops = DeltaLakeMaintenanceOperations()
        result = ops.optimize_table(self._two_file_table(tmp_path), strategy="z_order", columns=["id"])

        assert result.success is True
        assert result.metrics["strategy"] == "z_order"
        assert result.metrics["numFilesRemoved"] == 2
        assert result.metrics["numFilesAdded"] == 1

    def test_unknown_strategy_raises(self, tmp_path: Path) -> None:
        ops = DeltaLakeMaintenanceOperations()
        with pytest.raises(NotImplementedError, match="Unknown Delta optimize strategy"):
            ops.optimize_table(self._two_file_table(tmp_path), strategy="bogus")

    def test_vacuum_dry_run_preserves_files(self, tmp_path: Path) -> None:
        ops = DeltaLakeMaintenanceOperations()
        path = self._two_file_table(tmp_path)

        result = ops.vacuum_table(path, dry_run=True)

        assert result.success is True
        assert result.metrics["dry_run"] is True
        assert len(DeltaTable(path).file_uris()) == 2

    def test_vacuum_reclaims_with_zero_retention(self, tmp_path: Path) -> None:
        ops = DeltaLakeMaintenanceOperations()
        path = self._two_file_table(tmp_path)
        ops.optimize_table(path, strategy="compact")

        result = ops.vacuum_table(path, retention_hours=0, dry_run=False, enforce_retention=False)

        assert result.success is True
        assert result.rows_affected == 2
        assert len(result.metrics["deleted_paths"]) == 2

    def test_vacuum_enforces_retention_floor(self, tmp_path: Path) -> None:
        ops = DeltaLakeMaintenanceOperations()
        result = ops.vacuum_table(
            self._two_file_table(tmp_path), retention_hours=0, dry_run=False, enforce_retention=True
        )

        assert result.success is False


@pytest.mark.skipif(not ICEBERG_AVAILABLE, reason="pyiceberg not installed")
class TestIcebergVacuum:
    def _two_snapshot_table(self, tmp_path: Path) -> tuple[Any, str]:
        ops = IcebergMaintenanceOperations(working_dir=str(tmp_path / "ice"))
        identifier = "default.probe"
        table = ops._get_or_create_table(identifier, _arrow_batch([{"id": 1, "v": "a"}]).schema)
        table.append(_arrow_batch([{"id": 1, "v": "a"}]))
        table.append(_arrow_batch([{"id": 2, "v": "b"}]))
        assert len(ops.catalog.load_table(identifier).snapshots()) == 2
        return ops, identifier

    def test_vacuum_dry_run_reports_without_expiring(self, tmp_path: Path) -> None:
        ops, identifier = self._two_snapshot_table(tmp_path)

        result = ops.vacuum_table(identifier, dry_run=True)

        assert result.success is True
        assert result.operation_type.value == "vacuum"
        assert result.rows_affected == 1
        assert len(ops.catalog.load_table(identifier).snapshots()) == 2

    def test_vacuum_expires_old_snapshots(self, tmp_path: Path) -> None:
        ops, identifier = self._two_snapshot_table(tmp_path)

        result = ops.vacuum_table(identifier, dry_run=False)

        assert result.success is True
        assert result.rows_affected == 1
        remaining = ops.catalog.load_table(identifier).snapshots()
        assert len(remaining) == 1
        assert remaining[0].snapshot_id not in result.metrics["expired_snapshot_ids"]

    def test_optimize_raises_not_implemented(self, tmp_path: Path) -> None:
        ops, identifier = self._two_snapshot_table(tmp_path)

        with pytest.raises(NotImplementedError, match="no binpack rewrite"):
            ops.optimize_table(identifier)


class TestHudiProcedures:
    def _ops(self) -> tuple[Any, MagicMock]:
        from benchbox.platforms.dataframe.hudi_maintenance import HudiMaintenanceOperations

        spark = MagicMock()
        return HudiMaintenanceOperations(spark_session=spark), spark

    def test_compact_issues_run_compaction(self) -> None:
        ops, spark = self._ops()

        result = ops.optimize_table("mydb.tbl", strategy="compact")

        assert result.success is True
        assert spark.sql.call_count == 1
        assert spark.sql.call_args[0][0] == "CALL run_compaction(op => 'run', table => 'mydb.tbl')"

    def test_cluster_issues_run_clustering(self) -> None:
        ops, spark = self._ops()

        result = ops.optimize_table("mydb.tbl", strategy="cluster")

        assert result.success is True
        assert spark.sql.call_args[0][0] == "CALL run_clustering(table => 'mydb.tbl')"

    def test_path_target_uses_path_argument(self) -> None:
        ops, spark = self._ops()

        ops.optimize_table("/tmp/hoodie/tbl", strategy="compact")

        assert spark.sql.call_args[0][0] == "CALL run_compaction(op => 'run', path => '/tmp/hoodie/tbl')"

    def test_unknown_strategy_raises(self) -> None:
        ops, _ = self._ops()

        with pytest.raises(NotImplementedError, match="Unknown Hudi optimize strategy"):
            ops.optimize_table("mydb.tbl", strategy="bogus")

    def test_vacuum_issues_run_clean(self) -> None:
        ops, spark = self._ops()

        result = ops.vacuum_table("mydb.tbl", dry_run=False)

        assert result.success is True
        assert spark.sql.call_args[0][0] == "CALL run_clean(table => 'mydb.tbl')"

    def test_vacuum_retention_maps_to_hours_policy(self) -> None:
        ops, spark = self._ops()

        ops.vacuum_table("mydb.tbl", retention_hours=72, dry_run=False)

        assert spark.sql.call_args[0][0] == (
            "CALL run_clean(table => 'mydb.tbl', clean_policy => 'KEEP_LATEST_BY_HOURS', hours_retained => 72)"
        )

    def test_vacuum_dry_run_raises(self) -> None:
        ops, spark = self._ops()

        with pytest.raises(NotImplementedError, match="no dry-run mode"):
            ops.vacuum_table("mydb.tbl", dry_run=True)
        spark.sql.assert_not_called()


class TestOptimizationContracts:
    def test_capability_flags(self) -> None:
        from benchbox.core.dataframe.maintenance_interface import (
            DELTA_LAKE_CAPABILITIES,
            HUDI_CAPABILITIES,
            ICEBERG_CAPABILITIES,
            POLARS_CAPABILITIES,
            MaintenanceOperationType,
        )

        assert DELTA_LAKE_CAPABILITIES.supports_operation(MaintenanceOperationType.OPTIMIZE) is True
        assert DELTA_LAKE_CAPABILITIES.supports_operation(MaintenanceOperationType.VACUUM) is True
        assert ICEBERG_CAPABILITIES.supports_operation(MaintenanceOperationType.OPTIMIZE) is False
        assert ICEBERG_CAPABILITIES.supports_operation(MaintenanceOperationType.VACUUM) is True
        assert HUDI_CAPABILITIES.supports_operation(MaintenanceOperationType.OPTIMIZE) is True
        assert HUDI_CAPABILITIES.supports_operation(MaintenanceOperationType.VACUUM) is True
        assert POLARS_CAPABILITIES.supports_operation(MaintenanceOperationType.OPTIMIZE) is False
        assert POLARS_CAPABILITIES.supports_operation(MaintenanceOperationType.VACUUM) is False

    def test_protocol_membership(self) -> None:
        from benchbox.core.dataframe.maintenance_interface import TableFormatOptimizationOperations
        from benchbox.platforms.dataframe.delta_lake_maintenance import DeltaLakeMaintenanceOperations
        from benchbox.platforms.dataframe.hudi_maintenance import HudiMaintenanceOperations
        from benchbox.platforms.dataframe.iceberg_maintenance import IcebergMaintenanceOperations
        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        assert isinstance(DeltaLakeMaintenanceOperations(), TableFormatOptimizationOperations)
        assert isinstance(
            IcebergMaintenanceOperations(working_dir="/tmp/benchbox-protocol-probe"),
            TableFormatOptimizationOperations,
        )
        assert isinstance(
            HudiMaintenanceOperations(spark_session=MagicMock()),
            TableFormatOptimizationOperations,
        )
        assert not isinstance(PolarsMaintenanceOperations(), TableFormatOptimizationOperations)
