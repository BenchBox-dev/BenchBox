"""Behavioral tests for DataFrame Data Loading Strategy.

Tests targeting coverage gaps in data_loader.py:
- File format detection with real temp files (Parquet, CSV, TBL)
- Schema inference and validation (SchemaMapper type maps)
- Partition/shard handling
- Error paths: missing files, corrupt data, schema mismatch
- DataLoadResult edge cases
- CacheManifest shard support
- DataFrameDataLoader source filtering and write config table filtering

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchbox.core.dataframe.capabilities import DataFormat
from benchbox.core.dataframe.data_loader import (
    CacheManifest,
    ConversionStatus,
    DataCache,
    DataFrameDataLoader,
    DataLoadResult,
    FormatConverter,
    LoadedTable,
    SchemaMapper,
    _compute_source_hash,
    get_tpch_column_names,
)
from benchbox.core.dataframe.tuning.write_config import (
    DataFrameWriteConfiguration,
    SortColumn,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# SchemaMapper - type map coverage
# ---------------------------------------------------------------------------


class TestSchemaMapperTypeMaps:
    """Tests for SchemaMapper static type map dictionaries."""

    def test_polars_type_map_keys(self):
        """Verify all expected SQL types are mapped to Polars types."""
        expected_sql_types = {"INTEGER", "DECIMAL(15,2)", "VARCHAR", "CHAR", "DATE", "TIMESTAMP"}
        assert set(SchemaMapper.POLARS_TYPE_MAP.keys()) == expected_sql_types

    def test_polars_type_map_values_are_valid_polars_types(self):
        """Polars type map values must be recognized type strings."""
        valid_polars_types = {"Int64", "Float64", "Utf8", "Date", "Datetime"}
        for polars_type in SchemaMapper.POLARS_TYPE_MAP.values():
            assert polars_type in valid_polars_types, f"Unexpected Polars type: {polars_type}"

    def test_pandas_type_map_values_are_valid(self):
        """Pandas type map values must be recognized dtype strings."""
        valid_pandas_types = {"int64", "float64", "object", "datetime64[ns]"}
        for pandas_type in SchemaMapper.PANDAS_TYPE_MAP.values():
            assert pandas_type in valid_pandas_types, f"Unexpected Pandas type: {pandas_type}"

    def test_pyarrow_type_map_values_are_valid(self):
        """PyArrow type map values must be recognized type strings."""
        valid_arrow_types = {"int64", "float64", "string", "date32", "timestamp[us]"}
        for arrow_type in SchemaMapper.PYARROW_TYPE_MAP.values():
            assert arrow_type in valid_arrow_types, f"Unexpected Arrow type: {arrow_type}"

    def test_all_maps_have_same_keys(self):
        """All three type maps must cover the same SQL types."""
        assert set(SchemaMapper.POLARS_TYPE_MAP.keys()) == set(SchemaMapper.PANDAS_TYPE_MAP.keys())
        assert set(SchemaMapper.POLARS_TYPE_MAP.keys()) == set(SchemaMapper.PYARROW_TYPE_MAP.keys())


# ---------------------------------------------------------------------------
# FormatConverter - format detection with real temp files
# ---------------------------------------------------------------------------


class TestFormatConverterFormats:
    """Tests for FormatConverter with various real temp file formats."""

    def test_convert_csv_with_header(self, tmp_path):
        """CSV with header row converts to Parquet correctly."""
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\n")

        parquet_file = tmp_path / "data.parquet"

        status, row_count = FormatConverter.convert_csv_to_parquet(
            source_path=csv_file,
            target_path=parquet_file,
            delimiter=",",
        )

        assert status == ConversionStatus.SUCCESS
        assert row_count == 2
        assert parquet_file.exists()
        assert parquet_file.stat().st_size > 0

    def test_convert_empty_csv_with_header(self, tmp_path):
        """Empty CSV (header only) converts to 0-row Parquet."""
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("col_a,col_b\n")

        parquet_file = tmp_path / "empty.parquet"

        status, row_count = FormatConverter.convert_csv_to_parquet(
            source_path=csv_file,
            target_path=parquet_file,
            delimiter=",",
        )

        assert status == ConversionStatus.SUCCESS
        assert row_count == 0

    def test_convert_tbl_with_explicit_column_types(self, tmp_path):
        """TBL conversion with explicit column types maps types correctly."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        tbl_file = tmp_path / "test.tbl"
        tbl_file.write_text("1|2024-01-15|100.50|\n2|2024-02-20|200.75|\n")

        parquet_file = tmp_path / "test.parquet"
        col_names = ["item_id", "order_date", "amount"]
        col_types = {"item_id": "int64", "order_date": "date32", "amount": "float64"}

        status, row_count = FormatConverter.convert_csv_to_parquet(
            source_path=tbl_file,
            target_path=parquet_file,
            column_names=col_names,
            delimiter="|",
            column_types=col_types,
        )

        assert status == ConversionStatus.SUCCESS
        assert row_count == 2

        table = pq.read_table(parquet_file)
        assert table.schema.field("item_id").type == pa.int64()
        assert table.schema.field("order_date").type == pa.date32()
        assert table.schema.field("amount").type == pa.float64()

    def test_convert_unsupported_file_format_returns_failed(self, tmp_path):
        """Non-existent source files cause FAILED status without exceptions."""
        missing = tmp_path / "missing.csv"
        target = tmp_path / "out.parquet"

        status, row_count = FormatConverter.convert_csv_to_parquet(
            source_path=missing,
            target_path=target,
        )

        assert status == ConversionStatus.FAILED
        assert row_count == 0
        assert not target.exists()


