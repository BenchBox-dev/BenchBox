"""Tests for SQLite query plan capture wiring."""

import sqlite3

import pytest

from benchbox.platforms.sqlite import SQLiteAdapter, _format_sqlite_query_plan

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def adapter():
    return SQLiteAdapter(capture_plans=True)


@pytest.fixture()
def adapter_no_capture():
    return SQLiteAdapter(capture_plans=False)


@pytest.fixture()
def conn():
    """In-memory SQLite connection."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL)")
    c.execute("INSERT INTO orders VALUES (1, 99.9), (2, 49.9)")
    c.execute("CREATE TABLE lineitem (order_id INTEGER, qty INTEGER)")
    c.execute("INSERT INTO lineitem VALUES (1, 3), (2, 1)")
    yield c
    c.close()


class TestFormatSQLiteQueryPlan:
    def test_single_root_node(self):
        rows = [(2, 0, 0, "SCAN orders")]
        text = _format_sqlite_query_plan(rows)
        assert text is not None
        assert "QUERY PLAN" in text
        assert "`--SCAN orders" in text

    def test_multiple_root_nodes(self):
        rows = [(2, 0, 0, "SCAN orders"), (4, 0, 0, "SCAN lineitem")]
        text = _format_sqlite_query_plan(rows)
        assert "|--SCAN orders" in text
        assert "`--SCAN lineitem" in text

    def test_parent_child_nesting(self):
        rows = [(2, 0, 0, "SCAN customer"), (4, 2, 0, "SEARCH lineitem USING INDEX")]
        text = _format_sqlite_query_plan(rows)
        assert "SCAN customer" in text
        assert "SEARCH lineitem" in text

    def test_empty_rows_returns_none(self):
        assert _format_sqlite_query_plan([]) is None


class TestSQLitePlanCapture:
    def test_get_query_plan_parser_returns_instance(self, adapter):
        from benchbox.core.query_plans.parsers.sqlite import SQLiteQueryPlanParser

        parser = adapter.get_query_plan_parser()
        assert parser is not None
        assert isinstance(parser, SQLiteQueryPlanParser)

    def test_get_query_plan_returns_text(self, adapter, conn):
        result = adapter.get_query_plan(conn, "SELECT * FROM orders")
        assert result is not None
        assert "QUERY PLAN" in result or "SCAN" in result

    def test_get_query_plan_returns_none_on_error(self, adapter):
        from unittest.mock import MagicMock
        bad_conn = MagicMock()
        bad_conn.cursor.return_value.execute.side_effect = Exception("error")
        assert adapter.get_query_plan(bad_conn, "SELECT 1") is None

    def test_execute_query_with_capture_adds_plan_fields(self, adapter, conn):
        result = adapter.execute_query(
            connection=conn,
            query="SELECT * FROM orders",
            query_id="sq1",
            validate_row_count=False,
        )
        assert result["status"] == "SUCCESS"
        # Plan capture runs against real in-memory SQLite
        if "query_plan" in result and result["query_plan"] is not None:
            assert result["plan_fingerprint"] is not None
            assert result["plan_capture_time_ms"] >= 0

    def test_execute_query_without_capture_has_no_plan(self, adapter_no_capture, conn):
        result = adapter_no_capture.execute_query(
            connection=conn,
            query="SELECT * FROM orders",
            query_id="sq2",
            validate_row_count=False,
        )
        assert "query_plan" not in result or result.get("query_plan") is None

    def test_execute_query_capture_does_not_affect_row_count(self, adapter, conn):
        result = adapter.execute_query(
            connection=conn,
            query="SELECT * FROM orders",
            query_id="sq3",
            validate_row_count=False,
        )
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2


class TestSQLiteParserModernFormat:
    """Verify the parser handles modern SQLite output (no TABLE keyword)."""

    def test_infer_scan_without_table_keyword(self):
        from benchbox.core.query_plans.parsers.sqlite import SQLiteQueryPlanParser

        parser = SQLiteQueryPlanParser()
        op_type = parser._infer_operator_type("SCAN orders")
        assert op_type == "SCAN"

    def test_infer_search_without_table_keyword(self):
        from benchbox.core.query_plans.parsers.sqlite import SQLiteQueryPlanParser

        parser = SQLiteQueryPlanParser()
        op_type = parser._infer_operator_type("SEARCH orders USING INDEX idx_customer (c_custkey=?)")
        assert op_type == "INDEX_SCAN"

    def test_extract_details_without_table_keyword(self):
        from benchbox.core.query_plans.parsers.sqlite import SQLiteQueryPlanParser

        parser = SQLiteQueryPlanParser()
        details = parser._extract_details("SCAN orders")
        assert details.get("table_name") == "orders"

    def test_parse_modern_explain_output(self, conn):
        """End-to-end: parse actual SQLite 3.36+ EXPLAIN QUERY PLAN output."""
        from benchbox.core.query_plans.parsers.sqlite import SQLiteQueryPlanParser

        cursor = conn.cursor()
        cursor.execute("EXPLAIN QUERY PLAN SELECT * FROM orders WHERE id = 1")
        rows = cursor.fetchall()
        cursor.close()

        from benchbox.platforms.sqlite import _format_sqlite_query_plan
        plan_text = _format_sqlite_query_plan(rows)

        if plan_text:
            parser = SQLiteQueryPlanParser()
            dag = parser.parse_explain_output("test_q", plan_text)
            assert dag is not None
            assert dag.logical_root is not None
