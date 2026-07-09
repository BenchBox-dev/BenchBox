"""Shared fixtures for concurrency testing framework tests.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest


@pytest.fixture
def mock_connection():
    """Mock database connection."""

    class MockConnection:
        def __init__(self):
            self.closed = False
            self.query_count = 0

        def execute(self, sql):
            self.query_count += 1
            return [(1,)]

        def close(self):
            self.closed = True

    return MockConnection


@pytest.fixture
def mock_connection_factory(mock_connection):
    """Factory that creates mock connections."""

    def factory():
        return mock_connection()

    return factory


@pytest.fixture
def mock_query_factory():
    """Factory that creates query IDs and SQL."""

    def factory(index):
        return (f"query_{index}", f"SELECT {index}")

    return factory


@pytest.fixture
def mock_execute_query():
    """Function to execute queries on mock connections."""

    def execute(connection, sql):
        connection.execute(sql)
        return (True, 1, None)

    return execute
