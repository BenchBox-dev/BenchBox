# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Docker live capability probe for native ClickHouse Delta Lake reads.

Setup:
    make test-docker-up-clickhouse
    # or: docker compose -f docker/clickhouse/docker-compose.yml up -d --wait

ClickHouse reads Delta Lake tables directly through the ``DeltaLake`` table
engine and the ``deltaLake`` table-function family -- no Parquet conversion
is required on capable servers. These tests probe a running ClickHouse
instance (pinned image ``clickhouse/clickhouse-server:25.8``) for that
capability: server version plus registration of the ``deltaLake`` function
and the ``DeltaLake`` engine in the system tables.

A passing probe means BenchBox can issue the SQL built by
:mod:`benchbox.platforms.clickhouse.delta_lake` straight at the server. A
failure names the server version so the author can tell a missing
integration (image too old or minimal build) apart from a regression.
"""

import pytest

from benchbox.platforms.clickhouse import ClickHouseAdapter
from benchbox.platforms.clickhouse.delta_lake import (
    delta_lake_count_sql,
    delta_lake_table_function,
)

from .conftest import skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_clickhouse,
]


@pytest.fixture
def clickhouse_adapter():
    """Create a ClickHouse adapter connected to a local Docker instance."""
    skip_unless_docker_service("localhost", 9000, platform="ClickHouse")
    adapter = ClickHouseAdapter(
        host="localhost",
        port=9000,
        deployment_mode="server",
        database="benchbox_test",
    )
    adapter.skip_database_management = True
    yield adapter


def _query_names(connection, sql: str) -> list[str]:
    rows = connection.execute(sql)
    return [str(row[0]) for row in rows] if rows else []


class TestNativeDeltaCapability:
    """Probe the server for the native Delta Lake integration."""

    def test_server_version(self, clickhouse_adapter) -> None:
        connection = clickhouse_adapter.create_connection()
        try:
            rows = connection.execute("SELECT version()")
            assert rows and str(rows[0][0]).strip()
        finally:
            clickhouse_adapter.close_connection(connection)

    def test_delta_lake_table_function_registered(self, clickhouse_adapter) -> None:
        connection = clickhouse_adapter.create_connection()
        try:
            names = _query_names(
                connection,
                "SELECT name FROM system.functions WHERE name IN ('deltaLake', 'deltaLakeS3', 'deltaLakeLocal')",
            )
            version = str(connection.execute("SELECT version()")[0][0])
            assert "deltaLake" in names, f"Server {version} lacks the deltaLake table function"
        finally:
            clickhouse_adapter.close_connection(connection)

    def test_delta_lake_engine_registered(self, clickhouse_adapter) -> None:
        connection = clickhouse_adapter.create_connection()
        try:
            names = _query_names(connection, "SELECT name FROM system.table_engines WHERE name = 'DeltaLake'")
            version = str(connection.execute("SELECT version()")[0][0])
            assert names == ["DeltaLake"], f"Server {version} lacks the DeltaLake table engine"
        finally:
            clickhouse_adapter.close_connection(connection)

    def test_native_sql_shape_matches_probe(self) -> None:
        """The SQL builders must target exactly the probed function name."""
        source = delta_lake_table_function("s3://bucket/orders")
        assert source.startswith("deltaLake(")
        assert delta_lake_count_sql(source) == "SELECT count() FROM deltaLake('s3://bucket/orders')"