# ---------------------------------------------------------------------------
# FormatConverter - _resolve_arrow_types
# ---------------------------------------------------------------------------


class TestResolveArrowTypes:
    """Tests for FormatConverter._resolve_arrow_types static method."""

    def test_resolve_none_returns_none(self):
        """Passing None returns None."""
        result = FormatConverter._resolve_arrow_types(None)
        assert result is None

    def test_resolve_empty_dict_returns_none(self):
        """Passing empty dict returns None (falsy)."""
        result = FormatConverter._resolve_arrow_types({})
        assert result is None

    def test_resolve_known_types(self):
        """Known type strings resolve to PyArrow types."""
        import pyarrow as pa

        result = FormatConverter._resolve_arrow_types(
            {"col_a": "int64", "col_b": "date32", "col_c": "float64", "col_d": "string"}
        )

        assert result is not None
        assert result["col_a"] == pa.int64()
        assert result["col_b"] == pa.date32()
        assert result["col_c"] == pa.float64()
        assert result["col_d"] == pa.string()

    def test_resolve_unknown_type_falls_back_to_string(self):
        """Unknown type strings fall back to pa.string()."""
        import pyarrow as pa

        result = FormatConverter._resolve_arrow_types({"col_x": "unknown_type"})
        assert result is not None
        assert result["col_x"] == pa.string()


# ---------------------------------------------------------------------------
# FormatConverter - _build_write_kwargs
# ---------------------------------------------------------------------------


class TestBuildWriteKwargs:
    """Tests for FormatConverter._build_write_kwargs static method."""

    def test_default_no_config(self):
        """Without write config, returns default kwargs."""
        kwargs = FormatConverter._build_write_kwargs("zstd", None, None)
        assert kwargs["compression"] == "zstd"
        assert kwargs["use_dictionary"] is True
        assert "row_group_size" not in kwargs

    def test_with_row_group_size(self):
        """Write config with row_group_size is passed through."""
        config = DataFrameWriteConfiguration(row_group_size=5000)
        kwargs = FormatConverter._build_write_kwargs("zstd", config, None)
        assert kwargs["row_group_size"] == 5000

    def test_with_compression_level(self):
        """Write config with compression_level is passed through."""
        config = DataFrameWriteConfiguration(compression_level=9)
        kwargs = FormatConverter._build_write_kwargs("gzip", config, None)
        assert kwargs["compression"] == "gzip"
        assert kwargs["compression_level"] == 9


# ---------------------------------------------------------------------------
# DataCache - shard support in manifests
# ---------------------------------------------------------------------------


