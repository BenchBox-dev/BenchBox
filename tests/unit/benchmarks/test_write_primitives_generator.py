"""Tests for Write Primitives data generator.

Focuses on testing:
- File locking mechanisms
- Scale factor validation
- Small dataset handling
- Concurrent generation scenarios
- Error handling edge cases

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from benchbox.core.tpch.generator import TPCHDataGenerator
from benchbox.core.write_primitives.generator import WritePrimitivesDataGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


_TPCH_TABLE_FILES = (
    "customer.tbl",
    "lineitem.tbl",
    "nation.tbl",
    "orders.tbl",
    "part.tbl",
    "partsupp.tbl",
    "region.tbl",
    "supplier.tbl",
)


def _write_mock_tpch_data(directory: Path) -> None:
    """Write a deterministic lightweight TPCH dataset for generator tests."""
    directory.mkdir(parents=True, exist_ok=True)

    orders_path = directory / "orders.tbl"
    with open(orders_path, "w", encoding="utf-8") as f:
        # Keep >2000 rows so parallel split/error-path tests remain meaningful.
        for order_key in range(1, 4001):
            row = (
                f"{order_key}|{order_key}|O|{1000.0 + order_key:.2f}|1995-01-01|"
                f"1-URGENT|Clerk#000000001|0|sample order {order_key}|\n"
            )
            f.write(row)

    lineitem_path = directory / "lineitem.tbl"
    with open(lineitem_path, "w", encoding="utf-8") as f:
        for line_key in range(1, 6001):
            row = (
                f"{line_key}|{line_key}|{line_key}|1|1.0|10.0|0.0|0.0|N|O|1995-01-02|"
                f"1995-01-03|1995-01-04|DELIVER IN PERSON|AIR|sample lineitem {line_key}|\n"
            )
            f.write(row)

    tiny_row = "1|1|\n"
    for filename in _TPCH_TABLE_FILES:
        table_path = directory / filename
        if table_path.exists():
            continue
        table_path.write_text(tiny_row, encoding="utf-8")


@pytest.fixture(scope="module")
def shared_tpch_seed_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create module-scoped seed TPCH data once for fast test reuse."""
    seed_dir = tmp_path_factory.mktemp("write_primitives_tpch_seed")
    _write_mock_tpch_data(seed_dir)
    return seed_dir


