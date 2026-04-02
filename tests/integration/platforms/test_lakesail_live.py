"""Live integration tests for LakeSail Sail platform adapter.

These tests require a running LakeSail Sail server. They are skipped
when no server is available (LAKESAIL_ENDPOINT env var not set).

For stub-based CI tests, see test_lakesail_stub_smoke.py.

To run locally:
    1. Start a LakeSail Sail server (e.g., `sail serve`)
    2. Set LAKESAIL_ENDPOINT=sc://localhost:50051
    3. Run: uv run -- python -m pytest tests/integration/platforms/test_lakesail_live.py -v
"""

from __future__ import annotations

import os

import pytest

# Skip all tests if no LakeSail endpoint is configured
LAKESAIL_ENDPOINT = os.environ.get("LAKESAIL_ENDPOINT")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_integration,
    pytest.mark.live_lakesail,
    pytest.mark.skipif(
        not LAKESAIL_ENDPOINT,
        reason="Skipping LakeSail live test: LAKESAIL_ENDPOINT not set",
    ),
]


# Check PySpark availability
try:
    from benchbox.platforms.pyspark import PYSPARK_AVAILABLE
except ImportError:
    PYSPARK_AVAILABLE = False


@pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
class TestLakeSailSQLSmoke:
    """Smoke tests for LakeSail SQL adapter against a live Sail server."""

    @pytest.fixture
    def adapter(self):
        """Create a LakeSail SQL adapter connected to the test server."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter(
            endpoint=LAKESAIL_ENDPOINT,
            database="benchbox_lakesail_smoke",
        )
        yield adapter
        try:
            if adapter._spark_session:
                adapter.close_connection(adapter._spark_session)
        except Exception:
            pass

    def test_connection(self, adapter):
        """Test that we can connect to the Sail server."""
        assert adapter.test_connection() is True

    def test_select_one(self, adapter):
        """Test simple SELECT 1 query execution."""
        connection = adapter.create_connection()
        result = adapter.execute_query(connection, "SELECT 1 AS value", query_id="Q0", benchmark_type="tpch")
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 1
        adapter.close_connection(connection)

    def test_platform_info(self, adapter):
        """Test platform info collection with live connection."""
        connection = adapter.create_connection()
        info = adapter.get_platform_info(connection=connection)
        assert info["platform_type"] == "lakesail"
        assert info["platform_name"] == "LakeSail Sail"
        adapter.close_connection(connection)


@pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
class TestLakeSailDataFrameSmoke:
    """Smoke tests for LakeSail DataFrame adapter against a live Sail server."""

    @pytest.fixture
    def adapter(self):
        """Create a LakeSail DataFrame adapter connected to the test server."""
        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        adapter = LakeSailDataFrameAdapter(
            endpoint=LAKESAIL_ENDPOINT,
        )
        yield adapter
        adapter.close()

    def test_platform_info(self, adapter):
        """Test platform info collection."""
        info = adapter.get_platform_info()
        assert info["platform"] == "LakeSail"
        assert info["family"] == "expression"

    def test_create_context(self, adapter):
        """Test context creation connects to Sail server."""
        ctx = adapter.create_context()
        assert ctx is not None
        assert ctx.platform == "LakeSail"