class TestDataCacheShardedManifest:
    """Tests for DataCache handling of sharded (multi-file) manifests."""

    def test_has_cached_data_with_sharded_files(self, tmp_path):
        """Cache validates all shard files exist."""
        cache = DataCache(tmp_path)
        cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
        cache_path.mkdir(parents=True)

        # Create shard files
        (cache_path / "lineitem.1.parquet").touch()
        (cache_path / "lineitem.2.parquet").touch()

        manifest = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "format": "parquet",
            "created_at": "2026-01-01T00:00:00",
            "source_hash": "abc123",
            "tables": {
                "lineitem": {
                    "files": ["lineitem.1.parquet", "lineitem.2.parquet"],
                },
            },
        }

        with open(cache_path / "_manifest.json", "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)

        assert cache.has_cached_data("tpch", 1.0, DataFormat.PARQUET) is True

    def test_has_cached_data_with_missing_shard(self, tmp_path):
        """Cache invalidated when a shard file is missing."""
        cache = DataCache(tmp_path)
        cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
        cache_path.mkdir(parents=True)

        # Only create one of two shards
        (cache_path / "lineitem.1.parquet").touch()

        manifest = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "format": "parquet",
            "created_at": "2026-01-01T00:00:00",
            "source_hash": "abc123",
            "tables": {
                "lineitem": {
                    "files": ["lineitem.1.parquet", "lineitem.2.parquet"],
                },
            },
        }

        with open(cache_path / "_manifest.json", "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)

        assert cache.has_cached_data("tpch", 1.0, DataFormat.PARQUET) is False

    def test_get_cached_files_sharded(self, tmp_path):
        """get_cached_files resolves shard file lists."""
        cache = DataCache(tmp_path)
        cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
        cache_path.mkdir(parents=True)

        manifest = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "format": "parquet",
            "created_at": "2026-01-01T00:00:00",
            "source_hash": "abc123",
            "tables": {
                "lineitem": {
                    "files": ["lineitem.1.parquet", "lineitem.2.parquet"],
                },
            },
        }

        with open(cache_path / "_manifest.json", "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)

        files = cache.get_cached_files("tpch", 1.0, DataFormat.PARQUET)
        assert files is not None
        assert isinstance(files["lineitem"], list)
        assert len(files["lineitem"]) == 2

    def test_get_cached_files_returns_none_for_invalid_json(self, tmp_path):
        """Corrupt manifest JSON returns None."""
        cache = DataCache(tmp_path)
        cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
        cache_path.mkdir(parents=True)

        manifest_path = cache_path / "_manifest.json"
        manifest_path.write_text("{invalid json")

        result = cache.get_cached_files("tpch", 1.0, DataFormat.PARQUET)
        assert result is None

    def test_get_cached_files_returns_none_for_missing_manifest(self, tmp_path):
        """Missing manifest returns None."""
        cache = DataCache(tmp_path)
        result = cache.get_cached_files("tpch", 1.0, DataFormat.PARQUET)
        assert result is None

    def test_has_cached_data_with_corrupt_manifest(self, tmp_path):
        """Corrupt manifest JSON returns False."""
        cache = DataCache(tmp_path)
        cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
        cache_path.mkdir(parents=True)

        manifest_path = cache_path / "_manifest.json"
        manifest_path.write_text("not valid json")

        assert cache.has_cached_data("tpch", 1.0, DataFormat.PARQUET) is False


# ---------------------------------------------------------------------------
# DataCache - clear_cache branch coverage
# ---------------------------------------------------------------------------


class TestDataCacheClearBranches:
    """Tests for DataCache.clear_cache different parameter combinations."""

    def test_clear_cache_all_formats(self, tmp_path):
        """Clear all format conversions for a specific benchmark+SF."""
        cache = DataCache(tmp_path)

        # Create parquet and csv subdirectories
        parquet_path = cache.get_cache_path("tpch", 0.01, DataFormat.PARQUET)
        parquet_path.mkdir(parents=True)
        (parquet_path / "test.parquet").touch()

        # Also create a fake csv format dir at the right level
        base = parquet_path.parent.parent  # go up past version and format dir
        csv_dir = base / "csv"
        csv_dir.mkdir(parents=True)
        (csv_dir / "test.csv").touch()

        removed = cache.clear_cache("tpch", 0.01)
        assert removed >= 1

    def test_clear_cache_by_benchmark_only(self, tmp_path):
        """Clear all SFs for a specific benchmark."""
        cache = DataCache(tmp_path)

        cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
        cache_path.mkdir(parents=True)
        (cache_path / "test.parquet").touch()

        removed = cache.clear_cache("tpch")
        assert removed >= 1

    def test_clear_cache_all(self, tmp_path):
        """Clear all cached format conversions."""
        cache = DataCache(tmp_path)

        cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
        cache_path.mkdir(parents=True)
        (cache_path / "test.parquet").touch()

        removed = cache.clear_cache()
        assert removed >= 1

    def test_clear_cache_nonexistent_dir(self, tmp_path):
        """Clear on non-existent directory returns 0."""
        cache = DataCache(tmp_path / "nonexistent")
        removed = cache.clear_cache()
        assert removed == 0


# ---------------------------------------------------------------------------
# DataLoadResult - edge cases
# ---------------------------------------------------------------------------


class TestDataLoadResultEdgeCases:
    """Tests for DataLoadResult edge conditions."""

    def test_success_requires_both_no_errors_and_tables(self):
        """Success is only True when tables exist AND there are no errors."""
        # No tables, no errors => failure
        empty = DataLoadResult()
        assert empty.success is False

        # Tables with errors => failure
        with_errors = DataLoadResult(
            tables={"tbl": LoadedTable("tbl", Path("t.parquet"), DataFormat.PARQUET)},
            errors=["error"],
        )
        assert with_errors.success is False

    def test_default_format_values(self):
        """Default source/target formats are CSV/PARQUET."""
        result = DataLoadResult()
        assert result.source_format == DataFormat.CSV
        assert result.target_format == DataFormat.PARQUET
        assert result.conversion_performed is False
        assert result.cache_hit is False


# ---------------------------------------------------------------------------
# CacheManifest - from_dict with missing tables key
# ---------------------------------------------------------------------------


class TestCacheManifestEdgeCases:
    """Tests for CacheManifest edge cases."""

    def test_from_dict_missing_tables_defaults_to_empty(self):
        """Missing 'tables' key defaults to empty dict."""
        data = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "format": "parquet",
            "created_at": "2026-01-01",
            "source_hash": "abc",
        }
        manifest = CacheManifest.from_dict(data)
        assert manifest.tables == {}


