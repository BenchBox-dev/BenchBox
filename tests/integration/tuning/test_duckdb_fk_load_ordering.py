"""Regression coverage for the tuning FK load-ordering defect.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.

Background (tuning-fk-load-ordering-fix-20260716): once a tuning
configuration's ``foreign_keys.enabled: true`` actually reaches the DuckDB
adapter's constraint-application path, loading TPC-H with the shipped
``examples/tunings/duckdb/tpch_tuned.yaml`` template fails, because
``benchbox/platforms/base/data_loading.py::DataLoader._load_file_based_data``
falls back to *alphabetical* table order when the benchmark has no
``get_table_loading_order`` method -- and alphabetical order loads
``lineitem`` before ``orders``/``part``/``supplier`` (and other FK
violations), which a real FK-enforcing engine rejects.

At the time this defect was found, develop did not yet contain PR #1176's
tuning-delivery fix, so the CLI path (``benchbox run --tuning
tpch_tuned.yaml``) never actually turned on FK enforcement in the adapter
(confirmed separately via ``-vv`` logs: "Schema constraints - Primary keys:
False, Foreign keys: False" even with ``foreign_keys.enabled: true`` in the
YAML). This test bypasses that separate delivery gap by setting
``adapter.unified_tuning_configuration`` directly -- the same attribute
``PlatformAdapter.get_effective_tuning_configuration()`` reads -- which is
the actual constraint-application entry point used by
``DuckDBAdapter.create_schema`` / ``apply_constraint_configuration``. The
load-ordering defect this reproduces is present regardless of the delivery
fix's merge status.

The fix is FK-aware load ordering (``TPCHBenchmark.get_table_loading_order``,
backed by ``benchbox.core.tpch.schema.get_table_loading_order``, a stable
topological sort over the schema's own FK metadata via
``benchbox.core.schema_primitives.get_fk_ordered_table_names``) rather than
post-load ``ALTER TABLE ... ADD FOREIGN KEY``: DuckDB (the affected engine)
does not support adding foreign-key constraints via ``ALTER TABLE`` on an
existing table ("No support for that ALTER TABLE option yet!"), so the
"portable default" post-load-ALTER strategy from the TODO would not work
here anyway. Ordering is also the smaller diff -- constraint application
stays exactly where it already was (schema-creation time), so it needs no
new phase-metadata plumbing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tuning.interface import UnifiedTuningConfiguration
from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]

_SCALE_FACTOR = 0.01


def _fk_enabled_tuning_config() -> UnifiedTuningConfiguration:
    return UnifiedTuningConfiguration.from_dict(
        {
            "primary_keys": {"enabled": True},
            "foreign_keys": {"enabled": True, "enforce_referential_integrity": True},
        }
    )


@pytest.fixture(scope="module")
def tpch_fk_enforced_duckdb(tmp_path_factory: pytest.TempPathFactory):
    """Real DuckDB DB with TPC-H SF 0.01 data, FK enforcement forced on.

    Module-scoped: schema + load happen once and every test in this module
    exercises the same loaded database.
    """
    base = tmp_path_factory.mktemp("tpch_fk_load_order")
    db_path = str(base / "tpch.duckdb")
    adapter = DuckDBAdapter(database_path=db_path)
    adapter.unified_tuning_configuration = _fk_enabled_tuning_config()

    conn = adapter.create_connection()
    bench = TPCHBenchmark(scale_factor=_SCALE_FACTOR, output_dir=str(base / "data"))
    bench.generate_data()

    adapter.create_schema(bench, conn)
    table_stats, _duration, _extra = adapter.load_data(bench, conn, Path(base / "data"))

    yield adapter, bench, conn, table_stats
    conn.close()


def test_fk_enforced_tuned_load_completes_for_every_table(tpch_fk_enforced_duckdb):
    """The full tuned load must succeed with nonzero rows in every table.

    Before the fix, loading in alphabetical order under FK enforcement left
    every table except the two with no FK dependencies (``part``,
    ``region``) at 0 rows because their INSERT was rejected by DuckDB's FK
    constraint check.
    """
    _adapter, _bench, _conn, table_stats = tpch_fk_enforced_duckdb

    expected_tables = {"region", "nation", "supplier", "part", "partsupp", "customer", "orders", "lineitem"}
    assert set(table_stats) == expected_tables
    for table_name, row_count in table_stats.items():
        assert row_count > 0, f"table {table_name} loaded 0 rows (FK violation would zero it out)"

    # Spot-check the specific pair the original bug report called out.
    assert table_stats["orders"] == 15_000
    assert table_stats["lineitem"] > 0


def test_fk_constraint_is_actually_enforced_after_load(tpch_fk_enforced_duckdb):
    """The fix must not silently disable FK enforcement to make the run pass.

    Inserting an orders row that references a nonexistent customer must
    still be rejected post-load -- proving the constraint is real, not
    dropped or stripped, per the TODO's must_preserve/anti_patterns.
    """
    _adapter, _bench, conn, _table_stats = tpch_fk_enforced_duckdb

    with pytest.raises(Exception, match="[Ff]oreign key"):
        conn.execute(
            "INSERT INTO orders (o_orderkey, o_custkey, o_orderstatus, o_totalprice, "
            "o_orderdate, o_orderpriority, o_clerk, o_shippriority, o_comment) "
            "VALUES (999999999, 999999999, 'O', 1.0, '2026-01-01', '1-URGENT', 'Clerk#1', 0, 'x')"
        )


def test_table_loading_order_used_by_the_loader_is_fk_safe(tpch_fk_enforced_duckdb):
    """Directly verify the order DataLoader would use is dependency-safe.

    Mirrors benchbox/platforms/base/data_loading.py::_load_file_based_data's
    own lookup (``benchmark.get_table_loading_order(list(data_files.keys()))``).
    """
    _adapter, bench, _conn, table_stats = tpch_fk_enforced_duckdb

    order = bench.get_table_loading_order(list(table_stats.keys()))
    position = {name: i for i, name in enumerate(order)}

    assert position["region"] < position["nation"]
    assert position["nation"] < position["customer"]
    assert position["nation"] < position["supplier"]
    assert position["customer"] < position["orders"]
    assert position["orders"] < position["lineitem"]
    assert position["part"] < position["lineitem"]
    assert position["supplier"] < position["lineitem"]
    assert position["part"] < position["partsupp"]
    assert position["supplier"] < position["partsupp"]
