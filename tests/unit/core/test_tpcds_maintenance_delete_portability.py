"""Portable limited-DELETE coverage for TPC-DS maintenance operations.

Bare ``DELETE ... LIMIT`` is a syntax error on DuckDB and SQLite; it used to
be swallowed as a warning while the operation still reported success. These
tests run every delete operation against real local engines and prove the
reported row count equals the rows actually removed, and that a failing
statement fails the operation.
"""

import re
import sqlite3

import duckdb
import pytest

from benchbox.core.tpcds.maintenance_operations import (
    MaintenanceOperations,
    MaintenanceOperationType,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

CUTOFF_DATE_SK = 2450815
OLD_DATE_SK = 2450000
NEW_DATE_SK = 2452000

SALES_TABLES = {
    "STORE_SALES": "SS_SOLD_DATE_SK",
    "CATALOG_SALES": "CS_SOLD_DATE_SK",
    "WEB_SALES": "WS_SOLD_DATE_SK",
}
RETURNS_TABLES = {
    "STORE_RETURNS": "SR_RETURNED_DATE_SK",
    "CATALOG_RETURNS": "CR_RETURNED_DATE_SK",
    "WEB_RETURNS": "WR_RETURNED_DATE_SK",
}

# Every (operation, table) pair that must use a portable limited delete.
DELETE_OPERATION_TABLES = {
    MaintenanceOperationType.DELETE_OLD_SALES: SALES_TABLES,
    MaintenanceOperationType.DELETE_OLD_RETURNS: RETURNS_TABLES,
}

# A DELETE whose WHERE clause carries LIMIT outside a subquery (native
# MySQL-only form). The portable key-subquery form keeps LIMIT inside
# an IN (SELECT ...) predicate, so it never matches this pattern.
NATIVE_DELETE_LIMIT_RE = re.compile(r"DELETE\s+FROM\s+\w+\s+WHERE\s+[^();]*\bLIMIT\b", re.IGNORECASE)


def _make_engine(engine):
    if engine == "duckdb":
        return duckdb.connect()
    return sqlite3.connect(":memory:")


@pytest.fixture(params=["duckdb", "sqlite"])
def engine_connection(request):
    conn = _make_engine(request.param)
    yield request.param, conn
    conn.close()


def _seed_delete_tables(conn, tables, old_rows=5, new_rows=2):
    for table, date_column in tables.items():
        conn.execute(f"CREATE TABLE {table} ({date_column} INTEGER)")
        conn.executemany(
            f"INSERT INTO {table} ({date_column}) VALUES (?)",
            [(OLD_DATE_SK,)] * old_rows + [(NEW_DATE_SK,)] * new_rows,
        )


def _count_old_rows(conn, tables):
    return {
        table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} < {CUTOFF_DATE_SK}").fetchone()[0]
        for table, column in tables.items()
    }


@pytest.mark.parametrize("operation_type", list(DELETE_OPERATION_TABLES))
def test_delete_operation_removes_rows_it_reports(engine_connection, operation_type):
    """Each delete op removes exactly the rows it reports; newer rows are untouched."""
    _engine_name, conn = engine_connection
    tables = DELETE_OPERATION_TABLES[operation_type]
    _seed_delete_tables(conn, tables)

    ops = MaintenanceOperations()
    result = ops.execute_operation(conn, operation_type, estimated_rows=9)

    assert result.success is True
    # Per-table limit is 9 // 3 = 3, and each table holds 5 old rows.
    assert result.rows_affected == 9
    assert _count_old_rows(conn, tables) == dict.fromkeys(tables, 2)
    for table, column in tables.items():
        remaining_new = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} >= {CUTOFF_DATE_SK}").fetchone()[0]
        assert remaining_new == 2


def test_failed_delete_statement_fails_operation(engine_connection):
    """A delete against missing tables surfaces as a failed operation, not success."""
    _engine_name, conn = engine_connection

    ops = MaintenanceOperations()
    result = ops.execute_operation(conn, MaintenanceOperationType.DELETE_OLD_SALES, estimated_rows=9)

    assert result.success is False
    assert result.rows_affected == 0
    assert result.error_message


class _SQLiteRecordingConn:
    """Minimal connection double that records SQL and reports rowcounts.

    The class name intentionally contains "sqlite": dialect detection in
    MaintenanceOperations matches on the connection's module and type name,
    so this double exercises the rowid key-subquery path.
    """

    def __init__(self, rowcount=2):
        self.executed = []
        self._rowcount = rowcount

    def execute(self, sql, params=None):
        self.executed.append(sql)
        return self

    def fetchone(self):
        return (10,)

    @property
    def rowcount(self):
        return self._rowcount


@pytest.mark.parametrize("operation_type", list(DELETE_OPERATION_TABLES))
def test_delete_statements_use_portable_key_subquery_form(operation_type):
    """Enumerate every limited delete: all six target tables, none native LIMIT."""
    ops = MaintenanceOperations()
    conn = _SQLiteRecordingConn()
    handler = ops.operation_handlers[operation_type]
    deleted = handler(conn, 9)

    deletes = [sql for sql in conn.executed if sql.strip().upper().startswith("DELETE")]
    expected_tables = set(DELETE_OPERATION_TABLES[operation_type])
    assert {sql.split()[2] for sql in deletes} == expected_tables
    assert len(deletes) == len(expected_tables)
    for sql in deletes:
        assert "IN (SELECT" in sql.upper()
        assert NATIVE_DELETE_LIMIT_RE.search(sql) is None
    # Engine-reported rowcount is honored, never replaced by an estimate.
    assert deleted == 2 * len(expected_tables)


def test_rowid_column_per_dialect():
    """Per-dialect check: rowid/ctid mapping used by the portable delete form."""
    ops = MaintenanceOperations()
    duckdb_conn = _make_engine("duckdb")
    try:
        assert ops._get_delete_rowid_column(duckdb_conn) == "rowid"
    finally:
        duckdb_conn.close()
    sqlite_conn = _make_engine("sqlite")
    try:
        assert ops._get_delete_rowid_column(sqlite_conn) == "rowid"
    finally:
        sqlite_conn.close()
    # Unknown dialects fall back to native DELETE ... LIMIT (e.g. MySQL).
    assert ops._get_delete_rowid_column(object()) is None
