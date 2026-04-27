"""Unit tests for file format detection utilities.

Tests for:
- detect_data_format() with all format/compression combinations
- detect_compression() with all compression extensions
- strip_compression_suffix() with single and multi-suffix paths
- is_compression_extension() with valid and invalid inputs
- Edge cases: no suffix, unknown suffix, multiple compressions

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path

import pytest

from benchbox.utils.file_format import (
    COMPRESSION_EXTENSIONS,
    DATA_FORMAT_EXTENSIONS,
    detect_compression,
    detect_data_format,
    get_base_name_without_compression,
    get_data_extension,
    get_delimiter_for_file,
    is_compression_extension,
    is_csv_format,
    is_data_format_extension,
    is_parquet_format,
    is_tpc_format,
    normalize_format_extension,
    strip_compression_suffix,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestCompressionExtensionsConstant:
    """Tests for COMPRESSION_EXTENSIONS constant."""

    def test_contains_all_expected_extensions(self):
        """Verify all expected compression extensions are present."""
        expected = {".zst", ".gz", ".bz2", ".xz", ".lz4", ".snappy"}
        assert expected == COMPRESSION_EXTENSIONS

    def test_is_frozenset(self):
        """Verify constant is immutable."""
        assert isinstance(COMPRESSION_EXTENSIONS, frozenset)


class TestDataFormatExtensionsConstant:
    """Tests for DATA_FORMAT_EXTENSIONS constant."""

    def test_contains_all_expected_extensions(self):
        """Verify all expected data format extensions are present."""
        expected = {".parquet", ".vortex", ".tbl", ".csv", ".dat"}
        assert expected == DATA_FORMAT_EXTENSIONS

    def test_is_frozenset(self):
        """Verify constant is immutable."""
        assert isinstance(DATA_FORMAT_EXTENSIONS, frozenset)


class TestIsCompressionExtension:
    """Tests for is_compression_extension function."""

    @pytest.mark.parametrize(
        "suffix",
        [".zst", ".gz", ".bz2", ".xz", ".lz4", ".snappy"],
    )
    def test_valid_extensions_with_dot(self, suffix):
        """Test valid compression extensions with leading dot."""
        assert is_compression_extension(suffix) is True

    @pytest.mark.parametrize(
        "suffix",
        ["zst", "gz", "bz2", "xz", "lz4", "snappy"],
    )
    def test_valid_extensions_without_dot(self, suffix):
        """Test valid compression extensions without leading dot."""
        assert is_compression_extension(suffix) is True

    @pytest.mark.parametrize(
        "suffix",
        [".ZST", ".GZ", ".BZ2", ".XZ", ".LZ4", ".SNAPPY"],
    )
    def test_case_insensitive(self, suffix):
        """Test that extension checking is case-insensitive."""
        assert is_compression_extension(suffix) is True

    @pytest.mark.parametrize(
        "suffix",
        [".parquet", ".tbl", ".csv", ".txt", ".json", ""],
    )
    def test_non_compression_extensions(self, suffix):
        """Test non-compression extensions return False."""
        assert is_compression_extension(suffix) is False


class TestIsDataFormatExtension:
    """Tests for is_data_format_extension function."""

    @pytest.mark.parametrize(
        "suffix",
        [".parquet", ".vortex", ".tbl", ".csv", ".dat"],
    )
    def test_valid_extensions_with_dot(self, suffix):
        """Test valid data format extensions with leading dot."""
        assert is_data_format_extension(suffix) is True

    @pytest.mark.parametrize(
        "suffix",
        ["parquet", "vortex", "tbl", "csv", "dat"],
    )
    def test_valid_extensions_without_dot(self, suffix):
        """Test valid data format extensions without leading dot."""
        assert is_data_format_extension(suffix) is True

    @pytest.mark.parametrize(
        "suffix",
        [".PARQUET", ".VORTEX", ".TBL", ".CSV", ".DAT"],
    )
    def test_case_insensitive(self, suffix):
        """Test that extension checking is case-insensitive."""
        assert is_data_format_extension(suffix) is True

    @pytest.mark.parametrize(
        "suffix",
        [".zst", ".gz", ".txt", ".json", ""],
    )
    def test_non_format_extensions(self, suffix):
        """Test non-format extensions return False."""
        assert is_data_format_extension(suffix) is False


class TestDetectCompression:
    """Tests for detect_compression function."""

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("data.tbl.zst", "zstd"),
            ("data.csv.gz", "gzip"),
            ("archive.tar.bz2", "bzip2"),
            ("file.xz", "xz"),
            ("data.lz4", "lz4"),
            ("data.snappy", "snappy"),
        ],
    )
    def test_compressed_files(self, filename, expected):
        """Test detection of compressed files."""
        assert detect_compression(Path(filename)) == expected

    @pytest.mark.parametrize(
        "filename",
        [
            "data.parquet",
            "data.tbl",
            "data.csv",
            "file.txt",
            "noextension",
        ],
    )
    def test_uncompressed_files(self, filename):
        """Test uncompressed files return None."""
        assert detect_compression(Path(filename)) is None

    def test_accepts_string_path(self):
        """Test function accepts string paths."""
        assert detect_compression("data.csv.gz") == "gzip"

    def test_case_insensitive(self):
        """Test compression detection is case-insensitive."""
        assert detect_compression(Path("data.ZST")) == "zstd"
        assert detect_compression(Path("data.GZ")) == "gzip"


class TestDetectDataFormat:
    """Tests for detect_data_format function."""

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            # Uncompressed formats
            ("data.parquet", "parquet"),
            ("data.tbl", "tbl"),
            ("data.csv", "csv"),
            ("customer.dat", "tbl"),  # .dat is TPC-DS format, same as .tbl
            # Compressed formats
            ("data.tbl.zst", "tbl"),
            ("data.csv.gz", "csv"),
            ("data.parquet.lz4", "parquet"),
            ("customer.tbl.bz2", "tbl"),
            ("orders.csv.xz", "csv"),
            ("data.dat.snappy", "tbl"),
        ],
    )
    def test_format_detection(self, filename, expected):
        """Test format detection for various file types."""
        assert detect_data_format(Path(filename)) == expected

    def test_unknown_format_defaults_to_csv(self):
        """Test unknown formats default to csv."""
        assert detect_data_format(Path("data.txt")) == "csv"
        assert detect_data_format(Path("data.json")) == "csv"
        assert detect_data_format(Path("noextension")) == "csv"

    def test_accepts_string_path(self):
        """Test function accepts string paths."""
        assert detect_data_format("data.tbl.zst") == "tbl"

    def test_case_insensitive(self):
        """Test format detection is case-insensitive."""
        assert detect_data_format(Path("data.TBL.ZST")) == "tbl"
        assert detect_data_format(Path("DATA.PARQUET")) == "parquet"

    def test_multiple_suffixes(self):
        """Test files with multiple non-compression suffixes."""
        # First recognized format wins
        assert detect_data_format(Path("data.backup.tbl")) == "tbl"
        assert detect_data_format(Path("file.1.csv")) == "csv"


class TestStripCompressionSuffix:
    """Tests for strip_compression_suffix function."""

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("data.tbl.zst", "data.tbl"),
            ("data.csv.gz", "data.csv"),
            ("archive.tar.bz2", "archive.tar"),
            ("file.xz", "file"),
            ("data.parquet.lz4", "data.parquet"),
            ("data.snappy", "data"),
        ],
    )
    def test_strips_compression_suffix(self, filename, expected):
        """Test stripping compression suffixes."""
        result = strip_compression_suffix(Path(filename))
        assert result == Path(expected)

    @pytest.mark.parametrize(
        "filename",
        [
            "data.parquet",
            "data.tbl",
            "data.csv",
            "noextension",
        ],
    )
    def test_preserves_non_compressed_paths(self, filename):
        """Test non-compressed paths are unchanged."""
        path = Path(filename)
        result = strip_compression_suffix(path)
        assert result == path

    def test_accepts_string_path(self):
        """Test function accepts string paths."""
        result = strip_compression_suffix("data.tbl.zst")
        assert result == Path("data.tbl")

    def test_returns_path_object(self):
        """Test function returns Path object."""
        result = strip_compression_suffix("data.tbl.zst")
        assert isinstance(result, Path)

    def test_case_insensitive(self):
        """Test suffix stripping is case-insensitive."""
        result = strip_compression_suffix(Path("data.ZST"))
        assert result == Path("data")


class TestGetBaseNameWithoutCompression:
    """Tests for get_base_name_without_compression function."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/data/file.tbl.zst", "file.tbl"),
            ("file.csv.gz", "file.csv"),
            ("/path/to/data.parquet", "data.parquet"),
            ("nocompression.tbl", "nocompression.tbl"),
        ],
    )
    def test_extracts_base_name(self, path, expected):
        """Test extracting base name without compression suffix."""
        assert get_base_name_without_compression(path) == expected

    def test_accepts_path_object(self):
        """Test function accepts Path objects."""
        result = get_base_name_without_compression(Path("/data/file.tbl.zst"))
        assert result == "file.tbl"