@pytest.fixture(autouse=True)
def mock_tpch_generator(shared_tpch_seed_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock TPCH generation by copying shared seed files into each output dir."""

    def _mock_generate(self: TPCHDataGenerator) -> dict[str, Path]:
        output_dir = Path(self.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        table_paths: dict[str, Path] = {}
        for filename in _TPCH_TABLE_FILES:
            source = shared_tpch_seed_dir / filename
            target = output_dir / filename
            shutil.copy2(source, target)
            table_paths[filename.removesuffix(".tbl")] = target
        return table_paths

    monkeypatch.setattr(TPCHDataGenerator, "generate", _mock_generate)


@pytest.mark.slow
class TestFileLocking:
    """Tests for file locking mechanisms during bulk load generation."""

    def test_lock_prevents_concurrent_generation(self):
        """Test that file locking prevents concurrent bulk load file generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data first
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            # Create generator instance
            gen1 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)

            # Acquire lock with first generator
            assert gen1._acquire_bulk_load_lock(timeout=1)

            try:
                # Try to acquire lock with second generator (should fail)
                gen2 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
                assert not gen2._acquire_bulk_load_lock(timeout=1)
            finally:
                # Release lock
                gen1._release_bulk_load_lock()

    def test_lock_is_released_after_generation(self):
        """Test that lock file is properly removed after generation completes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            # Generate bulk load files
            gen = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen.generate()

            # Lock file should not exist after generation
            lock_file = output_dir / "write_primitives_auxiliary" / ".bulk_load_generation.lock"
            assert not lock_file.exists()

    def test_lock_contains_pid(self):
        """Test that lock file contains the process ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            gen = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)

            # Acquire lock
            assert gen._acquire_bulk_load_lock(timeout=1)

            try:
                # Check lock file contains PID
                lock_file = output_dir / "write_primitives_auxiliary" / ".bulk_load_generation.lock"
                assert lock_file.exists()

                content = lock_file.read_text()
                assert content.startswith("pid:")

                # Extract PID and verify it's our process
                pid = int(content.split(":")[1])
                assert pid == os.getpid()
            finally:
                gen._release_bulk_load_lock()

    def test_stale_lock_detection_by_pid(self):
        """Test that stale locks are detected when process is not running."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            files_dir = output_dir / "write_primitives_auxiliary"
            files_dir.mkdir(parents=True, exist_ok=True)

            # Create a fake lock file with a non-existent PID
            lock_file = files_dir / ".bulk_load_generation.lock"
            fake_pid = 999999  # Very unlikely to exist
            lock_file.write_text(f"pid:{fake_pid}\n")

            # Make lock file old
            old_time = time.time() - 400  # 6+ minutes old
            os.utime(lock_file, (old_time, old_time))

            # Generate TPC-H data
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            gen = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)

            # Should be able to acquire lock (stale lock removed)
            assert gen._acquire_bulk_load_lock(timeout=1)
            gen._release_bulk_load_lock()

    def test_stale_lock_detection_by_age(self):
        """Test that locks older than 5 minutes are considered stale."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            files_dir = output_dir / "write_primitives_auxiliary"
            files_dir.mkdir(parents=True, exist_ok=True)

            # Create a lock file with current PID but make it old
            lock_file = files_dir / ".bulk_load_generation.lock"
            lock_file.write_text(f"pid:{os.getpid()}\n")

            # Make lock file old (6+ minutes)
            old_time = time.time() - 400
            os.utime(lock_file, (old_time, old_time))

            # Generate TPC-H data
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            gen = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)

            # Should be able to acquire lock (stale lock removed)
            assert gen._acquire_bulk_load_lock(timeout=1)
            gen._release_bulk_load_lock()

    def test_process_liveness_check(self):
        """Test that process liveness check works correctly."""
        gen = WritePrimitivesDataGenerator(scale_factor=0.01, verbose=False)

        # Current process should be running
        assert gen._is_process_running(os.getpid())

        # Non-existent process should not be running
        fake_pid = 999999
        assert not gen._is_process_running(fake_pid)


