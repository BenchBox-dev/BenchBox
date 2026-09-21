"""Unit tests for the Delta Lake to Parquet export layer.

These tests use the ``deltalake`` package directly (no JVM or Spark
session) to build fixture tables, then verify the export produces
ClickHouse-ingestible Parquet output: ``.parquet`` files readable by
PyArrow with preserved schema and row counts, including pinned-version
exports.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from benchbox.utils.delta_export import DeltaExportError, export_delta_to_parquet

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

deltalake = pytest.importorskip("deltalake")


def _write_delta(path: Path, batches: list[pa.Table], mode: str = "overwrite") -> None:
    from deltalake import write_deltalake

    for index, batch in enumerate(batches):
        write_deltalake(str(path), batch, mode=mode if index == 0 else "append")


@pytest.fixture
def delta_table(tmp_path: Path) -> Path:
    path = tmp_path / "orders"
    _write_delta(
        path,
        [
            pa.table({"id": [1, 2], "v": ["a", "b"]}),
            pa.table({"id": [3], "v": ["c"]}),
        ],
    )
    return path


class TestExportLatest:
    def test_exports_all_rows_with_schema(self, delta_table: Path, tmp_path: Path):
        out = tmp_path / "parquet"
        result = export_delta_to_parquet(delta_table, out)

        assert result.version == 1
        assert result.row_count == 3
        assert result.column_names == ["id", "v"]
        assert result.parquet_files == [out / "data.parquet"]
        assert all(path.suffix == ".parquet" for path in result.parquet_files)

    def test_parquet_readable_by_pyarrow(self, delta_table: Path, tmp_path: Path):
        out = tmp_path / "parquet"
        result = export_delta_to_parquet(delta_table, out)

        table = pq.read_table(result.parquet_files[0])
        assert table.num_rows == 3
        assert table.schema.names == ["id", "v"]
        assert sorted(table.column("id").to_pylist()) == [1, 2, 3]

    def test_creates_output_dir(self, delta_table: Path, tmp_path: Path):
        out = tmp_path / "nested" / "parquet"
        result = export_delta_to_parquet(delta_table, out)
        assert out.is_dir()
        assert result.parquet_files[0].exists()


class TestExportVersionPin:
    def test_pinned_version_exports_snapshot(self, delta_table: Path, tmp_path: Path):
        out = tmp_path / "parquet_v0"
        result = export_delta_to_parquet(delta_table, out, version=0)

        assert result.version == 0
        assert result.row_count == 2
        assert pq.read_table(result.parquet_files[0]).num_rows == 2


class TestExportErrors:
    def test_missing_delta_log_raises(self, tmp_path: Path):
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(DeltaExportError, match="_delta_log"):
            export_delta_to_parquet(plain, tmp_path / "out")

    def test_absent_path_raises(self, tmp_path: Path):
        with pytest.raises(DeltaExportError, match="_delta_log"):
            export_delta_to_parquet(tmp_path / "absent", tmp_path / "out")

    def test_unknown_version_raises(self, delta_table: Path, tmp_path: Path):
        with pytest.raises(DeltaExportError, match="Cannot open Delta table"):
            export_delta_to_parquet(delta_table, tmp_path / "out", version=99)