class TestNormalizeFormatExtension:
    """Tests for normalize_format_extension function."""

    @pytest.mark.parametrize(
        ("suffix", "expected"),
        [
            (".parquet", "parquet"),
            (".tbl", "tbl"),
            (".csv", "csv"),
            (".dat", "tbl"),  # Normalized to tbl
            ("parquet", "parquet"),  # Without leading dot
            ("TBL", "tbl"),  # Case-insensitive
        ],
    )
    def test_normalizes_extensions(self, suffix, expected):
        """Test extension normalization."""
        assert normalize_format_extension(suffix) == expected

    def test_unknown_extension_defaults_to_csv(self):
        """Test unknown extensions default to csv."""
        assert normalize_format_extension(".txt") == "csv"
        assert normalize_format_extension(".unknown") == "csv"


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_empty_path(self):
        """Test handling of empty/minimal paths."""
        assert detect_data_format(Path("")) == "csv"
        assert detect_compression(Path("")) is None
        assert strip_compression_suffix(Path("")) == Path("")

    def test_only_compression_extension(self):
        """Test file with only compression extension.

        Note: Path(".zst") is treated as a hidden file named ".zst" with no extension,
        so we use "file.zst" to test this edge case.
        """
        # A file with only compression extension (unusual but valid)
        assert detect_data_format(Path("file.zst")) == "csv"  # Unknown format, defaults to csv
        assert detect_compression(Path("file.zst")) == "zstd"
        assert strip_compression_suffix(Path("file.zst")) == Path("file")

    def test_hidden_files(self):
        """Test hidden files (starting with dot)."""
        assert detect_data_format(Path(".data.tbl.zst")) == "tbl"
        assert detect_compression(Path(".data.gz")) == "gzip"

    def test_deeply_nested_path(self):
        """Test deeply nested file paths."""
        path = Path("/very/deep/nested/path/to/file.tbl.zst")
        assert detect_data_format(path) == "tbl"
        assert detect_compression(path) == "zstd"
        assert strip_compression_suffix(path) == Path("/very/deep/nested/path/to/file.tbl")

    def test_sharded_file_pattern(self):
        """Test TPC sharded file patterns like customer.tbl.1.zst."""
        path = Path("customer.tbl.1.zst")
        assert detect_compression(path) == "zstd"
        assert detect_data_format(path) == "tbl"
        assert strip_compression_suffix(path) == Path("customer.tbl.1")

    def test_double_compression_extension(self):
        """Test files with what looks like double compression."""
        # Only the last suffix is considered for compression
        path = Path("data.gz.zst")
        assert detect_compression(path) == "zstd"
        # After stripping, we get .gz which is also compression
        stripped = strip_compression_suffix(path)
        assert stripped == Path("data.gz")


