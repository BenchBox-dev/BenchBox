"""CSV-direct empty-string/null semantics for DataFrame adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benchbox.platforms.dataframe.benchmark_mixin import DataFrameRunOptions
from benchbox.platforms.dataframe.datafusion_df import DATAFUSION_DF_AVAILABLE, DataFusionDataFrameAdapter
from benchbox.platforms.dataframe.pyspark_df import PYSPARK_AVAILABLE, PySparkDataFrameAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


class _CsvNullMarkerBenchmark:
    name = "csv_null_marker_fixture"
    display_name = "CSV Null Marker Fixture"
    scale_factor = 0.01
    csv_delimiter = ","
    csv_has_header = True

    def __init__(self, csv_path: Path, null_marker: str | None) -> None:
        self.csv_null_marker = null_marker
        self.tables = {"events": csv_path}

    def get_schema(self) -> dict[str, dict[str, list[dict[str, str]]]]:
        return {
            "events": {
                "columns": [
                    {"name": "id", "type": "INTEGER"},
                    {"name": "phrase", "type": "VARCHAR"},
                ]
            }
        }


def _write_events_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "events.csv"
    csv_path.write_text("id,phrase\n1,\n2,abc\n", encoding="utf-8")
    return csv_path


def _load_phrase_values(adapter: Any, csv_path: Path, null_marker: str | None) -> list[Any]:
    benchmark = _CsvNullMarkerBenchmark(csv_path, null_marker)
    ctx = adapter.load_benchmark_into_context(
        benchmark,
        csv_path.parent,
        options=DataFrameRunOptions(prefer_parquet=False),
    )
    native_table = ctx._tables["events"]
    pdf = adapter.to_pandas(native_table)
    return pdf.sort_values("id")["phrase"].tolist()


@pytest.mark.skipif(not DATAFUSION_DF_AVAILABLE, reason="DataFusion DataFrame adapter is not installed")
def test_datafusion_csv_direct_keeps_empty_string_when_null_marker_is_none(tmp_path: Path) -> None:
    values = _load_phrase_values(DataFusionDataFrameAdapter(), _write_events_csv(tmp_path), null_marker=None)

    assert values == ["", "abc"]


@pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark DataFrame adapter is not installed")
def test_pyspark_csv_direct_keeps_empty_string_when_null_marker_is_none(tmp_path: Path) -> None:
    adapter = PySparkDataFrameAdapter(master="local[1]", driver_memory="1g", shuffle_partitions=1)
    try:
        values = _load_phrase_values(adapter, _write_events_csv(tmp_path), null_marker=None)
    finally:
        adapter.close()

    assert values == ["", "abc"]


@pytest.mark.skipif(not DATAFUSION_DF_AVAILABLE, reason="DataFusion DataFrame adapter is not installed")
def test_datafusion_csv_direct_preserves_null_when_null_marker_is_empty_string(tmp_path: Path) -> None:
    values = _load_phrase_values(DataFusionDataFrameAdapter(), _write_events_csv(tmp_path), null_marker="")

    assert values[0] is None
    assert values[1] == "abc"


@pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark DataFrame adapter is not installed")
def test_pyspark_csv_direct_preserves_null_when_null_marker_is_empty_string(tmp_path: Path) -> None:
    adapter = PySparkDataFrameAdapter(master="local[1]", driver_memory="1g", shuffle_partitions=1)
    try:
        values = _load_phrase_values(adapter, _write_events_csv(tmp_path), null_marker="")
    finally:
        adapter.close()

    assert values[0] is None
    assert values[1] == "abc"
