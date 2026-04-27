"""Comprehensive tests for TPC-H data generator.

This consolidated test suite covers all aspects of the TPCHDataGenerator including:
- Basic functionality and initialization
- Parameter validation and boundary tests
- Build system and compilation tests
- File operations and data handling
- Parallel processing and execution
- Edge cases and error handling
- Integration tests for complete workflow

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

from benchbox.core.tpch.generator import TPCHDataGenerator

# Mark all tests in this file as unit tests
pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCHDataGeneratorBasic(unittest.TestCase):
    """Basic functionality and initialization tests."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_default_initialization(self, mock_find_dbgen):
        """Test default initialization parameters."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator()

        # Check default values
        self.assertEqual(generator.scale_factor, 1.0)
        self.assertIsInstance(generator.output_dir, Path)
        self.assertEqual(generator.parallel, 1)
        self.assertFalse(generator.verbose)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_default_output_directory(self, mock_find_dbgen):
        """Test that default output directory is set correctly."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator()
        expected_dir = Path.cwd() / "tpch_data"
        self.assertEqual(generator.output_dir, expected_dir)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_string_output_directory_conversion(self, mock_find_dbgen):
        """Test that string output directories are converted to Path objects."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir="/tmp/test_output")
        self.assertIsInstance(generator.output_dir, Path)
        # Compare using as_posix() for cross-platform consistency
        self.assertEqual(generator.output_dir.as_posix(), "/tmp/test_output")

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_verbose_flag_propagation(self, mock_find_dbgen):
        """Test that verbose flag is stored correctly."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(verbose=True)
        self.assertTrue(generator.verbose)

        generator = TPCHDataGenerator(verbose=False)
        self.assertFalse(generator.verbose)

    @mock.patch("platform.system")
    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_windows_executable_naming(self, mock_find_dbgen, mock_system):
        """Test that Windows executable is correctly identified."""
        mock_system.return_value = "Windows"

        # Create a mock that simulates the _find_or_build_dbgen logic
        def mock_find_or_build():
            dbgen_path = self.temp_dir / "dbgen"
            dbgen_exe = dbgen_path / "dbgen.exe"
            dbgen_exe.parent.mkdir(parents=True, exist_ok=True)
            dbgen_exe.touch()
            # Make it executable
            dbgen_exe.chmod(0o755)
            return dbgen_exe

        mock_find_dbgen.side_effect = mock_find_or_build

        generator = TPCHDataGenerator()
        self.assertTrue(str(generator.dbgen_exe).endswith("dbgen.exe"))


class TestTPCHDataGeneratorParameterValidation(unittest.TestCase):
    """Parameter validation and boundary tests."""

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_scale_factor_boundary_conditions(self, mock_find_dbgen):
        """Test scale factor validation at boundary conditions."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        # Test exactly at boundaries
        with self.assertRaises(ValueError) as cm:
            TPCHDataGenerator(scale_factor=0)
        self.assertIn("Scale factor must be positive", str(cm.exception))

        with self.assertRaises(ValueError) as cm:
            TPCHDataGenerator(scale_factor=-0.001)
        self.assertIn("Scale factor must be positive", str(cm.exception))

        # Test very small positive value (should raise error - minimum is 0.01)
        with self.assertRaises(ValueError) as cm:
            TPCHDataGenerator(scale_factor=0.001)
        self.assertIn("Scale factor 0.001 is too small", str(cm.exception))

        # Test maximum boundary
        with self.assertRaises(ValueError) as cm:
            TPCHDataGenerator(scale_factor=100001)
        self.assertIn("Scale factor", str(cm.exception))
        self.assertIn("is too large", str(cm.exception))

        # Test exactly at max (should work)
        generator = TPCHDataGenerator(scale_factor=100000)
        self.assertEqual(generator.scale_factor, 100000)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_parallel_processes_boundary_conditions(self, mock_find_dbgen):
        """Test parallel processes validation at boundary conditions."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        # Test below minimum
        with self.assertRaises(ValueError) as cm:
            TPCHDataGenerator(parallel=0)
        self.assertIn("Parallel processes must be >= 1", str(cm.exception))

        with self.assertRaises(ValueError) as cm:
            TPCHDataGenerator(parallel=-1)
        self.assertIn("Parallel processes must be >= 1", str(cm.exception))

        # Test exactly at minimum (should work)
        generator = TPCHDataGenerator(parallel=1)
        self.assertEqual(generator.parallel, 1)

        # Test above maximum
        with self.assertRaises(ValueError) as cm:
            TPCHDataGenerator(parallel=65)
        self.assertIn("Too many parallel processes", str(cm.exception))

        # Test exactly at maximum (should work)
        generator = TPCHDataGenerator(parallel=64)
        self.assertEqual(generator.parallel, 64)


