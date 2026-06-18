"""
Tests for DuckDB query plan capture integration.

Verifies that query plans are captured and parsed during query execution.
"""

from unittest.mock import MagicMock

import pytest

from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestIsDmlQueryHelper:
    """Direct contract tests for the shared is_dml_query classifier."""

    @pytest.mark.parametrize(
        "query",
        [
            "INSERT INTO t VALUES (1)",
            "update t set x = 1",
            "  DELETE FROM t",
            "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN UPDATE SET x = 1",
            "COPY t FROM 'f.csv'",
            "/* banner */ INSERT INTO t VALUES (1)",
            "-- c\nUPDATE t SET x = 1",
            "WITH s AS (SELECT 1) INSERT INTO t SELECT * FROM s",
        ],
    )
    def test_dml_detected(self, query):
        from benchbox.platforms.base.result_capture import is_dml_query

        assert is_dml_query(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "CREATE TABLE t AS SELECT * FROM s",
            "create or replace table t as select 1",
            "CREATE TEMP TABLE t AS SELECT 1",
            "CREATE TEMPORARY TABLE t AS (SELECT 1)",
            "CREATE UNLOGGED TABLE t AS SELECT 1",
            "CREATE TABLE t (a, b) AS SELECT x, y FROM s",  # CTAS with column alias list
            "CREATE TABLE t AS\nWITH cte AS (SELECT 1) SELECT * FROM cte",
            "CREATE TABLE t AS VALUES (1), (2)",
            "/* banner */ CREATE TABLE t AS SELECT 1",
            "CREATE MATERIALIZED VIEW v AS SELECT 1",
            "CREATE OR REPLACE MATERIALIZED VIEW v AS (SELECT * FROM t)",
            "SELECT * INTO new_t FROM t",
            "select x into archive_t from t where x > 1",
        ],
    )
    def test_write_producing_ddl_detected(self, query):
        from benchbox.platforms.base.result_capture import is_dml_query

        assert is_dml_query(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "SELECT 1",
            "WITH cte AS (SELECT 1) SELECT * FROM cte",
            "SELECT copy_total, merge_flag FROM t",  # identifiers, not verbs (word boundary)
            "CREATE TABLE t (id INT)",  # column DDL writes no rows
            "CREATE TABLE t (x INT GENERATED ALWAYS AS (x + 1) STORED)",  # generated column AS is not CTAS
            "CREATE TABLE t (note TEXT DEFAULT 'AS SELECT')",  # literal inside column DDL is not CTAS
            "CREATE INDEX idx ON t (id)",
            "CREATE VIEW v AS SELECT 1",  # plain view stores no rows
            "DROP TABLE t",
            "ALTER TABLE t ADD COLUMN y INT",
            "TRUNCATE TABLE t",
            "SELECT * FROM t WHERE note = 'INTO the void'",  # INTO inside a string literal
            "SELECT * FROM (SELECT 1 INTO_X) sub",  # parenthesized, not a top-level INTO
            "EXPLAIN SELECT 1",
            "",
            "-- only a comment",
        ],
    )
    def test_non_dml_not_detected(self, query):
        from benchbox.platforms.base.result_capture import is_dml_query

        assert is_dml_query(query) is False