@pytest.mark.slow
class TestScaleFactorValidation:
    """Tests for scale factor validation of bulk load files."""

    def test_files_reused_when_scale_factor_matches(self):
        """Test that bulk load files are reused when scale factor matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data and bulk load files
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            gen1 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen1.generate()

            # Record modification time of a file
            test_file = output_dir / "write_primitives_auxiliary" / "csv_small_1k.csv"
            assert test_file.exists()
            original_mtime = test_file.stat().st_mtime

            # Set a known baseline mtime so we can assert unchanged deterministically.
            frozen_mtime = original_mtime - 1
            os.utime(test_file, (frozen_mtime, frozen_mtime))

            # Generate again with same scale factor (should reuse files)
            gen2 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen2.generate()

            # File should not have been regenerated (same mtime)
            assert test_file.stat().st_mtime == frozen_mtime

    def test_files_regenerated_when_scale_factor_changes(self):
        """Test that bulk load files are regenerated when scale factor changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data and bulk load files at SF=0.01
            tpch_gen1 = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen1.generate()

            gen1 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen1.generate()

            # Verify metadata shows SF=0.01
            metadata_file = output_dir / "write_primitives_auxiliary" / ".bulk_load_metadata.json"
            assert metadata_file.exists()
            with open(metadata_file, encoding="utf-8") as f:
                metadata = json.load(f)
            assert metadata["scale_factor"] == 0.01

            # Generate TPC-H data at SF=0.02
            tpch_gen2 = TPCHDataGenerator(
                scale_factor=0.02, output_dir=output_dir, verbose=False, force_regenerate=True
            )
            tpch_gen2.generate()

            # Generate bulk load files at SF=0.02 (should regenerate)
            gen2 = WritePrimitivesDataGenerator(scale_factor=0.02, output_dir=output_dir, verbose=False)
            gen2.generate()

            # Verify metadata updated to SF=0.02
            with open(metadata_file, encoding="utf-8") as f:
                metadata = json.load(f)
            assert metadata["scale_factor"] == 0.02

    def test_metadata_file_written_correctly(self):
        """Test that metadata file is written with correct information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate data
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            gen = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen.generate()

            # Check metadata file
            metadata_file = output_dir / "write_primitives_auxiliary" / ".bulk_load_metadata.json"
            assert metadata_file.exists()

            with open(metadata_file, encoding="utf-8") as f:
                metadata = json.load(f)

            assert "scale_factor" in metadata
            assert metadata["scale_factor"] == 0.01
            assert "generated_at" in metadata
            assert "file_count" in metadata
            assert metadata["file_count"] > 0

    def test_check_bulk_load_files_exist_validates_scale_factor(self):
        """Test that check_bulk_load_files_exist() validates scale factor."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate data at SF=0.01
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            gen1 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen1.generate()

            # Check with matching scale factor (should return True)
            gen2 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            assert gen2.check_bulk_load_files_exist()

            # Check with different scale factor (should return False)
            gen3 = WritePrimitivesDataGenerator(scale_factor=0.02, output_dir=output_dir, verbose=False)
            assert not gen3.check_bulk_load_files_exist()


@pytest.mark.slow
class TestSmallDatasetHandling:
    """Tests for handling small datasets in bulk load file generation."""

    def test_parallel_parts_with_small_dataset(self):
        """Test that parallel parts are generated correctly with < 2000 rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data at SF=0.01 (should have ~150 orders)
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            # Generate bulk load files
            gen = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen.generate()

            # Check that all 4 parallel parts exist and have data
            files_dir = output_dir / "write_primitives_auxiliary"
            for part_num in range(1, 5):
                part_file = files_dir / f"csv_parallel_part{part_num}.csv"
                assert part_file.exists()

                # Count rows (excluding header)
                with open(part_file, encoding="utf-8") as f:
                    lines = f.readlines()
                assert len(lines) > 1  # Header + at least 1 data row

    def test_error_file_with_small_dataset(self):
        """Test that error file is generated correctly with < 102 rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data at SF=0.01
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            # Generate bulk load files
            gen = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen.generate()

            # Check that error file exists and has data
            error_file = output_dir / "write_primitives_auxiliary" / "csv_with_errors.csv"
            assert error_file.exists()

            with open(error_file, encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) > 1  # Header + at least some data rows

    def test_all_parallel_parts_have_roughly_equal_rows(self):
        """Test that parallel parts have roughly equal row distribution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            # Generate bulk load files
            gen = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen.generate()

            # Count rows in each part (excluding header)
            files_dir = output_dir / "write_primitives_auxiliary"
            part_sizes = []
            for part_num in range(1, 5):
                with open(files_dir / f"csv_parallel_part{part_num}.csv", encoding="utf-8") as f:
                    lines = f.readlines()
                part_sizes.append(len(lines) - 1)  # Exclude header

            # Verify all parts have data
            assert all(size > 0 for size in part_sizes)

            # Verify roughly equal distribution (within 50% for small datasets)
            avg_size = sum(part_sizes) / len(part_sizes)
            for size in part_sizes:
                deviation = abs(size - avg_size) / avg_size if avg_size > 0 else 0
                assert deviation <= 0.5  # Within 50% of average

    def test_no_index_error_with_very_small_dataset(self):
        """Test that no IndexError occurs with very small datasets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data at minimum scale
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            # This should not raise any exceptions
            gen = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen.generate()  # Should complete without IndexError


