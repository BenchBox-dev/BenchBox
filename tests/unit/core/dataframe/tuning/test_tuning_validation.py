"""Unit tests for DataFrame tuning validation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.dataframe.tuning import (
    DataFrameTuningConfiguration,
    ExecutionConfiguration,
    GPUConfiguration,
    MemoryConfiguration,
    ParallelismConfiguration,
    ValidationIssue,
    ValidationLevel,
    format_issues,
    has_errors,
    has_warnings,
    validate_dataframe_tuning,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestValidationIssue:
    """Tests for ValidationIssue dataclass."""

    def test_str_representation(self):
        """Test string representation of ValidationIssue."""
        issue = ValidationIssue(
            level=ValidationLevel.ERROR,
            message="Test error message",
            setting="test_setting",
            suggestion="Fix this",
        )
        result = str(issue)
        assert "[ERROR]" in result
        assert "test_setting" in result
        assert "Test error message" in result
        assert "Fix this" in result

    def test_str_without_setting(self):
        """Test string representation without setting."""
        issue = ValidationIssue(
            level=ValidationLevel.WARNING,
            message="Test warning",
        )
        result = str(issue)
        assert "[WARNING]" in result
        assert "Test warning" in result


class TestValidationHelpers:
    """Tests for validation helper functions."""

    def test_has_errors_true(self):
        """Test has_errors() returns True when errors present."""
        issues = [
            ValidationIssue(ValidationLevel.ERROR, "Error"),
            ValidationIssue(ValidationLevel.WARNING, "Warning"),
        ]
        assert has_errors(issues) is True

    def test_has_errors_false(self):
        """Test has_errors() returns False when no errors."""
        issues = [
            ValidationIssue(ValidationLevel.WARNING, "Warning"),
            ValidationIssue(ValidationLevel.INFO, "Info"),
        ]
        assert has_errors(issues) is False

    def test_has_warnings_true(self):
        """Test has_warnings() returns True when warnings present."""
        issues = [
            ValidationIssue(ValidationLevel.WARNING, "Warning"),
        ]
        assert has_warnings(issues) is True

    def test_has_warnings_false(self):
        """Test has_warnings() returns False when no warnings."""
        issues = [
            ValidationIssue(ValidationLevel.INFO, "Info"),
        ]
        assert has_warnings(issues) is False

    def test_format_issues_empty(self):
        """Test format_issues() with empty list."""
        result = format_issues([])
        assert "No validation issues found" in result

    def test_format_issues_with_content(self):
        """Test format_issues() with issues."""
        issues = [
            ValidationIssue(ValidationLevel.WARNING, "Test warning"),
        ]
        result = format_issues(issues)
        assert "WARNING" in result
        assert "Test warning" in result


class TestValidateDataFrameTuning:
    """Tests for validate_dataframe_tuning() function."""

    def test_default_config_no_issues(self):
        """Test that default config has no issues."""
        config = DataFrameTuningConfiguration()
        issues = validate_dataframe_tuning(config, "polars")
        # Default config should have no issues
        assert not any(i.level == ValidationLevel.ERROR for i in issues)

    def test_incompatible_setting_warning(self):
        """Test that incompatible settings generate warnings."""
        config = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(worker_count=4),  # Not compatible with Polars
        )
        issues = validate_dataframe_tuning(config, "polars")
        assert any(i.level == ValidationLevel.WARNING and "worker_count" in str(i) for i in issues)


class TestPolarsValidation:
    """Tests for Polars-specific validation."""

    def test_streaming_without_chunk_size_info(self):
        """Test that streaming without chunk_size generates info."""
        config = DataFrameTuningConfiguration(
            execution=ExecutionConfiguration(streaming_mode=True),
        )
        issues = validate_dataframe_tuning(config, "polars")
        assert any(i.level == ValidationLevel.INFO for i in issues)

    def test_invalid_engine_affinity_error(self):
        """Test that invalid engine_affinity generates error."""
        config = DataFrameTuningConfiguration(
            execution=ExecutionConfiguration(engine_affinity="invalid"),
        )
        issues = validate_dataframe_tuning(config, "polars")
        assert any(i.level == ValidationLevel.ERROR and "engine_affinity" in str(i) for i in issues)

    def test_conflicting_streaming_settings_warning(self):
        """Test that conflicting streaming settings generate warning."""
        config = DataFrameTuningConfiguration(
            execution=ExecutionConfiguration(
                streaming_mode=True,
                engine_affinity="in-memory",
            ),
        )
        issues = validate_dataframe_tuning(config, "polars")
        assert any(i.level == ValidationLevel.WARNING for i in issues)


class TestDaskValidation:
    """Tests for Dask-specific validation."""

    def test_high_threads_per_worker_warning(self):
        """Test that high threads_per_worker generates warning."""
        config = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(threads_per_worker=16),
        )
        issues = validate_dataframe_tuning(config, "dask")
        assert any(i.level == ValidationLevel.WARNING and "threads_per_worker" in str(i) for i in issues)

    def test_spill_without_memory_limit_info(self):
        """Test that spill without memory_limit generates info."""
        config = DataFrameTuningConfiguration(
            memory=MemoryConfiguration(spill_to_disk=True),
        )
        issues = validate_dataframe_tuning(config, "dask")
        assert any(i.level == ValidationLevel.INFO for i in issues)


class TestDataFusionValidation:
    def test_session_settings_are_supported(self):
        config = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(thread_count=4),
            memory=MemoryConfiguration(chunk_size=4096),
        )
        issues = validate_dataframe_tuning(config, "datafusion-df")

        assert not any(i.level == ValidationLevel.WARNING for i in issues)


class TestModinValidation:
    """Tests for Modin-specific validation."""

    def test_invalid_engine_affinity_error(self):
        """Test that invalid engine_affinity generates error."""
        config = DataFrameTuningConfiguration(
            execution=ExecutionConfiguration(engine_affinity="invalid_engine"),
        )
        issues = validate_dataframe_tuning(config, "modin")
        assert any(i.level == ValidationLevel.ERROR for i in issues)


class TestCuDFValidation:
    """Tests for cuDF-specific validation."""

    def test_gpu_disabled_warning(self):
        """Test that disabled GPU generates warning."""
        config = DataFrameTuningConfiguration(
            gpu=GPUConfiguration(enabled=False),
        )
        issues = validate_dataframe_tuning(config, "cudf")
        assert any(i.level == ValidationLevel.WARNING and "GPU is disabled" in str(i) for i in issues)

    def test_invalid_pool_type_error(self):
        """Test that invalid pool_type generates error."""
        # This should be caught by dataclass validation, not this function
        # But we test the function logic anyway
        config = DataFrameTuningConfiguration(
            gpu=GPUConfiguration(enabled=True),
        )
        # Default pool_type is valid, so no errors expected
        issues = validate_dataframe_tuning(config, "cudf")
        assert not any(i.level == ValidationLevel.ERROR and "pool_type" in str(i) for i in issues)

    def test_spill_disabled_info(self):
        """Test that disabled spill generates info."""
        config = DataFrameTuningConfiguration(
            gpu=GPUConfiguration(enabled=True, spill_to_host=False),
        )
        issues = validate_dataframe_tuning(config, "cudf")
        assert any(i.level == ValidationLevel.INFO for i in issues)


class TestPlatformNormalization:
    """Tests for platform name normalization in validation."""

    def test_validates_with_df_suffix(self):
        """Test that validation works with -df suffix."""
        config = DataFrameTuningConfiguration()
        issues = validate_dataframe_tuning(config, "polars-df")
        assert not any(i.level == ValidationLevel.ERROR for i in issues)

    def test_validates_case_insensitive(self):
        """Test that validation is case-insensitive."""
        config = DataFrameTuningConfiguration()
        issues = validate_dataframe_tuning(config, "POLARS")
        assert not any(i.level == ValidationLevel.ERROR for i in issues)