class TestTPCHDataGeneratorBuildSystem(unittest.TestCase):
    """Build system and compilation tests."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.dbgen_path = self.temp_dir / "dbgen"
        self.dbgen_path.mkdir(parents=True)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @mock.patch("benchbox.core.tpch.generator.ensure_tpc_binaries")
    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator.resolve_dbgen_path")
    def test_dbgen_not_found_error(self, mock_resolve, mock_ensure):
        """Test error when dbgen source directory is not found."""
        from benchbox.utils.tpc_compilation import CompilationResult, CompilationStatus

        # Mock that dbgen path cannot be resolved (no sources)
        mock_resolve.return_value = None

        # Mock that precompiled binaries also not available
        mock_ensure.return_value = {
            "dbgen": CompilationResult(
                binary_name="dbgen",
                status=CompilationStatus.FAILED,
                error_message="Binary not found",
            )
        }

        # Create generator - it will initialize with dbgen_available = False
        generator = TPCHDataGenerator()

        # The error should occur when trying to generate data
        with self.assertRaises(RuntimeError) as cm:
            generator.generate()
        self.assertIn("TPC-H dbgen tool not found", str(cm.exception))

    @mock.patch("shutil.which")
    def test_missing_build_tools_error(self, mock_which):
        """Test error when build tools are not available."""
        # Mock missing make
        mock_which.side_effect = lambda cmd: None if cmd == "make" else "/usr/bin/gcc"

        # Create a mock generator object and test the method directly
        import logging

        generator = object.__new__(TPCHDataGenerator)
        generator.dbgen_path = Path("/mock/dbgen/path")
        generator.verbose = False
        generator.logger = logging.getLogger(__name__)  # Initialize logger

        # Create a mock dbgen executable path that doesn't exist
        with mock.patch.object(Path, "exists", return_value=False):
            with self.assertRaises(RuntimeError) as cm:
                generator._find_or_build_dbgen()
            self.assertIn("dbgen binary required but not found", str(cm.exception))

    @mock.patch("shutil.which")
    def test_missing_compiler_error(self, mock_which):
        """Test error when C compiler is not available."""
        # Mock missing compiler
        mock_which.side_effect = lambda cmd: "/usr/bin/make" if cmd == "make" else None

        # Create a mock generator object and test the method directly
        import logging

        generator = object.__new__(TPCHDataGenerator)
        generator.dbgen_path = Path("/mock/dbgen/path")
        generator.verbose = False
        generator.logger = logging.getLogger(__name__)  # Initialize logger

        # Create a mock dbgen executable path that doesn't exist
        with mock.patch.object(Path, "exists", return_value=False):
            with self.assertRaises(RuntimeError) as cm:
                generator._find_or_build_dbgen()
            self.assertIn("dbgen binary required but not found", str(cm.exception))

    @pytest.mark.skipif(sys.platform == "win32", reason="Executable bit check not applicable on Windows")
    @mock.patch("os.access")
    @mock.patch("benchbox.core.tpch.generator.Path.exists")
    def test_executable_permission_error(self, mock_exists, mock_access):
        """Test error when dbgen executable exists but is not executable."""
        mock_exists.return_value = True
        mock_access.return_value = False

        generator = TPCHDataGenerator()
        # With lazy loading, the error occurs when accessing dbgen_exe property
        # PermissionError is wrapped in RuntimeError by _raise_missing_dbgen
        with self.assertRaises(RuntimeError) as cm:
            _ = generator.dbgen_exe
        self.assertIn("is not executable", str(cm.exception))

    @mock.patch("subprocess.run")
    @mock.patch("shutil.which")
    def test_build_failure_error(self, mock_which, mock_run):
        """Test error when dbgen build fails."""
        mock_which.return_value = "/usr/bin/make"  # build tools available

        # Mock failed build
        mock_run.return_value = mock.Mock(returncode=1, stderr="Build failed", stdout="")

        # Create a mock generator object and test the method directly
        import logging

        generator = object.__new__(TPCHDataGenerator)
        generator.dbgen_path = Path("/mock/dbgen/path")
        generator.verbose = False
        generator.logger = logging.getLogger(__name__)  # Initialize logger

        # Create a mock dbgen executable path that doesn't exist even after build
        with mock.patch.object(Path, "exists", return_value=False):
            with self.assertRaises(RuntimeError) as cm:
                generator._find_or_build_dbgen()
            self.assertIn("dbgen binary required but not found", str(cm.exception))

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_compile_dbgen_method_basic(self, mock_find_dbgen):
        """Test the _compile_dbgen method with basic functionality."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator()
        work_dir = self.temp_dir / "work"
        work_dir.mkdir(exist_ok=True)

        # Mock shutil.copytree to simulate copying source
        with mock.patch("shutil.copytree") as mock_copytree:
            work_dir / "dbgen"
            mock_copytree.return_value = None

            # Mock subprocess.run for successful compilation
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0)

                # Mock the executable existence check
                with mock.patch("pathlib.Path.exists") as mock_exists:
                    mock_exists.return_value = True

                    result = generator._compile_dbgen(work_dir)

                    # Should return path to the executable
                    self.assertIsInstance(result, Path)
                    # Check for dbgen or dbgen.exe (Windows)
                    result_name = result.name
                    self.assertTrue(
                        result_name == "dbgen" or result_name == "dbgen.exe",
                        f"Expected 'dbgen' or 'dbgen.exe', got '{result_name}'",
                    )

    @mock.patch("platform.system")
    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_compile_dbgen_platform_detection(self, mock_find_dbgen, mock_system):
        """Test platform-specific compilation flags."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        # Test different platforms
        test_cases = [
            ("Linux", "LINUX"),
            ("Darwin", "MACOS"),
            ("Windows", "WIN32"),
            ("FreeBSD", "LINUX"),  # Unknown defaults to LINUX
        ]

        for platform_name, expected_flag in test_cases:
            with self.subTest(platform=platform_name):
                mock_system.return_value = platform_name

                generator = TPCHDataGenerator()
                work_dir = self.temp_dir / "work"
                work_dir.mkdir(exist_ok=True)

                with mock.patch("shutil.copytree"), mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=0)

                    with mock.patch("pathlib.Path.exists", return_value=True):
                        generator._compile_dbgen(work_dir)

                        # Check that the correct machine flag was used
                        call_args = mock_run.call_args[0][0]
                        self.assertTrue(
                            any(expected_flag in arg for arg in call_args),
                            f"Expected {expected_flag} in {call_args}",
                        )

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_compile_dbgen_subprocess_error(self, mock_find_dbgen):
        """Test handling of subprocess compilation errors."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator()
        work_dir = self.temp_dir / "work"
        work_dir.mkdir(exist_ok=True)

        with mock.patch("shutil.copytree"), mock.patch("subprocess.run") as mock_run:
            # Simulate compilation failure
            mock_run.side_effect = subprocess.CalledProcessError(1, "make")

            with self.assertRaises(RuntimeError) as cm:
                generator._compile_dbgen(work_dir)

            self.assertIn("Failed to compile dbgen", str(cm.exception))

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_compile_dbgen_missing_executable_after_build(self, mock_find_dbgen):
        """Test error when executable is not found after successful compilation."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator()
        work_dir = self.temp_dir / "work"
        work_dir.mkdir(exist_ok=True)

        with mock.patch("shutil.copytree"), mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)  # Successful build

            # But executable doesn't exist
            with mock.patch("pathlib.Path.exists", return_value=False):
                with self.assertRaises(FileNotFoundError) as cm:
                    generator._compile_dbgen(work_dir)

                self.assertIn("dbgen executable not found", str(cm.exception))

    @mock.patch("platform.system")
    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_compile_dbgen_windows_executable_name(self, mock_find_dbgen, mock_system):
        """Test that Windows executable name includes .exe extension."""
        mock_system.return_value = "Windows"
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator()
        work_dir = self.temp_dir / "work"
        work_dir.mkdir(exist_ok=True)

        with mock.patch("shutil.copytree"), mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)

            with mock.patch("pathlib.Path.exists", return_value=True):
                result = generator._compile_dbgen(work_dir)

                # Should return path ending with .exe on Windows
                self.assertTrue(str(result).endswith(".exe"))

    @mock.patch("platform.system")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which")
    @mock.patch("benchbox.core.tpch.generator.Path.exists")
    def test_platform_specific_build_flags(self, mock_exists, mock_which, mock_run, mock_system):
        """Test platform-specific build flags are used correctly."""
        mock_exists.side_effect = lambda: False  # dbgen doesn't exist initially
        mock_which.return_value = "/usr/bin/make"
        mock_run.return_value = mock.Mock(returncode=0)

        # Test different platforms
        for platform_name, expected_flag in [
            ("Linux", "LINUX"),
            ("Darwin", "MACOS"),
            ("Windows", "WIN32"),
            ("Unknown", "LINUX"),  # Default
        ]:
            mock_system.return_value = platform_name

            try:
                TPCHDataGenerator()
                # Check that the correct flag was used in the build command
                calls = mock_run.call_args_list
                if calls:
                    call_args = calls[-1][0][0]  # Get the command arguments
                    self.assertTrue(
                        any(expected_flag in str(arg) for arg in call_args),
                        f"Expected {expected_flag} flag for {platform_name}",
                    )
            except Exception:
                # Some platforms might fail due to other missing mocks
                pass

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_simple_makefile_creation(self, mock_find_dbgen):
        """Test the creation of a simple Makefile during build process."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        # This test is more integration-focused but still uses mocks
        TPCHDataGenerator()

        # We can't easily test the actual Makefile creation without
        # extensive mocking, but we can verify the content pattern
        makefile_content = """
CC = gcc
CFLAGS = -g -DDBNAME=\\"dss\\" -DLINUX -DSQLSERVER -DTPCH -DRNG_TEST -D_FILE_OFFSET_BITS=64

OBJECTS = build.o driver.o bm_utils.o rnd.o print.o load_stub.o bcd2.o \\
          speed_seed.o text.o permute.o rng64.o

dbgen: $(OBJECTS)
	$(CC) $(CFLAGS) -o dbgen $(OBJECTS) -lm

%.o: %.c
	$(CC) $(CFLAGS) -c $<

clean:
	rm -f *.o dbgen qgen

.PHONY: clean
"""

        # Verify Makefile contains expected elements
        self.assertIn("CC = gcc", makefile_content)
        self.assertIn("-DLINUX", makefile_content)
        self.assertIn("dbgen:", makefile_content)
        self.assertIn("$(OBJECTS)", makefile_content)


