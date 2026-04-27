from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from benchbox.core.tuning.interface import (
    BenchmarkTunings,
    TableTuning,
    TuningColumn,
    TuningType,
    UnifiedTuningConfiguration,
)
from benchbox.core.tuning.metadata import (
    MetadataValidationResult,
    TuningMetadata,
    TuningMetadataManager,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _Cursor:
    def __init__(self, fetchall_data=None, fetchone_data=None):
        self.fetchall_data = fetchall_data or []
        self.fetchone_data = fetchone_data
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.fetchall_data

    def fetchone(self):
        return self.fetchone_data


class _Conn:
    def __init__(self, cursor: _Cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


class _Adapter:
    def __init__(self, platform_name: str = "duckdb"):
        self.platform_name = platform_name
        self.platform_config = {}
        self.connections: list[_Conn] = []

    def create_connection(self, **_kwargs):
        conn = _Conn(_Cursor())
        self.connections.append(conn)
        return conn

    def close_connection(self, _conn):
        return None


def _col(name: str, order: int = 1) -> TuningColumn:
    return TuningColumn(name=name, type="INTEGER", order=order)


def test_tuning_metadata_round_trip_to_dict_from_dict():
    metadata = TuningMetadata(
        table_name="orders",
        tuning_type="sorting",
        column_name="o_orderkey",
        column_order=1,
        configuration_hash="abc",
        created_at=datetime(2026, 2, 8, 0, 0, 0),
        platform="duckdb",
    )

    rebuilt = TuningMetadata.from_dict(metadata.to_dict())
    assert rebuilt.table_name == "orders"
    assert rebuilt.created_at.year == 2026


def test_metadata_validation_result_helpers():
    result = MetadataValidationResult()
    result.add_warning("warn")
    result.add_error("err")

    assert result.is_valid is False
    assert result.has_issues() is True
    assert result.errors == ["err"]
    assert result.warnings == ["warn"]


@pytest.mark.parametrize(
    ("platform", "needle"),
    [
        ("bigquery", "CREATE TABLE"),
        ("snowflake", "TIMESTAMP_NTZ"),
        ("redshift", "ENCODE AUTO"),
        ("clickhouse", "ENGINE = MergeTree()"),
        ("duckdb", "CREATE TABLE IF NOT EXISTS"),
    ],
)
def test_create_table_sql_varies_by_platform(platform, needle):
    manager = TuningMetadataManager(_Adapter(platform_name=platform))
    assert needle in manager._get_create_table_sql()


def test_create_index_sql_skips_platforms_without_indexes():
    assert TuningMetadataManager(_Adapter("clickhouse"))._get_create_index_sql() is None
    assert TuningMetadataManager(_Adapter("bigquery"))._get_create_index_sql() is None
    assert "CREATE INDEX" in TuningMetadataManager(_Adapter("duckdb"))._get_create_index_sql()


def test_table_exists_check_caches_true_result(monkeypatch):
    manager = TuningMetadataManager(_Adapter("duckdb"))
    calls = {"n": 0}

    def _fetch_one(_conn, _sql):
        calls["n"] += 1
        return (1,)

    monkeypatch.setattr(manager, "_fetch_one", _fetch_one)

    assert manager._table_exists_check() is True
    assert manager._table_exists_check() is True
    assert calls["n"] == 1


def test_rebuild_tunings_from_records_groups_columns_by_table_and_type():
    manager = TuningMetadataManager(_Adapter("duckdb"))
    records = [
        ("orders", TuningType.SORTING.value, "o_orderkey", 1, "h", datetime.now(), "duckdb"),
        ("orders", TuningType.PARTITIONING.value, "o_orderdate", 1, "h", datetime.now(), "duckdb"),
    ]

    tunings = manager._rebuild_tunings_from_records(records, "tpch")

    table = tunings.get_table_tuning("orders")
    assert table is not None
    assert [c.name for c in table.sorting or []] == ["o_orderkey"]
    assert [c.name for c in table.partitioning or []] == ["o_orderdate"]


def test_compare_tuning_configurations_detects_missing_and_mismatch():
    manager = TuningMetadataManager(_Adapter("duckdb"))

    expected = BenchmarkTunings("tpch")
    expected.add_table_tuning(TableTuning(table_name="orders", sorting=[_col("o_orderkey", 1)]))

    existing = BenchmarkTunings("tpch")
    existing.add_table_tuning(TableTuning(table_name="orders", sorting=[_col("o_orderdate", 1)]))
    existing.add_table_tuning(TableTuning(table_name="lineitem", sorting=[_col("l_orderkey", 1)]))

    result = MetadataValidationResult()
    manager._compare_tuning_configurations(expected, existing, result)

    assert result.is_valid is False
    assert "lineitem" in result.extra_tables
    assert any("mismatch" in e for e in result.errors)


def test_clear_tunings_returns_true_when_no_table_exists(monkeypatch):
    manager = TuningMetadataManager(_Adapter("duckdb"))
    monkeypatch.setattr(manager, "_table_exists_check", lambda: False)
    assert manager.clear_tunings() is True


def test_get_metadata_summary_formats_query_result(monkeypatch):
    manager = TuningMetadataManager(_Adapter("duckdb"))
    monkeypatch.setattr(manager, "_table_exists_check", lambda: True)
    monkeypatch.setattr(
        manager,
        "_fetch_one",
        lambda _conn, _sql: (10, 2, 3, 1, datetime(2026, 1, 1), datetime(2026, 2, 1)),
    )

    summary = manager.get_metadata_summary()

    assert summary["table_exists"] is True
    assert summary["total_records"] == 10
    assert summary["unique_tables"] == 2


def test_execute_sql_falls_back_to_cursor_execution_without_adapter_execute_query():
    adapter = _Adapter("duckdb")
    manager = TuningMetadataManager(adapter)
    conn = _Conn(_Cursor(fetchall_data=[("ok",)]))

    rows = manager._execute_sql(conn, "SELECT 1")

    assert rows == [("ok",)]


def test_execute_sql_prefers_platform_adapter_execute_query_path():
    adapter = _Adapter("duckdb")
    adapter.execute_query = lambda _conn, _sql, _qid: {"result": [("adapter",)]}
    manager = TuningMetadataManager(adapter)

    rows = manager._execute_sql(_Conn(_Cursor()), "SELECT 1")
    assert rows == [("adapter",)]


def test_save_tunings_builds_and_batches_records(monkeypatch):
    manager = TuningMetadataManager(_Adapter("duckdb"))
    tunings = BenchmarkTunings("tpch")
    tunings.add_table_tuning(
        TableTuning(
            table_name="orders",
            partitioning=[_col("o_orderdate", 1)],
            sorting=[_col("o_orderkey", 2)],
        )
    )

    captured = {"records": None}
    monkeypatch.setattr(manager, "create_metadata_table", lambda: True)
    monkeypatch.setattr(manager, "clear_tunings", lambda _bn=None: True)
    monkeypatch.setattr(manager, "_batch_insert_records", lambda records: captured.__setitem__("records", records))

    assert manager.save_tunings(tunings) is True
    assert captured["records"] is not None
    assert len(captured["records"]) == 2
    assert {r.tuning_type for r in captured["records"]} == {
        TuningType.PARTITIONING.value,
        TuningType.SORTING.value,
    }


def test_save_tunings_short_circuits_when_metadata_table_fails(monkeypatch):
    manager = TuningMetadataManager(_Adapter("duckdb"))
    monkeypatch.setattr(manager, "create_metadata_table", lambda: False)
    assert manager.save_tunings(BenchmarkTunings("tpch")) is False


def test_save_unified_tunings_rejects_invalid_type(monkeypatch):
    manager = TuningMetadataManager(_Adapter("duckdb"))
    unified = UnifiedTuningConfiguration()
    monkeypatch.setattr(manager, "save_tunings", lambda _bt: True)
    assert manager.save_unified_tunings(unified) is True
    assert manager.save_unified_tunings(object()) is False


def test_load_tunings_paths(monkeypatch):
    manager = TuningMetadataManager(_Adapter("duckdb"))

    monkeypatch.setattr(manager, "_table_exists_check", lambda: False)
    assert manager.load_tunings() is None

    monkeypatch.setattr(manager, "_table_exists_check", lambda: True)
    monkeypatch.setattr(manager, "_fetch_all", lambda _conn, _sql: [])
    assert manager.load_tunings() is None

    rows = [
        ("orders", TuningType.SORTING.value, "o_orderkey", 1, "h", datetime.now(), "duckdb"),
    ]
    monkeypatch.setattr(manager, "_fetch_all", lambda _conn, _sql: rows)
    loaded = manager.load_tunings("tpch")
    assert loaded is not None
    assert loaded.get_table_tuning("orders") is not None


def test_validate_tunings_reports_missing_and_success(monkeypatch):
    manager = TuningMetadataManager(_Adapter("duckdb"))
    expected = BenchmarkTunings("tpch")
    expected.add_table_tuning(TableTuning(table_name="orders", sorting=[_col("o_orderkey", 1)]))

    monkeypatch.setattr(manager, "load_tunings", lambda _bn=None: None)
    missing = manager.validate_tunings(expected)
    assert missing.is_valid is False
    assert any("No tuning metadata found" in e for e in missing.errors)

    monkeypatch.setattr(manager, "load_tunings", lambda _bn=None: expected)
    ok = manager.validate_tunings(expected)
    assert ok.is_valid is True


def test_get_metadata_summary_handles_no_data_and_errors(monkeypatch):
    manager = TuningMetadataManager(_Adapter("duckdb"))
    monkeypatch.setattr(manager, "_table_exists_check", lambda: True)
    monkeypatch.setattr(manager, "_fetch_one", lambda _conn, _sql: None)
    assert manager.get_metadata_summary() == {"table_exists": True, "no_data": True}

    monkeypatch.setattr(manager, "_table_exists_check", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    summary = manager.get_metadata_summary()
    assert summary["table_exists"] is False
    assert "boom" in summary["error"]
