"""Regression tests for TPC-DI ingest dtype stability on pandas 3.x.

pandas 3 defaults to microsecond resolution for inferred datetimes (vs.
nanoseconds on 2.x). The TPC-DI file transforms must keep date-like payloads
as text through ingest: downstream loads treat them as strings, and a silent
datetime64 inference would change stored values. These tests pin the ingest
dtypes for the CSV, fixed-width, and JSON transform paths.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from benchbox.core.tpcdi.benchmark import TPCDIBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_benchmark(tmp_path: Path) -> TPCDIBenchmark:
    return TPCDIBenchmark(scale_factor=0.01, output_dir=tmp_path, max_workers=1)


def test_csv_transform_keeps_text_columns_as_strings(tmp_path: Path) -> None:
    benchmark = _make_benchmark(tmp_path)
    source = tmp_path / "trade_history.csv"
    source.write_text(
        "TradeID,Symbol,TradeDate,Quantity\n1,AAA,2023-01-15,100\n2,BBB,2023-01-16,200\n",
        encoding="utf-8",
    )

    result = benchmark._transform_csv_file(str(source), "historical")

    frame = result["dataframe"]
    assert result["records_processed"] == 2
    assert str(frame["TradeDate"].dtype) in {"str", "string", "object"}
    assert frame["TradeDate"].tolist() == ["2023-01-15", "2023-01-16"]


def test_fixed_width_transform_keeps_text_columns_as_strings(tmp_path: Path) -> None:
    benchmark = _make_benchmark(tmp_path)
    source = tmp_path / "securities.dat"
    source.write_text("AAA11111exch1name 100\nBBB22222exch2name 200\n", encoding="utf-8")

    result = benchmark._transform_fixed_width_file(str(source), "historical")

    frame = result["dataframe"]
    assert result["records_processed"] == 2
    assert str(frame["symbol"].dtype) in {"str", "string", "object"}


def test_json_transform_keeps_opening_date_as_string(tmp_path: Path) -> None:
    benchmark = _make_benchmark(tmp_path)
    source = tmp_path / "accounts.json"
    source.write_text(
        '[{"account_id": 1, "customer_id": 101, "opening_date": "2023-01-01", "status": "Active"},'
        ' {"account_id": 2, "customer_id": 102, "opening_date": "2023-02-01", "status": "Active"}]',
        encoding="utf-8",
    )

    result = benchmark._transform_json_file(str(source), "historical")

    frame = result["dataframe"]
    assert result["records_processed"] == 2
    assert str(frame["opening_date"].dtype) in {"str", "string", "object"}
    assert frame["opening_date"].tolist() == ["2023-01-01", "2023-02-01"]


def test_pandas_major_version_is_declared() -> None:
    assert int(pd.__version__.split(".")[0]) >= 2