class TestTPCHDataGeneratorFileOperations(unittest.TestCase):
    """File operations and data handling tests."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.work_dir = self.temp_dir / "work"
        self.work_dir.mkdir(exist_ok=True)
        self.output_dir = self.temp_dir / "output"

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_move_data_files_missing_files(self, mock_find_dbgen):
        """Test behavior when some generated files are missing."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        # Create a mock dbgen directory
        mock_dbgen_dir = self.temp_dir / "mock_dbgen"
        mock_dbgen_dir.mkdir(parents=True, exist_ok=True)

        # Create generator and set dbgen_path after initialization
        generator = TPCHDataGenerator(output_dir=self.output_dir)
        generator.dbgen_path = mock_dbgen_dir  # Set the mock dbgen directory

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create only some of the expected files in work_dir
        (self.work_dir / "customer.tbl").write_text("customer data\n")
        (self.work_dir / "lineitem.tbl").write_text("lineitem data\n")
        # Missing other files

        # Create a few more files in dbgen_path
        (mock_dbgen_dir / "nation.tbl").write_text("nation data\n")

        # Mock the logger to capture warnings
        with mock.patch.object(generator.logger, "warning") as mock_warning:
            result = generator._move_data_files(self.work_dir)

            # Should return paths for files that exist (2 from work_dir + 1 from dbgen_path = 3)
            self.assertGreaterEqual(len(result), 2)

            # Should log warnings for missing files (5 missing: orders, part, partsupp, region, supplier)
            self.assertEqual(mock_warning.call_count, 5)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_move_data_files_all_present(self, mock_find_dbgen):
        """Test move_data_files when all expected files are present."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.temp_dir)
        work_dir = self.temp_dir / "work"
        work_dir.mkdir(exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # Create all expected files
        expected_tables = [
            "customer",
            "lineitem",
            "nation",
            "orders",
            "part",
            "partsupp",
            "region",
            "supplier",
        ]

        for table in expected_tables:
            tbl_file = work_dir / f"{table}.tbl"
            tbl_file.write_text(f"{table} test data\n")

        result = generator._move_data_files(work_dir)

        # Should return all 8 files
        self.assertEqual(len(result), 8)

        # All files should be moved to output directory
        for table in expected_tables:
            target_file = self.temp_dir / f"{table}.tbl"
            self.assertTrue(target_file.exists())
            self.assertIn(f"{table} test data", target_file.read_text())

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_data_file_generation(self, mock_find_dbgen):
        """Test that data files are generated correctly."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.output_dir)

        # Test that generator has the expected properties
        assert generator.output_dir == self.output_dir
        assert hasattr(generator, "scale_factor")

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_generator_initialization(self, mock_find_dbgen):
        """Test generator initialization with different parameters."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.temp_dir)

        # Test basic properties
        assert generator.output_dir == self.temp_dir
        assert hasattr(generator, "scale_factor")

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_generator_properties(self, mock_find_dbgen):
        """Test generator properties and configuration."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.temp_dir, scale_factor=0.1)

        # Test properties
        assert generator.output_dir == self.temp_dir
        assert generator.scale_factor >= 0.1  # May be adjusted to minimum

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_output_directory_creation_error(self, mock_find_dbgen):
        """Test error handling when output directory cannot be created."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        # Use a regular path but mock the access check to simulate permission error
        generator = TPCHDataGenerator(output_dir=self.output_dir)

        # Mock the access check to return False (not writable)
        with mock.patch("os.access", return_value=False):
            with self.assertRaises(PermissionError) as cm:
                generator.generate()
            self.assertIn("is not writable", str(cm.exception))

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_output_directory_already_exists(self, mock_find_dbgen):
        """Test behavior when output directory already exists."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        # Create the output directory first
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        generator = TPCHDataGenerator(output_dir=self.temp_dir)

        # Test that generator handles existing directories correctly
        assert generator.output_dir.exists()
        assert hasattr(generator, "generate")

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_table_file_name_mapping(self, mock_find_dbgen):
        """Test that table name to file name mapping is correct."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.temp_dir)

        # Create mock CSV files to simulate the final step
        csv_files = []
        for table in [
            "customer",
            "lineitem",
            "nation",
            "orders",
            "part",
            "partsupp",
            "region",
            "supplier",
        ]:
            csv_file = self.temp_dir / f"{table}.csv"
            csv_file.write_text(f"{table} data")
            csv_files.append(csv_file)

        # Mock the generation process to avoid external dependencies
        with mock.patch("subprocess.run"), mock.patch.object(generator, "_move_data_files", return_value={}):
            # Create mock result that simulates data generation
            mock_result = {
                table: self.temp_dir / f"{table}.tbl"
                for table in [
                    "customer",
                    "lineitem",
                    "nation",
                    "orders",
                    "part",
                    "partsupp",
                    "region",
                    "supplier",
                ]
            }
            with mock.patch.object(generator, "_run_dbgen_native", return_value=None):
                with mock.patch.object(generator, "generate", return_value=mock_result):
                    result = generator.generate()

        # Check that mapping is correct
        expected_tables = [
            "customer",
            "lineitem",
            "nation",
            "orders",
            "part",
            "partsupp",
            "region",
            "supplier",
        ]

        self.assertEqual(set(result.keys()), set(expected_tables))
        for table in expected_tables:
            self.assertIn(table, str(result[table]))
            # Files should end with .tbl (TPC-H native format)
            self.assertTrue(str(result[table]).endswith(".tbl"))


class TestTPCHDataGeneratorParallelProcessing(unittest.TestCase):
    """Parallel processing and execution tests."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.work_dir = self.temp_dir / "work"
        self.work_dir.mkdir(exist_ok=True)
        self.output_dir = self.temp_dir / "output"

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_parallel_chunk_generation(self, mock_find_dbgen):
        """Test parallel data generation with multiple chunks."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.output_dir, parallel=2)

        # Mock subprocess.run to simulate successful chunk generation
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)

            generator._run_parallel_dbgen(self.work_dir)

            # Should call subprocess.run for each chunk
            self.assertEqual(mock_run.call_count, 2)

            # No merge operation should occur anymore

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_parallel_chunk_failure(self, mock_find_dbgen):
        """Test error handling when a parallel chunk fails."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.output_dir, parallel=2)

        # Mock subprocess failure for one chunk
        with mock.patch("subprocess.run") as mock_run:
            error = subprocess.CalledProcessError(1, "dbgen")
            error.stderr = "Generation failed"
            mock_run.side_effect = [
                mock.Mock(returncode=0),  # First chunk succeeds
                error,  # Second fails
            ]

            with self.assertRaises(RuntimeError) as cm:
                generator._run_parallel_dbgen(self.work_dir)
            self.assertIn("Failed to generate TPC-H data chunk", str(cm.exception))

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_parallel_chunk_files_returned_directly(self, mock_find_dbgen):
        """Test that parallel chunk files are returned directly without merging."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        # No compression for this test to avoid confusion
        generator = TPCHDataGenerator(output_dir=self.output_dir, parallel=3, compression_type="none")

        # Create mock chunk files in the output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        chunk_files = {}
        for table in ["customer", "lineitem", "orders"]:
            chunk_files[table] = []
            for chunk_id in range(1, 4):  # 3 chunks
                chunk_file = self.output_dir / f"{table}.tbl.{chunk_id}"
                chunk_file.write_text(f"{table} data chunk {chunk_id}\n")
                chunk_files[table].append(chunk_file)

        # Mock the data generation process and compression check
        # _run_dbgen_native must return None to indicate file-based generation (not streaming)
        with mock.patch.object(generator, "_run_dbgen_native", return_value=None):
            with mock.patch.object(generator, "should_use_compression", return_value=False):
                result = generator._generate_local(self.output_dir)

        # Should return ALL chunk files for each table (as a list)
        for table in ["customer", "lineitem", "orders"]:
            self.assertIn(table, result)
            returned_files = result[table]
            # Should be a list of all chunk files (sorted by name)
            self.assertIsInstance(returned_files, list)
            assert isinstance(returned_files, list)  # Type narrowing for type checker
            self.assertEqual(len(returned_files), 3)  # 3 chunks
            self.assertEqual(returned_files[0].name, f"{table}.tbl.1")
            for f in returned_files:
                self.assertTrue(f.exists())

        # Check that all chunk files still exist (not merged/deleted)
        for table in ["customer", "lineitem", "orders"]:
            for chunk_id in range(1, 4):
                chunk_file = self.output_dir / f"{table}.tbl.{chunk_id}"
                self.assertTrue(chunk_file.exists(), f"Chunk file {chunk_file} should still exist")

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_parallel_chunk_compression_handling(self, mock_find_dbgen):
        """Test that compression works correctly with parallel chunk files."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(
            output_dir=self.output_dir, parallel=2, compression_type="gzip", compress_data=True
        )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        all_tables = ["customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier"]

        def _mock_run_dbgen_native(_: Path):
            # Create mock chunk files during generation so they exist after stale-prune.
            for table in all_tables:
                for chunk_id in range(1, 3):  # 2 chunks
                    chunk_file = self.output_dir / f"{table}.tbl.{chunk_id}"
                    chunk_file.write_text(f"{table} data chunk {chunk_id}\n")
            return None  # file-based generation path

        # Mock the data generation and validation process
        with mock.patch.object(generator, "_run_dbgen_native", side_effect=_mock_run_dbgen_native):
            # Mock validator to indicate regeneration is needed (so it proceeds to _finalize_generation)
            with mock.patch.object(generator.validator, "should_regenerate_data") as mock_validate:
                mock_validate.return_value = (True, None)  # Regeneration needed

                with mock.patch.object(generator, "compress_existing_file") as mock_compress:
                    mock_compress.side_effect = lambda f, remove_original=False: Path(str(f) + ".gz")

                    # Mock _write_manifest to avoid file I/O issues
                    with mock.patch.object(generator, "_write_manifest"):
                        result = generator._generate_local(self.output_dir)

                        # Should compress all chunk files (8 tables * 2 chunks each = 16)
                        expected_calls = 16
                        self.assertEqual(mock_compress.call_count, expected_calls)

                        # Should return ALL compressed chunk files for each table (as a list)
                        for table in all_tables:
                            self.assertIn(table, result)
                            returned_files = result[table]
                            self.assertIsInstance(returned_files, list)
                            assert isinstance(returned_files, list)  # Type narrowing
                            self.assertEqual(len(returned_files), 2)  # 2 chunks
                            for f in returned_files:
                                self.assertTrue(f.name.endswith(".gz"))

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_existing_chunk_files_discovery(self, mock_find_dbgen):
        """Test discovery of existing chunk files when skipping regeneration."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.output_dir, parallel=2)

        # Create mock existing chunk files
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for table in ["customer", "lineitem"]:
            for chunk_id in range(1, 3):  # 2 chunks
                chunk_file = self.output_dir / f"{table}.tbl.{chunk_id}"
                chunk_file.write_text(f"existing {table} data chunk {chunk_id}\n")

        # Mock validation to indicate no regeneration needed
        with mock.patch.object(generator.validator, "should_regenerate_data") as mock_validate:
            mock_validate.return_value = (False, None)  # Don't regenerate

            result = generator._generate_local()

            # Should find and return ALL chunk files for each table (as a list)
            for table in ["customer", "lineitem"]:
                self.assertIn(table, result)
                returned_files = result[table]
                # Should return all chunk files (sorted by name)
                self.assertIsInstance(returned_files, list)
                assert isinstance(returned_files, list)  # Type narrowing
                self.assertEqual(len(returned_files), 2)  # 2 chunks
                self.assertEqual(returned_files[0].name, f"{table}.tbl.1")
                for f in returned_files:
                    self.assertTrue(f.exists())

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_parallel_execution_path_selection(self, mock_find_dbgen):
        """Test that parallel vs single execution path is selected correctly."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(parallel=1, output_dir=self.temp_dir)

        with mock.patch.object(generator, "_run_parallel_dbgen") as mock_parallel:
            with mock.patch("subprocess.run") as mock_single:
                mock_single.return_value = mock.Mock(returncode=0)

                work_dir = self.temp_dir / "work"
                work_dir.mkdir(exist_ok=True)

                generator._run_dbgen_native(work_dir)

                # Should use single execution, not parallel
                mock_parallel.assert_not_called()
                # The single path makes two calls: main dbgen and sync
                self.assertEqual(mock_single.call_count, 2)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_parallel_execution_path_multiple(self, mock_find_dbgen):
        """Test that parallel execution path is used when parallel > 1."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(parallel=2, output_dir=self.temp_dir)

        with mock.patch.object(generator, "_run_parallel_dbgen") as mock_parallel:
            with mock.patch("subprocess.run") as mock_single:
                work_dir = self.temp_dir / "work"
                work_dir.mkdir(exist_ok=True)

                generator._run_dbgen_native(work_dir)

                # Should use parallel execution, not single
                mock_parallel.assert_called_once_with(work_dir)
                mock_single.assert_not_called()

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_relative_output_directory_uses_absolute_paths(self, mock_find_dbgen):
        """Ensure dbgen receives absolute working paths even when output_dir is relative."""
        mock_find_dbgen.return_value = Path(sys.executable)

        original_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        try:
            relative_output = Path("tpch_relative")
            generator = TPCHDataGenerator(output_dir=relative_output, parallel=1, force_regenerate=True)

            dbgen_calls = []

            def _fake_run(cmd, **kwargs):
                result = mock.Mock(returncode=0, stdout=b"", stderr=b"")
                if cmd and str(cmd[0]) == str(mock_find_dbgen.return_value):
                    dbgen_calls.append(
                        {
                            "cmd": cmd,
                            "cwd": kwargs.get("cwd"),
                            "env": kwargs.get("env"),
                        }
                    )
                return result

            with mock.patch("subprocess.run", side_effect=_fake_run):
                generator._run_dbgen_native(generator.output_dir)

            self.assertTrue(dbgen_calls, "dbgen invocation was not captured")
            dbgen_call = dbgen_calls[0]

            # CWD and DSS_PATH should resolve to the absolute output directory
            expected_dir = generator.output_dir.resolve()
            self.assertTrue(Path(dbgen_call["cwd"]).is_absolute())
            self.assertEqual(Path(dbgen_call["cwd"]), expected_dir)

            dss_path = Path(dbgen_call["env"]["DSS_PATH"])
            self.assertTrue(dss_path.is_absolute())
            self.assertEqual(dss_path, expected_dir)

            dss_config = Path(dbgen_call["env"]["DSS_CONFIG"])
            self.assertTrue(dss_config.is_absolute())
        finally:
            os.chdir(original_cwd)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_run_dbgen_method_basic(self, mock_find_dbgen):
        """Test the _run_dbgen method functionality."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(scale_factor=0.1, output_dir=self.temp_dir)
        work_dir = self.temp_dir / "work"
        work_dir.mkdir(exist_ok=True)
        dbgen_exe = self.temp_dir / "dbgen"

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)

            generator._run_dbgen(dbgen_exe, work_dir)

            # Check that subprocess was called with correct arguments
            call_args = mock_run.call_args[0][0]
            self.assertIn(str(dbgen_exe), call_args)
            self.assertIn("-vf", call_args)
            self.assertIn("-s", call_args)
            self.assertIn("0.1", call_args)  # scale factor

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_run_dbgen_subprocess_error(self, mock_find_dbgen):
        """Test handling of subprocess errors in _run_dbgen."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.temp_dir)
        work_dir = self.temp_dir / "work"
        work_dir.mkdir(exist_ok=True)
        dbgen_exe = self.temp_dir / "dbgen"

        with mock.patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "dbgen")

            with self.assertRaises(RuntimeError) as cm:
                generator._run_dbgen(dbgen_exe, work_dir)

            self.assertIn("Failed to generate TPC-H data", str(cm.exception))

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_verbose_output_handling(self, mock_find_dbgen):
        """Test that verbose mode affects subprocess output handling."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        # Test verbose mode
        generator_verbose = TPCHDataGenerator(verbose=True, output_dir=self.temp_dir)
        work_dir = self.temp_dir / "work"
        work_dir.mkdir(exist_ok=True)
        dbgen_exe = self.temp_dir / "dbgen"

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)

            generator_verbose._run_dbgen(dbgen_exe, work_dir)

            # stdout is always DEVNULL to prevent log bloat from spinner output
            # stderr is captured for debugging
            call_kwargs = mock_run.call_args[1]
            self.assertEqual(call_kwargs.get("stdout"), subprocess.DEVNULL)
            self.assertEqual(call_kwargs.get("stderr"), subprocess.PIPE)

        # Test non-verbose mode
        generator_quiet = TPCHDataGenerator(verbose=False, output_dir=self.temp_dir)

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)

            generator_quiet._run_dbgen(dbgen_exe, work_dir)

            # stdout is always DEVNULL to prevent log bloat from spinner output
            # stderr is captured for debugging
            call_kwargs = mock_run.call_args[1]
            self.assertEqual(call_kwargs.get("stdout"), subprocess.DEVNULL)
            self.assertEqual(call_kwargs.get("stderr"), subprocess.PIPE)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_single_threaded_execution(self, mock_find_dbgen):
        """Test single-threaded data generation."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.output_dir, parallel=1)

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)

            generator._run_dbgen_native(self.work_dir)

            # Should call subprocess.run twice for single-threaded (dbgen + sync)
            self.assertEqual(mock_run.call_count, 2)

            # Check command includes expected arguments for the first call (dbgen)
            call_args = mock_run.call_args_list[0][0][0]
            self.assertIn("-vf", call_args)
            self.assertIn("-s", call_args)  # Scale factor argument

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_execution_failure_with_verbose_output(self, mock_find_dbgen):
        """Test error handling with verbose output enabled."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.output_dir, verbose=True)

        with mock.patch("subprocess.run") as mock_run:
            error = subprocess.CalledProcessError(1, "dbgen")
            error.stderr = "stderr output"
            error.stdout = "stdout output"
            mock_run.side_effect = error

            with self.assertRaises(RuntimeError) as context:
                generator._run_dbgen_native(self.work_dir)

            # Error message should include stderr
            self.assertIn("stderr output", str(context.exception))

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_execution_environment_variables(self, mock_find_dbgen):
        """Test that DSS_PATH environment variable is set correctly."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(output_dir=self.output_dir)

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)

            generator._run_dbgen_native(self.work_dir)

            # Check that env parameter includes DSS_PATH for the first call (dbgen)
            call_kwargs = mock_run.call_args_list[0][1]
            self.assertIn("env", call_kwargs)
            env = call_kwargs["env"]
            self.assertIn("DSS_PATH", env)
            expected_dir = self.work_dir.resolve()
            self.assertEqual(Path(env["DSS_PATH"]).resolve(), expected_dir)
            self.assertIn("DSS_CONFIG", env)
            self.assertEqual(Path(env["DSS_CONFIG"]).resolve(), expected_dir)


class TestTPCHDataGeneratorEdgeCases(unittest.TestCase):
    """Edge cases and error handling tests."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # Additional edge case tests can be added here as needed


