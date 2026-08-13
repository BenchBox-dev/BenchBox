"""Regression tests for measured TPC-H manifest row counts."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from benchbox.core.tpch.generator import TPCHDataGenerator

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _manifest_lineitem_counts(output_dir: Path) -> list[int]:
    payload = json.loads((output_dir / "_datagen_manifest.json").read_text(encoding="utf-8"))
    return [entry["row_count"] for entry in payload["tables"]["lineitem"]["formats"]["tbl"]]


def _write_rows(path: Path, row_count: int) -> None:
    path.write_text("".join(f"row-{index}|\n" for index in range(row_count)), encoding="utf-8")


def test_manifest_records_uneven_rows_for_explicit_shards(tmp_path: Path) -> None:
    generator = TPCHDataGenerator(
        scale_factor=0.01,
        output_dir=tmp_path,
        parallel=2,
        compression_type="none",
        quiet=True,
    )
    shard_paths = [tmp_path / "lineitem.tbl.1", tmp_path / "lineitem.tbl.2"]
    _write_rows(shard_paths[0], 3)
    _write_rows(shard_paths[1], 4)

    generator._write_manifest(tmp_path, {"lineitem": shard_paths})

    assert _manifest_lineitem_counts(tmp_path) == [3, 4]


@pytest.mark.parametrize("compression_type", ["gzip", "zstd"])
def test_manifest_records_uneven_rows_for_legacy_compressed_shards(tmp_path: Path, compression_type: str) -> None:
    generator = TPCHDataGenerator(
        scale_factor=0.01,
        output_dir=tmp_path,
        parallel=2,
        compression_type=compression_type,
        compress_data=True,
        quiet=True,
    )
    raw_paths = [tmp_path / "lineitem.tbl.1", tmp_path / "lineitem.tbl.2"]
    _write_rows(raw_paths[0], 2)
    _write_rows(raw_paths[1], 5)
    shard_paths = [generator.compress_existing_file(path, remove_original=True) for path in raw_paths]

    # Passing one shard exercises the legacy discovery branch, which must
    # discover and measure every compressed shard in the output directory.
    generator._write_manifest(tmp_path, {"lineitem": shard_paths[0]})

    assert _manifest_lineitem_counts(tmp_path) == [2, 5]


def test_reused_data_refreshes_stale_manifest_counts(tmp_path: Path) -> None:
    generator = TPCHDataGenerator(
        scale_factor=0.01,
        output_dir=tmp_path,
        parallel=2,
        compression_type="none",
        quiet=True,
    )
    shard_paths = [tmp_path / "lineitem.tbl.1", tmp_path / "lineitem.tbl.2"]
    _write_rows(shard_paths[0], 3)
    _write_rows(shard_paths[1], 4)

    stale_manifest = {
        "version": 2,
        "tables": {"lineitem": {"formats": {"tbl": [{"path": path.name, "row_count": 1} for path in shard_paths]}}},
    }
    (tmp_path / "_datagen_manifest.json").write_text(json.dumps(stale_manifest), encoding="utf-8")

    with patch.object(generator, "_find_or_build_dbgen", return_value=Path("/tmp/dbgen")):
        with patch.object(generator.validator, "should_regenerate_data", return_value=(False, None)):
            with patch.object(generator, "_collect_existing_table_files", return_value={"lineitem": shard_paths}):
                result = generator._generate_local(tmp_path)

    assert result == {"lineitem": shard_paths}
    assert _manifest_lineitem_counts(tmp_path) == [3, 4]
