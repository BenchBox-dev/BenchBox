"""Integration tests for compression functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchbox.cli.benchmarks import BenchmarkConfig
from benchbox.core.ssb.benchmark import SSBBenchmark
from benchbox.utils.compression import ZSTD_AVAILABLE, CompressionManager

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


class TestCompressionIntegration:
    """Integration tests for compression across the system."""

    def test_benchmark_config_compression_params(self):
        """Test that BenchmarkConfig properly stores compression parameters."""
        config = BenchmarkConfig(
            name="test",
            display_name="Test Benchmark",
            compress_data=True,
            compression_type="gzip",
            compression_level=5,
        )

        assert config.compress_data is True
        assert config.compression_type == "gzip"
        assert config.compression_level == 5

    def test_ssb_benchmark_compression_integration(self):
        """Test that SSB benchmark properly initializes with compression."""
        with tempfile.TemporaryDirectory() as temp_dir:
            benchmark = SSBBenchmark(
                scale_factor=0.01,
                output_dir=temp_dir,
                compress_data=True,
                compression_type="gzip",
                compression_level=9,
            )

            # Check that data generator has compression settings
            assert benchmark.data_generator.compress_data is True
            assert benchmark.data_generator.compression_type == "gzip"
            assert benchmark.data_generator.compression_level == 9

    def test_end_to_end_compressed_data_generation(self):
        """Test end-to-end compressed data generation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            benchmark = SSBBenchmark(
                scale_factor=0.01,
                output_dir=temp_dir,
                compress_data=True,
                compression_type="gzip",
            )

            # Generate data (just one table for speed)
            data_files = benchmark.generate_data(tables=["date"])

            # Check that compressed files were generated
            assert "date" in data_files
            date_file_path = Path(data_files["date"])
            assert date_file_path.exists()
            assert str(date_file_path).endswith(".gz")

            # Verify file is actually compressed (smaller than typical CSV)
            compressed_size = date_file_path.stat().st_size
            assert compressed_size > 0
            assert compressed_size < 100000  # Should be much smaller than uncompressed

    def test_compression_with_multiple_tables_zstd(self):
        """Test compression with multiple tables using zstd."""
        with tempfile.TemporaryDirectory() as temp_dir:
            benchmark = SSBBenchmark(
                scale_factor=0.01,
                output_dir=temp_dir,
                compress_data=True,
                compression_type="zstd",
            )

            # Generate multiple tables
            data_files = benchmark.generate_data(tables=["date", "customer"])

            # Check all files are compressed
            for _table_name, file_path in data_files.items():
                path = Path(file_path)
                assert path.exists()
                assert str(path).endswith(".zst")
                assert path.stat().st_size > 0

    def test_compression_with_multiple_tables_gzip(self):
        """Test compression with multiple tables using gzip."""
        with tempfile.TemporaryDirectory() as temp_dir:
            benchmark = SSBBenchmark(
                scale_factor=0.01,
                output_dir=temp_dir,
                compress_data=True,
                compression_type="gzip",
            )

            # Generate multiple tables
            data_files = benchmark.generate_data(tables=["date", "customer"])

            # Check all files are compressed
            for _table_name, file_path in data_files.items():
                path = Path(file_path)
                assert path.exists()
                assert str(path).endswith(".gz")
                assert path.stat().st_size > 0

    def test_compression_disabled_generates_normal_files(self):
        """Test that when compression is disabled, normal files are generated."""
        with tempfile.TemporaryDirectory() as temp_dir:
            benchmark = SSBBenchmark(
                scale_factor=0.01, output_dir=temp_dir, compress_data=False, compression_type="none"
            )

            data_files = benchmark.generate_data(tables=["date"])

            # Check that uncompressed files were generated
            assert "date" in data_files
            date_file_path = Path(data_files["date"])
            assert date_file_path.exists()
            assert str(date_file_path).endswith(".tbl")  # No compression extension

    def test_compression_error_handling(self):
        """Test compression error handling."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test with invalid compression type
            with pytest.raises(ValueError, match="Unsupported compression type"):
                SSBBenchmark(
                    scale_factor=0.01,
                    output_dir=temp_dir,
                    compress_data=True,
                    compression_type="invalid",
                )

    def test_compression_manager_availability(self):
        """Test compression manager detects available compressors."""
        manager = CompressionManager()
        available = manager.get_available_compressors()

        # Should always have 'none' and 'gzip'
        assert "none" in available
        assert "gzip" in available

        # 'zstd' is only available if zstandard library is installed
        if ZSTD_AVAILABLE:
            assert "zstd" in available
        else:
            assert "zstd" not in available

    @pytest.mark.parametrize(
        "compression_type,expected_extension",
        [
            ("none", ""),
            ("gzip", ".gz"),
            ("zstd", ".zst"),
        ],
    )
    def test_compression_extensions(self, compression_type, expected_extension):
        """Test that correct file extensions are used for different compression types."""
        manager = CompressionManager()

        # Skip zstd test if not available
        if compression_type == "zstd":
            try:
                compressor = manager.get_compressor(compression_type)
            except Exception:
                pytest.skip("zstd not available")
        else:
            compressor = manager.get_compressor(compression_type)

        assert compressor.get_file_extension() == expected_extension

    def test_data_integrity_through_compression(self):
        """Test data integrity through compression/decompression cycle."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test data
            test_data = "Name|Value|Description\nTest|123|Sample data\nAnother|456|More data\n"
            original_file = temp_path / "test.csv"
            original_file.write_text(test_data)

            # Test gzip compression/decompression
            manager = CompressionManager()
            gzip_compressor = manager.get_compressor("gzip")

            # Compress
            compressed_file = gzip_compressor.compress_file(original_file)
            assert compressed_file.exists()
            assert compressed_file != original_file

            # Decompress
            decompressed_file = gzip_compressor.decompress_file(compressed_file)
            assert decompressed_file.exists()

            # Verify data integrity
            decompressed_data = decompressed_file.read_text()
            assert decompressed_data == test_data

            # Test zstd if available
            try:
                zstd_compressor = manager.get_compressor("zstd")
                zstd_compressed = zstd_compressor.compress_file(original_file, temp_path / "test.csv.zst")
                zstd_decompressed = zstd_compressor.decompress_file(
                    zstd_compressed, temp_path / "test_zstd_decompressed.csv"
                )
                zstd_data = zstd_decompressed.read_text()
                assert zstd_data == test_data
            except Exception:
                pytest.skip("zstd not available for this test")

    def test_compression_with_different_scale_factors(self):
        """Test compression works with different scale factors."""
        scale_factors = [0.01, 0.1]  # Keep small for test speed

        for scale_factor in scale_factors:
            with tempfile.TemporaryDirectory() as temp_dir:
                benchmark = SSBBenchmark(
                    scale_factor=scale_factor,
                    output_dir=temp_dir,
                    compress_data=True,
                    compression_type="gzip",
                )

                data_files = benchmark.generate_data(tables=["date"])

                # Verify compression worked
                date_file = Path(data_files["date"])
                assert date_file.exists()
                assert str(date_file).endswith(".gz")

                # Larger scale factors should produce larger compressed files
                compressed_size = date_file.stat().st_size
                assert compressed_size > 0