class TestIsTpcFormat:
    """Tests for is_tpc_format function."""

    @pytest.mark.parametrize("path", ["data.tbl", Path("data.tbl")])
    def test_simple_tbl(self, path):
        """Test simple .tbl files."""
        assert is_tpc_format(path) is True

    @pytest.mark.parametrize("path", ["data.dat", Path("data.dat")])
    def test_simple_dat(self, path):
        """Test simple .dat files (TPC-DS format)."""
        assert is_tpc_format(path) is True

    @pytest.mark.parametrize(
        "path",
        ["data.tbl.zst", "data.tbl.gz", "data.tbl.bz2", "data.tbl.xz", "data.tbl.lz4"],
    )
    def test_compressed_tbl(self, path):
        """Test compressed .tbl files."""
        assert is_tpc_format(path) is True

    @pytest.mark.parametrize("path", ["data.dat.zst", "data.dat.gz"])
    def test_compressed_dat(self, path):
        """Test compressed .dat files."""
        assert is_tpc_format(path) is True

    @pytest.mark.parametrize("path", ["data.csv", "data.parquet", "data.json", "data.txt"])
    def test_non_tpc_formats(self, path):
        """Test non-TPC formats return False."""
        assert is_tpc_format(path) is False

    def test_sharded_tpc_file(self):
        """Test sharded TPC file pattern like customer.tbl.1."""
        assert is_tpc_format("customer.tbl.1") is True
        assert is_tpc_format("customer.tbl.1.zst") is True

    def test_case_insensitive(self):
        """Test case-insensitive detection."""
        assert is_tpc_format("data.TBL") is True
        assert is_tpc_format("data.DAT.ZST") is True


