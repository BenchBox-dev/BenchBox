"""Test helper: configurable stand-in for DataFrameWriteOperationsManager.

Lets unit tests for ``WritePrimitivesBenchmark._execute_aggregate_state_op``
exercise dispatch without spinning up a JVM. Each test injects whatever
DataFrameWriteResult shape it needs for persist + merge.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from benchbox.core.write_primitives.dataframe_operations import (
    DataFrameWriteResult,
    WriteOperationType,
)


def make_result(
    *,
    operation_type: WriteOperationType,
    success: bool = True,
    rows_affected: int = 100,
    error_message: str | None = None,
    metrics: dict[str, Any] | None = None,
    duration_ms: float = 1.0,
) -> DataFrameWriteResult:
    """Build a DataFrameWriteResult for use in dispatch tests."""
    now = time.time()
    return DataFrameWriteResult(
        operation_type=operation_type,
        success=success,
        start_time=now,
        end_time=now + duration_ms / 1000,
        duration_ms=duration_ms,
        rows_affected=rows_affected,
        error_message=error_message,
        metrics=metrics or {},
    )


@dataclass
class MockDataFrameWriteOperationsManager:
    """Configurable mock returning preset persist/merge results.

    Tests typically construct one with explicit results, attach to
    ``get_dataframe_write_manager`` via monkeypatch, and assert against
    the dispatch fork's returned envelope.
    """

    persist_result: DataFrameWriteResult | None = None
    merge_result: DataFrameWriteResult | None = None
    persist_raises: BaseException | None = None
    merge_raises: BaseException | None = None
    last_persist_path: Any = None
    last_merge_path: Any = None

    def execute_aggregate_persist(self, target_path: Any, state_builder: Callable) -> DataFrameWriteResult:
        self.last_persist_path = target_path
        if self.persist_raises is not None:
            raise self.persist_raises
        if self.persist_result is None:
            return make_result(operation_type=WriteOperationType.AGGREGATE_PERSIST)
        return self.persist_result

    def execute_aggregate_merge(self, target_path: Any, merge_extract: Callable) -> DataFrameWriteResult:
        self.last_merge_path = target_path
        if self.merge_raises is not None:
            raise self.merge_raises
        if self.merge_result is None:
            return make_result(
                operation_type=WriteOperationType.AGGREGATE_MERGE,
                metrics={"aggregate_value": 1.0},
            )
        return self.merge_result
