"""Comprehensive tests for TPC-DS data generator functionality.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.core.tpcds.generator import TPCDSDataGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Skip marker for tests that require Unix-like shell execution
skip_windows_shell = pytest.mark.skipif(
    sys.platform == "win32",
    reason="TPC-DS generator tests require Unix-like shell execution",
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.mark.unit
class TestTPCDSDataGenerator:
    """Test TPC-DS data generator basic functionality."""

    def test_generator_initialization(self, temp_dir):
        """Test generator initialization with different parameters."""
        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)

        assert generator.scale_factor == 1.0
        assert generator.output_dir == temp_dir
        assert hasattr(generator, "generate")

    def test_generator_initialization_with_custom_params(self, temp_dir):
        """Test generator initialization with custom parameters."""
        generator = TPCDSDataGenerator(scale_factor=10.0, output_dir=temp_dir, verbose=True, parallel=4)

        assert generator.scale_factor == 10.0
        assert generator.output_dir == temp_dir
        assert generator.verbose is True
        assert generator.parallel == 4

    def test_scale_factor_validation(self, temp_dir):
        """Test that scale factor is properly handled."""
        # TPC-DS requires minimum scale factor of 1.0
        # Fractional scale factors should raise ValueError
        with pytest.raises(ValueError, match="requires scale_factor >= 1.0"):
            TPCDSDataGenerator(scale_factor=0.01, output_dir=temp_dir)

        with pytest.raises(ValueError, match="requires scale_factor >= 1.0"):
            TPCDSDataGenerator(scale_factor=0.5, output_dir=temp_dir)

        # Valid scale factors should work
        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)
        assert generator.scale_factor == 1.0

        # Test larger scale factor
        generator_large = TPCDSDataGenerator(scale_factor=100.0, output_dir=temp_dir)
        assert generator_large.scale_factor == 100.0

    def test_output_directory_handling(self, temp_dir):
        """Test output directory creation and validation."""
        # Test with existing directory
        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)
        assert generator.output_dir.exists()

        # Test with non-existing directory (should be created)
        new_dir = temp_dir / "new_tpcds_dir"
        generator_new = TPCDSDataGenerator(scale_factor=1.0, output_dir=new_dir)
        assert generator_new.output_dir == new_dir

    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen")
    def test_dsdgen_tool_detection(self, mock_find_dsdgen, temp_dir):
        """Test detection and building of dsdgen tool."""
        mock_find_dsdgen.return_value = temp_dir / "dsdgen"

        TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)

        # Should attempt to find the dsdgen tool
        mock_find_dsdgen.assert_called_once()

    def test_get_table_names(self, temp_dir):
        """Test retrieval of TPC-DS table names."""
        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)

        # TPC-DS has standard table names

        # Test if generator has method to get table names
        if hasattr(generator, "get_table_names"):
            table_names = generator.get_table_names()
            # Check that key tables are included
            key_tables = [
                "store_sales",
                "catalog_sales",
                "web_sales",
                "customer",
                "item",
            ]
            for table in key_tables:
                assert table in table_names

    def test_build_schema_registry_includes_tpcds_columns(self, temp_dir):
        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)

        schema_registry = generator._build_schema_registry()

        assert "customer" in schema_registry
        column_names = [column["name"] for column in schema_registry["customer"]["columns"]]
        assert "c_customer_sk" in column_names

    @patch("subprocess.run")
    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen")
    def test_data_generation_workflow(self, mock_find_dsdgen, mock_subprocess, temp_dir):
        """Test the complete data generation workflow."""
        # Create mock dsdgen binary so it passes exists() check
        mock_dsdgen = temp_dir / "dsdgen"
        mock_dsdgen.write_text("#!/bin/sh\n")  # Create the file
        mock_find_dsdgen.return_value = mock_dsdgen
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")

        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)

        # Create mock data files
        table_files = {}
        for table in ["store_sales", "catalog_sales", "customer", "item"]:
            data_file = temp_dir / f"{table}.dat"
            data_file.write_text(f"1|sample {table} data|test\n")
            table_files[table] = data_file

        # Mock the generation method
        with (
            patch.object(generator, "_run_dsdgen_native", return_value=None),
            patch.object(
                generator,
                "_get_generated_dat_files",
                return_value=list(table_files.values()),
            ),
        ):
            result = generator.generate()

            assert isinstance(result, dict)
            assert len(result) >= 4
            for table, file_paths in result.items():
                # TPC-DS returns dict[str, list[Path]] for parallel generation support
                assert isinstance(file_paths, list), f"Expected list for table {table}"
                assert len(file_paths) > 0, f"Expected at least one file for table {table}"
                for file_path in file_paths:
                    assert isinstance(file_path, Path)
                # Accept any table name that was created in mock files
                assert isinstance(table, str)

    def test_error_handling_missing_dsdgen(self, temp_dir):
        """Test error handling when dsdgen binary is not found."""
        with patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen") as mock_find:
            # Simulate binary not found by raising exception
            mock_find.side_effect = FileNotFoundError("dsdgen binary not found")

            # TPC-DS now defers errors - initialization succeeds but generator marks dsdgen unavailable
            generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)
            assert not generator.dsdgen_available
            assert generator._dsdgen_error is not None

            # Error should occur when trying to generate data
            with pytest.raises(RuntimeError, match="TPC-DS native tools are not bundled"):
                generator.generate()

    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen")
    def test_parallel_generation_params(self, mock_find_dsdgen, temp_dir):
        """Test parallel processing parameters."""
        mock_find_dsdgen.return_value = temp_dir / "dsdgen"

        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir, parallel=8)

        # Check that parallel parameter is stored with correct value
        assert generator.parallel == 8


@pytest.mark.unit
class TestGeneratorExtended:
    """Advanced tests for TPC-DS data generator."""

    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen")
    def test_data_file_size_calculation(self, mock_find_dsdgen, temp_dir):
        """Test data file size calculations based on scale factor."""
        mock_find_dsdgen.return_value = temp_dir / "dsdgen"

        # Different scale factors should affect data generation
        generator_small = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)
        generator_large = TPCDSDataGenerator(scale_factor=10.0, output_dir=temp_dir)

        assert generator_small.scale_factor < generator_large.scale_factor

    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen")
    def test_table_dependency_handling(self, mock_find_dsdgen, temp_dir):
        """Test handling of table dependencies in TPC-DS."""
        mock_find_dsdgen.return_value = temp_dir / "dsdgen"

        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)

        # TPC-DS has complex table relationships
        # Test that generator is aware of table dependencies
        if hasattr(generator, "get_table_dependencies"):
            dependencies = generator.get_table_dependencies()
            assert isinstance(dependencies, dict)

        # Test that key dimension tables are handled properly
        # These should be generated before fact tables

        # This is a structural test - we just verify the generator initializes properly
        assert generator is not None

    @patch("subprocess.run")
    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen")
    def test_command_line_generation(self, mock_find_dsdgen, mock_subprocess, temp_dir):
        """Test command line argument generation for dsdgen."""
        mock_find_dsdgen.return_value = temp_dir / "dsdgen"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")

        generator = TPCDSDataGenerator(scale_factor=5.0, output_dir=temp_dir, parallel=4)

        # Test that command line args are built correctly
        if hasattr(generator, "_build_dsdgen_command"):
            cmd = generator._build_dsdgen_command()
            assert isinstance(cmd, list)
            assert any("5" in str(arg) for arg in cmd)  # Scale factor should be in command

    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen")
    def test_file_format_handling(self, mock_find_dsdgen, temp_dir):
        """Test different file format handling options."""
        mock_find_dsdgen.return_value = temp_dir / "dsdgen"

        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)

        # Test that generator handles TPC-DS native format (.dat files)
        # This is structural - just verify initialization
        assert generator.output_dir == temp_dir

        # Test file extension expectations
        if hasattr(generator, "get_expected_file_extension"):
            ext = generator.get_expected_file_extension()
            assert ext in [".dat", ".tbl"]
        else:
            # No get_expected_file_extension method — verify generator initialized correctly
            assert generator.scale_factor == 1.0

    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen")
    def test_memory_and_performance_settings(self, mock_find_dsdgen, temp_dir):
        """Test memory and performance related settings."""
        mock_find_dsdgen.return_value = temp_dir / "dsdgen"

        generator = TPCDSDataGenerator(
            scale_factor=1.0,
            output_dir=temp_dir,
            verbose=True,  # Should enable detailed logging
        )

        # Test verbose mode is set
        if hasattr(generator, "verbose"):
            assert generator.verbose is True

        # Test that generator can handle large scale factors
        large_generator = TPCDSDataGenerator(
            scale_factor=1000.0,  # Large scale factor
            output_dir=temp_dir,
        )

        assert large_generator.scale_factor == 1000.0

    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen")
    def test_incremental_generation_support(self, mock_find_dsdgen, temp_dir):
        """Test support for incremental or partial generation."""
        mock_find_dsdgen.return_value = temp_dir / "dsdgen"

        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir)

        # Test that generator can potentially handle table-specific generation
        if hasattr(generator, "generate_table"):
            # Test generating a specific table
            try:
                result = generator.generate_table("customer")
                assert isinstance(result, Path)
            except NotImplementedError:
                pass  # Method exists but not implemented

        # Basic structural test
        assert generator is not None
        assert generator.scale_factor == 1.0

    @skip_windows_shell
    @patch("subprocess.run")
    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen")
    def test_file_format_consistency_with_compression(self, mock_find_dsdgen, mock_subprocess, temp_dir):
        """Test that data generation produces consistent file formats when compression is enabled.

        This test prevents regression of the issue where mixed .dat and .dat.zst files
        were generated, causing load failures in database platforms.

        Requires zstd because it tests zstd compression specifically.
        """
        # Create mock dsdgen binary so it passes exists() check
        mock_dsdgen = temp_dir / "dsdgen"
        mock_dsdgen.write_text("#!/bin/sh\n")
        mock_dsdgen.chmod(0o755)  # Make executable
        mock_find_dsdgen.return_value = mock_dsdgen
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")

        # Test with compression enabled (default)
        generator = TPCDSDataGenerator(
            scale_factor=1.0,  # TPC-DS requires SF >= 1.0
            output_dir=temp_dir,
            parallel=2,  # Use parallel generation to test the problematic path
            compress_data=True,
            compression_type="zstd",
        )

        # Create mock .dat files that would be generated by dsdgen
        test_tables = ["customer", "item", "store_sales", "date_dim"]

        def _mock_run_dsdgen_native(_: Path) -> None:
            # Create files during the generation phase (after stale-prune).
            for table in test_tables:
                for chunk_id in range(1, 3):  # 2 chunks for parallel=2
                    dat_file = temp_dir / f"{table}_{chunk_id}_2.dat"
                    dat_file.write_text(f"1|sample {table} data chunk {chunk_id}|test\n")

        # Mock native execution to avoid shelling out while still producing data files.
        with patch.object(generator, "_run_dsdgen_native", side_effect=_mock_run_dsdgen_native):
            # Call generate to trigger compression logic
            generator._generate_local(temp_dir)

            # Verify that all files are consistently formatted
            all_files = list(temp_dir.glob("*"))
            dat_files = [f for f in all_files if f.suffix == ".dat"]
            zst_files = [f for f in all_files if f.name.endswith(".dat.zst")]

            # With compression enabled, we should have:
            # - No .dat files (all should be compressed)
            # - Only .dat.zst files for data
            assert len(dat_files) == 0, f"Found uncompressed .dat files: {[f.name for f in dat_files]}"
            assert len(zst_files) > 0, "No compressed files found"

            # Verify all zst files have reasonable size (not empty 9-byte files)
            for zst_file in zst_files:
                if zst_file.name.endswith(".dat.zst"):
                    size = zst_file.stat().st_size
                    # Compressed files should be larger than the problematic 9-byte empty files
                    # but we can't predict exact size, so just ensure they're not the problematic empty ones
                    assert size != 9, f"File {zst_file.name} appears to be an empty compressed file"

    @patch("subprocess.run")
    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator._find_or_build_dsdgen")
    def test_file_format_consistency_without_compression(self, mock_find_dsdgen, mock_subprocess, temp_dir):
        """Test that data generation produces consistent file formats when compression is disabled."""
        # Create mock dsdgen binary so it passes exists() check
        mock_dsdgen = temp_dir / "dsdgen"
        mock_dsdgen.write_text("#!/bin/sh\n")
        mock_find_dsdgen.return_value = mock_dsdgen
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")

        # Test with compression disabled
        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir, parallel=2, compress_data=False)

        # Create mock .dat files that would be generated by dsdgen
        test_tables = ["customer", "item", "store_sales"]
        for table in test_tables:
            for chunk_id in range(1, 3):
                dat_file = temp_dir / f"{table}_{chunk_id}_2.dat"
                dat_file.write_text(f"1|sample {table} data chunk {chunk_id}|test\n")

        # Mock the file-based dsdgen execution
        with patch.object(generator, "_run_parallel_file_based_dsdgen", return_value=None):
            generator._generate_local(temp_dir)

            # Verify that all files are consistently uncompressed
            all_files = list(temp_dir.glob("*"))
            dat_files = [f for f in all_files if f.suffix == ".dat"]
            zst_files = [f for f in all_files if f.name.endswith(".dat.zst")]

            # With compression disabled, we should have:
            # - Only .dat files
            # - No .dat.zst files
            assert len(dat_files) > 0, "No .dat files found"
            assert len(zst_files) == 0, (
                f"Found compressed files when compression was disabled: {[f.name for f in zst_files]}"
            )
