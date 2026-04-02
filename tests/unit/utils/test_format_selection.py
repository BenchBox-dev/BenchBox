"""Tests for format selection logic."""

from pathlib import Path

import pytest

from benchbox.utils.format_selection import FormatSelector

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestFormatSelector:
    """Tests for FormatSelector class."""

    def test_select_format_with_preference(self):
        """Test format selection with user preference."""
        selector = FormatSelector()
        result = selector.select_format(
            platform_name="duckdb",
            available_formats=["tbl", "parquet"],
            user_preference="parquet",
        )
        assert result == "parquet"

    def test_select_format_without_preference(self):
        """Test format selection without user preference (uses platform default)."""
        selector = FormatSelector()
        result = selector.select_format(
            platform_name="duckdb",
            available_formats=["tbl", "parquet"],
            user_preference=None,
        )
        assert result == "tbl"  # DuckDB prefers text files

    def test_select_format_databricks_prefers_delta(self):
        """Test that Databricks prefers Delta over Parquet."""
        selector = FormatSelector()
        result = selector.select_format(
            platform_name="databricks",
            available_formats=["tbl", "parquet", "delta"],
            user_preference=None,
        )
        assert result == "delta"

    def test_select_format_invalid_preference(self):
        """Test that invalid preference raises error."""
        selector = FormatSelector()
        with pytest.raises(ValueError, match="not available"):
            selector.select_format(
                platform_name="duckdb",
                available_formats=["tbl"],
                user_preference="parquet",
            )

    def test_select_format_unsupported_preference(self):
        """Test that unsupported format raises error."""
        selector = FormatSelector()
        with pytest.raises(ValueError, match="not supported"):
            selector.select_format(
                platform_name="clickhouse",
                available_formats=["tbl", "delta"],
                user_preference="delta",  # ClickHouse doesn't support Delta
            )

    def test_select_format_no_formats_available(self):
        """Test format selection with no formats available."""
        selector = FormatSelector()
        result = selector.select_format(
            platform_name="duckdb",
            available_formats=[],
            user_preference=None,
        )
        assert result == "tbl"  # Fallback to tbl

    def test_get_fallback_chain(self):
        """Test fallback chain generation."""
        selector = FormatSelector()
        chain = selector.get_fallback_chain(
            platform_name="duckdb",
            available_formats=["tbl", "parquet", "csv"],
        )
        # Should be in order of preference (tbl first, then parquet before csv)
        assert chain[0] == "tbl"
        assert chain.index("parquet") < chain.index("csv")
        assert "csv" in chain

    def test_get_fallback_chain_databricks(self):
        """Test fallback chain for Databricks."""
        selector = FormatSelector()
        chain = selector.get_fallback_chain(
            platform_name="databricks",
            available_formats=["tbl", "parquet", "delta"],
        )
        # Delta should be first
        assert chain[0] == "delta"
        assert chain[1] == "parquet"

    def test_get_fallback_chain_bigquery_prefers_parquet(self):
        """Test fallback chain for BigQuery prefers parquet over text sources."""
        selector = FormatSelector()
        chain = selector.get_fallback_chain(
            platform_name="bigquery",
            available_formats=["tbl", "parquet", "csv"],
        )
        assert chain == ["parquet", "tbl", "csv"]

    def test_detect_available_formats_from_manifest(self):
        """Test format detection from manifest data."""
        selector = FormatSelector()
        manifest_data = {
            "version": 2,
            "formats": ["tbl", "parquet"],
        }
        formats = selector.detect_available_formats(
            data_dir=Path("/tmp"),
            table_name="customer",
            manifest_data=manifest_data,
        )
        assert formats == ["tbl", "parquet"]

    def test_detect_available_formats_from_table_specific_manifest(self):
        """Test format detection from table-specific manifest data."""
        selector = FormatSelector()
        manifest_data = {
            "version": 2,
            "formats": ["parquet", "delta"],
            "tables": {
                "customer": {
                    "formats": {"parquet": [], "delta": []},
                }
            },
        }
        formats = selector.detect_available_formats(
            data_dir=Path("/tmp"),
            table_name="customer",
            manifest_data=manifest_data,
        )
        assert formats == ["parquet", "delta"]

    def test_detect_available_formats_from_table_formats_dict(self):
        """Test detection when table formats are stored as mapping of format->entries."""
        selector = FormatSelector()
        manifest_data = {
            "version": 2,
            "formats": ["delta", "parquet"],
            "tables": {
                "customer": {
                    "formats": {
                        "parquet": [{"path": "customer.parquet"}],
                        "delta": [{"path": "customer"}],
                    }
                }
            },
        }

        formats = selector.detect_available_formats(
            data_dir=Path("/tmp"),
            table_name="customer",
            manifest_data=manifest_data,
        )

        assert formats == ["delta", "parquet"]

    def test_detect_available_formats_fallback_to_tbl(self, tmp_path):
        """Test format detection falls back to tbl when nothing found."""
        selector = FormatSelector()
        formats = selector.detect_available_formats(
            data_dir=tmp_path,
            table_name="customer",
            manifest_data=None,
        )
        assert formats == ["tbl"]