class TestDuckDBDMLPlanGuard:
    """EXPLAIN ANALYZE re-executes statements; DML must downgrade to FORMAT JSON."""

    @pytest.mark.parametrize(
        "dml",
        [
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET x = 1",
            "DELETE FROM t WHERE id = 1",
            "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN UPDATE SET x = 1",
            "COPY t FROM 'data.csv'",
        ],
    )
    def test_dml_query_does_not_use_analyze(self, dml):
        adapter = DuckDBAdapter(capture_plans=True, analyze_plans=True)
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [("logical_plan", "{}")]

        adapter.get_query_plan(conn, dml)

        called_sql = conn.execute.call_args[0][0].upper()
        assert "ANALYZE" not in called_sql, f"DML must not run EXPLAIN ANALYZE: {called_sql}"
        assert "FORMAT JSON" in called_sql

    @pytest.mark.parametrize(
        "dml",
        [
            "-- leading comment\nINSERT INTO t VALUES (1)",
            "  insert into t values (1)",
            "/* query 12 */ INSERT INTO t VALUES (1)",
            "/* a */ -- b\n  DELETE FROM t",
            "WITH src AS (SELECT * FROM staging) INSERT INTO t SELECT * FROM src",
            "WITH d AS (SELECT id FROM t) DELETE FROM t WHERE id IN (SELECT id FROM d)",
        ],
    )
    def test_dml_guard_handles_comments_cte_and_whitespace(self, dml):
        adapter = DuckDBAdapter(capture_plans=True, analyze_plans=True)
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [("logical_plan", "{}")]

        adapter.get_query_plan(conn, dml)

        assert "ANALYZE" not in conn.execute.call_args[0][0].upper(), f"DML must not run ANALYZE: {dml!r}"

    @pytest.mark.parametrize(
        "write_ddl",
        [
            "CREATE TABLE t2 AS SELECT * FROM t",
            "CREATE OR REPLACE TABLE t2 AS SELECT * FROM t",
            "CREATE MATERIALIZED VIEW mv AS SELECT * FROM t",
            "SELECT * INTO t2 FROM t",
        ],
    )
    def test_ctas_query_does_not_use_analyze(self, write_ddl):
        """CTAS/CMV/SELECT-INTO materialize rows; EXPLAIN ANALYZE would write them twice."""
        adapter = DuckDBAdapter(capture_plans=True, analyze_plans=True)
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [("logical_plan", "{}")]

        adapter.get_query_plan(conn, write_ddl)

        called_sql = conn.execute.call_args[0][0].upper()
        assert "ANALYZE" not in called_sql, f"Write DDL must not run EXPLAIN ANALYZE: {called_sql}"
        assert "FORMAT JSON" in called_sql

    @pytest.mark.parametrize(
        "non_dml",
        [
            "SELECT * FROM t WHERE id = 1",
            "WITH cte AS (SELECT 1) SELECT * FROM cte",
            "SELECT copy_count, update_ts FROM t",  # column names starting with DML verbs
            "CREATE TABLE t (id INT)",  # column DDL writes no rows
        ],
    )
    def test_non_dml_query_still_uses_analyze(self, non_dml):
        adapter = DuckDBAdapter(capture_plans=True, analyze_plans=True)
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [("analyzed_plan", "{}")]

        adapter.get_query_plan(conn, non_dml)

        called_sql = conn.execute.call_args[0][0].upper()
        assert "ANALYZE" in called_sql, f"Non-DML must still use EXPLAIN ANALYZE: {non_dml!r}"
        assert "FORMAT JSON" in called_sql


class TestDuckDBDisplayQueryPlan:
    """display_query_plan_if_enabled must not be called when capture_plans is active."""

    def _make_adapter(self, capture_plans: bool):
        return DuckDBAdapter(capture_plans=capture_plans)

    def _mock_execute(self, monkeypatch, adapter):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        monkeypatch.setattr(
            adapter,
            "_build_query_result_with_validation",
            lambda **kw: {"query_id": kw.get("query_id", "q"), "status": "SUCCESS", "rows_returned": 0},
        )
        monkeypatch.setattr(adapter, "_merge_plan_capture_into_result", lambda *a, **k: None)
        return conn

    def test_display_called_when_not_capturing(self, monkeypatch):
        adapter = self._make_adapter(capture_plans=False)
        conn = self._mock_execute(monkeypatch, adapter)
        display_calls = []
        monkeypatch.setattr(adapter, "display_query_plan_if_enabled", lambda *a, **k: display_calls.append(True))

        adapter.execute_query(connection=conn, query="SELECT 1", query_id="q", validate_row_count=False)

        assert len(display_calls) == 1, "display_query_plan_if_enabled should fire once when capture_plans=False"

    def test_display_suppressed_when_capturing(self, monkeypatch):
        adapter = self._make_adapter(capture_plans=True)
        conn = self._mock_execute(monkeypatch, adapter)
        display_calls = []
        monkeypatch.setattr(adapter, "display_query_plan_if_enabled", lambda *a, **k: display_calls.append(True))

        adapter.execute_query(connection=conn, query="SELECT 1", query_id="q", validate_row_count=False)

        assert len(display_calls) == 0, (
            "display_query_plan_if_enabled must not fire when capture_plans=True (avoids double EXPLAIN)"
        )


