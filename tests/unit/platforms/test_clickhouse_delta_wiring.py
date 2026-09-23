"""Unit tests for ClickHouse Delta read-path wiring.

Server-free: stub connections stand in for ``clickhouse_driver`` clients so
the probe/decision flow is pinned without a server. Live execution against
the Docker-gated server is covered by the native suite.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.platforms.clickhouse.workload import ClickHouseWorkloadMixin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class StubConnection:
    """Minimal ``execute()`` stand-in returning canned system-table rows."""

    def __init__(self, functions: list[str], engines: list[str]) -> None:
        self._functions = functions
        self._engines = engines
        self.queries: list[str] = []

    def execute(self, sql: str) -> list[tuple[str]]:
        self.queries.append(sql)
        if "system.table_functions" in sql:
            return [(name,) for name in self._functions]
        if "system.table_engines" in sql:
            return [(name,) for name in self._engines]
        raise AssertionError(f"unexpected query: {sql}")


@pytest.fixture
def mixin() -> ClickHouseWorkloadMixin:
    return ClickHouseWorkloadMixin()


class TestDeltaNativeRegistration:
    def test_true_on_capable_server(self, mixin: ClickHouseWorkloadMixin) -> None:
        connection = StubConnection(["deltaLake", "deltaLakeS3"], ["DeltaLake", "MergeTree"])
        assert mixin.delta_native_registration(connection) is True
        assert len(connection.queries) == 2

    def test_false_without_base_function(self, mixin: ClickHouseWorkloadMixin) -> None:
        connection = StubConnection(["deltaLakeS3"], ["DeltaLake"])
        assert mixin.delta_native_registration(connection) is False

    def test_false_without_engine(self, mixin: ClickHouseWorkloadMixin) -> None:
        connection = StubConnection(["deltaLake"], ["MergeTree"])
        assert mixin.delta_native_registration(connection) is False


class TestDeltaReaderFor:
    def test_native_for_s3_on_capable_server(self, mixin: ClickHouseWorkloadMixin) -> None:
        connection = StubConnection(["deltaLake"], ["DeltaLake"])
        reader = mixin.delta_reader_for(connection, "s3://bucket/orders")
        assert reader.kind == "native"
        assert reader.source_sql == "deltaLake('s3://bucket/orders')"

    def test_snapshot_on_incapable_server(self, mixin: ClickHouseWorkloadMixin) -> None:
        connection = StubConnection([], [])
        reader = mixin.delta_reader_for(connection, "s3://bucket/orders")
        assert reader.kind == "parquet-snapshot"
        assert reader.source_sql == ""

    def test_unknown_location_raises(self, mixin: ClickHouseWorkloadMixin) -> None:
        connection = StubConnection(["deltaLake"], ["DeltaLake"])
        with pytest.raises(ValueError, match="Unrecognized Delta location"):
            mixin.delta_reader_for(connection, "hdfs://namenode/table")
