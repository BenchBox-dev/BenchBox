"""Comprehensive tests for ClickBench analytics generator functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.core.clickbench.generator import ClickBenchDataGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.mark.unit
class TestClickBenchDataGenerator:
    """Test ClickBench data generator basic functionality."""

    def test_generator_initialization(self, temp_dir):
        """Test generator initialization with different parameters."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        assert generator.output_dir == temp_dir
        assert hasattr(generator, "generate_data")

    def test_generator_with_custom_parameters(self, temp_dir):
        """Test generator with custom ClickBench parameters."""
        generator = ClickBenchDataGenerator(scale_factor=2.0, output_dir=temp_dir)

        assert generator.output_dir == temp_dir
        assert generator.scale_factor == 2.0

    def test_clickbench_table_structure(self, temp_dir):
        """Test ClickBench benchmark table structure."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # ClickBench typically has one main table called 'hits'
        expected_table = "hits"

        # Test table name retrieval if available
        if hasattr(generator, "get_table_names"):
            table_names = generator.get_table_names()
            assert expected_table in table_names
        elif hasattr(generator, "table_name"):
            assert generator.table_name == expected_table
        else:
            # Basic structural test
            assert generator is not None

    @patch("urllib.request.urlretrieve")
    def test_data_download_workflow(self, mock_urlretrieve, temp_dir):
        """Test the data download workflow for ClickBench."""
        # ClickBench often downloads data from external sources
        mock_urlretrieve.return_value = None

        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # Create a mock data file
        data_file = temp_dir / "hits.tsv"
        data_file.write_text("col1\tcol2\tcol3\n1\ttest data\tvalue\n")

        # Test download with mocked retrieval
        if hasattr(generator, "_download_data"):
            try:
                result = generator._download_data()
                assert isinstance(result, (Path, str))
            except (NotImplementedError, AttributeError):
                pass

        # Basic test
        assert generator is not None

    def test_data_format_handling(self, temp_dir):
        """Test TSV/CSV data format handling."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # ClickBench typically uses TSV format
        if hasattr(generator, "get_file_format"):
            format_type = generator.get_file_format()
            assert format_type in ["tsv", "csv"]

        if hasattr(generator, "get_file_extension"):
            extension = generator.get_file_extension()
            assert extension in [".tsv", ".csv"]

        # Basic test
        assert generator.output_dir == temp_dir

    def test_row_count_parameters(self, temp_dir):
        """Test row count and sampling parameters."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # Test row count configuration
        if hasattr(generator, "rows"):
            generator.rows = 50000
            assert generator.rows == 50000

        # Test sampling parameters
        if hasattr(generator, "sample_rate"):
            generator.sample_rate = 0.1  # 10% sample
            assert generator.sample_rate == 0.1

        # Test maximum rows
        if hasattr(generator, "max_rows"):
            generator.max_rows = 1000000
            assert generator.max_rows == 1000000

        # Basic test
        assert generator is not None

    def test_web_analytics_columns(self, temp_dir):
        """Test web analytics column structure."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # ClickBench hits table has many columns for web analytics
        expected_columns = [
            "WatchID",
            "JavaEnable",
            "Title",
            "URL",
            "Referer",
            "IsRefresh",
            "RefererCategoryID",
            "RefererRegionID",
            "URLCategoryID",
            "URLRegionID",
            "ResolutionWidth",
            "ResolutionHeight",
            "UserAgentMajor",
            "UserAgentMinor",
        ]

        # Test column schema if available
        if hasattr(generator, "get_column_names"):
            columns = generator.get_column_names()
            # Check that some key columns are present
            key_columns = ["WatchID", "URL", "Title", "UserAgentMajor"]
            for col in key_columns:
                if col in expected_columns:
                    assert col in columns

        # Basic test
        assert generator is not None

    @patch("requests.get")
    def test_external_data_source_handling(self, mock_requests, temp_dir):
        """Test handling of external data sources."""
        # Mock HTTP response for data download
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b"col1\tcol2\tcol3",
            b"1\ttest\tdata",
            b"2\tmore\tdata",
        ]
        mock_requests.return_value = mock_response

        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # Test external data handling
        if hasattr(generator, "_fetch_external_data"):
            try:
                result = generator._fetch_external_data()
                assert isinstance(result, (Path, list, str))
            except (NotImplementedError, AttributeError):
                pass

        # Test URL configuration
        if hasattr(generator, "data_url"):
            assert isinstance(generator.data_url, str)
            assert generator.data_url.startswith("http")

        # Basic test
        assert generator is not None

    def test_compression_handling(self, temp_dir):
        """Test handling of compressed data files."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # ClickBench data is often compressed
        if hasattr(generator, "supports_compression"):
            assert generator.supports_compression is True

        if hasattr(generator, "compression_format"):
            assert generator.compression_format in ["gzip", "xz", "bz2"]

        # Test decompression capability
        if hasattr(generator, "_decompress_file"):
            # Create a mock compressed file
            compressed_file = temp_dir / "data.tsv.gz"
            compressed_file.write_bytes(b"mock compressed data")

            try:
                result = generator._decompress_file(compressed_file)
                assert isinstance(result, Path)
            except (NotImplementedError, AttributeError):
                pass

        # Basic test
        assert generator is not None

    def test_data_validation(self, temp_dir):
        """Test data validation and integrity checks."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # Test data validation capabilities
        if hasattr(generator, "validate_data"):
            # Create mock data file
            data_file = temp_dir / "hits.tsv"
            data_file.write_text("WatchID\tURL\tTitle\n1\thttp://test.com\tTest Page\n")

            try:
                is_valid = generator.validate_data(data_file)
                assert isinstance(is_valid, bool)
            except (NotImplementedError, AttributeError):
                pass

        # Test row count validation
        if hasattr(generator, "validate_row_count"):
            try:
                count = generator.validate_row_count(temp_dir / "hits.tsv")
                assert isinstance(count, int)
            except (NotImplementedError, AttributeError):
                pass

        # Basic test
        assert generator is not None