class TestIsParquetFormat:
    """Tests for is_parquet_format function."""

    @pytest.mark.parametrize("path", ["data.parquet", Path("data.parquet")])
    def test_simple_parquet(self, path):
        """Test simple .parquet files."""
        assert is_parquet_format(path) is True

    @pytest.mark.parametrize(
        "path",
        ["data.parquet.zst", "data.parquet.gz", "data.parquet.bz2", "data.parquet.lz4"],
    )
    def test_compressed_parquet(self, path):
        """Test compressed .parquet files."""
        assert is_parquet_format(path) is True

    @pytest.mark.parametrize("path", ["data.csv", "data.tbl", "data.dat", "data.json"])
    def test_non_parquet_formats(self, path):
        """Test non-parquet formats return False."""
        assert is_parquet_format(path) is False

    def test_sharded_parquet_file(self):
        """Test sharded parquet file pattern like data.parquet.1."""
        # Sharded files have numeric suffix after .parquet
        assert is_parquet_format("data.parquet.1") is True
        assert is_parquet_format("data.parquet.1.zst") is True

    def test_case_insensitive(self):
        """Test case-insensitive detection."""
        assert is_parquet_format("data.PARQUET") is True
        assert is_parquet_format("data.Parquet.ZST") is True

    def test_empty_path(self):
        """Test empty path returns False."""
        assert is_parquet_format("") is False
        assert is_parquet_format(Path("")) is False


class TestIsCsvFormat:
    """Tests for is_csv_format function."""

    @pytest.mark.parametrize("path", ["data.csv", Path("data.csv")])
    def test_simple_csv(self, path):
        """Test simple .csv files."""
        assert is_csv_format(path) is True

    @pytest.mark.parametrize(
        "path",
        ["data.csv.gz", "data.csv.zst", "data.csv.bz2", "data.csv.xz"],
    )
    def test_compressed_csv(self, path):
        """Test compressed .csv files."""
        assert is_csv_format(path) is True

    @pytest.mark.parametrize("path", ["data.parquet", "data.tbl", "data.dat", "data.json"])
    def test_non_csv_formats(self, path):
        """Test non-csv formats return False."""
        assert is_csv_format(path) is False

    def test_case_insensitive(self):
        """Test case-insensitive detection."""
        assert is_csv_format("data.CSV") is True
        assert is_csv_format("data.Csv.GZ") is True

    def test_empty_path(self):
        """Test empty path returns False."""
        assert is_csv_format("") is False
        assert is_csv_format(Path("")) is False


