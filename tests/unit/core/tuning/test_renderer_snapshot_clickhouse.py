"""Before/after DDL snapshot test: ClickHouse dry-run preview vs. real execution.

Per the tuning-renderer-consolidation-and-baseline-policy-20260712 TODO
(w2, ADR-3 "single renderer"), dry-run preview
(`core/dryrun.py::DryRunExecutor._extract_ddl_preview`) and real execution
(`ClickHouseWorkloadMixin._optimize_table_definition`, via
`ClickHouseWorkloadMixin._resolve_tuned_ddl_clauses`) now call the same
`core.tuning.generators.clickhouse.ClickHouseDDLGenerator`. Before this
migration, tuned `table_tunings` (partitioning/sorting/clustering columns)
were rendered by dry-run preview but NEVER applied to the real schema --
`create_schema` only ran the engine-mandatory PK-derived-or-tuple() ORDER BY
fallback, regardless of tuning mode. This test proves the after-state:
tuned columns now render identically in both paths.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from benchbox.core.tuning.ddl_generator import get_ddl_generator
from benchbox.core.tuning.interface import TableTuning, TuningColumn
from benchbox.platforms.clickhouse.workload import ClickHouseWorkloadMixin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _preview_clauses(table_tuning: TableTuning):
    """Reproduce the dry-run preview call path (core/dryrun.py::_extract_ddl_preview)."""
    generator = get_ddl_generator("clickhouse")
    return generator.generate_tuning_clauses(table_tuning)


class _HostAdapter(ClickHouseWorkloadMixin):
    """Minimal host exposing just what _optimize_table_definition/_resolve_tuned_ddl_clauses need."""

    def __init__(self):
        self.logger = Mock()


class TestClickHousePreviewExecutionParity:
    """Dry-run preview and real schema-creation execution must render identical DDL."""

    def test_partitioning_and_sorting_render_identically(self):
        table_tuning = TableTuning(
            table_name="lineitem",
            partitioning=[TuningColumn(name="l_shipdate", type="DATE", order=1)],
            sorting=[TuningColumn(name="l_orderkey", type="INTEGER", order=1)],
        )
        table_tunings = {"lineitem": table_tuning}

        preview = _preview_clauses(table_tuning)
        assert preview.partition_by == "toYYYYMM(l_shipdate)"
        assert preview.sort_by == "l_orderkey"

        adapter = _HostAdapter()
        statement = "CREATE TABLE lineitem (l_orderkey INT, l_shipdate DATE)"
        rendered = adapter._optimize_table_definition(statement, table_tunings)

        assert f"PARTITION BY {preview.partition_by}" in rendered
        assert f"ORDER BY ({preview.sort_by})" in rendered

    def test_no_table_tuning_falls_back_to_engine_mandatory_baseline(self):
        """A table absent from table_tunings still gets the ORDER BY tuple() fallback."""
        adapter = _HostAdapter()
        statement = "CREATE TABLE untuned_table (id INT)"

        rendered = adapter._optimize_table_definition(statement, {"lineitem": Mock()})

        assert "ORDER BY tuple()" in rendered

    def test_tuning_disabled_falls_back_to_engine_mandatory_baseline(self):
        """create_schema passes table_tunings=None when tuning is disabled; baseline fallback applies."""
        adapter = _HostAdapter()
        statement = "CREATE TABLE lineitem (l_orderkey INT PRIMARY KEY, l_shipdate DATE)"

        rendered = adapter._optimize_table_definition(statement, None)

        assert "ORDER BY (l_orderkey)" in rendered
        assert "PARTITION BY" not in rendered
