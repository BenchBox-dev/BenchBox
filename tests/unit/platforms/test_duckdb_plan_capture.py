"""
Tests for DuckDB query plan capture integration.

Verifies that query plans are captured and parsed during query execution.
"""

import pytest

from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDuckDBPlanCapture:
    """Test query plan capture in DuckDB adapter."""

    @pytest.fixture
    def adapter_with_capture(self):
        """Create DuckDB adapter with plan capture enabled."""
        adapter = DuckDBAdapter(capture_plans=True)
        return adapter

    @pytest.fixture
    def adapter_without_capture(self):
        """Create DuckDB adapter with plan capture disabled."""
        adapter = DuckDBAdapter(capture_plans=False)
        return adapter

    def test_parser_is_available(self, adapter_with_capture):
        """Test that DuckDB parser is available."""
        parser = adapter_with_capture.get_query_plan_parser()
        assert parser is not None
        assert parser.platform_name == "duckdb"

    def test_plan_capture_when_enabled(self, adapter_with_capture):
        """Test that plan is captured with actual timing when capture_plans=True.

        Default behavior uses EXPLAIN (ANALYZE, FORMAT JSON) so captured plans include
        actual per-operator timing and cardinality from real execution.
        """
        connection = adapter_with_capture.create_connection()

        try:
            result = adapter_with_capture.execute_query(
                connection=connection,
                query="SELECT 1 as test_column",
                query_id="test_q1",
                validate_row_count=False,
            )

            assert "query_plan" in result, "query_plan should be present when capture_plans=True"
            assert "plan_fingerprint" in result

            plan = result["query_plan"]
            assert plan is not None
            assert plan.logical_root is not None
            # Default capture uses EXPLAIN (ANALYZE, FORMAT JSON) - physical operator must carry timing
            phys = plan.logical_root.physical_operator
            assert phys is not None, "physical_operator should always be present"
            assert phys.properties.get("timing") is not None, "EXPLAIN ANALYZE should populate timing"
            assert phys.properties["timing"] >= 0, "timing should be non-negative"

        finally:
            adapter_with_capture.close_connection(connection)

    def test_plan_not_captured_when_disabled(self, adapter_without_capture):
        """Test that plan is not captured when capture_plans=False."""
        connection = adapter_without_capture.create_connection()

        try:
            result = adapter_without_capture.execute_query(
                connection=connection,
                query="SELECT 1 as test_column",
                query_id="test_q2",
                validate_row_count=False,
            )

            # Should NOT have query_plan in result
            assert "query_plan" not in result or result["query_plan"] is None

        finally:
            adapter_without_capture.close_connection(connection)

    def test_capture_query_plan_method(self, adapter_with_capture):
        """Test the capture_query_plan method directly."""
        connection = adapter_with_capture.create_connection()

        try:
            plan, capture_time_ms = adapter_with_capture.capture_query_plan(
                connection=connection,
                query="SELECT * FROM (VALUES (1, 'a'), (2, 'b')) AS t(id, name) WHERE id > 0",
                query_id="test_q3",
            )

            # Capture time should always be measured
            assert capture_time_ms >= 0

            # Plan may be None if parsing fails, but method should not crash
            if plan:
                assert plan.query_id == "test_q3"
                assert plan.platform == "duckdb"
                assert plan.logical_root is not None
                assert plan.plan_fingerprint is not None

        finally:
            adapter_with_capture.close_connection(connection)

    def test_plan_capture_with_table(self, adapter_with_capture):
        """Test plan capture with actual table creation and query."""
        connection = adapter_with_capture.create_connection()

        try:
            # Create a simple table
            connection.execute("CREATE TABLE test_table (id INTEGER, name VARCHAR)")
            connection.execute("INSERT INTO test_table VALUES (1, 'Alice'), (2, 'Bob')")

            # Execute query with plan capture
            result = adapter_with_capture.execute_query(
                connection=connection,
                query="SELECT * FROM test_table WHERE id = 1",
                query_id="test_q4",
                validate_row_count=False,
            )

            assert result["status"] == "SUCCESS"
            assert result["rows_returned"] == 1

            # Plan may or may not be captured depending on DuckDB's EXPLAIN output
            if "query_plan" in result and result["query_plan"]:
                plan = result["query_plan"]
                assert plan.platform == "duckdb"

        finally:
            adapter_with_capture.close_connection(connection)

    def test_get_query_plan_returns_json_format(self, adapter_with_capture):
        """get_query_plan must use EXPLAIN (ANALYZE, FORMAT JSON), not the text/box format.

        The text-box parser rejects branching structures (JOINs) and would
        produce incorrect fingerprints. JSON format handles all query shapes.
        EXPLAIN ANALYZE adds actual timing and cardinality data to the captured plan.
        """
        connection = adapter_with_capture.create_connection()
        try:
            connection.execute("CREATE TABLE t1 (id INTEGER, val VARCHAR)")
            connection.execute("CREATE TABLE t2 (id INTEGER, score DOUBLE)")
            connection.execute("INSERT INTO t1 VALUES (1, 'a'), (2, 'b')")
            connection.execute("INSERT INTO t2 VALUES (1, 1.5), (2, 2.5)")

            raw = adapter_with_capture.get_query_plan(
                connection,
                "SELECT t1.val, t2.score FROM t1 JOIN t2 ON t1.id = t2.id",
            )

            assert raw is not None, "get_query_plan returned None for a JOIN query"
            stripped = raw.strip()
            assert stripped.startswith("{") or stripped.startswith("["), (
                f"Expected JSON output from EXPLAIN (FORMAT JSON), got text format:\n{raw[:200]}"
            )
        finally:
            adapter_with_capture.close_connection(connection)

    def test_plan_capture_succeeds_for_join_query(self, adapter_with_capture):
        """Multi-JOIN queries must be parseable - the branching-structure error must not occur."""
        connection = adapter_with_capture.create_connection()
        try:
            connection.execute("CREATE TABLE a (id INTEGER, x INTEGER)")
            connection.execute("CREATE TABLE b (id INTEGER, y INTEGER)")
            connection.execute("CREATE TABLE c (id INTEGER, z INTEGER)")
            connection.execute("INSERT INTO a VALUES (1, 10)")
            connection.execute("INSERT INTO b VALUES (1, 20)")
            connection.execute("INSERT INTO c VALUES (1, 30)")

            plan, capture_ms = adapter_with_capture.capture_query_plan(
                connection=connection,
                query="SELECT a.x, b.y, c.z FROM a JOIN b ON a.id = b.id JOIN c ON a.id = c.id",
                query_id="join_test",
            )

            # Must not fail - plan should be captured for a branching query
            assert plan is not None, (
                "Plan capture returned None for a multi-JOIN query. "
                "Likely still using text-box EXPLAIN which rejects branching structures."
            )
            assert plan.logical_root is not None
            assert capture_ms >= 0
        finally:
            adapter_with_capture.close_connection(connection)

    def test_plan_capture_does_not_affect_correctness(self, adapter_with_capture, adapter_without_capture):
        """Test that enabling plan capture doesn't affect query results."""
        # Execute same query with and without capture
        conn_with = adapter_with_capture.create_connection()
        conn_without = adapter_without_capture.create_connection()

        try:
            result_with = adapter_with_capture.execute_query(
                connection=conn_with,
                query="SELECT 42 as answer",
                query_id="test_q5",
                validate_row_count=False,
            )

            result_without = adapter_without_capture.execute_query(
                connection=conn_without,
                query="SELECT 42 as answer",
                query_id="test_q5",
                validate_row_count=False,
            )

            # Core results should be the same
            assert result_with["status"] == result_without["status"]
            assert result_with["rows_returned"] == result_without["rows_returned"]
            assert result_with["execution_time_seconds"] >= 0
            assert result_without["execution_time_seconds"] >= 0

        finally:
            adapter_with_capture.close_connection(conn_with)
            adapter_without_capture.close_connection(conn_without)

    def test_analyze_plans_false_produces_no_timing(self):
        """With analyze_plans=False, captured plans use EXPLAIN (FORMAT JSON) - no timing data.

        This verifies the opt-out path for users who want structural-only plan capture
        without the re-execution overhead of EXPLAIN ANALYZE.
        """
        adapter = DuckDBAdapter(capture_plans=True, analyze_plans=False)
        connection = adapter.create_connection()

        try:
            connection.execute("CREATE TABLE est_test (id INTEGER, val VARCHAR)")
            connection.execute("INSERT INTO est_test VALUES (1, 'a'), (2, 'b')")

            plan, _ = adapter.capture_query_plan(
                connection=connection,
                query="SELECT * FROM est_test WHERE id = 1",
                query_id="est_q1",
            )

            assert plan is not None, "Plan should be captured even with analyze_plans=False"
            assert plan.logical_root is not None

            # EXPLAIN (FORMAT JSON) without ANALYZE does not populate timing
            phys = plan.logical_root.physical_operator
            if phys:
                timing = phys.properties.get("timing")
                assert timing is None or timing == 0, f"Expected no timing with analyze_plans=False, got {timing}"

        finally:
            adapter.close_connection(connection)