# ---------------------------------------------------------------------------
# _compute_source_hash - shard support
# ---------------------------------------------------------------------------


class TestSourceHashShards:
    """Tests for _compute_source_hash with sharded (list) paths."""

    def test_hash_with_list_paths(self, tmp_path):
        """Hash computation works with list-valued paths (shards)."""
        shard1 = tmp_path / "customer.tbl.1"
        shard2 = tmp_path / "customer.tbl.2"
        shard1.write_text("shard1")
        shard2.write_text("shard2")

        tables = {"customer": [shard1, shard2]}
        hash_val = _compute_source_hash(tmp_path, tables)

        assert isinstance(hash_val, str)
        assert len(hash_val) == 12  # MD5 truncated to 12 chars

    def test_hash_with_nonexistent_shard_skipped(self, tmp_path):
        """Non-existent files in shard list are silently skipped."""
        real_file = tmp_path / "customer.tbl.1"
        real_file.write_text("data")

        tables = {"customer": [real_file, tmp_path / "missing.tbl.2"]}
        hash_val = _compute_source_hash(tmp_path, tables)

        assert isinstance(hash_val, str)
        assert len(hash_val) == 12


# ---------------------------------------------------------------------------
# DataFrameDataLoader - source format detection
# ---------------------------------------------------------------------------


class TestDataLoaderFormatDetection:
    """Tests for DataFrameDataLoader._detect_source_format with real files."""

    def test_detect_csv_format_from_csv_extension(self, tmp_path):
        """CSV files detected as CSV format."""
        loader = DataFrameDataLoader()
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b\n1,2\n")

        result = loader._detect_source_format({"data": csv_file})
        assert result == DataFormat.CSV

    def test_detect_parquet_format(self, tmp_path):
        """Parquet files detected as Parquet format."""
        loader = DataFrameDataLoader()
        pq_file = tmp_path / "data.parquet"
        pq_file.touch()

        result = loader._detect_source_format({"data": pq_file})
        assert result == DataFormat.PARQUET

    def test_detect_format_from_first_shard(self, tmp_path):
        """Format detected from first file in shard list."""
        loader = DataFrameDataLoader()
        shard1 = tmp_path / "orders.tbl.1"
        shard2 = tmp_path / "orders.tbl.2"
        shard1.write_text("1|A\n")
        shard2.write_text("2|B\n")

        result = loader._detect_source_format({"orders": [shard1, shard2]})
        assert result == DataFormat.CSV


# ---------------------------------------------------------------------------
# DataFrameDataLoader - table write config filtering
# ---------------------------------------------------------------------------


