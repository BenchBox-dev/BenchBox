"""
Copyright 2026 Joe Harris / BenchBox Project

Tests for fractional scale factor support across TPC-H and TPC-DS benchmarks.
Verifies that data generation works correctly with small scale factors and
that no trailing delimiters are emitted.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile

import pytest

from benchbox.core.tpcds.compliance import TpcdsComplianceClass
from benchbox.core.tpcds.generator import TPCDSDataGenerator
from benchbox.core.tpch.generator import TPCHDataGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.slow,
]


@pytest.mark.slow
class TestFractionalScaleFactors:
    """Test fractional scale factor support for TPC benchmarks."""

    def test_tpch_fractional_scale_factor_generation(self):
        """Test TPC-H data generation with fractional scale factors."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCHDataGenerator(scale_factor=0.01, output_dir=tmp_dir, verbose=False)

            # TPC-H supports fractional scale factors down to 0.01
            assert generator.scale_factor == 0.01, "Scale factor should be exactly 0.01"

            # Generate data
            files = generator.generate()

            # Should generate all 8 TPC-H tables
            expected_tables = {
                "customer",
                "lineitem",
                "nation",
                "orders",
                "part",
                "partsupp",
                "region",
                "supplier",
            }
            assert set(files.keys()) == expected_tables, "All TPC-H tables should be generated"

            # All files should exist and be non-empty
            for table_name, file_path in files.items():
                assert file_path.exists(), f"{table_name} file should exist"
                assert file_path.stat().st_size > 0, f"{table_name} file should not be empty"

    def test_tpch_no_trailing_delimiters(self):
        """Test that TPC-H data has no trailing pipe delimiters."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCHDataGenerator(
                scale_factor=0.01,
                output_dir=tmp_dir,
                verbose=False,
                compress_data=False,
            )
            files = generator.generate()

            # Test several key tables for trailing delimiters
            test_tables = ["customer", "lineitem", "orders"]

            for table_name in test_tables:
                if table_name in files:
                    table_file = files[table_name]
                    with open(table_file, encoding="utf-8") as f:
                        lines = f.readlines()[:10]  # Check first 10 lines

                    for i, line in enumerate(lines):
                        line = line.rstrip("\n")
                        has_trailing = line.endswith("|")
                        assert not has_trailing, (
                            f"{table_name} line {i + 1} should not end with trailing pipe: {line[:50]}..."
                        )

    def test_tpcds_fractional_scale_factor_is_unofficial_subscale(self):
        """Test TPC-DS accepts supported fractional scale factors as unofficial subscale runs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCDSDataGenerator(scale_factor=0.01, output_dir=tmp_dir, verbose=False)

            assert generator.scale_factor == 0.01
            assert generator.compliance_class is TpcdsComplianceClass.UNOFFICIAL_SUBSCALE

    def test_tpcds_minimum_scale_factor_accepted(self):
        """Test TPC-DS accepts scale factor = 1.0 (minimum valid value)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_dir, verbose=False)
            assert generator.scale_factor == 1.0

    def test_tpcds_no_trailing_delimiters(self):
        """Test that TPC-DS data has no trailing pipe delimiters."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_dir, verbose=False, compress_data=False)

            # Only generate the tables we need to test (not all 24 tables)
            test_tables = ["customer_demographics", "date_dim", "item"]
            files = generator.generate_tables(test_tables)

            for table_name in test_tables:
                if table_name in files:
                    # TPC-DS returns list[Path], get first file
                    table_file = files[table_name][0]
                    with open(table_file, encoding="utf-8") as f:
                        lines = f.readlines()[:10]  # Check first 10 lines

                    for i, line in enumerate(lines):
                        line = line.rstrip("\n")
                        has_trailing = line.endswith("|")
                        assert not has_trailing, (
                            f"{table_name} line {i + 1} should not end with trailing pipe: {line[:50]}..."
                        )

    def test_tpch_column_counts_consistent(self):
        """Test that TPC-H tables have consistent column counts without trailing delimiters."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCHDataGenerator(
                scale_factor=0.01,
                output_dir=tmp_dir,
                verbose=False,
                compress_data=False,
            )
            files = generator.generate()

            # Expected column counts for key TPC-H tables
            expected_columns = {
                "customer": 8,
                "lineitem": 16,
                "orders": 9,
                "supplier": 7,
                "part": 9,
                "partsupp": 5,
                "nation": 4,
                "region": 3,
            }

            for table_name, expected_count in expected_columns.items():
                if table_name in files:
                    table_file = files[table_name]
                    with open(table_file, encoding="utf-8") as f:
                        lines = f.readlines()[:5]  # Check first 5 lines

                    for i, line in enumerate(lines):
                        line = line.rstrip("\n")
                        column_count = len(line.split("|"))
                        assert column_count == expected_count, (
                            f"{table_name} line {i + 1} should have {expected_count} columns, "
                            f"got {column_count}: {line[:50]}..."
                        )

    def test_tpcds_column_counts_consistent(self):
        """Test that TPC-DS tables have consistent column counts without trailing delimiters."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_dir, verbose=False)

            # Expected column counts for key TPC-DS tables
            expected_columns = {
                "customer_demographics": 9,
                "date_dim": 28,
                "item": 22,
                "customer": 18,
                "store": 29,
            }

            # Only generate the tables we need to test (not all 24 tables)
            test_tables = list(expected_columns.keys())
            files = generator.generate_tables(test_tables)

            for table_name, expected_count in expected_columns.items():
                if table_name in files:
                    # TPC-DS returns list[Path], get first file
                    table_file = files[table_name][0]
                    try:
                        # Handle potentially compressed files
                        if str(table_file).endswith(".zst"):
                            import zstandard as zstd

                            with open(table_file, "rb") as compressed_file:
                                dctx = zstd.ZstdDecompressor()
                                with dctx.stream_reader(compressed_file) as reader:
                                    text_data = reader.read().decode("utf-8")
                                    lines = text_data.split("\n")[:5]
                        else:
                            with open(table_file, encoding="utf-8", errors="replace") as f:
                                lines = f.readlines()[:5]  # Check first 5 lines
                    except UnicodeDecodeError:
                        # If UTF-8 fails, try with binary mode and latin-1
                        with open(table_file, encoding="latin-1") as f:
                            lines = f.readlines()[:5]

                    for i, line in enumerate(lines):
                        line = line.rstrip("\n")
                        column_count = len(line.split("|"))
                        assert column_count == expected_count, (
                            f"{table_name} line {i + 1} should have {expected_count} columns, "
                            f"got {column_count}: {line[:50]}..."
                        )

    @pytest.mark.slow
    def test_benchmark_integration_with_fractional_scale(self):
        """Test full benchmark integration with fractional scale factors."""
        from benchbox.core.tpch.benchmark import TPCHBenchmark

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Test TPC-H with fractional scale factor

            benchmark = TPCHBenchmark(scale_factor=0.01, output_dir=tmp_dir, verbose=False)

            # Generate data to test fractional scale factor works
            files = benchmark.generate_data()

            # Verify data was generated correctly
            assert len(files) == 8, "Should generate all 8 TPC-H tables"

            # Check that files exist and are not empty
            for table_file in files:
                assert table_file.exists(), f"Generated file {table_file} should exist"
                assert table_file.stat().st_size > 0, f"Generated file {table_file} should not be empty"