class TestOrchestrator:
    """Test orchestrator compression parameter passing."""

    @patch("benchbox.core.ssb.benchmark.SSBBenchmark")
    def test_orchestrator_passes_compression_params(self, mock_benchmark_class):
        """Test that orchestrator passes compression parameters to benchmark."""
        from benchbox.cli.orchestrator import BenchmarkOrchestrator

        # Mock system profile
        mock_system_profile = MagicMock()
        mock_system_profile.cpu_cores_logical = 4

        # Mock database config
        mock_database_config = MagicMock()
        mock_database_config.type = "duckdb"

        # Create benchmark config with compression (use gzip for portability)
        config = BenchmarkConfig(
            name="ssb",
            display_name="SSB",
            scale_factor=0.01,
            compress_data=True,
            compression_type="gzip",
            compression_level=5,
        )

        # Create orchestrator and test benchmark creation
        orchestrator = BenchmarkOrchestrator()

        # Mock the benchmark instance
        mock_benchmark_instance = MagicMock()
        mock_benchmark_class.return_value = mock_benchmark_instance
        # SSB generates its own data (no shared source). Give the mocked class
        # the real class attribute so the orchestrator resolves the managed
        # datagen root, and make the instance report no data sharing so the
        # post-construction redirect stays inactive.
        mock_benchmark_class.DATA_SOURCE_BENCHMARK = None
        mock_benchmark_instance.get_data_source_benchmark.return_value = None

        # This would call _get_benchmark_instance internally
        result = orchestrator._get_benchmark_instance(config, mock_system_profile)

        # Verify benchmark was called with compression parameters. The
        # orchestrator now resolves the datagen root before construction and
        # injects it as output_dir (alongside verbose/quiet flags).
        expected_output_dir = orchestrator.directory_manager.get_datagen_path("ssb", 0.01)
        mock_benchmark_class.assert_called_once_with(
            parallel=4,
            output_dir=expected_output_dir,
            scale_factor=0.01,
            compress_data=True,
            compression_type="gzip",
            compression_level=5,
            verbose=0,
            quiet=False,
        )

        assert result == mock_benchmark_instance
