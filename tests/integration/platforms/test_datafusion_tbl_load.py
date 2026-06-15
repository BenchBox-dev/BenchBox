"""Regression test: DataFusionAdapter ingests trailing-delimiter TPC-H .tbl files.

Raw TPC-H ``.tbl`` (and TPC-DS ``.dat``) data files use a field-TERMINATING
delimiter: a row of N values ends with a trailing ``|`` and so splits into N+1
fields. Both of ``DataFusionAdapter.load_data``'s paths used to reject this (the
CSV->Parquet path read with the bare schema column count and errored on the extra
field; the CREATE EXTERNAL TABLE path has no ignore-trailing-delimiter option).
This test loads real TPC-H ``.tbl`` through the adapter for BOTH ``data_format``
values and asserts correct row counts and that the trailing dummy column never
leaks into a registered table's schema.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.utils.file_format import TRAILING_DUMMY_COLUMN

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]

_TPCH_TABLES = ("lineitem", "orders", "partsupp", "part", "customer", "supplier", "nation", "region")
_LINEITEM_COLUMN_COUNT = 16


@pytest.fixture(scope="module")
def tpch_tbl_dir(tmp_path_factory):
    """Generate real TPC-H .tbl data at a tiny scale ONCE for the parametrized loads."""
    from benchbox.core.tpch.generator import TPCHDataGenerator

    output_dir = tmp_path_factory.mktemp("datafusion_tbl_load")
    generated = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir).generate()
    return next(Path(paths[0] if isinstance(paths, list) else paths).parent for paths in generated.values())


@pytest.mark.parametrize("data_format", ["parquet", "csv"])
def test_datafusion_loads_trailing_delimiter_tbl(tpch_tbl_dir, tmp_path, data_format):
    """Real TPC-H .tbl loads on both formats with correct counts and no leaked column."""
    pytest.importorskip("datafusion", reason="DataFusion not installed")

    from benchbox import TPCH
    from benchbox.platforms.datafusion import DataFusionAdapter

    benchmark = TPCH(scale_factor=0.01)
    adapter = DataFusionAdapter(working_dir=str(tmp_path / f"wd_{data_format}"), data_format=data_format)
    connection = adapter.create_connection()
    adapter.create_schema(benchmark, connection)

    table_stats, _, _ = adapter.load_data(benchmark, connection, tpch_tbl_dir)

    for table in _TPCH_TABLES:
        assert table_stats.get(table, 0) > 0, f"{table} loaded 0 rows under {data_format}: {table_stats}"

    # The trailing dummy column must never leak into a registered table's schema,
    # and the real column count must be exact (no extra/shifted columns).
    columns = [
        row[0]
        for row in connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'lineitem'"
        ).fetchall()
    ]
    assert TRAILING_DUMMY_COLUMN not in columns, f"dummy column leaked under {data_format}: {columns}"
    assert len(columns) == _LINEITEM_COLUMN_COUNT, f"unexpected lineitem schema under {data_format}: {columns}"

    # The registered row count is queryable and matches the reported load stats.
    queried = connection.execute("SELECT COUNT(*) FROM lineitem").fetchall()[0][0]
    assert queried == table_stats["lineitem"]
