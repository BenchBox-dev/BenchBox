"""Regression: DataFusion load_data coerces string table paths to Path.

``DataSource.tables`` is typed ``dict[str, Any]`` on purpose - the value may be a
single path, a list of paths, or in-memory rows - and the two providers that read
straight from a benchmark's generated ``tables`` attribute
(``BenchmarkTablesSource``/``BenchmarkImplTablesSource``) hand back whatever the
generator recorded, which is a plain ``str``. ``ManifestFileSource`` hands back
``Path``.

``DataFusionAdapter.load_data`` normalized only the *shape* of that payload
(wrapping a scalar in a list) and never the *type*, so a fresh
``generate -> load`` in one process reached ``_detect_directory_format`` with a
``str`` and died on ``'str' object has no attribute 'is_dir'``. A second run in
the same output directory resolved through the manifest instead and passed, which
is why the Seed Corpus workflow failed only on the DataFusion cells and only on a
clean runner.

The shared ``normalize_table_paths`` helper exists for exactly this and is
documented as the funnel adapters must use; postgresql, questdb, mysql_wire and
the DataFrame mixin already do.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.base.data_loading import DataSource

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _capturing_adapter(tmp_path: Path, table_path: str):
    """Build a DataFusionAdapter whose per-table loader records the paths it receives."""
    from benchbox.platforms.datafusion import DataFusionAdapter

    data_source = DataSource(
        source_type="benchmark_tables",
        tables={"customer": table_path},
        table_formats={"customer": "tbl"},
    )

    received: list[object] = []

    def record(connection, table_name, file_paths, data_dir, **kwargs):
        received.extend(file_paths)
        return 2

    with patch("benchbox.platforms.datafusion.SessionContext"):
        adapter = DataFusionAdapter(working_dir=str(tmp_path / "wd"), data_format="parquet")

    resolver = Mock()
    resolver.resolve.return_value = data_source

    with (
        patch("benchbox.platforms.base.data_loading.DataSourceResolver", return_value=resolver),
        patch.object(adapter, "_load_table_parquet", side_effect=record),
        patch.object(adapter, "_load_table_csv", side_effect=record),
    ):
        table_stats, _duration, _timings = adapter.load_data(Mock(), Mock(), tmp_path)

    return table_stats, received


def test_load_data_coerces_string_table_path_to_path(tmp_path):
    """A str-valued ``tables`` entry must not raise and must arrive as a Path."""
    data_file = tmp_path / "customer.tbl.zst"
    data_file.write_bytes(b"")

    table_stats, received = _capturing_adapter(tmp_path, str(data_file))

    assert table_stats == {"customer": 2}
    assert received == [data_file]
    assert all(isinstance(path, Path) for path in received), f"expected Paths, got {[type(p) for p in received]}"


def test_load_data_accepts_list_of_string_table_paths(tmp_path):
    """Chunked tables recorded as a list of strings are coerced element-wise."""
    from benchbox.platforms.datafusion import DataFusionAdapter

    chunks = []
    for index in (1, 2):
        chunk = tmp_path / f"lineitem.tbl.{index}"
        chunk.write_bytes(b"")
        chunks.append(chunk)

    data_source = DataSource(
        source_type="benchmark_tables",
        tables={"lineitem": [str(chunk) for chunk in chunks]},
        table_formats={"lineitem": "tbl"},
    )

    received: list[object] = []

    def record(connection, table_name, file_paths, data_dir, **kwargs):
        received.extend(file_paths)
        return 4

    with patch("benchbox.platforms.datafusion.SessionContext"):
        adapter = DataFusionAdapter(working_dir=str(tmp_path / "wd"), data_format="parquet")

    resolver = Mock()
    resolver.resolve.return_value = data_source

    with (
        patch("benchbox.platforms.base.data_loading.DataSourceResolver", return_value=resolver),
        patch.object(adapter, "_load_table_parquet", side_effect=record),
        patch.object(adapter, "_load_table_csv", side_effect=record),
    ):
        adapter.load_data(Mock(), Mock(), tmp_path)

    assert received == chunks
    assert all(isinstance(path, Path) for path in received)


def test_load_data_still_detects_directory_format_from_string_path(tmp_path):
    """Delta detection must survive the coercion: a str pointing at a Delta dir loads as Delta."""
    from benchbox.platforms.datafusion import DataFusionAdapter

    delta_dir = tmp_path / "customer"
    (delta_dir / "_delta_log").mkdir(parents=True)

    data_source = DataSource(
        source_type="benchmark_tables",
        tables={"customer": str(delta_dir)},
    )

    with patch("benchbox.platforms.datafusion.SessionContext"):
        adapter = DataFusionAdapter(working_dir=str(tmp_path / "wd"), data_format="parquet")

    resolver = Mock()
    resolver.resolve.return_value = data_source

    with (
        patch("benchbox.platforms.base.data_loading.DataSourceResolver", return_value=resolver),
        patch.object(adapter, "_load_table_delta", return_value=7) as load_delta,
    ):
        table_stats, _duration, _timings = adapter.load_data(Mock(), Mock(), tmp_path)

    assert table_stats == {"customer": 7}
    assert load_delta.call_args.args[2] == delta_dir
