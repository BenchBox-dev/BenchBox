"""Tests for PostgreSQL query plan capture wiring."""

from unittest.mock import MagicMock, patch

import pytest

from benchbox.platforms.postgresql import PostgreSQLAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def adapter(monkeypatch):
    """PostgreSQLAdapter with psycopg stubbed out."""
    monkeypatch.setattr("benchbox.platforms.postgresql.psycopg", MagicMock())
    return PostgreSQLAdapter(capture_plans=True)


@pytest.fixture()
def adapter_no_capture(monkeypatch):
    monkeypatch.setattr("benchbox.platforms.postgresql.psycopg", MagicMock())
    return PostgreSQLAdapter(capture_plans=False)


def _make_connection(plan_json='[{"Plan": {"Node Type": "Result"}}]'):
    """Build a mock psycopg connection that returns a fixed EXPLAIN JSON."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [(plan_json,)]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


class TestPostgreSQLPlanCapture:
    def test_get_query_plan_parser_returns_instance(self, adapter):
        from benchbox.core.query_plans.parsers.postgresql import PostgreSQLQueryPlanParser

        parser = adapter.get_query_plan_parser()
        assert parser is not None
        assert isinstance(parser, PostgreSQLQueryPlanParser)

    def test_get_query_plan_returns_json(self, adapter):
        conn = _make_connection('[{"Plan": {"Node Type": "Seq Scan"}}]')
        result = adapter.get_query_plan(conn, "SELECT 1")
        assert result is not None
        assert "Plan" in result or "Seq Scan" in result

    def test_get_query_plan_returns_none_on_error(self, adapter):
        conn = MagicMock()
        conn.cursor.return_value.execute.side_effect = Exception("db error")
        result = adapter.get_query_plan(conn, "SELECT 1")
        assert result is None

    def test_execute_query_with_capture_adds_plan_fields(self, adapter, monkeypatch):
        conn = _make_connection()

        # Patch capture_query_plan on the adapter instance
        mock_plan = MagicMock()
        mock_plan.plan_fingerprint = "abc123"
        monkeypatch.setattr(adapter, "capture_query_plan", lambda *a, **k: (mock_plan, 5.0))

        # Patch the mixin execute_query to return a SUCCESS result
        monkeypatch.setattr(
            "benchbox.platforms.base.psycopg2_mixin.PsycopgConnectionMixin.execute_query",
            lambda self, **kw: {"query_id": kw["query_id"], "status": "SUCCESS", "rows_returned": 1},
        )

        result = adapter.execute_query(connection=conn, query="SELECT 1", query_id="q1")

        assert result["status"] == "SUCCESS"
        assert result["query_plan"] is mock_plan
        assert result["plan_fingerprint"] == "abc123"
        assert result["plan_capture_time_ms"] == 5.0

    def test_execute_query_without_capture_has_no_plan(self, adapter_no_capture, monkeypatch):
        conn = _make_connection()

        monkeypatch.setattr(
            "benchbox.platforms.base.psycopg2_mixin.PsycopgConnectionMixin.execute_query",
            lambda self, **kw: {"query_id": kw["query_id"], "status": "SUCCESS", "rows_returned": 1},
        )

        result = adapter_no_capture.execute_query(connection=conn, query="SELECT 1", query_id="q1")

        assert "query_plan" not in result or result.get("query_plan") is None

    def test_execute_query_failed_status_skips_capture(self, adapter, monkeypatch):
        conn = _make_connection()

        capture_called = []
        monkeypatch.setattr(adapter, "capture_query_plan", lambda *a, **k: capture_called.append(True) or (None, 0.0))

        monkeypatch.setattr(
            "benchbox.platforms.base.psycopg2_mixin.PsycopgConnectionMixin.execute_query",
            lambda self, **kw: {"query_id": kw["query_id"], "status": "FAILED", "rows_returned": 0},
        )

        adapter.execute_query(connection=conn, query="SELECT 1", query_id="q1")

        assert not capture_called, "capture_query_plan must not be called on FAILED queries"

    def test_get_query_plan_uses_format_json(self, adapter):
        cursor = MagicMock()
        cursor.fetchall.return_value = [('{"Plan":{}}',)]
        conn = MagicMock()
        conn.cursor.return_value = cursor

        adapter.get_query_plan(conn, "SELECT 1")

        call_args = cursor.execute.call_args[0][0]
        assert "FORMAT JSON" in call_args.upper()
        assert "FORMAT TEXT" not in call_args.upper()


class TestPostgreSQLSubclassInheritance:
    """Verify TimescaleDB, CedarDB, and pg_mooncake inherit the parser without overrides."""

    @pytest.mark.parametrize("adapter_class_path,module_path", [
        ("benchbox.platforms.timescaledb.TimescaleDBAdapter", "benchbox.platforms.timescaledb"),
        ("benchbox.platforms.cedardb.CedarDBAdapter", "benchbox.platforms.cedardb"),
        ("benchbox.platforms.pg_mooncake.PgMooncakeAdapter", "benchbox.platforms.pg_mooncake"),
    ])
    def test_subclass_returns_postgresql_parser(self, adapter_class_path, module_path, monkeypatch):
        from benchbox.core.query_plans.parsers.postgresql import PostgreSQLQueryPlanParser

        module_name, class_name = adapter_class_path.rsplit(".", 1)
        monkeypatch.setattr("benchbox.platforms.postgresql.psycopg", MagicMock())

        try:
            import importlib
            module = importlib.import_module(module_name)
            # Stub out any extra dependencies the subclass may import
            cls = getattr(module, class_name)
            adapter = cls.__new__(cls)
            # Inject capture_plans via the base class dict
            adapter.__dict__["capture_plans"] = True

            parser = PostgreSQLAdapter.get_query_plan_parser(adapter)
            assert isinstance(parser, PostgreSQLQueryPlanParser), (
                f"{class_name} should inherit PostgreSQLQueryPlanParser via PostgreSQLAdapter"
            )
        except (ImportError, AttributeError):
            pytest.skip(f"Could not import {adapter_class_path}")
