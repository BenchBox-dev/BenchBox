"""Unit tests for BenchmarkDataValidator and data validation dataclasses.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from datetime import datetime
from pathlib import Path

import pytest

from benchbox.utils.data_validation import (
    BenchmarkDataValidator,
    DataValidationResult,
    TableExpectation,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# DataValidationResult dataclass
# ---------------------------------------------------------------------------


class TestDataValidationResult:
    """Tests for the DataValidationResult dataclass."""

    def test_fields_are_stored(self):
        now = datetime.now()
        result = DataValidationResult(
            valid=True,
            tables_validated={"orders": True, "lineitem": True},
            missing_tables=[],
            row_count_mismatches={},
            file_size_info={"orders.tbl": 1024},
            validation_timestamp=now,
            issues=[],
        )
        assert result.valid is True
        assert result.tables_validated == {"orders": True, "lineitem": True}
        assert result.missing_tables == []
        assert result.row_count_mismatches == {}
        assert result.file_size_info == {"orders.tbl": 1024}
        assert result.validation_timestamp is now
        assert result.issues == []

    def test_invalid_result_with_issues(self):
        result = DataValidationResult(
            valid=False,
            tables_validated={"orders": False},
            missing_tables=["lineitem"],
            row_count_mismatches={"orders": (1500000, 999)},
            file_size_info={},
            validation_timestamp=datetime.now(),
            issues=["Missing data files for table lineitem"],
        )
        assert result.valid is False
        assert "lineitem" in result.missing_tables
        assert result.row_count_mismatches["orders"] == (1500000, 999)
        assert len(result.issues) == 1


# ---------------------------------------------------------------------------
# TableExpectation dataclass
# ---------------------------------------------------------------------------


class TestTableExpectation:
    """Tests for the TableExpectation dataclass."""

    def test_required_fields(self):
        texp = TableExpectation(name="customer", expected_rows=150000, expected_files=["customer.tbl"])
        assert texp.name == "customer"
        assert texp.expected_rows == 150000
        assert texp.expected_files == ["customer.tbl"]

    def test_default_optional_fields(self):
        texp = TableExpectation(name="t", expected_rows=0, expected_files=[])
        assert texp.min_file_size == 0
        assert texp.allow_zero_rows is False

    def test_allow_zero_rows_flag(self):
        texp = TableExpectation(name="empty_table", expected_rows=0, expected_files=[], allow_zero_rows=True)
        assert texp.allow_zero_rows is True


# ---------------------------------------------------------------------------
# BenchmarkDataValidator: initialization
# ---------------------------------------------------------------------------


class TestValidatorInit:
    """Tests for BenchmarkDataValidator initialization."""

    def test_tpch_benchmark_loads_expectations(self):
        v = BenchmarkDataValidator("tpch", scale_factor=1.0)
        assert v.benchmark_name == "tpch"
        assert v.scale_factor == 1.0
        assert "lineitem" in v.table_expectations
        assert "customer" in v.table_expectations

    def test_tpcds_benchmark_loads_expectations(self):
        v = BenchmarkDataValidator("tpcds", scale_factor=1.0)
        assert "catalog_sales" in v.table_expectations
        assert "store_sales" in v.table_expectations

    def test_case_insensitive_benchmark_name(self):
        v = BenchmarkDataValidator("TPCH", scale_factor=1.0)
        assert v.benchmark_name == "tpch"
        assert len(v.table_expectations) == 8  # 8 TPC-H tables

    def test_unknown_benchmark_has_empty_expectations(self):
        v = BenchmarkDataValidator("custom_bench", scale_factor=1.0)
        assert v.table_expectations == {}


# ---------------------------------------------------------------------------
# Table expectations constants
# ---------------------------------------------------------------------------


class TestTableExpectationsConstants:
    """Verify the static table expectations dictionaries."""

    def test_tpch_expectations_non_empty(self):
        exps = BenchmarkDataValidator.TPCH_TABLE_EXPECTATIONS
        assert len(exps) == 8
        for name, texp in exps.items():
            assert isinstance(texp, TableExpectation)
            assert texp.name == name
            assert texp.expected_rows > 0
            assert len(texp.expected_files) >= 1

    def test_tpcds_expectations_non_empty(self):
        exps = BenchmarkDataValidator.TPCDS_TABLE_EXPECTATIONS
        assert len(exps) == 24
        for name, texp in exps.items():
            assert isinstance(texp, TableExpectation)
            assert texp.name == name
            assert len(texp.expected_files) >= 1

    def test_tpch_nation_has_25_rows_at_sf1(self):
        assert BenchmarkDataValidator.TPCH_TABLE_EXPECTATIONS["nation"].expected_rows == 25

    def test_tpch_region_has_5_rows_at_sf1(self):
        assert BenchmarkDataValidator.TPCH_TABLE_EXPECTATIONS["region"].expected_rows == 5


# ---------------------------------------------------------------------------
# Scale-adjusted expectations (_scale_expectations via __init__)
# ---------------------------------------------------------------------------


class TestScaleAdjustedExpectations:
    """Verify that scale factor adjusts row counts correctly."""

    def test_sf001_scales_variable_tables(self):
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        # lineitem SF=1 has 6001215 rows -> SF=0.01 -> int(6001215 * 0.01) = 60012
        assert v.table_expectations["lineitem"].expected_rows == int(6001215 * 0.01)
        # customer SF=1 has 150000 -> SF=0.01 -> 1500
        assert v.table_expectations["customer"].expected_rows == 1500

    def test_sf001_fixed_tables_unchanged(self):
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        # nation and region are fixed-size tables
        assert v.table_expectations["nation"].expected_rows == 25
        assert v.table_expectations["region"].expected_rows == 5

    def test_sf10_scales_up(self):
        v = BenchmarkDataValidator("tpch", scale_factor=10.0)
        assert v.table_expectations["customer"].expected_rows == 1500000
        assert v.table_expectations["nation"].expected_rows == 25  # still fixed

    def test_tpcds_fixed_tables_at_different_scale(self):
        v = BenchmarkDataValidator("tpcds", scale_factor=0.5)
        # At sf=0.5 (unofficial subscale), "fixed" TPC-DS tables scale proportionally
        # with max(1, floor(sf1_baseline * sf)). See _sources/tpcds-subscale-contract.md.
        assert v.table_expectations["call_center"].expected_rows == max(1, int(6 * 0.5))  # 3
        assert v.table_expectations["ship_mode"].expected_rows == max(1, int(20 * 0.5))  # 10
        assert v.table_expectations["warehouse"].expected_rows == max(1, int(5 * 0.5))  # 2 (floor -> 2? no: int(2.5)=2)
        assert v.table_expectations["time_dim"].expected_rows == max(1, int(86400 * 0.5))  # 43200
        # catalog_sales scales the same way
        expected_cs = max(1, int(1441548 * 0.5))
        assert v.table_expectations["catalog_sales"].expected_rows == expected_cs

    def test_tpcds_fixed_tables_at_official_scale(self):
        v = BenchmarkDataValidator("tpcds", scale_factor=1.0)
        # At sf=1.0 (official scale), "fixed" TPC-DS tables use their baseline row counts
        assert v.table_expectations["call_center"].expected_rows == 6
        assert v.table_expectations["ship_mode"].expected_rows == 20
        assert v.table_expectations["warehouse"].expected_rows == 5
        assert v.table_expectations["time_dim"].expected_rows == 86400


# ---------------------------------------------------------------------------
# validate_data_directory
# ---------------------------------------------------------------------------


class TestValidateDataDirectory:
    """Tests for validate_data_directory with real temp directories."""

    def test_nonexistent_directory_returns_invalid(self, tmp_path):
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        result = v.validate_data_directory(tmp_path / "does_not_exist")
        assert result.valid is False
        assert any("does not exist" in issue for issue in result.issues)

    def test_empty_directory_reports_missing_tables(self, tmp_path):
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        result = v.validate_data_directory(tmp_path)
        assert result.valid is False
        # All 8 TPC-H tables should be listed as missing
        assert len(result.missing_tables) == 8
        assert "lineitem" in result.missing_tables
        assert "customer" in result.missing_tables

    def test_unknown_benchmark_empty_dir_reports_no_data(self, tmp_path):
        v = BenchmarkDataValidator("custom", scale_factor=1.0)
        result = v.validate_data_directory(tmp_path)
        assert result.valid is False
        assert any("No data files" in issue for issue in result.issues)

    def test_unknown_benchmark_with_files_is_valid(self, tmp_path):
        # Write some data files (non-empty)
        (tmp_path / "data.csv").write_text("a,b,c\n1,2,3\n")
        v = BenchmarkDataValidator("custom", scale_factor=1.0)
        result = v.validate_data_directory(tmp_path)
        assert result.valid is True
        assert "data.csv" in result.file_size_info
        assert result.file_size_info["data.csv"] > 0

    def test_unknown_benchmark_empty_file_flagged(self, tmp_path):
        (tmp_path / "empty.csv").write_text("")
        v = BenchmarkDataValidator("custom", scale_factor=1.0)
        result = v.validate_data_directory(tmp_path)
        assert any("Empty data file" in issue for issue in result.issues)


# ---------------------------------------------------------------------------
# Table existence validation
# ---------------------------------------------------------------------------


class TestTableExistenceValidation:
    """Tests for table file resolution and existence checking."""

    def test_present_table_file_is_validated(self, tmp_path):
        # Create a customer.tbl file with enough rows for SF=0.01 (1500 rows)
        lines = "\n".join([f"row{i}" for i in range(1500)]) + "\n"
        (tmp_path / "customer.tbl").write_text(lines)
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        result = v.validate_data_directory(tmp_path)
        # customer should be validated (may or may not pass row count, but not missing)
        assert "customer" not in result.missing_tables

    def test_missing_table_reported(self, tmp_path):
        # Create only a customer file, not lineitem
        (tmp_path / "customer.tbl").write_text("row\n")
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        result = v.validate_data_directory(tmp_path)
        assert "lineitem" in result.missing_tables

    def test_compressed_gz_variant_resolved(self, tmp_path):
        import gzip

        data = b"row1\nrow2\nrow3\n"
        with gzip.open(tmp_path / "customer.tbl.gz", "wb") as f:
            f.write(data)
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        result = v.validate_data_directory(tmp_path)
        # customer should not be listed as missing
        assert "customer" not in result.missing_tables


# ---------------------------------------------------------------------------
# Row count validation
# ---------------------------------------------------------------------------


class TestRowCountValidation:
    """Tests for row count checking in TPC-H validation."""

    def test_matching_row_count_passes(self, tmp_path):
        # nation at SF=0.01 should still be 25 (fixed table)
        lines = "\n".join([f"row{i}" for i in range(25)]) + "\n"
        (tmp_path / "nation.tbl").write_text(lines)
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        # Validate just this one table by checking it's not in mismatches
        missing = []
        mismatches: dict[str, tuple[int, int]] = {}
        sizes: dict[str, int] = {}
        issues: list[str] = []
        expectation = v.table_expectations["nation"]
        valid = v._validate_single_table(tmp_path, "nation", expectation, missing, mismatches, sizes, issues)
        assert valid is True
        assert "nation" not in mismatches

    def test_mismatching_row_count_detected(self, tmp_path):
        # nation expects 25 rows but we write 100 (well outside 5% tolerance)
        lines = "\n".join([f"row{i}" for i in range(100)]) + "\n"
        (tmp_path / "nation.tbl").write_text(lines)
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        missing = []
        mismatches: dict[str, tuple[int, int]] = {}
        sizes: dict[str, int] = {}
        issues: list[str] = []
        expectation = v.table_expectations["nation"]
        valid = v._validate_single_table(tmp_path, "nation", expectation, missing, mismatches, sizes, issues)
        assert valid is False
        assert "nation" in mismatches
        expected_rows, actual_rows = mismatches["nation"]
        assert expected_rows == 25
        assert actual_rows == 100

    def test_empty_file_invalid_when_zero_rows_not_allowed(self, tmp_path):
        (tmp_path / "customer.tbl").write_text("")
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        missing = []
        mismatches: dict[str, tuple[int, int]] = {}
        sizes: dict[str, int] = {}
        issues: list[str] = []
        expectation = v.table_expectations["customer"]
        valid = v._validate_single_table(tmp_path, "customer", expectation, missing, mismatches, sizes, issues)
        assert valid is False
        assert any("empty" in issue.lower() for issue in issues)


# ---------------------------------------------------------------------------
# should_regenerate_data
# ---------------------------------------------------------------------------


class TestShouldRegenerateData:
    """Tests for should_regenerate_data decision logic."""

    def test_force_regenerate_always_returns_true(self, tmp_path):
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        should_regen, result = v.should_regenerate_data(tmp_path, force_regenerate=True)
        assert should_regen is True
        assert result.valid is False
        assert any("Force regeneration" in issue for issue in result.issues)

    def test_invalid_data_triggers_regeneration(self, tmp_path):
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        should_regen, result = v.should_regenerate_data(tmp_path)
        assert should_regen is True
        assert result.valid is False


# ---------------------------------------------------------------------------
# Validation timestamp
# ---------------------------------------------------------------------------


class TestValidationTimestamp:
    """Tests that validation timestamps are populated."""

    def test_timestamp_is_recent(self, tmp_path):
        before = datetime.now()
        v = BenchmarkDataValidator("tpch", scale_factor=0.01)
        result = v.validate_data_directory(tmp_path)
        after = datetime.now()
        assert before <= result.validation_timestamp <= after


# ---------------------------------------------------------------------------
# _format_bytes helper
# ---------------------------------------------------------------------------


class TestFormatBytes:
    """Tests for the human-readable byte formatting helper."""

    def test_zero_bytes(self):
        v = BenchmarkDataValidator("tpch")
        assert v._format_bytes(0) == "0 B"

    def test_kilobytes(self):
        v = BenchmarkDataValidator("tpch")
        formatted = v._format_bytes(1024)
        assert "KB" in formatted
        assert "1.0" in formatted

    def test_megabytes(self):
        v = BenchmarkDataValidator("tpch")
        formatted = v._format_bytes(1048576)
        assert "MB" in formatted

    def test_gigabytes(self):
        v = BenchmarkDataValidator("tpch")
        formatted = v._format_bytes(1073741824)
        assert "GB" in formatted