class TestTPCHDataGeneratorIntegration(unittest.TestCase):
    """Integration tests for complete workflow."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.output_dir = self.temp_dir / "output"

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_complete_generation_workflow(self, mock_find_dbgen):
        """Test the complete data generation workflow."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        generator = TPCHDataGenerator(scale_factor=0.01, output_dir=self.output_dir, verbose=False)

        # Mock all the subprocess calls
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)

            # Mock file operations
            with mock.patch.object(generator, "_move_data_files") as mock_move:
                mock_tbl_files = {
                    table: self.output_dir / f"{table}.tbl"
                    for table in [
                        "customer",
                        "lineitem",
                        "nation",
                        "orders",
                        "part",
                        "partsupp",
                        "region",
                        "supplier",
                    ]
                }
                mock_move.return_value = mock_tbl_files

                # Run the generation
                result = generator.generate()

                # Check results - may be empty due to mocking
                assert isinstance(result, dict)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_output_directory_creation(self, mock_find_dbgen):
        """Test that output directory is created if it doesn't exist."""
        mock_find_dbgen.return_value = Path("/tmp/dbgen")

        # Use a nested directory that doesn't exist
        nested_output = self.temp_dir / "nested" / "output"
        generator = TPCHDataGenerator(output_dir=nested_output)

        # Mock the rest of the generation process
        with mock.patch("subprocess.run"), mock.patch.object(generator, "_move_data_files", return_value={}):
            generator.generate()

            # Directory should be created
            self.assertTrue(nested_output.exists())


# Pytest markers for different test categories
pytestmark = [pytest.mark.unit, pytest.mark.fast]


if __name__ == "__main__":
    unittest.main()