class TestDuckDBPlanRawOutputPolicy:
    """capture_query_plan must honor the plan_raw_output retention config."""

    def _capture(self, **config):
        adapter = DuckDBAdapter(capture_plans=True, **config)
        connection = adapter.create_connection()
        try:
            connection.execute("CREATE TABLE t (id INTEGER, val VARCHAR)")
            connection.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b')")
            plan, _ = adapter.capture_query_plan(connection, "SELECT * FROM t WHERE id = 1", "rawpol")
            return plan
        finally:
            adapter.close_connection(connection)

    def test_default_policy_retains_raw_output(self):
        # Default 'truncated' with a 16 KiB cap keeps a small plan's raw text whole.
        plan = self._capture()
        assert plan is not None
        assert plan.raw_explain_output is not None
        assert plan.plan_fingerprint is not None

    def test_none_policy_drops_raw_output_but_keeps_dag(self):
        plan = self._capture(plan_raw_output="none")
        assert plan is not None
        assert plan.raw_explain_output is None
        # Structured DAG and fingerprint are retained regardless of the raw policy.
        assert plan.logical_root is not None
        assert plan.plan_fingerprint is not None

    def test_truncated_policy_caps_raw_output(self):
        plan = self._capture(plan_raw_output="truncated", plan_raw_output_max_bytes=64)
        assert plan is not None
        assert plan.raw_explain_output is not None
        assert "truncated" in plan.raw_explain_output
        assert plan.logical_root is not None

    def test_invalid_max_bytes_config_falls_back_to_default(self):
        # A non-integer cap must not crash capture; it falls back to the default cap.
        plan = self._capture(plan_raw_output="truncated", plan_raw_output_max_bytes="not-an-int")
        assert plan is not None
        assert plan.raw_explain_output is not None

    def test_non_positive_max_bytes_falls_back_to_default_not_drop(self):
        # A non-positive cap is misconfiguration: it must fall back to the default cap
        # (retaining raw text) rather than silently nulling it like the 'none' policy.
        plan = self._capture(plan_raw_output="truncated", plan_raw_output_max_bytes=0)
        assert plan is not None
        assert plan.raw_explain_output is not None


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


class TestDuckDBFingerprintIntegration:
    """Integration tests against a real in-memory DuckDB connection (no mocking).

    Exercises the full capture path (real EXPLAIN, real parser, real fingerprint)
    and verifies the plan fingerprint stability contract documented in
    query_plan_models.py. DuckDB in-memory needs no credentials.
    """

    @pytest.fixture
    def adapter(self):
        return DuckDBAdapter(capture_plans=True)

    @pytest.fixture
    def conn(self, adapter):
        connection = adapter.create_connection()
        connection.execute("CREATE TABLE orders (id INTEGER, amount DOUBLE)")
        connection.executemany("INSERT INTO orders VALUES (?, ?)", [(i, float(i)) for i in range(1, 500)])
        yield connection
        adapter.close_connection(connection)

    def test_get_query_plan_returns_non_empty_json(self, adapter, conn):
        raw = adapter.get_query_plan(conn, "SELECT * FROM orders WHERE id = 1")
        assert raw, "get_query_plan should return non-empty EXPLAIN output"
        stripped = raw.strip()
        assert stripped.startswith("{") or stripped.startswith("["), "Expected FORMAT JSON output"

    def test_parser_produces_dag_from_real_explain(self, adapter, conn):
        raw = adapter.get_query_plan(conn, "SELECT * FROM orders WHERE id = 1")
        parser = adapter.get_query_plan_parser()
        dag = parser.parse_explain_output("dq_dag", raw)
        assert dag is not None
        assert dag.logical_root is not None
        assert dag.plan_fingerprint is not None

    def test_fingerprint_is_idempotent_across_calls(self, adapter, conn):
        query = "SELECT * FROM orders WHERE id = 1"
        plan1, _ = adapter.capture_query_plan(conn, query, "dq_a")
        plan2, _ = adapter.capture_query_plan(conn, query, "dq_b")
        assert plan1 is not None and plan2 is not None
        assert plan1.plan_fingerprint is not None
        assert plan1.plan_fingerprint == plan2.plan_fingerprint

    def test_fingerprint_stable_across_index_addition(self, adapter, conn):
        # Logical fingerprint excludes the physical access method, so adding an
        # index does not change it (physical-independence guarantee).
        query = "SELECT * FROM orders WHERE amount = 250.0"
        before, _ = adapter.capture_query_plan(conn, query, "dq_before_idx")
        conn.execute("CREATE INDEX idx_orders_amount ON orders(amount)")
        after, _ = adapter.capture_query_plan(conn, query, "dq_after_idx")
        assert before is not None and after is not None
        assert before.plan_fingerprint == after.plan_fingerprint, (
            "Adding an index is a physical change; the logical fingerprint must be stable"
        )

    def test_fingerprint_differs_for_logically_distinct_plans(self, adapter, conn):
        # A self-join adds a second table scan to the logical tree, so the
        # signature differs by construction (two Scan nodes vs one), independent of
        # indexes, stats, or planner access-method choices.
        scan_plan, _ = adapter.capture_query_plan(conn, "SELECT * FROM orders", "dq_scan")
        join_plan, _ = adapter.capture_query_plan(
            conn, "SELECT o.id FROM orders o JOIN orders o2 ON o.id = o2.id", "dq_join"
        )
        assert scan_plan is not None and join_plan is not None
        assert scan_plan.plan_fingerprint != join_plan.plan_fingerprint, "A join must change the logical plan shape"
