"""Regression tests for data loading contamination guards.

Tests that the shared SQL/file loader raises DataLoadingError instead of
silently recording zero rows when shard paths are directories or missing,
and that _load_single_file rejects directory inputs.

These failures were observed when stale Iceberg table directories (customer/,
lineitem/) coexisted with valid manifest-tracked .tbl files in the datagen
cache, causing silent zero-row loads and opaque IsADirectoryError traces.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from benchbox.platforms.base.data_loading import DataLoader, DataLoadingError

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_loader(tmp_path: Path) -> DataLoader:
    """Create a DataLoader with minimal mocks for testing file-based loading."""
    adapter = Mock()
    adapter.verbose_enabled = False
    adapter.log_operation_start = Mock()
    adapter.log_operation_complete = Mock()
    adapter.log_very_verbose = Mock()
    benchmark = Mock(spec=[])
    connection = Mock()
    return DataLoader(
        adapter=adapter,
        benchmark=benchmark,
        connection=connection,
        data_dir=tmp_path,
    )


class TestShardPathContamination:
    """Tests for shard path filtering and empty-shard error handling."""

    def test_empty_resolved_shard_list_raises(self, tmp_path: Path) -> None:
        """When all shard paths are missing, raise DataLoadingError."""
        loader = _make_loader(tmp_path)
        missing_a = tmp_path / "customer.tbl.1.zst"
        missing_b = tmp_path / "customer.tbl.2.zst"

        with pytest.raises(DataLoadingError, match="customer.*2 shard.*0 directories.*2 missing"):
            loader._load_file_based_data({"customer": [missing_a, missing_b]})

    def test_directory_shards_filtered_and_raise_when_no_files_remain(self, tmp_path: Path) -> None:
        """When all shard paths are directories, raise DataLoadingError mentioning directory count."""
        loader = _make_loader(tmp_path)
        # Create directories where files are expected
        dir_a = tmp_path / "lineitem.tbl.1"
        dir_a.mkdir()
        dir_b = tmp_path / "lineitem.tbl.2"
        dir_b.mkdir()

        with pytest.raises(DataLoadingError, match="lineitem.*2 shard.*2 directories.*0 missing"):
            loader._load_file_based_data({"lineitem": [dir_a, dir_b]})

    def test_mixed_dirs_and_missing_raises_with_both_counts(self, tmp_path: Path) -> None:
        """When shards are a mix of directories and missing, error includes both counts."""
        loader = _make_loader(tmp_path)
        dir_shard = tmp_path / "orders.tbl.1"
        dir_shard.mkdir()
        missing_shard = tmp_path / "orders.tbl.2.zst"

        with pytest.raises(DataLoadingError, match="orders.*2 shard.*1 director.*1 missing"):
            loader._load_file_based_data({"orders": [dir_shard, missing_shard]})

    def test_partial_shard_contamination_raises(self, tmp_path: Path) -> None:
        """When some shards are files but others are dirs/missing, raise DataLoadingError."""
        loader = _make_loader(tmp_path)
        good_file = tmp_path / "nation.tbl.1"
        good_file.write_text("1|USA\n")
        bad_dir = tmp_path / "nation.tbl.2"
        bad_dir.mkdir()

        with pytest.raises(DataLoadingError, match="nation.*2 shard.*1 director.*0 missing.*1 valid"):
            loader._load_file_based_data({"nation": [good_file, bad_dir]})

    def test_legitimate_shards_load_normally(self, tmp_path: Path) -> None:
        """Legitimate file shards pass through categorization without error."""
        loader = _make_loader(tmp_path)
        shard_a = tmp_path / "region.tbl.1"
        shard_a.write_text("1|AMERICA\n")
        shard_b = tmp_path / "region.tbl.2"
        shard_b.write_text("2|EUROPE\n")

        # Should NOT raise DataLoadingError — the shards are files, not dirs/missing.
        stats = loader._load_file_based_data({"region": [shard_a, shard_b]})
        assert "region" in stats


class TestSingleFileDirectoryGuard:
    """Tests for _load_single_file directory rejection."""

    def test_directory_input_raises(self, tmp_path: Path) -> None:
        """_load_single_file raises DataLoadingError when path is a directory."""
        loader = _make_loader(tmp_path)
        table_dir = tmp_path / "customer"
        table_dir.mkdir()

        with pytest.raises(DataLoadingError, match="customer.*expected file but found directory"):
            loader._load_single_file("customer", table_dir)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """Missing single file raises DataLoadingError since all paths come from manifest."""
        loader = _make_loader(tmp_path)
        missing = tmp_path / "nonexistent.tbl"

        with pytest.raises(DataLoadingError, match="test_table.*data file not found"):
            loader._load_single_file("test_table", missing)