class TestDataLoaderWriteConfigFiltering:
    """Tests for DataFrameDataLoader._get_table_write_config."""

    def test_filter_sort_columns_to_table_schema(self):
        """Sort columns not in the table schema are filtered out."""
        loader = DataFrameDataLoader()
        config = DataFrameWriteConfiguration(
            sort_by=[
                SortColumn(name="l_shipdate", order="asc"),
                SortColumn(name="o_orderdate", order="asc"),  # Wrong table
            ]
        )

        filtered = loader._get_table_write_config(config, "lineitem", ["l_orderkey", "l_shipdate", "l_quantity"])

        assert filtered is not None
        sort_col_names = [sc.name for sc in filtered.sort_by]
        assert "l_shipdate" in sort_col_names
        assert "o_orderdate" not in sort_col_names

    def test_none_config_returns_none(self):
        """None write config returns None."""
        loader = DataFrameDataLoader()
        result = loader._get_table_write_config(None, "test", ["col_a"])
        assert result is None

    def test_default_config_returns_as_is(self):
        """Default write config is returned unchanged."""
        loader = DataFrameDataLoader()
        config = DataFrameWriteConfiguration()
        result = loader._get_table_write_config(config, "test", ["col_a"])
        assert result is config

    def test_none_column_names_returns_config_as_is(self):
        """Without column names, config is returned unfiltered."""
        loader = DataFrameDataLoader()
        config = DataFrameWriteConfiguration(
            sort_by=[SortColumn(name="l_shipdate", order="asc")],
        )
        result = loader._get_table_write_config(config, "lineitem", None)
        assert result is config


# ---------------------------------------------------------------------------
# DataFrameDataLoader - file discovery
# ---------------------------------------------------------------------------


class TestDataLoaderFileDiscovery:
    """Tests for DataFrameDataLoader._discover_files."""

    def test_discover_csv_tbl_parquet(self, tmp_path):
        """Discovers files with .tbl, .csv, and .parquet extensions."""
        loader = DataFrameDataLoader()

        (tmp_path / "region.tbl").write_text("1|AFRICA|comment\n")
        (tmp_path / "custom.csv").write_text("a,b\n1,2\n")
        (tmp_path / "loaded.parquet").touch()

        files = loader._discover_files(tmp_path)

        assert "region" in files
        assert "custom" in files
        assert "loaded" in files

    def test_discover_ignores_non_data_files(self, tmp_path):
        """Non-data files (txt, json) are ignored."""
        loader = DataFrameDataLoader()

        (tmp_path / "readme.txt").write_text("not data")
        (tmp_path / "manifest.json").write_text("{}")

        files = loader._discover_files(tmp_path)
        assert len(files) == 0

    def test_discover_parquet_directory(self, tmp_path):
        """Parquet directory containing parquet files is recursed into."""
        loader = DataFrameDataLoader()

        pq_dir = tmp_path / "output.parquet"
        pq_dir.mkdir()
        (pq_dir / "lineitem.parquet").touch()
        (pq_dir / "orders.parquet").touch()

        files = loader._discover_files(tmp_path)
        assert "lineitem" in files
        assert "orders" in files


# ---------------------------------------------------------------------------
# ConversionStatus - enum values
# ---------------------------------------------------------------------------


class TestConversionStatusEnum:
    """Tests for ConversionStatus enum completeness."""

    def test_all_statuses_exist(self):
        """All expected conversion statuses are defined."""
        assert ConversionStatus.NOT_NEEDED.value == "not_needed"
        assert ConversionStatus.SUCCESS.value == "success"
        assert ConversionStatus.FAILED.value == "failed"
        assert ConversionStatus.SKIPPED.value == "skipped"


# ---------------------------------------------------------------------------
# get_tpch_column_names - completeness
# ---------------------------------------------------------------------------


class TestGetTPCHColumnNamesCompleteness:
    """Tests for get_tpch_column_names coverage."""

    def test_all_eight_tables_present(self):
        """All 8 TPC-H tables are included."""
        columns = get_tpch_column_names()
        expected_tables = {"region", "nation", "supplier", "part", "partsupp", "customer", "orders", "lineitem"}
        assert set(columns.keys()) == expected_tables

    def test_column_names_are_prefixed(self):
        """Each table's columns follow the TPC-H naming convention (prefix_colname)."""
        columns = get_tpch_column_names()
        prefix_map = {
            "region": "r_",
            "nation": "n_",
            "supplier": "s_",
            "part": "p_",
            "partsupp": "ps_",
            "customer": "c_",
            "orders": "o_",
            "lineitem": "l_",
        }
        for table_name, prefix in prefix_map.items():
            for col_name in columns[table_name]:
                assert col_name.startswith(prefix), f"{col_name} in {table_name} missing prefix {prefix}"

    def test_lineitem_has_16_columns(self):
        """TPC-H lineitem table has exactly 16 columns."""
        columns = get_tpch_column_names()
        assert len(columns["lineitem"]) == 16

    def test_region_has_3_columns(self):
        """TPC-H region table has exactly 3 columns."""
        columns = get_tpch_column_names()
        assert len(columns["region"]) == 3
