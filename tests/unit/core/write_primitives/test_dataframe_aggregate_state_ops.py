"""Tests for AGGREGATE_PERSIST/AGGREGATE_MERGE op types (W2 of architecture-fixes).

Covers:
- Enum values
- DataFrameWriteCapabilities default flags + platform presets
- supports_operation routing for the new types
- DataFrameWriteOperationsManager dispatch (success + failure paths)
- Skip messaging for unsupported engines
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from benchbox.core.write_primitives.dataframe_operations import (
    PANDAS_WRITE_CAPABILITIES,
    POLARS_WRITE_CAPABILITIES,
    PYSPARK_WRITE_CAPABILITIES,
    DataFrameWriteCapabilities,
    DataFrameWriteOperationsManager,
    WriteOperationType,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------
class TestAggregateStateEnum:
    def test_persist_value(self):
        assert WriteOperationType.AGGREGATE_PERSIST.value == "aggregate_persist"

    def test_merge_value(self):
        assert WriteOperationType.AGGREGATE_MERGE.value == "aggregate_merge"

    def test_persist_and_merge_are_distinct(self):
        assert WriteOperationType.AGGREGATE_PERSIST != WriteOperationType.AGGREGATE_MERGE


# ---------------------------------------------------------------------------
# Capabilities defaults + platform presets
# ---------------------------------------------------------------------------
class TestAggregateStateCapabilities:
    def test_default_caps_have_aggregate_disabled(self):
        caps = DataFrameWriteCapabilities(platform_name="test")
        assert caps.supports_aggregate_persist is False
        assert caps.supports_aggregate_merge is False

    def test_pyspark_preset_enables_both(self):
        assert PYSPARK_WRITE_CAPABILITIES.supports_aggregate_persist is True
        assert PYSPARK_WRITE_CAPABILITIES.supports_aggregate_merge is True

    def test_polars_preset_keeps_both_disabled(self):
        # Polars has no DataFrame-layer sketch APIs today; preset must not opt in.
        assert POLARS_WRITE_CAPABILITIES.supports_aggregate_persist is False
        assert POLARS_WRITE_CAPABILITIES.supports_aggregate_merge is False

    def test_pandas_preset_keeps_both_disabled(self):
        assert PANDAS_WRITE_CAPABILITIES.supports_aggregate_persist is False
        assert PANDAS_WRITE_CAPABILITIES.supports_aggregate_merge is False


# ---------------------------------------------------------------------------
# supports_operation routing
# ---------------------------------------------------------------------------
class TestSupportsOperationAggregateStateRouting:
    def test_persist_consults_dedicated_flag_not_maintenance_caps(self):
        caps = DataFrameWriteCapabilities(
            platform_name="test",
            maintenance_caps=None,  # row-level ops would all be False
            supports_aggregate_persist=True,
        )
        assert caps.supports_operation(WriteOperationType.AGGREGATE_PERSIST) is True

    def test_merge_consults_dedicated_flag_not_maintenance_caps(self):
        caps = DataFrameWriteCapabilities(
            platform_name="test",
            maintenance_caps=None,
            supports_aggregate_merge=True,
        )
        assert caps.supports_operation(WriteOperationType.AGGREGATE_MERGE) is True

    def test_persist_unsupported_when_flag_false(self):
        caps = DataFrameWriteCapabilities(platform_name="test")
        assert caps.supports_operation(WriteOperationType.AGGREGATE_PERSIST) is False

    def test_merge_unsupported_when_flag_false(self):
        caps = DataFrameWriteCapabilities(platform_name="test")
        assert caps.supports_operation(WriteOperationType.AGGREGATE_MERGE) is False

    def test_unsupported_operations_includes_aggregate_when_off(self):
        caps = DataFrameWriteCapabilities(platform_name="test", supports_bulk_load=True)
        unsupported = caps.get_unsupported_operations()
        assert WriteOperationType.AGGREGATE_PERSIST in unsupported
        assert WriteOperationType.AGGREGATE_MERGE in unsupported

    def test_unsupported_operations_excludes_aggregate_when_on(self):
        caps = DataFrameWriteCapabilities(
            platform_name="test",
            supports_aggregate_persist=True,
            supports_aggregate_merge=True,
        )
        unsupported = caps.get_unsupported_operations()
        assert WriteOperationType.AGGREGATE_PERSIST not in unsupported
        assert WriteOperationType.AGGREGATE_MERGE not in unsupported


# ---------------------------------------------------------------------------
# Manager dispatch
# ---------------------------------------------------------------------------
def _make_manager_with_caps(caps: DataFrameWriteCapabilities) -> DataFrameWriteOperationsManager:
    """Construct a manager bypassing the platform-detection __init__ logic.

    The aggregate-state dispatch unit tests don't need a real maintenance
    handler; they only need the capability flags and the dispatch methods.
    """
    manager = DataFrameWriteOperationsManager.__new__(DataFrameWriteOperationsManager)
    manager.platform_name = caps.platform_name
    manager.spark_session = None
    manager.logger = MagicMock()
    manager._maintenance_ops = None
    manager._capabilities = caps
    return manager


class TestExecuteAggregatePersist:
    def test_returns_failure_when_unsupported(self, tmp_path: Path):
        manager = _make_manager_with_caps(DataFrameWriteCapabilities(platform_name="test"))
        result = manager.execute_aggregate_persist(tmp_path / "state", lambda: None)
        assert result.success is False
        assert result.operation_type == WriteOperationType.AGGREGATE_PERSIST
        assert "aggregate_persist" in result.error_message
        assert "sketch APIs" in result.error_message

    def test_invokes_builder_and_returns_success(self, tmp_path: Path, monkeypatch):
        caps = DataFrameWriteCapabilities(platform_name="test", supports_aggregate_persist=True)
        manager = _make_manager_with_caps(caps)

        sentinel_df = MagicMock(name="state_df")
        builder = MagicMock(return_value=sentinel_df)

        # Bypass the engine-specific writer for this unit test.
        monkeypatch.setattr(
            manager,
            "_persist_dataframe_to_parquet",
            lambda df, path, compression: (10, 4096, 1),
        )

        target = tmp_path / "state"
        result = manager.execute_aggregate_persist(target, builder, compression="zstd")

        builder.assert_called_once_with()
        assert result.success is True
        assert result.operation_type == WriteOperationType.AGGREGATE_PERSIST
        assert result.rows_affected == 10
        assert result.bytes_written == 4096
        assert result.file_count == 1
        assert result.compression == "zstd"
        assert target.exists()  # mkdir was called

    def test_builder_exception_returns_failure(self, tmp_path: Path):
        caps = DataFrameWriteCapabilities(platform_name="test", supports_aggregate_persist=True)
        manager = _make_manager_with_caps(caps)

        def boom():
            raise RuntimeError("builder blew up")

        result = manager.execute_aggregate_persist(tmp_path / "state", boom)
        assert result.success is False
        assert "builder blew up" in result.error_message
        assert result.operation_type == WriteOperationType.AGGREGATE_PERSIST


class TestExecuteAggregateMerge:
    def test_returns_failure_when_unsupported(self, tmp_path: Path):
        manager = _make_manager_with_caps(DataFrameWriteCapabilities(platform_name="test"))
        result = manager.execute_aggregate_merge(tmp_path / "state", lambda _path: None)
        assert result.success is False
        assert result.operation_type == WriteOperationType.AGGREGATE_MERGE
        assert "aggregate_merge" in result.error_message

    def test_invokes_extractor_and_records_value_in_metrics(self, tmp_path: Path):
        caps = DataFrameWriteCapabilities(platform_name="test", supports_aggregate_merge=True)
        manager = _make_manager_with_caps(caps)

        source = tmp_path / "state"
        merge_extract = MagicMock(return_value=14836.5)
        result = manager.execute_aggregate_merge(source, merge_extract)

        merge_extract.assert_called_once_with(source)
        assert result.success is True
        assert result.operation_type == WriteOperationType.AGGREGATE_MERGE
        assert result.rows_affected == 1
        assert result.metrics["aggregate_value"] == 14836.5

    def test_extractor_exception_returns_failure(self, tmp_path: Path):
        caps = DataFrameWriteCapabilities(platform_name="test", supports_aggregate_merge=True)
        manager = _make_manager_with_caps(caps)

        def boom(_path):
            raise ValueError("merge failed")

        result = manager.execute_aggregate_merge(tmp_path / "state", boom)
        assert result.success is False
        assert "merge failed" in result.error_message


class TestUnsupportedAggregateStateMessage:
    def test_persist_message_mentions_sketch_apis(self):
        manager = _make_manager_with_caps(DataFrameWriteCapabilities(platform_name="pandas-df"))
        msg = manager.get_unsupported_message(WriteOperationType.AGGREGATE_PERSIST)
        assert "pandas-df" in msg
        assert "aggregate_persist" in msg
        assert "sketch" in msg.lower()

    def test_merge_message_mentions_sketch_apis(self):
        manager = _make_manager_with_caps(DataFrameWriteCapabilities(platform_name="polars-df"))
        msg = manager.get_unsupported_message(WriteOperationType.AGGREGATE_MERGE)
        assert "polars-df" in msg
        assert "aggregate_merge" in msg
        assert "sketch" in msg.lower()
