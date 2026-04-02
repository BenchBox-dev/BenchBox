# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Docker live integration tests for InfluxDB 3 Core.

Setup:
    make test-docker-up-influxdb
    # or: docker compose -f docker/influxdb/docker-compose.yml up -d --wait

These tests require a running InfluxDB 3 Core instance at localhost:8181.
Note: InfluxDB 3 creates databases on first write, so we seed test data
before running queries.
"""

import pytest

from benchbox.platforms.influxdb import InfluxDBAdapter

from .conftest import skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_influxdb,
]


@pytest.fixture(scope="module")
def influxdb_adapter():
    """Create an InfluxDB adapter connected to a local Docker instance."""
    skip_unless_docker_service("localhost", 8181, platform="InfluxDB")
    adapter = InfluxDBAdapter(
        host="localhost",
        port=8181,
        token="test",
        database="benchbox_test",
        mode="core",
        ssl=False,
    )
    adapter.skip_database_management = True
    return adapter


@pytest.fixture(scope="module", autouse=True)
def seed_test_data(influxdb_adapter):
    """Write a data point to create the database (InfluxDB 3 creates DBs on first write)."""
    from benchbox.platforms.influxdb.client import InfluxDBConnection

    conn = InfluxDBConnection(
        host="localhost",
        port=8181,
        token="test",
        database="benchbox_test",
        ssl=False,
    )
    conn.connect()
    try:
        conn.write_line_protocol(["cpu,host=server01 usage=42.0"])
    finally:
        conn.close()


class TestLiveInfluxDBConnection:
    """Test basic InfluxDB connectivity via Docker."""

    def test_connection(self, influxdb_adapter):
        """Verify we can connect to InfluxDB and query after seeding."""
        connection = influxdb_adapter.create_connection()
        try:
            assert connection is not None
        finally:
            influxdb_adapter.close_connection(connection)

    def test_platform_info(self, influxdb_adapter):
        """Verify platform info reports correct metadata."""
        info = influxdb_adapter.get_platform_info()
        assert info is not None
        assert info["platform_type"] == "influxdb"


class TestLiveInfluxDBQueryExecution:
    """Test query execution against a live InfluxDB instance."""

    def test_execute_query(self, influxdb_adapter):
        """Verify basic query execution against seeded data."""
        connection = influxdb_adapter.create_connection()
        try:
            # InfluxDB adapter returns (execution_time, row_count, error) tuple
            execution_time, row_count, error = influxdb_adapter.execute_query(
                connection,
                "SELECT * FROM cpu",
                query_id="Q0",
                iteration=1,
            )
            assert error is None
            assert row_count >= 1
        finally:
            influxdb_adapter.close_connection(connection)
