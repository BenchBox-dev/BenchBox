from __future__ import annotations

import duckdb
import pytest

from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tuning.applied_ledger import (
    APPLIED_UNVERIFIED,
    APPLIED_VERIFIED,
    PHASE_DDL,
    AppliedTuningLedger,
    recording_connection,
)
from benchbox.core.tuning.interface import TableTuning, TuningColumn, UnifiedTuningConfiguration
from benchbox.core.tuning.introspection import (
    BOUND_EXPRESSION_DIFF_NOTE,
    CORROBORATED,
    MISMATCH,
    corroborate,
)
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.platforms.duckdb_introspection import DuckDBTuningIntrospector

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture
def schema_connection(tmp_path):
    connection = duckdb.connect(":memory:")
    adapter = DuckDBAdapter()
    adapter.create_schema(TPCHBenchmark(scale_factor=0.01, output_dir=tmp_path), connection)
    adapter.tuning_enabled = True
    adapter._applied_tuning_ledger = AppliedTuningLedger()
    adapter._applied_layout_operations = []
    return adapter, connection


def _sort_config() -> UnifiedTuningConfiguration:
    config = UnifiedTuningConfiguration()
    config.table_tunings["LINEITEM"] = TableTuning(
        table_name="LINEITEM",
        sorting=[
            TuningColumn(name="L_ORDERKEY", type="INTEGER", order=1),
            TuningColumn(name="L_LINENUMBER", type="INTEGER", order=2),
        ],
    )
    config.table_tunings["ORDERS"] = TableTuning(
        table_name="ORDERS",
        sorting=[
            TuningColumn(name="O_ORDERDATE", type="DATE", order=1),
            TuningColumn(name="O_ORDERKEY", type="INTEGER", order=2),
        ],
    )
    return config


def _catalog_tables(connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT table_name FROM duckdb_tables()").fetchall()}


class TestDuckDBPhysicalIdentifiers:
    def test_logical_table_resolves_to_what_create_schema_made(self, schema_connection):
        adapter, connection = schema_connection
        tables = _catalog_tables(connection)
        for logical in ("LINEITEM", "lineitem", "Orders"):
            assert adapter.resolve_physical_table(logical, connection) in tables

    def test_logical_column_resolves_to_what_create_schema_made(self, schema_connection):
        adapter, connection = schema_connection
        columns = {row[0] for row in connection.execute("SELECT column_name FROM duckdb_columns()").fetchall()}
        for logical in ("L_ORDERKEY", "l_linenumber"):
            assert adapter.resolve_physical_column("LINEITEM", logical, connection) in columns

    def test_resolution_without_a_catalog_follows_the_adapter_policy(self):
        adapter = DuckDBAdapter()
        assert adapter.resolve_physical_table("LINEITEM") == "lineitem"
        assert adapter.resolve_physical_column("LINEITEM", "L_ORDERKEY") == "l_orderkey"

    def test_index_ddl_stores_bare_identifiers_in_the_catalog(self, schema_connection):
        adapter, connection = schema_connection
        adapter.apply_unified_tuning(_sort_config(), connection)
        expressions = {
            row[0]: row[1]
            for row in connection.execute("SELECT index_name, expressions FROM duckdb_indexes()").fetchall()
        }
        assert expressions["idx_lineitem_sort"] == "[l_orderkey, l_linenumber]"
        assert expressions["idx_orders_sort"] == "[o_orderdate, o_orderkey]"

    def test_sort_only_config_reaches_applied_verified_without_mismatch(self, schema_connection):
        adapter, connection = schema_connection
        ledger = adapter._applied_tuning_ledger
        adapter.apply_unified_tuning(_sort_config(), recording_connection(connection, ledger, PHASE_DDL))
        receipt = corroborate(ledger, DuckDBTuningIntrospector().introspect(connection, ledger))
        assert receipt.corroborated
        assert {entry.verdict for entry in receipt.entries} == {CORROBORATED}
        status, payload = adapter._corroborate_applied_ledger(connection, APPLIED_UNVERIFIED)
        assert status == APPLIED_VERIFIED
        assert payload["corroborated"] is True

    def test_bound_form_catalog_fact_is_still_a_mismatch_with_explicit_diff(self, schema_connection):
        _, connection = schema_connection
        ledger = AppliedTuningLedger()
        statement = "CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)"
        recording_connection(connection, ledger, PHASE_DDL).execute(statement)
        stored = connection.execute(
            "SELECT expressions FROM duckdb_indexes() WHERE index_name = 'idx_lineitem_sort'"
        ).fetchone()[0]
        assert "LINEITEM.L_ORDERKEY" in stored

        receipt = corroborate(ledger, DuckDBTuningIntrospector().introspect(connection, ledger))

        assert not receipt.corroborated
        [entry] = receipt.entries
        assert entry.verdict == MISMATCH
        assert BOUND_EXPRESSION_DIFF_NOTE in entry.diff

    def test_unbound_mismatch_does_not_claim_a_bound_expression(self, schema_connection):
        _, connection = schema_connection
        ledger = AppliedTuningLedger()
        connection.execute('CREATE INDEX idx_lineitem_sort ON "lineitem" ("l_partkey")')
        recording_connection(connection, ledger, PHASE_DDL).execute(
            'CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON "lineitem" ("l_orderkey")'
        )
        receipt = corroborate(ledger, DuckDBTuningIntrospector().introspect(connection, ledger))
        [entry] = receipt.entries
        assert entry.verdict == MISMATCH
        assert BOUND_EXPRESSION_DIFF_NOTE not in entry.diff