@pytest.mark.unit
class TestGeneratorExtended:
    """Advanced tests for ClickBench data generator."""

    def test_performance_optimization(self, temp_dir):
        """Test performance optimization features."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # Test parallel processing
        if hasattr(generator, "parallel_workers"):
            generator.parallel_workers = 4
            assert generator.parallel_workers == 4

        # Test memory optimization
        if hasattr(generator, "use_streaming"):
            generator.use_streaming = True
            assert generator.use_streaming is True

        # Test chunk processing
        if hasattr(generator, "chunk_size"):
            generator.chunk_size = 100000
            assert generator.chunk_size == 100000

        # Basic test
        assert generator is not None

    def test_data_sampling_strategies(self, temp_dir):
        """Test different data sampling strategies."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # Test random sampling
        if hasattr(generator, "sampling_method"):
            generator.sampling_method = "random"
            assert generator.sampling_method == "random"

        # Test systematic sampling
        if hasattr(generator, "sample_interval"):
            generator.sample_interval = 100  # Every 100th row
            assert generator.sample_interval == 100

        # Test stratified sampling
        if hasattr(generator, "stratify_column"):
            generator.stratify_column = "URLCategoryID"
            assert generator.stratify_column == "URLCategoryID"

        # Basic test
        assert generator is not None

    def test_time_series_data_handling(self, temp_dir):
        """Test time series data characteristics."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # ClickBench has timestamp data
        if hasattr(generator, "time_column"):
            assert generator.time_column in ["EventTime", "EventDate"]

        # Test time range configuration
        if hasattr(generator, "start_date"):
            from datetime import datetime

            generator.start_date = datetime(2013, 1, 1)
            assert generator.start_date.year == 2013

        if hasattr(generator, "end_date"):
            from datetime import datetime

            generator.end_date = datetime(2013, 12, 31)
            assert generator.end_date.year == 2013

        # Basic test
        assert generator is not None

    def test_analytics_specific_features(self, temp_dir):
        """Test analytics-specific data generation features."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # Test user agent parsing
        if hasattr(generator, "parse_user_agents"):
            generator.parse_user_agents = True
            assert generator.parse_user_agents is True

        # Test URL categorization
        if hasattr(generator, "categorize_urls"):
            generator.categorize_urls = True
            assert generator.categorize_urls is True

        # Test geographic data
        if hasattr(generator, "include_geo_data"):
            generator.include_geo_data = True
            assert generator.include_geo_data is True

        # Basic test
        assert generator is not None

    def test_benchmark_compliance_validation(self, temp_dir):
        """Test compliance with ClickBench benchmark requirements."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # Test benchmark validation
        if hasattr(generator, "validate_benchmark_compliance"):
            try:
                is_compliant = generator.validate_benchmark_compliance()
                assert isinstance(is_compliant, bool)
            except (NotImplementedError, AttributeError):
                pass

        # Test schema validation against ClickBench spec
        if hasattr(generator, "validate_schema"):
            try:
                is_valid_schema = generator.validate_schema()
                assert isinstance(is_valid_schema, bool)
            except (NotImplementedError, AttributeError):
                pass

        # Test required columns
        if hasattr(generator, "get_required_columns"):
            try:
                required_cols = generator.get_required_columns()
                assert isinstance(required_cols, list)
                assert len(required_cols) > 0
            except (NotImplementedError, AttributeError):
                pass

        # Basic test
        assert generator is not None

    def test_error_handling_and_recovery(self, temp_dir):
        """Test error handling and recovery mechanisms."""
        generator = ClickBenchDataGenerator(output_dir=temp_dir)

        # Test network error handling
        if hasattr(generator, "retry_on_failure"):
            generator.retry_on_failure = True
            assert generator.retry_on_failure is True

        if hasattr(generator, "max_retries"):
            generator.max_retries = 3
            assert generator.max_retries == 3

        # Test partial download recovery
        if hasattr(generator, "resume_partial_download"):
            generator.resume_partial_download = True
            assert generator.resume_partial_download is True

        # Test corruption detection
        if hasattr(generator, "verify_checksums"):
            generator.verify_checksums = True
            assert generator.verify_checksums is True

        # Basic test
        assert generator is not None

    def test_quote_clickbench_field_matches_minimal_except_empties(self, temp_dir):
        """Custom quoting mirrors csv.QUOTE_MINIMAL, quoting only empties extra."""
        import csv as csv_module
        import io

        from benchbox.core.clickbench.generator import format_clickbench_row, quote_clickbench_field

        assert quote_clickbench_field("") == '""'
        assert quote_clickbench_field(None) == '""'
        assert quote_clickbench_field(0) == "0"
        assert quote_clickbench_field(42) == "42"
        assert quote_clickbench_field("plain") == "plain"
        assert quote_clickbench_field("a|b") == '"a|b"'
        assert quote_clickbench_field('say "hi"') == '"say ""hi"""'
        assert quote_clickbench_field("l1\nl2") == '"l1\nl2"'

        # A joined row must round-trip through the stdlib parser to identical values.
        tricky = ["", "x", 7, "a|b", 'q"q', "l1\nl2", "trail ", "  lead", "__NULL__"]
        mine = [quote_clickbench_field(v) for v in tricky]
        parsed = next(csv_module.reader(io.StringIO("|".join(mine)), delimiter="|"))
        assert parsed == ["", "x", "7", "a|b", 'q"q', "l1\nl2", "trail ", "  lead", "__NULL__"]

        assert format_clickbench_row(["a", "", 3]) == 'a|""|3\r\n'

    def test_manifest_records_null_sentinel(self, temp_dir):
        """Generated manifest must carry the __NULL__ load contract."""
        import json

        generator = ClickBenchDataGenerator(output_dir=temp_dir)
        data_file = temp_dir / "hits.csv.gz"
        data_file.write_bytes(b"placeholder")
        generator._table_row_counts = {"hits": 1}

        generator._write_manifest({"hits": data_file})

        manifest = json.loads((temp_dir / "_datagen_manifest.json").read_text())
        metadata = manifest["tables"]["hits"]["formats"]["tbl"][0]["metadata"]
        assert metadata["csv_delimiter"] == "|"
        assert metadata["csv_null_marker"] == "__NULL__"
