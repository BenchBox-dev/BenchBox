"""Tests for data loading operations: validation, escaping, data sources, and providers.

Covers validate_sql_identifier, escape_sql_string_literal, DataSource,
FileFormatRegistry (extensions, handlers, compression), DataSourceProvider
chain (BenchmarkTablesSource, BenchmarkImplTablesSource, ManifestFileSource),
DataSourceResolver, RowBatchProcessor, SchemaInspector, and
NoCompressionHandler/GzipHandler.

Does NOT duplicate the handler detection tests already in
tests/unit/platforms/test_data_loading_registry.py.
"""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from benchbox.platforms.base.data_loading import (
    BenchmarkImplTablesSource,
    BenchmarkTablesSource,
    DataLoadingError,
    DataSource,
    DataSourceResolver,
    FileFormatRegistry,
    GzipHandler,
    ManifestFileSource,
    NoCompressionHandler,
    RowBatchProcessor,
    SchemaInspector,
    ZstdHandler,
    escape_sql_string_literal,
    validate_sql_identifier,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# validate_sql_identifier
# ---------------------------------------------------------------------------


class TestValidateSqlIdentifier:
    """Tests for validate_sql_identifier."""

    def test_simple_valid_name(self):
        assert validate_sql_identifier("customer") == "customer"

    def test_underscore_prefix(self):
        assert validate_sql_identifier("_temp") == "_temp"

    def test_mixed_case_with_digits(self):
        assert validate_sql_identifier("LineItem2") == "LineItem2"

    def test_all_underscores(self):
        assert validate_sql_identifier("___") == "___"

    def test_single_letter(self):
        assert validate_sql_identifier("x") == "x"

    def test_max_length_exactly(self):
        name = "a" * 128
        assert validate_sql_identifier(name) == name

    def test_empty_string_raises(self):
        with pytest.raises(DataLoadingError, match="Empty"):
            validate_sql_identifier("")

    def test_none_like_empty_raises(self):
        """Empty string is the falsy path; None would be a type error upstream."""
        with pytest.raises(DataLoadingError, match="Empty"):
            validate_sql_identifier("")

    def test_exceeds_max_length(self):
        name = "a" * 129
        with pytest.raises(DataLoadingError, match="exceeds maximum length"):
            validate_sql_identifier(name)

    def test_starts_with_digit(self):
        with pytest.raises(DataLoadingError, match="must contain only"):
            validate_sql_identifier("1table")

    def test_contains_space(self):
        with pytest.raises(DataLoadingError, match="must contain only"):
            validate_sql_identifier("my table")

    def test_contains_semicolon(self):
        with pytest.raises(DataLoadingError, match="must contain only"):
            validate_sql_identifier("tbl;DROP")

    def test_sql_injection_attempt(self):
        with pytest.raises(DataLoadingError):
            validate_sql_identifier("x; DROP TABLE users --")

    def test_contains_dash(self):
        with pytest.raises(DataLoadingError, match="must contain only"):
            validate_sql_identifier("my-table")

    def test_contains_dot(self):
        with pytest.raises(DataLoadingError, match="must contain only"):
            validate_sql_identifier("schema.table")

    def test_single_quote_injection(self):
        with pytest.raises(DataLoadingError):
            validate_sql_identifier("table'; DROP TABLE--")

    def test_custom_context_in_error(self):
        with pytest.raises(DataLoadingError, match="table name"):
            validate_sql_identifier("bad name", context="table name")

    def test_unicode_characters_rejected(self):
        with pytest.raises(DataLoadingError, match="must contain only"):
            validate_sql_identifier("tbl_\u00e9")

    def test_tab_in_name_rejected(self):
        with pytest.raises(DataLoadingError, match="must contain only"):
            validate_sql_identifier("tbl\ttbl")

    def test_returns_validated_value(self):
        """Confirm the return value is the same object when valid."""
        result = validate_sql_identifier("orders", "table name")
        assert result == "orders"


# ---------------------------------------------------------------------------
# escape_sql_string_literal
# ---------------------------------------------------------------------------


class TestEscapeSqlStringLiteral:
    """Tests for escape_sql_string_literal."""

    def test_no_special_characters(self):
        assert escape_sql_string_literal("hello") == "hello"

    def test_empty_string(self):
        assert escape_sql_string_literal("") == ""

    def test_single_quote_doubled(self):
        assert escape_sql_string_literal("it's") == "it''s"

    def test_multiple_single_quotes(self):
        assert escape_sql_string_literal("a'b'c") == "a''b''c"

    def test_consecutive_quotes(self):
        assert escape_sql_string_literal("''") == "''''"

    def test_double_quotes_unchanged(self):
        assert escape_sql_string_literal('say "hi"') == 'say "hi"'

    def test_backslash_unchanged(self):
        assert escape_sql_string_literal("path\\to\\file") == "path\\to\\file"

    def test_file_path_with_quotes(self):
        assert escape_sql_string_literal("/tmp/it's a file.csv") == "/tmp/it''s a file.csv"

    def test_newlines_preserved(self):
        assert escape_sql_string_literal("line1\nline2") == "line1\nline2"


# ---------------------------------------------------------------------------
# DataSource
# ---------------------------------------------------------------------------


class TestDataSource:
    """Tests for the DataSource dataclass."""

    def test_creation(self):
        ds = DataSource(source_type="benchmark_tables", tables={"t1": [Path("/a")]})
        assert ds.source_type == "benchmark_tables"
        assert "t1" in ds.tables

    def test_empty_tables(self):
        ds = DataSource(source_type="manifest", tables={})
        assert ds.tables == {}

    def test_multiple_tables(self):
        ds = DataSource(
            source_type="benchmark_impl_tables",
            tables={
                "customer": [Path("/data/customer.tbl")],
                "orders": [Path("/data/orders.tbl")],
            },
        )
        assert len(ds.tables) == 2

    def test_equality(self):
        a = DataSource(source_type="x", tables={"t": 1})
        b = DataSource(source_type="x", tables={"t": 1})
        assert a == b

    def test_table_formats_defaults_to_empty_dict_when_none(self):
        """__post_init__ converts table_formats=None to {} so callers never see None."""
        ds = DataSource(source_type="benchmark_tables", tables={})
        assert ds.table_formats == {}
        assert ds.table_formats is not None

    def test_table_formats_preserved_when_provided(self):
        ds = DataSource(source_type="manifest_v2", tables={}, table_formats={"orders": "tbl"})
        assert ds.table_formats == {"orders": "tbl"}

    def test_table_formats_empty_dict_preserved(self):
        ds = DataSource(source_type="benchmark_tables", tables={}, table_formats={})
        assert ds.table_formats == {}


# ---------------------------------------------------------------------------
# FileFormatRegistry.get_base_data_extension - additional cases
# (basic .tbl.1.zst already covered in test_data_loading_registry.py)
# ---------------------------------------------------------------------------


class TestFileFormatRegistryExtensions:
    """Extension detection edge-cases not in test_data_loading_registry.py."""

    def test_csv_extension(self):
        assert FileFormatRegistry.get_base_data_extension(Path("/d/file.csv")) == ".csv"

    def test_dat_extension(self):
        assert FileFormatRegistry.get_base_data_extension(Path("/d/file.dat")) == ".dat"

    def test_parquet_extension(self):
        assert FileFormatRegistry.get_base_data_extension(Path("/d/file.parquet")) == ".parquet"

    def test_vortex_extension(self):
        assert FileFormatRegistry.get_base_data_extension(Path("/d/file.vortex")) == ".vortex"

    def test_csv_gz(self):
        assert FileFormatRegistry.get_base_data_extension(Path("/d/file.csv.gz")) == ".csv"

    def test_dat_zst(self):
        assert FileFormatRegistry.get_base_data_extension(Path("/d/file.dat.zst")) == ".dat"

    def test_unknown_extension_returns_none(self):
        assert FileFormatRegistry.get_base_data_extension(Path("/d/file.jsonl")) is None

    def test_no_extension_returns_none(self):
        assert FileFormatRegistry.get_base_data_extension(Path("/d/somefile")) is None

    def test_only_compression_ext_returns_none(self):
        assert FileFormatRegistry.get_base_data_extension(Path("/d/file.zst")) is None

    def test_double_compression_stripped(self):
        """Files like foo.csv.gz.zst - both compression suffixes stripped."""
        assert FileFormatRegistry.get_base_data_extension(Path("/d/foo.csv.gz.zst")) == ".csv"

    def test_numeric_shard_suffix_with_compression(self):
        """customer.tbl.5.gz still finds .tbl."""
        assert FileFormatRegistry.get_base_data_extension(Path("/d/customer.tbl.5.gz")) == ".tbl"

    def test_parquet_zst(self):
        assert FileFormatRegistry.get_base_data_extension(Path("/d/data.parquet.zst")) == ".parquet"


# ---------------------------------------------------------------------------
# FileFormatRegistry.get_handler - additional edge-cases
# (Delta, Iceberg, Parquet, multi-suffix .tbl already tested elsewhere)
# ---------------------------------------------------------------------------


class TestFileFormatRegistryHandlers:
    """Handler resolution edge-cases."""

    def test_csv_handler_returns_comma_delimiter(self):
        handler = FileFormatRegistry.get_handler(Path("/d/data.csv"))
        assert handler is not None
        assert handler.get_delimiter() == ","

    def test_dat_handler_returns_pipe_delimiter(self):
        handler = FileFormatRegistry.get_handler(Path("/d/data.dat"))
        assert handler is not None
        assert handler.get_delimiter() == "|"

    def test_unknown_extension_returns_none(self):
        handler = FileFormatRegistry.get_handler(Path("/d/data.jsonl"))
        assert handler is None

    def test_no_extension_returns_none(self):
        handler = FileFormatRegistry.get_handler(Path("/d/somefile"))
        assert handler is None

    def test_csv_gz_handler(self):
        """Compressed CSV should still resolve to CSV handler."""
        handler = FileFormatRegistry.get_handler(Path("/d/data.csv.gz"))
        assert handler is not None
        assert handler.get_delimiter() == ","

    def test_dat_zst_handler(self):
        handler = FileFormatRegistry.get_handler(Path("/d/data.dat.zst"))
        assert handler is not None
        assert handler.get_delimiter() == "|"

    def test_ducklake_directory(self, tmp_path):
        """DuckLake directory (metadata.ducklake file) gets DuckLakeFileHandler."""
        from benchbox.platforms.base.data_loading import DuckLakeFileHandler

        tbl_dir = tmp_path / "orders"
        tbl_dir.mkdir()
        (tbl_dir / "metadata.ducklake").touch()
        handler = FileFormatRegistry.get_handler(tbl_dir)
        assert isinstance(handler, DuckLakeFileHandler)


# ---------------------------------------------------------------------------
# FileFormatRegistry.get_compression_handler
# ---------------------------------------------------------------------------


class TestFileFormatRegistryCompression:
    """Compression handler resolution."""

    def test_zst_returns_zstd_handler(self):
        handler = FileFormatRegistry.get_compression_handler(Path("/d/file.zst"))
        assert isinstance(handler, ZstdHandler)

    def test_gz_returns_gzip_handler(self):
        handler = FileFormatRegistry.get_compression_handler(Path("/d/file.gz"))
        assert isinstance(handler, GzipHandler)

    def test_uncompressed_returns_no_compression(self):
        handler = FileFormatRegistry.get_compression_handler(Path("/d/file.csv"))
        assert isinstance(handler, NoCompressionHandler)

    def test_unknown_ext_returns_no_compression(self):
        handler = FileFormatRegistry.get_compression_handler(Path("/d/file.xyz"))
        assert isinstance(handler, NoCompressionHandler)


# ---------------------------------------------------------------------------
# NoCompressionHandler
# ---------------------------------------------------------------------------


class TestNoCompressionHandler:
    """NoCompressionHandler opens plain files."""

    def test_reads_plain_file(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b,c\n1,2,3\n")
        handler = NoCompressionHandler()
        with handler.open(f) as fh:
            content = fh.read()
        assert "a,b,c" in content


# ---------------------------------------------------------------------------
# GzipHandler
# ---------------------------------------------------------------------------


class TestGzipHandler:
    """GzipHandler decompresses .gz files."""

    def test_reads_gzip_file(self, tmp_path):
        gz_file = tmp_path / "data.csv.gz"
        with gzip.open(gz_file, "wt") as f:
            f.write("x,y\n10,20\n")
        handler = GzipHandler()
        with handler.open(gz_file) as fh:
            content = fh.read()
        assert "x,y" in content
        assert "10,20" in content


# ---------------------------------------------------------------------------
# SchemaInspector
# ---------------------------------------------------------------------------


class TestSchemaInspector:
    """Tests for SchemaInspector.get_column_count."""

    def test_from_schema(self):
        benchmark = MagicMock()
        benchmark.get_schema.return_value = {"t1": {"columns": ["a", "b", "c"]}}
        fh = io.StringIO("x|y|z\n")
        count = SchemaInspector.get_column_count(benchmark, "t1", fh, "|")
        assert count == 3

    def test_fallback_to_first_line(self):
        benchmark = MagicMock()
        benchmark.get_schema.return_value = {}
        fh = io.StringIO("a|b|c|d\n1|2|3|4\n")
        count = SchemaInspector.get_column_count(benchmark, "t1", fh, "|")
        assert count == 4
        # File pointer should be reset
        assert fh.tell() == 0

    def test_no_schema_method(self):
        """Benchmark without get_schema falls back to file inspection."""
        benchmark = MagicMock(spec=[])  # no get_schema
        fh = io.StringIO("a,b\n1,2\n")
        count = SchemaInspector.get_column_count(benchmark, "t1", fh, ",")
        assert count == 2

    def test_empty_file_returns_none(self):
        benchmark = MagicMock()
        benchmark.get_schema.return_value = {}
        fh = io.StringIO("")
        count = SchemaInspector.get_column_count(benchmark, "t1", fh, "|")
        assert count is None


# ---------------------------------------------------------------------------
# RowBatchProcessor
# ---------------------------------------------------------------------------


class TestRowBatchProcessor:
    """Tests for RowBatchProcessor."""

    def test_single_batch(self):
        proc = RowBatchProcessor(batch_size=100)
        fh = io.StringIO("a|b\n1|2\n3|4\n")
        batches = list(proc.process_file(fh, "|", 2))
        assert len(batches) == 1
        data, count = batches[0]
        assert count == 3
        assert len(data) == 3

    def test_multiple_batches(self):
        proc = RowBatchProcessor(batch_size=2)
        fh = io.StringIO("a|b\n1|2\n3|4\n5|6\n")
        batches = list(proc.process_file(fh, "|", 2))
        assert len(batches) == 2
        # First batch of 2 rows
        assert len(batches[0][0]) == 2
        # Remaining 2 rows (header + 1 data)
        assert len(batches[1][0]) == 2

    def test_empty_lines_skipped(self):
        proc = RowBatchProcessor(batch_size=100)
        fh = io.StringIO("a|b\n\n1|2\n\n")
        batches = list(proc.process_file(fh, "|", 2))
        assert len(batches) == 1
        data, count = batches[0]
        assert count == 2  # header + 1 data row

    def test_pads_short_rows(self):
        proc = RowBatchProcessor(batch_size=100)
        fh = io.StringIO("a\n")
        batches = list(proc.process_file(fh, "|", 3))
        data, _ = batches[0]
        assert len(data[0]) == 3  # padded to 3

    def test_truncates_long_rows(self):
        proc = RowBatchProcessor(batch_size=100)
        fh = io.StringIO("a|b|c|d|e\n")
        batches = list(proc.process_file(fh, "|", 2))
        data, _ = batches[0]
        assert len(data[0]) == 2  # truncated to 2

    def test_empty_file(self):
        proc = RowBatchProcessor(batch_size=100)
        fh = io.StringIO("")
        batches = list(proc.process_file(fh, "|", 2))
        assert batches == []


# ---------------------------------------------------------------------------
# BenchmarkTablesSource
# ---------------------------------------------------------------------------


class TestBenchmarkTablesSource:
    """Tests for BenchmarkTablesSource provider."""

    def test_can_provide_with_tables(self):
        benchmark = MagicMock()
        benchmark.tables = {"t1": Path("/a")}
        src = BenchmarkTablesSource()
        assert src.can_provide(benchmark, Path("/data")) is True

    def test_cannot_provide_without_tables_attr(self):
        benchmark = MagicMock(spec=[])  # no tables attribute
        src = BenchmarkTablesSource()
        assert src.can_provide(benchmark, Path("/data")) is False

    def test_cannot_provide_with_empty_tables(self):
        benchmark = MagicMock()
        benchmark.tables = {}
        src = BenchmarkTablesSource()
        assert src.can_provide(benchmark, Path("/data")) is False

    def test_cannot_provide_with_none_tables(self):
        benchmark = MagicMock()
        benchmark.tables = None
        src = BenchmarkTablesSource()
        assert src.can_provide(benchmark, Path("/data")) is False

    def test_get_data_source_normalizes_single_path(self):
        benchmark = MagicMock()
        benchmark.tables = {"customer": Path("/data/customer.tbl")}
        src = BenchmarkTablesSource()
        ds = src.get_data_source(benchmark, Path("/data"))
        assert ds is not None
        assert ds.source_type == "benchmark_tables"
        # Single path should be wrapped in a list
        assert ds.tables["customer"] == [Path("/data/customer.tbl")]

    def test_get_data_source_preserves_list(self):
        benchmark = MagicMock()
        benchmark.tables = {"customer": [Path("/a"), Path("/b")]}
        src = BenchmarkTablesSource()
        ds = src.get_data_source(benchmark, Path("/data"))
        assert ds.tables["customer"] == [Path("/a"), Path("/b")]

    def test_get_data_source_returns_none_when_cannot_provide(self):
        benchmark = MagicMock(spec=[])
        src = BenchmarkTablesSource()
        ds = src.get_data_source(benchmark, Path("/data"))
        assert ds is None

    def test_get_data_source_does_not_populate_table_formats(self, tmp_path):
        """Provider returns empty table_formats - format injection is the resolver's job."""
        benchmark = MagicMock()
        benchmark.tables = {"lineitem": tmp_path / "lineitem.csv.zst"}
        # Write a v2 manifest so we can confirm the provider does NOT read it
        manifest_data = {
            "version": 2,
            "benchmark": "clickbench",
            "scale_factor": 1,
            "format_preference": ["tbl"],
            "tables": {
                "lineitem": {
                    "formats": {
                        "tbl": [{"path": "lineitem.csv.zst", "size_bytes": 100, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        src = BenchmarkTablesSource()
        ds = src.get_data_source(benchmark, tmp_path)

        assert ds is not None
        # Provider must not touch the manifest - table_formats is empty here
        assert ds.table_formats == {}


# ---------------------------------------------------------------------------
# BenchmarkImplTablesSource
# ---------------------------------------------------------------------------


class TestBenchmarkImplTablesSource:
    """Tests for BenchmarkImplTablesSource provider."""

    def test_can_provide_with_impl_tables(self):
        impl = MagicMock()
        impl.tables = {"t1": Path("/a")}
        benchmark = MagicMock()
        benchmark._impl = impl
        src = BenchmarkImplTablesSource()
        assert src.can_provide(benchmark, Path("/data")) is True

    def test_cannot_provide_without_impl(self):
        benchmark = MagicMock(spec=[])
        src = BenchmarkImplTablesSource()
        assert src.can_provide(benchmark, Path("/data")) is False

    def test_cannot_provide_with_no_impl_tables(self):
        impl = MagicMock(spec=[])  # no tables attribute on _impl
        benchmark = MagicMock()
        benchmark._impl = impl
        src = BenchmarkImplTablesSource()
        assert src.can_provide(benchmark, Path("/data")) is False

    def test_get_data_source_normalizes(self):
        impl = MagicMock()
        impl.tables = {"orders": Path("/data/orders.tbl")}
        benchmark = MagicMock()
        benchmark._impl = impl
        src = BenchmarkImplTablesSource()
        ds = src.get_data_source(benchmark, Path("/data"))
        assert ds is not None
        assert ds.source_type == "benchmark_impl_tables"
        assert ds.tables["orders"] == [Path("/data/orders.tbl")]


# ---------------------------------------------------------------------------
# ManifestFileSource - v1
# ---------------------------------------------------------------------------


class TestManifestFileSource:
    """Tests for ManifestFileSource (v1 manifest)."""

    def test_can_provide_when_manifest_exists(self, tmp_path):
        manifest = tmp_path / "_datagen_manifest.json"
        manifest.write_text("{}")
        src = ManifestFileSource()
        assert src.can_provide(MagicMock(), tmp_path) is True

    def test_cannot_provide_when_manifest_missing(self, tmp_path):
        src = ManifestFileSource()
        assert src.can_provide(MagicMock(), tmp_path) is False

    def test_v1_manifest_loads_tables(self, tmp_path):
        manifest_data = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "tables": {
                "customer": [{"path": "customer.tbl", "size_bytes": 100, "row_count": 10}],
                "orders": [
                    {"path": "orders.tbl.1", "size_bytes": 200, "row_count": 20},
                    {"path": "orders.tbl.2", "size_bytes": 200, "row_count": 20},
                ],
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        src = ManifestFileSource()
        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)
        assert ds is not None
        assert ds.source_type == "manifest"
        assert len(ds.tables["customer"]) == 1
        assert len(ds.tables["orders"]) == 2
        assert ds.tables["customer"][0] == tmp_path / "customer.tbl"

    def test_v1_manifest_empty_tables(self, tmp_path):
        manifest_data = {"benchmark": "tpch", "scale_factor": 0.01, "tables": {}}
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))
        src = ManifestFileSource()
        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)
        assert ds is None

    def test_v1_manifest_skips_entries_without_path(self, tmp_path):
        """Entries missing 'path' key are skipped by the v1 fallback parser."""
        manifest_data = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "tables": {
                "t1": [
                    {"path": "a.tbl", "size_bytes": 50, "row_count": 5},
                    {"path": "b.tbl", "size_bytes": 50, "row_count": 5},
                ],
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))
        src = ManifestFileSource()
        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)
        assert ds is not None
        assert len(ds.tables["t1"]) == 2

    def test_manifest_bad_json_returns_none(self, tmp_path):
        (tmp_path / "_datagen_manifest.json").write_text("NOT JSON")
        src = ManifestFileSource()
        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)
        assert ds is None


class TestManifestFileSourceV2:
    """Tests for ManifestFileSource using manifest v2 format selection."""

    def test_manifest_v2_native_mode_prefers_platform_defaults(self, tmp_path):
        """Native-mode platforms use PLATFORM_FORMAT_PREFERENCES, not manifest order."""
        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": ["parquet", "tbl"],
            "tables": {
                "customer": {
                    "formats": {
                        "tbl": [{"path": "customer.tbl", "size_bytes": 100, "row_count": 10}],
                        "parquet": [{"path": "customer.parquet", "size_bytes": 50, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        src = ManifestFileSource()
        src._platform_name = "duckdb"

        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)

        assert ds is not None
        assert ds.source_type == "manifest_v2"
        # DuckDB's PLATFORM_FORMAT_PREFERENCES has tbl first
        assert ds.tables["customer"] == [tmp_path / "customer.tbl"]

    def test_manifest_v2_redshift_native_prefers_platform_default(self, tmp_path):
        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": ["parquet", "tbl"],
            "tables": {
                "customer": {
                    "formats": {
                        "tbl": [{"path": "customer.tbl", "size_bytes": 100, "row_count": 10}],
                        "parquet": [{"path": "customer.parquet", "size_bytes": 50, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        src = ManifestFileSource()
        src._platform_name = "redshift"
        src._table_mode = "native"

        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)

        assert ds is not None
        assert ds.source_type == "manifest_v2"
        assert ds.tables["customer"] == [tmp_path / "customer.tbl"]

    def test_manifest_v2_bigquery_native_prefers_parquet(self, tmp_path):
        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": [],
            "tables": {
                "customer": {
                    "formats": {
                        "tbl": [{"path": "customer.tbl", "size_bytes": 100, "row_count": 10}],
                        "parquet": [{"path": "customer.parquet", "size_bytes": 50, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        src = ManifestFileSource()
        src._platform_name = "bigquery"
        src._table_mode = "native"

        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)

        assert ds is not None
        assert ds.source_type == "manifest_v2"
        assert ds.tables["customer"] == [tmp_path / "customer.parquet"]

    def test_manifest_v2_redshift_external_keeps_manifest_order(self, tmp_path):
        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": ["parquet", "delta", "tbl"],
            "tables": {
                "lineitem": {
                    "formats": {
                        "tbl": [{"path": "lineitem.tbl", "size_bytes": 100, "row_count": 10}],
                        "parquet": [{"path": "lineitem.parquet", "size_bytes": 50, "row_count": 10}],
                        "delta": [{"path": "lineitem", "size_bytes": 75, "row_count": 10, "is_directory": True}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        src = ManifestFileSource()
        src._platform_name = "redshift"
        src._table_mode = "external"
        src._platform_config = {
            "staging_root": "s3://bucket/prefix",
            "iam_role": "arn:aws:iam::123456789012:role/benchbox",
        }

        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)

        assert ds is not None
        assert ds.source_type == "manifest_v2"
        assert ds.tables["lineitem"] == [tmp_path / "lineitem.parquet"]

    def test_manifest_v2_lowercases_table_format_hints_for_mixed_case_tables(self, tmp_path):
        manifest_data = {
            "version": 2,
            "benchmark": "tpcdi",
            "scale_factor": 0.01,
            "format_preference": ["csv"],
            "tables": {
                "DimCustomer": {
                    "formats": {
                        "csv": [{"path": "DimCustomer.csv", "size_bytes": 100, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        src = ManifestFileSource()
        src._platform_name = "datafusion"

        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)

        assert ds is not None
        assert ds.source_type == "manifest_v2"
        assert ds.tables["DimCustomer"] == [tmp_path / "DimCustomer.csv"]
        assert ds.table_formats == {"dimcustomer": "csv"}

    def test_manifest_v2_falls_back_to_first_available_format_when_no_preference_matches(self, tmp_path, monkeypatch):
        manifest_data = {
            "version": 2,
            "benchmark": "tpcdi",
            "scale_factor": 0.01,
            "format_preference": ["parquet"],
            "tables": {
                "DimCustomer": {
                    "formats": {
                        "csv": [{"path": "DimCustomer.csv", "size_bytes": 100, "row_count": 10}],
                        "tbl": [{"path": "DimCustomer.tbl", "size_bytes": 120, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))
        monkeypatch.setattr("benchbox.core.manifest.get_preferred_format", lambda *args, **kwargs: None)

        src = ManifestFileSource()
        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)

        assert ds is not None
        assert ds.tables["DimCustomer"] == [tmp_path / "DimCustomer.csv"]
        assert ds.table_formats == {"dimcustomer": "csv"}

    def test_manifest_v2_returns_none_when_selected_format_has_no_files(self, tmp_path, monkeypatch):
        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": ["parquet"],
            "tables": {
                "lineitem": {
                    "formats": {
                        "parquet": [{"path": "lineitem.parquet", "size_bytes": 50, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))
        monkeypatch.setattr("benchbox.core.manifest.get_preferred_format", lambda *args, **kwargs: "parquet")
        monkeypatch.setattr("benchbox.core.manifest.get_files_for_format", lambda *args, **kwargs: [])

        src = ManifestFileSource()
        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)

        assert ds is None

    def test_manifest_v2_returns_none_when_no_fallback_formats_have_files(self, tmp_path, monkeypatch):
        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": ["parquet"],
            "tables": {
                "lineitem": {
                    "formats": {
                        "csv": [],
                        "tbl": [],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))
        monkeypatch.setattr("benchbox.core.manifest.get_preferred_format", lambda *args, **kwargs: None)

        src = ManifestFileSource()
        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)

        assert ds is None

    def test_manifest_v2_defaults_to_duckdb_when_platform_name_unset(self, tmp_path):
        """When _platform_name is not set, format selection uses 'duckdb' platform defaults."""
        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": ["parquet", "tbl"],
            "tables": {
                "customer": {
                    "formats": {
                        "tbl": [{"path": "customer.tbl", "size_bytes": 100, "row_count": 10}],
                        "parquet": [{"path": "customer.parquet", "size_bytes": 50, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        src = ManifestFileSource()
        # _platform_name intentionally NOT set - defaults to "duckdb" which prefers tbl
        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)

        assert ds is not None
        assert ds.source_type == "manifest_v2"
        # DuckDB's PLATFORM_FORMAT_PREFERENCES has tbl first
        assert ds.tables["customer"] == [tmp_path / "customer.tbl"]

    def test_manifest_v2_non_import_error_falls_back_to_v1(self, tmp_path, monkeypatch):
        """Non-ImportError exceptions in _try_manifest_v2 are caught and v1 fallback runs.

        Previously _try_manifest_v2 only caught ImportError, so RuntimeError etc. would
        propagate and bypass the v1 path. The fix added a separate except Exception handler
        that logs at DEBUG before falling through to v1.
        """
        manifest_data = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "tables": {
                "customer": [{"path": "customer.tbl", "size_bytes": 100, "row_count": 10}],
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        def bad_load(_path):
            raise RuntimeError("simulated non-import error in load_manifest")

        monkeypatch.setattr("benchbox.core.manifest.load_manifest", bad_load, raising=False)

        src = ManifestFileSource()
        ds = src.get_data_source(MagicMock(spec=[]), tmp_path)

        # v1 fallback must have run since _try_manifest_v2 swallowed the RuntimeError
        assert ds is not None
        assert ds.source_type == "manifest"
        assert "customer" in ds.tables


# ---------------------------------------------------------------------------
# ManifestFileSource.read_format_hints
# ---------------------------------------------------------------------------


class TestManifestFileSourceReadFormatHints:
    """Tests for ManifestFileSource.read_format_hints() - the shared helper used by
    DataSourceResolver to inject format metadata after a non-manifest provider wins."""

    def test_returns_empty_when_manifest_missing(self, tmp_path):
        src = ManifestFileSource()
        result = src.read_format_hints(tmp_path / "_datagen_manifest.json", MagicMock(spec=[]), ["t1"])
        assert result == {}

    def test_returns_empty_for_v1_manifest(self, tmp_path):
        """v1 manifests have no per-table format declaration - hints are always empty."""
        manifest_data = {
            "benchmark": "tpch",
            "tables": {"lineitem": [{"path": "lineitem.tbl", "size_bytes": 100, "row_count": 10}]},
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))
        src = ManifestFileSource()
        result = src.read_format_hints(tmp_path / "_datagen_manifest.json", MagicMock(spec=[]), ["lineitem"])
        assert result == {}

    def test_returns_format_for_v2_manifest(self, tmp_path):
        """v2 manifest with tbl format → read_format_hints returns {"lineitem": "tbl"}."""
        manifest_data = {
            "version": 2,
            "benchmark": "clickbench",
            "scale_factor": 1,
            "format_preference": ["tbl", "csv"],
            "tables": {
                "lineitem": {
                    "formats": {
                        "tbl": [{"path": "lineitem.csv.zst", "size_bytes": 100, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))
        src = ManifestFileSource()
        result = src.read_format_hints(tmp_path / "_datagen_manifest.json", MagicMock(spec=[]), ["lineitem"])
        assert result == {"lineitem": "tbl"}

    def test_read_format_hints_defaults_platform_name_to_duckdb(self, tmp_path):
        """read_format_hints uses 'duckdb' platform defaults when _platform_name is not set."""
        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": ["parquet", "tbl"],
            "tables": {
                "customer": {
                    "formats": {
                        "tbl": [{"path": "customer.tbl", "size_bytes": 100, "row_count": 10}],
                        "parquet": [{"path": "customer.parquet", "size_bytes": 50, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))
        src = ManifestFileSource()
        # _platform_name not set → defaults to "duckdb", which prefers tbl via PLATFORM_FORMAT_PREFERENCES
        result = src.read_format_hints(tmp_path / "_datagen_manifest.json", MagicMock(spec=[]), ["customer"])
        assert result == {"customer": "tbl"}

    def test_uses_platform_name_for_format_selection(self, tmp_path):
        """Explicit _platform_name on ManifestFileSource is used, not inferred from benchmark."""
        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": ["parquet", "tbl"],
            "tables": {
                "customer": {
                    "formats": {
                        "parquet": [{"path": "customer.parquet", "size_bytes": 50, "row_count": 10}],
                        "tbl": [{"path": "customer.tbl", "size_bytes": 100, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))
        src = ManifestFileSource()
        src._platform_name = "bigquery"  # explicitly set - should NOT fall through to benchmark mock
        src._table_mode = "native"
        result = src.read_format_hints(tmp_path / "_datagen_manifest.json", MagicMock(spec=[]), ["customer"])
        # Manifest format_preference is ["parquet", "tbl"] - parquet wins for any platform
        assert result.get("customer") == "parquet"

    def test_only_returns_hints_for_requested_tables(self, tmp_path):
        """Only tables in the table_names argument are returned."""
        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": ["tbl"],
            "tables": {
                "customer": {"formats": {"tbl": [{"path": "customer.tbl", "size_bytes": 10, "row_count": 1}]}},
                "orders": {"formats": {"tbl": [{"path": "orders.tbl", "size_bytes": 10, "row_count": 1}]}},
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))
        src = ManifestFileSource()
        result = src.read_format_hints(tmp_path / "_datagen_manifest.json", MagicMock(spec=[]), ["customer"])
        assert "customer" in result
        assert "orders" not in result

    def test_returns_empty_on_exception(self, tmp_path, monkeypatch):
        """Errors in format resolution are swallowed - caller falls back to extension-based detection."""
        manifest_path = tmp_path / "_datagen_manifest.json"
        manifest_path.write_text("{}")  # invalid but parseable JSON

        def bad_load(_path):
            raise RuntimeError("simulated error")

        src = ManifestFileSource()
        monkeypatch.setattr("benchbox.core.manifest.load_manifest", bad_load, raising=False)
        result = src.read_format_hints(manifest_path, MagicMock(), ["t1"])
        assert result == {}

    def test_skips_requested_tables_without_resolved_format(self, tmp_path, monkeypatch):
        """Tables without a resolved preferred format are omitted from the injected hint map."""
        manifest_data = {
            "version": 2,
            "benchmark": "tpcdi",
            "scale_factor": 0.01,
            "format_preference": ["csv"],
            "tables": {
                "DimCustomer": {
                    "formats": {
                        "csv": [{"path": "DimCustomer.csv", "size_bytes": 100, "row_count": 10}],
                    }
                },
                "FactTrade": {
                    "formats": {
                        "csv": [{"path": "FactTrade.csv", "size_bytes": 120, "row_count": 10}],
                    }
                },
            },
        }
        manifest_path = tmp_path / "_datagen_manifest.json"
        manifest_path.write_text(json.dumps(manifest_data))

        def fake_get_preferred_format(_manifest, table_name, *_args, **_kwargs):
            return "csv" if table_name == "DimCustomer" else None

        src = ManifestFileSource()
        monkeypatch.setattr("benchbox.core.manifest.get_preferred_format", fake_get_preferred_format)
        result = src.read_format_hints(manifest_path, MagicMock(spec=[]), ["DimCustomer", "FactTrade"])

        assert result == {"dimcustomer": "csv"}


# ---------------------------------------------------------------------------
# DataSourceResolver
# ---------------------------------------------------------------------------


class TestDataSourceResolver:
    """Tests for DataSourceResolver chain-of-responsibility."""

    def test_prefers_benchmark_tables_first(self, tmp_path):
        """BenchmarkTablesSource has higher priority than manifest."""
        benchmark = MagicMock()
        benchmark.tables = {"t1": Path("/x")}
        # Also create a manifest so we can verify it was NOT used
        manifest_data = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "tables": {"t1": [{"path": "t1.csv", "size_bytes": 10, "row_count": 1}]},
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        resolver = DataSourceResolver()
        ds = resolver.resolve(benchmark, tmp_path)
        assert ds is not None
        assert ds.source_type == "benchmark_tables"

    def test_falls_through_to_manifest(self, tmp_path):
        """When benchmark has no tables, resolver uses manifest."""
        benchmark = MagicMock(spec=[])  # no tables attribute
        manifest_data = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "tables": {"t1": [{"path": "t1.csv", "size_bytes": 10, "row_count": 1}]},
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        resolver = DataSourceResolver()
        ds = resolver.resolve(benchmark, tmp_path)
        assert ds is not None
        assert ds.source_type == "manifest"

    def test_returns_none_when_no_source(self, tmp_path):
        benchmark = MagicMock(spec=[])
        resolver = DataSourceResolver()
        ds = resolver.resolve(benchmark, tmp_path)
        assert ds is None

    def test_platform_name_propagated_to_manifest_source(self):
        resolver = DataSourceResolver(platform_name="snowflake")
        assert getattr(resolver._manifest_source, "_platform_name", None) == "snowflake"

    def test_table_mode_propagated(self):
        resolver = DataSourceResolver(table_mode="external")
        assert getattr(resolver._manifest_source, "_table_mode", None) == "external"

    def test_platform_config_propagated(self):
        cfg = {"key": "value"}
        resolver = DataSourceResolver(platform_config=cfg)
        assert getattr(resolver._manifest_source, "_platform_config", None) is cfg

    def test_format_hints_injected_for_benchmark_tables_source(self, tmp_path):
        """Resolver injects table_formats from manifest when BenchmarkTablesSource wins."""
        # benchmark.tables provides file paths (bypasses ManifestFileSource)
        benchmark = MagicMock()
        benchmark.tables = {"lineitem": tmp_path / "lineitem.csv.zst"}

        manifest_data = {
            "version": 2,
            "benchmark": "clickbench",
            "scale_factor": 1,
            "format_preference": ["tbl", "csv"],
            "tables": {
                "lineitem": {
                    "formats": {
                        "tbl": [{"path": "lineitem.csv.zst", "size_bytes": 100, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        resolver = DataSourceResolver(platform_name="datafusion")
        ds = resolver.resolve(benchmark, tmp_path)

        assert ds is not None
        assert ds.source_type == "benchmark_tables"
        assert ds.table_formats.get("lineitem") == "tbl"

    def test_format_hints_injected_for_mixed_case_benchmark_tables_source(self, tmp_path):
        """Resolver normalizes mixed-case format hints so downstream lowercase lookups succeed."""
        benchmark = MagicMock()
        benchmark.tables = {"DimCustomer": tmp_path / "DimCustomer.csv"}

        manifest_data = {
            "version": 2,
            "benchmark": "tpcdi",
            "scale_factor": 0.01,
            "format_preference": ["csv"],
            "tables": {
                "DimCustomer": {
                    "formats": {
                        "csv": [{"path": "DimCustomer.csv", "size_bytes": 100, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        resolver = DataSourceResolver(platform_name="datafusion")
        ds = resolver.resolve(benchmark, tmp_path)

        assert ds is not None
        assert ds.source_type == "benchmark_tables"
        assert ds.table_formats == {"dimcustomer": "csv"}

    def test_format_hints_injected_for_impl_tables_source(self, tmp_path):
        """Resolver injects table_formats from manifest when BenchmarkImplTablesSource wins."""
        impl = MagicMock()
        impl.tables = {"hits": tmp_path / "hits.csv.zst"}
        benchmark = MagicMock(spec=["_impl"])
        benchmark._impl = impl

        manifest_data = {
            "version": 2,
            "benchmark": "clickbench",
            "scale_factor": 1,
            "format_preference": ["tbl"],
            "tables": {
                "hits": {
                    "formats": {
                        "tbl": [{"path": "hits.csv.zst", "size_bytes": 100, "row_count": 10}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        resolver = DataSourceResolver(platform_name="datafusion")
        ds = resolver.resolve(benchmark, tmp_path)

        assert ds is not None
        assert ds.source_type == "benchmark_impl_tables"
        assert ds.table_formats.get("hits") == "tbl"

    def test_manifest_source_table_formats_not_overwritten(self, tmp_path):
        """When ManifestFileSource wins, its table_formats are preserved (no double-read)."""
        benchmark = MagicMock(spec=[])  # no tables attribute - falls through to manifest

        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": ["parquet", "tbl"],
            "tables": {
                "customer": {
                    "formats": {
                        "parquet": [{"path": "customer.parquet", "size_bytes": 50, "row_count": 5}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))
        (tmp_path / "customer.parquet").write_bytes(b"")

        resolver = DataSourceResolver(platform_name="datafusion")
        ds = resolver.resolve(benchmark, tmp_path)

        assert ds is not None
        assert ds.source_type == "manifest_v2"
        # ManifestFileSource already populated table_formats - resolver must not overwrite
        assert ds.table_formats.get("customer") == "parquet"

    def test_format_hints_empty_when_no_manifest(self, tmp_path):
        """When benchmark.tables wins and no manifest exists, table_formats stays empty."""
        benchmark = MagicMock()
        benchmark.tables = {"orders": tmp_path / "orders.tbl"}
        # No _datagen_manifest.json written

        resolver = DataSourceResolver(platform_name="datafusion")
        ds = resolver.resolve(benchmark, tmp_path)

        assert ds is not None
        assert ds.source_type == "benchmark_tables"
        assert ds.table_formats == {}

    def test_format_hints_empty_for_v1_manifest(self, tmp_path):
        """When benchmark.tables wins and the manifest is v1, table_formats stays empty."""
        benchmark = MagicMock()
        benchmark.tables = {"lineitem": tmp_path / "lineitem.tbl"}
        manifest_data = {
            "benchmark": "tpch",
            "tables": {"lineitem": [{"path": "lineitem.tbl", "size_bytes": 100, "row_count": 10}]},
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        resolver = DataSourceResolver(platform_name="datafusion")
        ds = resolver.resolve(benchmark, tmp_path)

        assert ds is not None
        assert ds.source_type == "benchmark_tables"
        # v1 manifests carry no format metadata
        assert ds.table_formats == {}

    def test_manifest_source_is_shared_with_providers(self):
        """_manifest_source must be the same object as providers[2] so platform_name is injected once."""
        resolver = DataSourceResolver(platform_name="snowflake")
        assert resolver._manifest_source is resolver.providers[2]

    def test_athena_external_replaces_non_parquet_benchmark_tables_with_manifest_selection(self, tmp_path):
        """Athena external mode should replace benchmark text files with manifest-selected Parquet files centrally."""
        benchmark = MagicMock()
        tbl_file = tmp_path / "lineitem.tbl"
        parquet_file = tmp_path / "lineitem.parquet"
        tbl_file.write_text("1|x|\n")
        parquet_file.write_bytes(b"PAR1")
        benchmark.tables = {"lineitem": tbl_file}

        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "format_preference": ["tbl", "parquet"],
            "tables": {
                "lineitem": {
                    "formats": {
                        "tbl": [{"path": "lineitem.tbl", "size_bytes": 5, "row_count": 1}],
                        "parquet": [{"path": "lineitem.parquet", "size_bytes": 4, "row_count": 1}],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        resolver = DataSourceResolver(platform_name="athena", table_mode="external")
        ds = resolver.resolve(benchmark, tmp_path)

        assert ds is not None
        assert ds.source_type == "benchmark_tables"
        assert ds.tables == {"lineitem": [parquet_file]}
        assert ds.table_formats.get("lineitem") == "parquet"

    def test_redshift_native_replaces_directory_benchmark_tables_with_manifest_selection(self, tmp_path):
        """Redshift native mode should replace directory-valued benchmark tables with manifest-selected files."""
        benchmark = MagicMock()
        table_dir = tmp_path / "orders"
        table_dir.mkdir()
        (table_dir / "_delta_log").mkdir()
        (table_dir / "part-00000.parquet").write_bytes(b"PAR1")
        tbl_file = tmp_path / "orders.tbl"
        tbl_file.write_text("1|2024-01-01|O|1.00|\n")
        benchmark.tables = {"orders": [table_dir]}

        manifest_data = {
            "version": 2,
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "format_preference": ["delta", "tbl"],
            "tables": {
                "orders": {
                    "formats": {
                        "delta": [
                            {
                                "path": "orders",
                                "size_bytes": 4,
                                "row_count": 1,
                                "is_directory": True,
                            }
                        ],
                        "tbl": [
                            {
                                "path": "orders.tbl",
                                "size_bytes": tbl_file.stat().st_size,
                                "row_count": 1,
                            }
                        ],
                    }
                }
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest_data))

        resolver = DataSourceResolver(platform_name="redshift", table_mode="native")
        ds = resolver.resolve(benchmark, tmp_path)

        assert ds is not None
        assert ds.source_type == "benchmark_tables"
        assert ds.tables == {"orders": [tbl_file]}
        assert ds.table_formats.get("orders") == "tbl"

    def test_impl_tables_source_format_hints_empty_when_no_manifest(self, tmp_path):
        """BenchmarkImplTablesSource wins, no manifest → table_formats stays empty."""
        impl = MagicMock()
        impl.tables = {"hits": tmp_path / "hits.csv.zst"}
        benchmark = MagicMock(spec=["_impl"])
        benchmark._impl = impl

        resolver = DataSourceResolver(platform_name="datafusion")
        ds = resolver.resolve(benchmark, tmp_path)

        assert ds is not None
        assert ds.source_type == "benchmark_impl_tables"
        assert ds.table_formats == {}


# ---------------------------------------------------------------------------
# InMemoryDataHandler
# ---------------------------------------------------------------------------


class TestInMemoryDataHandler:
    """Tests for InMemoryDataHandler."""

    def test_load_dict_rows(self):
        from benchbox.platforms.base.data_loading import InMemoryDataHandler

        conn = MagicMock()
        rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        count = InMemoryDataHandler.load_table("mytable", rows, conn)
        assert count == 2
        conn.executemany.assert_called_once()

    def test_load_tuple_rows(self):
        from benchbox.platforms.base.data_loading import InMemoryDataHandler

        conn = MagicMock()
        rows = [(1, 2), (3, 4)]
        count = InMemoryDataHandler.load_table("mytable", rows, conn)
        assert count == 2

    def test_load_empty_iterable(self):
        from benchbox.platforms.base.data_loading import InMemoryDataHandler

        conn = MagicMock()
        count = InMemoryDataHandler.load_table("mytable", [], conn)
        assert count == 0

    def test_load_string_returns_zero(self):
        """Strings are iterable but should be rejected."""
        from benchbox.platforms.base.data_loading import InMemoryDataHandler

        conn = MagicMock()
        count = InMemoryDataHandler.load_table("mytable", "not_iterable_data", conn)
        assert count == 0


# ---------------------------------------------------------------------------
# prepare_local_load_file
# ---------------------------------------------------------------------------


class TestPrepareLocalLoadFile:
    """Unit tests for prepare_local_load_file() file-transformation logic.

    Verifies the actual file content produced by the context manager, independent
    of any adapter (SingleStore, QuestDB, PostgreSQL) that calls it.
    """

    def _dialect(self, delimiter=",", null_marker=None, normalize_booleans=False):
        from benchbox.platforms.base.data_loading import CsvDialect

        return CsvDialect(
            delimiter=delimiter,
            has_header=False,
            null_marker=null_marker,
            normalize_booleans=normalize_booleans,
            quote=None,
        )

    def test_no_transform_yields_original_path(self, tmp_path):
        """No-op case: plain CSV with no stripping or boolean normalisation yields the original file."""
        from benchbox.platforms.base.data_loading import prepare_local_load_file

        data_file = tmp_path / "data.csv"
        data_file.write_text("1,foo\n2,bar\n", encoding="utf-8")

        dialect = self._dialect(delimiter=",")
        with prepare_local_load_file(data_file, dialect=dialect, strip_trailing_delim=False) as load_path:
            assert load_path == data_file  # no temp file written

    def test_strip_trailing_delim_removes_trailing_pipe(self, tmp_path):
        """strip_trailing_delim=True removes the trailing delimiter from each line.

        TPC-H dbgen emits "field1|field2|field3|\\n" — the trailing pipe must be
        stripped before LOAD DATA / COPY so the column count matches the schema.
        """
        from benchbox.platforms.base.data_loading import prepare_local_load_file

        data_file = tmp_path / "lineitem.tbl"
        data_file.write_text("1|hello|world|\n2|foo|bar|\n", encoding="utf-8")

        dialect = self._dialect(delimiter="|", null_marker="")
        with prepare_local_load_file(data_file, dialect=dialect, strip_trailing_delim=True) as load_path:
            content = load_path.read_text(encoding="utf-8")

        assert content == "1|hello|world\n2|foo|bar\n"

    def test_no_strip_preserves_trailing_delimiter(self, tmp_path):
        """strip_trailing_delim=False keeps trailing delimiters intact.

        A trailing comma in a CSV line is an empty (NULL) last field, not a
        spurious terminator.  Stripping it would drop the column and cause a
        column-count error on load.
        """
        from benchbox.platforms.base.data_loading import prepare_local_load_file

        # JoinOrder-style line: trailing commas are NULL fields (episode_of_id etc.)
        data_file = tmp_path / "title.csv"
        data_file.write_text("1,Comedy Adventure,,4,1957,,,,,,,\n", encoding="utf-8")

        dialect = self._dialect(delimiter=",", null_marker="")
        with prepare_local_load_file(data_file, dialect=dialect, strip_trailing_delim=False) as load_path:
            content = load_path.read_text(encoding="utf-8")

        assert content == "1,Comedy Adventure,,4,1957,,,,,,,\n"

    def test_strip_trailing_delim_also_works_for_dat_files(self, tmp_path):
        """TPC-DS .dat files also carry a trailing pipe that must be stripped.

        dsdgen emits the same spurious trailing pipe as dbgen. The gate
        ``get_data_extension(path) in (".tbl", ".dat")`` covers both; this test
        locks the .dat case so a future narrowing of the gate is caught.
        """
        from benchbox.platforms.base.data_loading import prepare_local_load_file

        data_file = tmp_path / "customer.dat"
        data_file.write_text("1|Smith|Jane|24525083|\n2|Jones|Bob|99887766|\n", encoding="utf-8")

        dialect = self._dialect(delimiter="|", null_marker="")
        with prepare_local_load_file(data_file, dialect=dialect, strip_trailing_delim=True) as load_path:
            content = load_path.read_text(encoding="utf-8")

        assert content == "1|Smith|Jane|24525083\n2|Jones|Bob|99887766\n"

    def test_strip_only_strips_final_delimiter_not_embedded(self, tmp_path):
        """Stripping removes only the last character when it equals the delimiter.

        A line like "a|b|c|" becomes "a|b|c".  A line like "a|b|c" (no trailing
        delimiter) is left unchanged — the check is conditional on line.endswith(delim).
        """
        from benchbox.platforms.base.data_loading import prepare_local_load_file

        data_file = tmp_path / "mixed.tbl"
        # First line has trailing pipe; second does not (edge case for partial files)
        data_file.write_text("a|b|c|\nd|e|f\n", encoding="utf-8")

        dialect = self._dialect(delimiter="|", null_marker="")
        with prepare_local_load_file(data_file, dialect=dialect, strip_trailing_delim=True) as load_path:
            content = load_path.read_text(encoding="utf-8")

        assert content == "a|b|c\nd|e|f\n"

    def test_boolean_normalisation_rewrites_true_false(self, tmp_path):
        """normalize_booleans=True rewrites True→1, False→0 in each field."""
        from benchbox.platforms.base.data_loading import prepare_local_load_file

        data_file = tmp_path / "data.csv"
        data_file.write_text("True,hello,False\nFalse,world,True\n", encoding="utf-8")

        dialect = self._dialect(delimiter=",", normalize_booleans=True)
        with prepare_local_load_file(data_file, dialect=dialect, strip_trailing_delim=False) as load_path:
            content = load_path.read_text(encoding="utf-8")

        assert content == "1,hello,0\n0,world,1\n"

    def test_temp_file_cleaned_up_after_context(self, tmp_path):
        """The temp file is deleted when the context manager exits."""
        from benchbox.platforms.base.data_loading import prepare_local_load_file

        data_file = tmp_path / "lineitem.tbl"
        data_file.write_text("1|2|3|\n", encoding="utf-8")

        dialect = self._dialect(delimiter="|", null_marker="")
        captured: list[Path] = []
        with prepare_local_load_file(data_file, dialect=dialect, strip_trailing_delim=True) as load_path:
            assert load_path != data_file  # temp file was created
            captured.append(load_path)

        assert not captured[0].exists()  # temp file cleaned up on exit

    def test_load_none_returns_zero(self):
        from benchbox.platforms.base.data_loading import InMemoryDataHandler

        conn = MagicMock()
        count = InMemoryDataHandler.load_table("mytable", None, conn)
        assert count == 0
