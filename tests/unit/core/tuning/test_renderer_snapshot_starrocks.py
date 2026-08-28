"""Before/after DDL snapshot test: StarRocks dry-run preview vs. real execution.

Per the StarRocks DDL-generator migration (ADR-3 "single renderer"), dry-run
preview (``core/dryrun.py::DryRunExecutor._extract_ddl_preview``) and real
execution (``StarRocksWorkloadMixin._optimize_table_definition``, via
``StarRocksWorkloadMixin._resolve_tuned_ddl_clauses``) now call the same
``core.tuning.generators.starrocks.StarRocksDDLGenerator``. Before this
migration, tuned ``table_tunings`` (partitioning/sorting/distribution columns)
were rendered by dry-run preview but NEVER applied to the real schema --
``create_schema`` only ran the engine-mandatory ``DISTRIBUTED BY HASH(
<first_column>)`` injection, regardless of tuning mode. This test proves the
after-state: tuned columns now render identically in both paths, and the
untuned baseline is unchanged (byte-identical).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from benchbox.core.tuning.ddl_generator import get_ddl_generator
from benchbox.core.tuning.interface import TableTuning, TuningColumn
from benchbox.platforms.starrocks.workload import StarRocksWorkloadMixin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _preview_clauses(table_tuning: TableTuning):
    """Reproduce the dry-run preview call path (core/dryrun.py::_extract_ddl_preview)."""
    generator = get_ddl_generator("starrocks")
    return generator.generate_tuning_clauses(table_tuning)


class _HostAdapter(StarRocksWorkloadMixin):
    """Minimal host exposing just what _optimize_table_definition needs."""

    def __init__(self):
        self.logger = Mock()


# The exact untuned baseline DDL the adapter emitted before this migration.
# Pinned byte-for-byte so any regression in the engine-mandatory path fails here.
_BASELINE_REGION_DDL = (
    "CREATE TABLE region (r_regionkey INT, r_name VARCHAR(25))\n"
    "DUPLICATE KEY(`r_regionkey`)\n"
    "DISTRIBUTED BY HASH(`r_regionkey`) BUCKETS 8"
)


class TestStarRocksEngineMandatoryBaselineUnchanged:
    """Untuned CREATE TABLE must keep the historical DISTRIBUTED BY HASH baseline."""

    def test_untuned_output_is_byte_identical(self):
        adapter = _HostAdapter()
        statement = "CREATE TABLE region (r_regionkey INT, r_name VARCHAR(25))"
        assert adapter._optimize_table_definition(statement, None) == _BASELINE_REGION_DDL

    def test_tuning_disabled_passes_none_and_gets_baseline(self):
        """create_schema passes table_tunings=None when tuning is disabled."""
        adapter = _HostAdapter()
        statement = "CREATE TABLE lineitem (l_orderkey INT, l_shipdate DATE)"
        rendered = adapter._optimize_table_definition(statement, None)
        assert "DISTRIBUTED BY HASH(`l_orderkey`) BUCKETS 8" in rendered
        assert "PARTITION BY" not in rendered
        assert rendered.count("DISTRIBUTED BY") == 1

    def test_table_absent_from_tunings_gets_baseline(self):
        adapter = _HostAdapter()
        statement = "CREATE TABLE untuned_table (id INT, payload VARCHAR(20))"
        rendered = adapter._optimize_table_definition(statement, {"lineitem": Mock()})
        assert "DISTRIBUTED BY HASH(`id`) BUCKETS 8" in rendered
        assert "PARTITION BY" not in rendered
        assert rendered.count("DISTRIBUTED BY") == 1


class TestStarRocksPreviewExecutionParity:
    """Dry-run preview and real schema-creation execution must render identical clauses."""

    def test_partitioning_distribution_and_sorting_render_identically(self):
        table_tuning = TableTuning(
            table_name="lineitem",
            distribution=[TuningColumn(name="l_orderkey", type="INTEGER", order=1)],
            partitioning=[TuningColumn(name="l_shipdate", type="DATE", order=1)],
            sorting=[TuningColumn(name="l_linenumber", type="INTEGER", order=1)],
        )
        table_tunings = {"lineitem": table_tuning}

        preview = _preview_clauses(table_tuning)
        assert preview.partition_by == "l_shipdate"
        assert preview.distribute_by == "l_orderkey"
        assert preview.order_by == "l_linenumber"
        assert preview.additional_clauses == ["DISTRIBUTED BY HASH(`l_orderkey`) BUCKETS 8"]

        adapter = _HostAdapter()
        statement = "CREATE TABLE lineitem (l_orderkey INT, l_linenumber INT, l_shipdate DATE)"
        rendered = adapter._optimize_table_definition(statement, table_tunings)

        # Execution emits exactly the preview clause strings.
        assert f"PARTITION BY ({preview.partition_by})" in rendered
        assert preview.additional_clauses[0] in rendered
        assert f"ORDER BY ({preview.order_by})" in rendered

        # No duplicate DISTRIBUTED BY, and StarRocks clause order is preserved.
        assert rendered.count("DISTRIBUTED BY") == 1
        assert rendered.index("PARTITION BY") < rendered.index("DISTRIBUTED BY") < rendered.index("ORDER BY")

    def test_tuned_distribution_overrides_first_column_in_execution(self):
        table_tuning = TableTuning(
            table_name="orders",
            distribution=[TuningColumn(name="o_custkey", type="INTEGER", order=1)],
        )
        preview = _preview_clauses(table_tuning)
        assert preview.distribute_by == "o_custkey"

        adapter = _HostAdapter()
        statement = "CREATE TABLE orders (o_orderkey INT, o_custkey INT, o_orderdate DATE)"
        rendered = adapter._optimize_table_definition(statement, {"orders": table_tuning})

        assert "DISTRIBUTED BY HASH(`o_custkey`) BUCKETS 8" in rendered
        # The first column (o_orderkey) is still the key-model column, but is NOT
        # used as the hash key when a tuned distribution column is configured.
        assert "HASH(`o_orderkey`)" not in rendered
        assert rendered.count("DISTRIBUTED BY") == 1

    def test_case_insensitive_table_lookup(self):
        """Shipped tuning templates key tables uppercase; benchmark DDL is lowercase."""
        table_tuning = TableTuning(
            table_name="LINEITEM",
            distribution=[TuningColumn(name="l_orderkey", type="INTEGER", order=1)],
        )
        adapter = _HostAdapter()
        statement = "CREATE TABLE lineitem (l_orderkey INT, l_shipdate DATE)"
        rendered = adapter._optimize_table_definition(statement, {"LINEITEM": table_tuning})
        assert "DISTRIBUTED BY HASH(`l_orderkey`) BUCKETS 8" in rendered


class TestStarRocksAppliedLedgerInstrumentation:
    """w4: rendered tuned clauses are recorded into the applied-tuning ledger so a
    tuned StarRocks run reports ``applied_unverified`` rather than ``noop``."""

    def _host_with_ledger(self):
        from benchbox.core.tuning.applied_ledger import AppliedTuningLedger

        adapter = _HostAdapter()
        adapter._applied_tuning_ledger = AppliedTuningLedger()
        return adapter

    def test_tuned_clauses_recorded_with_mechanism_and_table(self):
        from benchbox.core.tuning.applied_ledger import APPLIED_UNVERIFIED, PHASE_DDL

        adapter = self._host_with_ledger()
        table_tuning = TableTuning(
            table_name="lineitem",
            distribution=[TuningColumn(name="l_orderkey", type="INTEGER", order=1)],
            partitioning=[TuningColumn(name="l_shipdate", type="DATE", order=1)],
            sorting=[TuningColumn(name="l_linenumber", type="INTEGER", order=1)],
        )
        statement = "CREATE TABLE lineitem (l_orderkey INT, l_linenumber INT, l_shipdate DATE)"
        adapter._optimize_table_definition(statement, {"lineitem": table_tuning})

        ledger = adapter._applied_tuning_ledger
        recorded = [s.statement for s in ledger.statements]
        assert "PARTITION BY (l_shipdate)" in recorded
        assert "DISTRIBUTED BY HASH(`l_orderkey`) BUCKETS 8" in recorded
        assert "ORDER BY (l_linenumber)" in recorded
        assert all(s.phase == PHASE_DDL and s.mechanism == "starrocks_ddl_generator" for s in ledger.statements)
        assert all(s.table == "lineitem" for s in ledger.statements)
        # A tuned run is now honestly applied_unverified, not noop.
        assert ledger.overall_status(tuning_enabled=True, has_config=True) == APPLIED_UNVERIFIED

    def test_untuned_records_nothing(self):
        adapter = self._host_with_ledger()
        statement = "CREATE TABLE region (r_regionkey INT, r_name VARCHAR(25))"
        # table_tunings=None -> engine-mandatory baseline only, no tuning recorded.
        adapter._optimize_table_definition(statement, None)
        assert adapter._applied_tuning_ledger.is_empty()

    def test_engine_mandatory_distribution_not_recorded_as_tuning(self):
        """A tuned table with partition/sort but no explicit distribution column
        falls back to the first-column DISTRIBUTED BY baseline; that baseline is
        engine-mandatory, not a tuning choice, so it must NOT be recorded."""
        adapter = self._host_with_ledger()
        table_tuning = TableTuning(
            table_name="lineitem",
            partitioning=[TuningColumn(name="l_shipdate", type="DATE", order=1)],
        )
        statement = "CREATE TABLE lineitem (l_orderkey INT, l_shipdate DATE)"
        adapter._optimize_table_definition(statement, {"lineitem": table_tuning})
        recorded = [s.statement for s in adapter._applied_tuning_ledger.statements]
        assert recorded == ["PARTITION BY (l_shipdate)"]  # baseline distribution excluded

    def test_no_ledger_attribute_is_a_safe_noop(self):
        """Capture must never break a run: a host with no ledger renders normally."""
        adapter = _HostAdapter()  # no _applied_tuning_ledger
        table_tuning = TableTuning(
            table_name="lineitem",
            distribution=[TuningColumn(name="l_orderkey", type="INTEGER", order=1)],
        )
        statement = "CREATE TABLE lineitem (l_orderkey INT)"
        rendered = adapter._optimize_table_definition(statement, {"lineitem": table_tuning})
        assert "DISTRIBUTED BY HASH(`l_orderkey`) BUCKETS 8" in rendered
