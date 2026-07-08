"""Regression: DataFusion ingests trailing-delimiter .tbl chunks (compressed/sharded).

Raw TPC-H ``.tbl`` (and TPC-DS ``.dat``) rows use a field-TERMINATING delimiter:
a row of N values ends with a trailing ``|`` and so splits into N+1 fields. PR #810
taught the DataFusion adapters to tolerate that by reading with a dummy column and
projecting it away — but it gated detection on ``Path(...).suffix in {".tbl", ".dat"}``.
That suffix is only ``.tbl``/``.dat`` for a *bare, uncompressed, single* file. Real
dbgen output is compressed and/or shard-numbered, so the gate silently failed for:

    customer.tbl.zst      -> Path.suffix == ".zst"
    customer.tbl.1        -> Path.suffix == ".1"
    customer.tbl.1.zst    -> Path.suffix == ".zst"

and DataFusion raised ``CSV parse error: Expected 8 columns, got 9`` on those chunks
while the bare ``customer.tbl`` loaded fine. This bit CI only on Linux, where the
bundled dbgen emits trailing pipes (the macOS binary happens to be built with
``-DEOL_HANDLING`` and does not), so the failure did not reproduce on macOS.

The fix resolves the *base* data extension (transparent to compression and shard
numbers) instead of ``Path.suffix``. These tests use synthetic trailing-pipe fixtures
— independent of which platform's dbgen is bundled — so the regression reproduces on
any host. Both the SQL (``DataFusionAdapter``) and DataFrame
(``DataFusionDataFrameAdapter``) paths are covered across all four naming variants.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.utils.compression import CompressionManager
from benchbox.utils.file_format import TRAILING_DUMMY_COLUMN

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# TPC-H customer has 8 columns; the reported failure is "Expected 8 columns, got 9".
_CUSTOMER_COLUMNS = [
    "c_custkey",
    "c_name",
    "c_address",
    "c_nationkey",
    "c_phone",
    "c_acctbal",
    "c_mktsegment",
    "c_comment",
]
# Two rows, each with a TRAILING pipe: 8 values -> 9 fields after split.
_TRAILING_ROWS = (
    "1|Customer#000000001|IVhzIApeRb|15|25-989-741-2988|711.56|BUILDING|regular accounts|\n"
    "2|Customer#000000002|XSTf4NCwDV|13|23-768-687-3665|121.65|AUTOMOBILE|ironic requests|\n"
)


def _write_variant(dir_path: Path, filename: str) -> Path:
    """Write the trailing-pipe customer rows under ``filename``, zstd-compressing .zst."""
    path = dir_path / filename
    if filename.endswith(".zst"):
        compressor = CompressionManager().get_compressor("zstd")
        with compressor.open_for_write(path, "wt") as handle:
            handle.write(_TRAILING_ROWS)
    else:
        path.write_text(_TRAILING_ROWS)
    return path


# The four on-disk names real generation produces. Bare .tbl is the #810 control;
# the other three are the chunked/compressed names that regressed.
_VARIANTS = [
    "customer.tbl",
    "customer.tbl.zst",
    "customer.tbl.1",
    "customer.tbl.1.zst",
]


try:
    import pyarrow as pa  # noqa: F401
    import pyarrow.parquet as pq

    _PYARROW = True
except ImportError:  # pragma: no cover - pyarrow is a hard dependency in practice
    _PYARROW = False

try:
    import datafusion  # noqa: F401

    from benchbox.platforms.dataframe.datafusion_df import (
        DATAFUSION_DF_AVAILABLE,
        DataFusionDataFrameAdapter,
    )
except ImportError:
    DATAFUSION_DF_AVAILABLE = False


@pytest.mark.skipif(not _PYARROW, reason="pyarrow not installed")
@pytest.mark.parametrize("filename", _VARIANTS)
def test_sql_adapter_loads_trailing_delimiter_chunk(tmp_path, filename):
    """SQL CSV->Parquet path loads trailing-pipe chunks without the dummy column leaking."""
    from benchbox.platforms.datafusion import DataFusionAdapter

    data_path = _write_variant(tmp_path, filename)

    mock_benchmark = Mock()
    mock_benchmark.__class__.__name__ = "TPCHBenchmark"
    mock_benchmark.get_schema.return_value = {
        "customer": {
            "name": "customer",
            "columns": [{"name": name, "type": "VARCHAR"} for name in _CUSTOMER_COLUMNS],
        }
    }

    with patch("benchbox.platforms.datafusion.SessionContext"):
        adapter = DataFusionAdapter(working_dir=str(tmp_path / "wd"), data_format="parquet")
        with (
            patch.object(adapter, "_get_constraint_configuration", return_value=(False, False)),
            patch.object(adapter, "_log_constraint_configuration"),
        ):
            adapter.create_schema(mock_benchmark, Mock())

        # Mock connection: register_parquet is a no-op capture; the real work
        # (the pyarrow CSV read that used to raise "Expected 8 columns, got 9")
        # happens inside _convert_and_register_parquet before registration.
        row_count = adapter._load_table_parquet(Mock(), "customer", [data_path], tmp_path)

    assert row_count == 2, f"{filename}: expected 2 rows, got {row_count}"

    written = adapter.working_dir / "customer.parquet"
    schema = pq.read_schema(written)
    assert TRAILING_DUMMY_COLUMN not in schema.names, f"{filename}: dummy column leaked: {schema.names}"
    assert len(schema.names) == len(_CUSTOMER_COLUMNS), f"{filename}: wrong column count: {schema.names}"


@pytest.mark.skipif(not DATAFUSION_DF_AVAILABLE, reason="DataFusion not installed")
@pytest.mark.parametrize("filename", _VARIANTS)
def test_dataframe_adapter_reads_trailing_delimiter_chunk(tmp_path, filename):
    """DataFrame read_csv loads trailing-pipe chunks with correct shape, no dummy column."""
    data_path = _write_variant(tmp_path, filename)

    adapter = DataFusionDataFrameAdapter()
    df = adapter.read_csv(
        data_path,
        delimiter="|",
        has_header=False,
        column_names=_CUSTOMER_COLUMNS,
    )
    result = adapter.collect(df)

    assert result.num_rows == 2, f"{filename}: expected 2 rows, got {result.num_rows}"
    assert result.column_names == _CUSTOMER_COLUMNS, f"{filename}: wrong columns: {result.column_names}"
    assert TRAILING_DUMMY_COLUMN not in result.column_names, f"{filename}: dummy column leaked"
