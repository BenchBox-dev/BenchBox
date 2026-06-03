"""Tests for Redshift query plan capture wiring."""

from unittest.mock import MagicMock

import pytest

from benchbox.platforms.redshift import RedshiftAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


_STUB_CREDS = {"host": "localhost", "username": "test", "password": "test"}


@pytest.fixture()
def adapter(monkeypatch):
    monkeypatch.setattr("benchbox.platforms.redshift.redshift_connector", MagicMock(), raising=False)
    return RedshiftAdapter(**_STUB_CREDS, capture_plans=True)


@pytest.fixture()
def adapter_no_capture(monkeypatch):
    monkeypatch.setattr("benchbox.platforms.redshift.redshift_connector", MagicMock(), raising=False)
    return RedshiftAdapter(**_STUB_CREDS, capture_plans=False)


def _make_connection(plan_text="XN Seq Scan on orders\n  (cost=0.00..10.00 rows=1 width=4)"):
    cursor = MagicMock()
    cursor.fetchall.return_value = [(line,) for line in plan_text.split("\n")]
    cursor.__enter__ = lambda s: s
    cursor.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


class TestRedshiftPlanCapture:
    def test_get_query_plan_parser_returns_instance(self, adapter):
        from benchbox.core.query_plans.parsers.redshift import RedshiftQueryPlanParser

        parser = adapter.get_query_plan_parser()
        assert parser is not None
        assert isinstance(parser, RedshiftQueryPlanParser)

    def test_get_query_plan_returns_text(self, adapter):
        conn, _ = _make_connection("XN Seq Scan on orders")
        result = adapter.get_query_plan(conn, "SELECT 1")
        assert result is not None
        assert "XN Seq Scan" in result

    def test_get_query_plan_returns_none_on_error(self, adapter):
        conn = MagicMock()
        conn.cursor.return_value.execute.side_effect = Exception("network error")
        result = adapter.get_query_plan(conn, "SELECT 1")
        assert result is None

    def test_execute_query_with_capture_adds_plan_fields(self, adapter, monkeypatch):
        conn, cursor = _make_connection()
        cursor.fetchall.return_value = [(0, "col1")]  # query result rows

        mock_plan = MagicMock()
        mock_plan.plan_fingerprint = "rs_fingerprint"
        monkeypatch.setattr(adapter, "capture_query_plan", lambda *a, **k: (mock_plan, 3.0))
        monkeypatch.setattr(adapter, "_get_query_statistics", lambda *a, **k: {})

        result = adapter.execute_query(connection=conn, query="SELECT 1", query_id="rq1", validate_row_count=False)

        assert result["status"] == "SUCCESS"
        assert result["query_plan"] is mock_plan
        assert result["plan_fingerprint"] == "rs_fingerprint"
        assert result["plan_capture_time_ms"] == 3.0

    def test_execute_query_without_capture_has_no_plan(self, adapter_no_capture, monkeypatch):
        conn, cursor = _make_connection()
        cursor.fetchall.return_value = [(0, "col1")]
        monkeypatch.setattr(adapter_no_capture, "_get_query_statistics", lambda *a, **k: {})

        result = adapter_no_capture.execute_query(
            connection=conn, query="SELECT 1", query_id="rq2", validate_row_count=False
        )

        assert "query_plan" not in result or result.get("query_plan") is None

    def test_get_query_plan_does_not_use_analyze(self, adapter):
        cursor = MagicMock()
        cursor.fetchall.return_value = [("XN Seq Scan",)]
        conn = MagicMock()
        conn.cursor.return_value = cursor

        adapter.get_query_plan(conn, "SELECT 1")

        call_args = cursor.execute.call_args[0][0].upper()
        assert "EXPLAIN ANALYZE" not in call_args, "Redshift does not support EXPLAIN ANALYZE"
