"""Tests for TPC-H stdout data generation with -z flag.

These tests verify that the TPC-H dbgen binary correctly supports stdout output
via the -z flag, and that the BenchBox integration correctly uses streaming
compression when the flag is available.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from benchbox.core.tpch.generator import _TPCH_TABLE_CODES, TPCHDataGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.slow,
]


class TestDbgenStdoutSupport:
    """Tests for dbgen -z flag support at the binary level."""

    @pytest.fixture
    def dbgen_exe(self) -> Path | None:
        """Get the dbgen executable path if available."""
        try:
            generator = TPCHDataGenerator(scale_factor=0.01)
            return generator.dbgen_exe
        except (RuntimeError, FileNotFoundError):
            pytest.skip("dbgen binary not available")

    def test_dbgen_help_shows_z_flag(self, dbgen_exe: Path):

        result = subprocess.run(
            [str(dbgen_exe), "-h"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # -z help text should be in stderr (where dbgen prints help)
        assert "-z" in result.stderr or "-z" in result.stdout, "dbgen binary does not support -z flag for stdout output"

    def test_dbgen_z_flag_produces_output(self, dbgen_exe: Path):

        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy dists.dss if needed
            generator = TPCHDataGenerator(scale_factor=0.01)
            dists_file = generator.dbgen_path / "dists.dss"
            if dists_file.exists():
                import shutil

                shutil.copy2(dists_file, Path(tmpdir) / "dists.dss")

            # Generate region table (smallest, only 5 rows)
            result = subprocess.run(
                [str(dbgen_exe), "-z", "-s", "0.01", "-T", "r", "-q"],
                capture_output=True,
                cwd=tmpdir,
                timeout=10,
            )

            assert result.returncode == 0, f"dbgen failed: {result.stderr}"
            assert len(result.stdout) > 0, "dbgen -z produced no output"

            # Verify output is pipe-delimited and has expected format
            lines = result.stdout.decode().strip().split("\n")
            assert len(lines) == 5, f"Expected 5 region rows, got {len(lines)}"
            for line in lines:
                # Region table format: regionkey|name|comment
                parts = line.split("|")
                assert len(parts) >= 3, f"Invalid region row format: {line}"

    @pytest.mark.parametrize("table_name,table_code", list(_TPCH_TABLE_CODES.items()))
    def test_dbgen_z_flag_all_tables(self, dbgen_exe: Path, table_name: str, table_code: str):

        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy dists.dss if needed
            generator = TPCHDataGenerator(scale_factor=0.01)
            dists_file = generator.dbgen_path / "dists.dss"
            if dists_file.exists():
                import shutil

                shutil.copy2(dists_file, Path(tmpdir) / "dists.dss")

            result = subprocess.run(
                [str(dbgen_exe), "-z", "-s", "0.01", "-T", table_code, "-q"],
                capture_output=True,
                cwd=tmpdir,
                timeout=60,  # lineitem can be slow at SF 0.01
            )

            assert result.returncode == 0, f"dbgen -z failed for {table_name}: {result.stderr}"
            assert len(result.stdout) > 0, f"dbgen -z produced no output for {table_name}"


class TestStdoutMatchesFileOutput:
    """Tests that verify stdout output matches file-based output exactly."""

    @pytest.fixture
    def dbgen_exe(self) -> Path | None:
        """Get the dbgen executable path if available."""
        try:
            generator = TPCHDataGenerator(scale_factor=0.01)
            return generator.dbgen_exe
        except (RuntimeError, FileNotFoundError):
            pytest.skip("dbgen binary not available")

    def test_stdout_matches_file_output_region(self, dbgen_exe: Path):

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Copy dists.dss if needed
            generator = TPCHDataGenerator(scale_factor=0.01)
            dists_file = generator.dbgen_path / "dists.dss"
            if dists_file.exists():
                import shutil

                shutil.copy2(dists_file, tmpdir_path / "dists.dss")

            stdout_result = subprocess.run(
                [str(dbgen_exe), "-z", "-s", "0.01", "-T", "r", "-q"],
                capture_output=True,
                cwd=tmpdir,
                timeout=10,
            )
            assert stdout_result.returncode == 0

            subprocess.run(
                [str(dbgen_exe), "-s", "0.01", "-T", "r", "-f", "-q"],
                capture_output=True,
                cwd=tmpdir,
                timeout=10,
            )

            file_output = (tmpdir_path / "region.tbl").read_bytes()

            assert stdout_result.stdout == file_output, "stdout output does not match file output for region table"

    def test_stdout_matches_file_output_customer(self, dbgen_exe: Path):

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Copy dists.dss if needed
            generator = TPCHDataGenerator(scale_factor=0.01)
            dists_file = generator.dbgen_path / "dists.dss"
            if dists_file.exists():
                import shutil

                shutil.copy2(dists_file, tmpdir_path / "dists.dss")

            stdout_result = subprocess.run(
                [str(dbgen_exe), "-z", "-s", "0.01", "-T", "c", "-q"],
                capture_output=True,
                cwd=tmpdir,
                timeout=30,
            )
            assert stdout_result.returncode == 0

            subprocess.run(
                [str(dbgen_exe), "-s", "0.01", "-T", "c", "-f", "-q"],
                capture_output=True,
                cwd=tmpdir,
                timeout=30,
            )

            file_output = (tmpdir_path / "customer.tbl").read_bytes()

            assert stdout_result.stdout == file_output, "stdout output does not match file output for customer table"


class TestGeneratorStdoutDetection:
    """Tests for TPCHDataGenerator stdout support detection."""

    def test_check_stdout_support_returns_bool(self):

        try:
            generator = TPCHDataGenerator(scale_factor=0.01)
            result = generator._check_stdout_support()
            assert isinstance(result, bool)
        except (RuntimeError, FileNotFoundError):
            pytest.skip("dbgen binary not available")

    def test_check_stdout_support_is_cached(self):

        try:
            generator = TPCHDataGenerator(scale_factor=0.01)
            # First call
            result1 = generator._check_stdout_support()
            # Second call should use cached value
            result2 = generator._check_stdout_support()
            assert result1 == result2
            # Check cache attribute exists
            assert hasattr(generator, "_stdout_support_cached")
        except (RuntimeError, FileNotFoundError):
            pytest.skip("dbgen binary not available")

    def test_updated_binary_supports_z_flag(self):

        try:
            generator = TPCHDataGenerator(scale_factor=0.01)
            assert generator._check_stdout_support(), "dbgen binary should support -z flag after patches are applied"
        except (RuntimeError, FileNotFoundError):
            pytest.skip("dbgen binary not available")


class TestBackwardCompatibility:
    """Tests verifying file-based generation still works correctly."""

    def test_file_mode_generation_works(self):
        """Verify file-based generation still works (no -z flag)."""
        try:
            generator = TPCHDataGenerator(scale_factor=0.01)
            dbgen_exe = generator.dbgen_exe
        except (RuntimeError, FileNotFoundError):
            pytest.skip("dbgen binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Copy dists.dss if needed
            dists_file = generator.dbgen_path / "dists.dss"
            if dists_file.exists():
                import shutil

                shutil.copy2(dists_file, tmpdir_path / "dists.dss")

            # Generate region table using file mode (no -z)
            result = subprocess.run(
                [str(dbgen_exe), "-s", "0.01", "-T", "r", "-f", "-q"],
                capture_output=True,
                cwd=tmpdir,
                timeout=10,
            )

            assert result.returncode == 0, f"File-mode generation failed: {result.stderr}"
            assert (tmpdir_path / "region.tbl").exists(), "region.tbl not created"
            assert (tmpdir_path / "region.tbl").stat().st_size > 0, "region.tbl is empty"

    def test_file_mode_creates_correct_format(self):

        try:
            generator = TPCHDataGenerator(scale_factor=0.01)
            dbgen_exe = generator.dbgen_exe
        except (RuntimeError, FileNotFoundError):
            pytest.skip("dbgen binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Copy dists.dss if needed
            dists_file = generator.dbgen_path / "dists.dss"
            if dists_file.exists():
                import shutil

                shutil.copy2(dists_file, tmpdir_path / "dists.dss")

            # Generate region table
            subprocess.run(
                [str(dbgen_exe), "-s", "0.01", "-T", "r", "-f", "-q"],
                capture_output=True,
                cwd=tmpdir,
                timeout=10,
            )

            content = (tmpdir_path / "region.tbl").read_text()
            lines = content.strip().split("\n")

            # Verify format
            assert len(lines) == 5, f"Expected 5 regions, got {len(lines)}"
            for i, line in enumerate(lines):
                parts = line.split("|")
                assert len(parts) >= 3, f"Invalid format in line {i}: {line}"
                # First column should be region key (0-4)
                assert parts[0].isdigit()


class TestMoneyFormatFix:
    """Tests for the money format bug fix (%ld -> %d)."""

    def test_money_format_is_correct(self):
        """Verify money values are correctly formatted (bug fix verification)."""
        try:
            generator = TPCHDataGenerator(scale_factor=0.01)
            dbgen_exe = generator.dbgen_exe
        except (RuntimeError, FileNotFoundError):
            pytest.skip("dbgen binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Copy dists.dss if needed
            dists_file = generator.dbgen_path / "dists.dss"
            if dists_file.exists():
                import shutil

                shutil.copy2(dists_file, tmpdir_path / "dists.dss")

            # Generate customer table (has money field: acctbal)
            result = subprocess.run(
                [str(dbgen_exe), "-z", "-s", "0.01", "-T", "c", "-q"],
                capture_output=True,
                cwd=tmpdir,
                timeout=30,
            )

            assert result.returncode == 0

            lines = result.stdout.decode().strip().split("\n")
            for i, line in enumerate(lines[:10]):  # Check first 10 rows
                parts = line.split("|")
                # Customer table: custkey|name|address|nationkey|phone|acctbal|mktsegment|comment
                assert len(parts) >= 7, f"Invalid customer row {i}: {line}"

                acctbal = parts[5]
                # Money should be decimal with 2 decimal places (e.g., "711.56")
                assert "." in acctbal, f"Money format missing decimal: {acctbal}"
                whole, decimal = acctbal.replace("-", "").split(".")
                assert len(decimal) == 2, f"Money should have 2 decimal places: {acctbal}"
                # Values should be reasonable (not garbage from wrong format specifier)
                try:
                    value = float(acctbal)
                    assert -10000 <= value <= 10000, f"Account balance out of range: {value}"
                except ValueError:
                    pytest.fail(f"Invalid money value: {acctbal}")