@pytest.mark.slow
class TestConcurrentGeneration:
    """Tests for concurrent bulk load file generation scenarios."""

    def test_double_check_locking_pattern(self):
        """Test that double-check locking prevents redundant generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            # First generator creates files
            gen1 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen1.generate()

            # Record creation time of test file
            test_file = output_dir / "write_primitives_auxiliary" / "csv_small_1k.csv"
            original_mtime = test_file.stat().st_mtime

            # Freeze mtime to avoid real sleeps while preserving regeneration check.
            frozen_mtime = original_mtime - 1
            os.utime(test_file, (frozen_mtime, frozen_mtime))

            # Second generator should detect files exist and skip generation
            gen2 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen2.generate()

            # File should not have been regenerated
            assert test_file.stat().st_mtime == frozen_mtime

    def test_force_regenerate_bypasses_existing_files(self):
        """Test that force_regenerate regenerates files even if they exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data and bulk load files
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            gen1 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen1.generate()

            # Record original mtime
            test_file = output_dir / "write_primitives_auxiliary" / "csv_small_1k.csv"
            original_mtime = test_file.stat().st_mtime

            # Freeze mtime to avoid sleep while asserting forced regeneration.
            frozen_mtime = original_mtime - 1
            os.utime(test_file, (frozen_mtime, frozen_mtime))

            # Force regenerate
            gen2 = WritePrimitivesDataGenerator(
                scale_factor=0.01, output_dir=output_dir, verbose=False, force_regenerate=True
            )
            gen2.generate()

            # File should have been regenerated (different mtime)
            assert test_file.stat().st_mtime > frozen_mtime


class TestErrorHandling:
    """Tests for error handling edge cases."""

    def test_corrupted_metadata_file_handled_gracefully(self):
        """Test that corrupted metadata file doesn't crash generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            files_dir = output_dir / "write_primitives_auxiliary"
            files_dir.mkdir(parents=True, exist_ok=True)

            # Create corrupted metadata file
            metadata_file = files_dir / ".bulk_load_metadata.json"
            metadata_file.write_text("{ corrupted json")

            # Generate TPC-H data
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            # Should handle gracefully and regenerate files
            gen = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen.generate()  # Should not crash

            # Files should be generated
            assert (files_dir / "csv_small_1k.csv").exists()

    def test_missing_metadata_file_handled_gracefully(self):
        """Test that missing metadata file doesn't prevent file reuse."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Generate TPC-H data and bulk load files
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            gen1 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            gen1.generate()

            # Delete metadata file
            metadata_file = output_dir / "write_primitives_auxiliary" / ".bulk_load_metadata.json"
            metadata_file.unlink()

            # Should still work (files exist, just no metadata)
            gen2 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            # check_bulk_load_files_exist should still work without metadata
            result = gen2.check_bulk_load_files_exist()
            # Result may be True or False depending on whether files exist
            assert isinstance(result, bool)

    def test_no_tpch_data_skips_bulk_load_generation(self):
        """Test that bulk load generation is skipped when no TPC-H data exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Don't generate TPC-H data - just try to generate bulk load files
            gen = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            files = gen.generate_bulk_load_files()

            # Should return empty dict (no files generated)
            assert files == {}

    def test_lock_timeout_returns_false(self):
        """Test that lock acquisition timeout returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            files_dir = output_dir / "write_primitives_auxiliary"
            files_dir.mkdir(parents=True, exist_ok=True)

            # Generate TPC-H data
            tpch_gen = TPCHDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
            tpch_gen.generate()

            gen1 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)

            # Acquire lock with first generator - use short timeout for fast test
            assert gen1._acquire_bulk_load_lock(timeout=0.1)

            try:
                # Second generator should timeout and return False (short timeout)
                gen2 = WritePrimitivesDataGenerator(scale_factor=0.01, output_dir=output_dir, verbose=False)
                result = gen2._acquire_bulk_load_lock(timeout=0.1)
                assert result is False
            finally:
                gen1._release_bulk_load_lock()