class TestGetDelimiterForFile:
    """Tests for get_delimiter_for_file function."""

    @pytest.mark.parametrize(
        "path",
        ["lineitem.tbl", "store_sales.dat", "data.tbl.zst", "data.dat.gz"],
    )
    def test_tpc_format_returns_pipe(self, path):
        """Test TPC formats return pipe delimiter."""
        assert get_delimiter_for_file(path) == "|"

    @pytest.mark.parametrize(
        "path",
        ["data.csv", "data.parquet", "data.csv.gz", "data.json", "unknown.txt"],
    )
    def test_non_tpc_format_returns_comma(self, path):
        """Test non-TPC formats return comma delimiter."""
        assert get_delimiter_for_file(path) == ","

    def test_accepts_path_object(self):
        """Test function accepts Path objects."""
        assert get_delimiter_for_file(Path("lineitem.tbl")) == "|"
        assert get_delimiter_for_file(Path("data.csv")) == ","

    def test_sharded_tpc_file(self):
        """Test sharded TPC file returns pipe delimiter."""
        assert get_delimiter_for_file("customer.tbl.1") == "|"
        assert get_delimiter_for_file("customer.tbl.1.zst") == "|"


class TestGetDataExtension:
    """Tests for get_data_extension function."""

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            # Uncompressed formats
            ("lineitem.tbl", ".tbl"),
            ("store_sales.dat", ".dat"),
            ("data.csv", ".csv"),
            ("data.parquet", ".parquet"),
            ("data.vortex", ".vortex"),
            # Compressed formats
            ("store_sales.dat.zst", ".dat"),
            ("lineitem.tbl.gz", ".tbl"),
            ("data.csv.bz2", ".csv"),
            ("data.parquet.lz4", ".parquet"),
            ("data.vortex.xz", ".vortex"),
        ],
    )
    def test_basic_formats(self, filename, expected):
        assert get_data_extension(Path(filename)) == expected

    def test_numeric_shard_single_digit(self):
        """Shard suffix (.7) is skipped to reveal the data extension."""
        assert get_data_extension(Path("customer.tbl.7.zst")) == ".tbl"

    def test_numeric_shard_multi_digit(self):
        """Multi-digit shard suffix (.10) is skipped."""
        assert get_data_extension(Path("customer.tbl.10.zst")) == ".tbl"

    def test_numeric_shard_uncompressed(self):
        """Shard without compression wrapper is handled."""
        assert get_data_extension(Path("customer.tbl.7")) == ".tbl"

    def test_multiple_compression_layers(self):
        """Multiple compression suffixes are all skipped."""
        assert get_data_extension(Path("hits.csv.gz.bz2")) == ".csv"

    def test_unknown_suffix_skipped(self):
        """Unrecognized suffixes (e.g. .bak) are skipped, not treated as a stop."""
        assert get_data_extension(Path("data.tbl.bak")) == ".tbl"

    def test_no_extension(self):
        assert get_data_extension(Path("README")) is None

    def test_only_compression_suffix(self):
        assert get_data_extension(Path("file.zst")) is None

    def test_unknown_suffix_only(self):
        assert get_data_extension(Path("file.txt")) is None

    def test_accepts_string_path(self):
        assert get_data_extension("lineitem.tbl.zst") == ".tbl"

    def test_case_insensitive(self):
        assert get_data_extension(Path("DATA.TBL.ZST")) == ".tbl"
        assert get_data_extension(Path("store_sales.DAT.GZ")) == ".dat"

    def test_dat_not_collapsed_to_tbl(self):
        """Critical: .dat must be returned as '.dat', not '.tbl' (unlike detect_data_format)."""
        assert get_data_extension(Path("store_sales.dat")) == ".dat"
        assert get_data_extension(Path("store_sales.dat")) != ".tbl"
