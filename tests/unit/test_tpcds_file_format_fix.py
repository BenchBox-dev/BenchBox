"""Tests for TPC-DS file format consistency fixes.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.core.tpcds.c_tools import tpcds_option
from benchbox.core.tpcds.generator import TPCDSDataGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.unit
class TestTPCDSFileFormatFix:
    """Test the fixes for TPC-DS file format inconsistency issue.

    These tests specifically test zstd compression features.
    """

    def test_streaming_compression_no_empty_files(self):
        """Test that streaming compression doesn't create empty compressed files."""
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td)
            generator = TPCDSDataGenerator(
                scale_factor=1.0,  # TPC-DS requires scale_factor >= 1.0
                output_dir=output_dir,
                parallel=3,
                compress_data=True,
                compression_type="zstd",
                verbose=False,
            )

            # Mock dsdgen Popen to return no data for chunk 2 and 3, data for chunk 1
            def mock_popen(cmd, **kwargs):
                process = Mock()
                process.returncode = 0
                process.stderr = None

                # Check if this is a streaming compression call (has -FILTER Y)
                if tpcds_option("filter") in cmd and "Y" in cmd:
                    # Simulate dsdgen behavior: only chunk 1 has data for call_center
                    if "call_center" in cmd and tpcds_option("child") in cmd:
                        chunk_id_idx = cmd.index(tpcds_option("child")) + 1
                        if chunk_id_idx < len(cmd):
                            chunk_id = int(cmd[chunk_id_idx])
                            if chunk_id == 1:
                                # Chunk 1 has data
                                import io

                                process.stdout = io.BytesIO(b"1|call_center_data|test\n")
                            else:
                                # Chunks 2 and 3 have no data
                                import io

                                process.stdout = io.BytesIO(b"")
                        else:
                            import io

                            process.stdout = io.BytesIO(b"")
                    else:
                        import io

                        process.stdout = io.BytesIO(b"")
                else:
                    import io

                    process.stdout = io.BytesIO(b"")

                process.wait = Mock(return_value=None)
                return process

            with patch("benchbox.core.tpcds.generator.streaming.subprocess.Popen", side_effect=mock_popen):
                # Test single table streaming compression
                generator._generate_single_table_chunk_streaming(output_dir, "call_center", 1)  # Should create file
                generator._generate_single_table_chunk_streaming(output_dir, "call_center", 2)  # Should not create file
                generator._generate_single_table_chunk_streaming(output_dir, "call_center", 3)  # Should not create file

                # Check files created
                all_files = list(output_dir.glob("*"))
                dat_files = [f for f in all_files if f.suffix == ".dat"]
                zst_files = [f for f in all_files if f.name.endswith(".dat.zst")]

                # Should have no .dat files (streaming compression)
                assert len(dat_files) == 0, f"Found uncompressed .dat files: {[f.name for f in dat_files]}"

                # Should have exactly one .zst file (only chunk 1 had data)
                assert len(zst_files) == 1, (
                    f"Expected 1 .zst file, found {len(zst_files)}: {[f.name for f in zst_files]}"
                )

                # The created file should have meaningful content (not empty)
                zst_file = zst_files[0]
                assert zst_file.stat().st_size > 20, (
                    f"Compressed file {zst_file.name} is too small: {zst_file.stat().st_size} bytes"
                )

    def test_file_validation_filters_empty_files(self):
        """Test that _is_valid_data_file correctly filters empty compressed files."""
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td)
            generator = TPCDSDataGenerator(
                scale_factor=1.0,  # TPC-DS requires scale_factor >= 1.0
                output_dir=output_dir,
                compress_data=True,
                compression_type="zstd",
            )

            # Create test files
            empty_zst = output_dir / "empty.dat.zst"
            empty_zst.write_bytes(b"\x28\xb5\x2f\xfd\x00\x00\x00\x00\x00")  # 9-byte empty zstd file

            valid_zst = output_dir / "valid.dat.zst"
            valid_zst.write_text("some data that compresses to more than 50 bytes of content here")

            empty_dat = output_dir / "empty.dat"
            empty_dat.write_bytes(b"")  # 0-byte file

            valid_dat = output_dir / "valid.dat"
            valid_dat.write_text("some data")

            # Test validation
            assert not generator._is_valid_data_file(empty_zst), "Empty .zst file should be invalid"
            assert generator._is_valid_data_file(valid_zst), "Valid .zst file should be valid"
            assert not generator._is_valid_data_file(empty_dat), "Empty .dat file should be invalid"
            assert generator._is_valid_data_file(valid_dat), "Valid .dat file should be valid"
            assert not generator._is_valid_data_file(output_dir / "nonexistent.dat"), (
                "Nonexistent file should be invalid"
            )

    def test_file_discovery_skips_empty_files(self):
        """Test that file discovery logic skips empty compressed files."""
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td)
            generator = TPCDSDataGenerator(
                scale_factor=1.0,  # TPC-DS requires scale_factor >= 1.0
                output_dir=output_dir,
                compress_data=True,
                compression_type="zstd",
            )

            # Create test files mimicking the issue
            # call_center_1_3.dat.zst - valid file with data
            valid_file = output_dir / "call_center_1_3.dat.zst"
            valid_file.write_text("1|call center data here|test\n" * 20)  # Enough data to be > 50 bytes when compressed

            # call_center_2_3.dat.zst and call_center_3_3.dat.zst - empty compressed files (the problem)
            empty_file1 = output_dir / "call_center_2_3.dat.zst"
            empty_file1.write_bytes(b"\x28\xb5\x2f\xfd\x00\x00\x00\x00\x00")  # 9-byte empty zstd file

            empty_file2 = output_dir / "call_center_3_3.dat.zst"
            empty_file2.write_bytes(b"\x28\xb5\x2f\xfd\x00\x00\x00\x00\x00")  # 9-byte empty zstd file

            # Test that file discovery only finds valid files
            # Mock the table names to just test call_center
            with patch.object(generator, "_generate_local"):
                table_paths = {}
                table_names = ["call_center"]

                for table_name in table_names:
                    if generator.should_use_compression():
                        base_pattern = f"{table_name}_*"
                        extension = generator.get_compressor().get_file_extension()
                        parallel_files = list(output_dir.glob(f"{base_pattern}.dat{extension}"))
                        # Use the same filtering logic from the fix
                        valid_parallel_files = [f for f in parallel_files if generator._is_valid_data_file(f)]
                        if valid_parallel_files:
                            table_paths[table_name] = valid_parallel_files[0]

                # Should only find one valid file, not the empty ones
                assert len(table_paths) == 1, f"Expected 1 table path, found {len(table_paths)}"
                assert "call_center" in table_paths, "call_center table should be found"

                # The found file should be the valid one, not the empty ones
                found_file = table_paths["call_center"]
                assert found_file.name == "call_center_1_3.dat.zst", (
                    f"Expected call_center_1_3.dat.zst, found {found_file.name}"
                )
                assert generator._is_valid_data_file(found_file), "Found file should be valid"

    def test_comprehensive_fix_validation(self):
        """Test that all components of the fix work together."""
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td)
            generator = TPCDSDataGenerator(
                scale_factor=1.0,  # TPC-DS requires scale_factor >= 1.0
                output_dir=output_dir,
                parallel=3,
                compress_data=True,
                compression_type="zstd",
                verbose=False,
            )

            # Simulate the original issue: mixed .dat and empty .zst files
            # This is what the broken system would create

            # Create a valid .dat file (the problem - shouldn't exist with compression)
            broken_dat = output_dir / "call_center_1_3.dat"
            broken_dat.write_text("1|call center data|test\n")

            # Create empty .zst files (the problem - empty compressed files)
            empty_zst1 = output_dir / "call_center_2_3.dat.zst"
            empty_zst1.write_bytes(b"\x28\xb5\x2f\xfd\x00\x00\x00\x00\x00")  # 9-byte empty zstd

            empty_zst2 = output_dir / "call_center_3_3.dat.zst"
            empty_zst2.write_bytes(b"\x28\xb5\x2f\xfd\x00\x00\x00\x00\x00")  # 9-byte empty zstd

            # Verify the problem exists
            all_files = list(output_dir.glob("*"))
            dat_files = [f for f in all_files if f.suffix == ".dat"]
            zst_files = [f for f in all_files if f.name.endswith(".dat.zst")]
            empty_zst = [f for f in zst_files if f.stat().st_size <= 9]

            assert len(dat_files) > 0, "Test setup should have created .dat files"
            assert len(empty_zst) > 0, "Test setup should have created empty .zst files"

            # Now test that the fix prevents this from appearing in results
            table_paths = {}
            table_names = ["call_center"]

            for table_name in table_names:
                if generator.should_use_compression():
                    # The fix: only look for valid compressed files
                    base_pattern = f"{table_name}_*"
                    extension = generator.get_compressor().get_file_extension()
                    parallel_files = list(output_dir.glob(f"{base_pattern}.dat{extension}"))
                    valid_parallel_files = [f for f in parallel_files if generator._is_valid_data_file(f)]
                    if valid_parallel_files:
                        table_paths[table_name] = valid_parallel_files[0]

            # The fix should result in no tables found (all files are invalid)
            assert len(table_paths) == 0, (
                f"Expected 0 tables (all invalid), found {len(table_paths)}: {list(table_paths.keys())}"
            )

            # This demonstrates the fix: the broken files are filtered out
            # In the real scenario, the streaming compression would prevent creating
            # the broken files in the first place, and this filtering provides defense in depth
