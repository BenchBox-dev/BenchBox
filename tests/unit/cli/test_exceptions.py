"""Tests for CLI exception handling and validation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from io import StringIO

import pytest
from rich.console import Console

import benchbox
from benchbox.cli.exceptions import (
    BenchboxCLIError,
    CloudStorageError,
    ConfigurationError,
    DatabaseError,
    ErrorContext,
    ErrorHandler,
    ExecutionError,
    PlatformError,
    ValidationError,
    ValidationRules,
    create_error_handler,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


def _assert_version_metadata(payload: dict) -> None:
    """Assert that version metadata is present and correct."""

    assert payload.get("benchbox_version") == benchbox.__version__
    assert payload.get("release_tag") == f"v{benchbox.__version__}"
    # Presence of the consistency flag is sufficient; value may vary in tests
    assert "version_consistent" not in payload or isinstance(payload["version_consistent"], bool)


class TestBenchboxCLIErrors:
    """Test CLI exception hierarchy."""

    def test_base_cli_error(self):
        """Test base CLI error."""
        error = BenchboxCLIError("Test error", {"key": "value"})

        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.details.get("key") == "value"
        _assert_version_metadata(error.details)

    def test_configuration_error(self):
        """Test configuration error."""
        error = ConfigurationError("Invalid configuration", {"config": "test"})

        assert isinstance(error, BenchboxCLIError)
        assert error.message == "Invalid configuration"
        assert error.details.get("config") == "test"
        _assert_version_metadata(error.details)

    def test_database_error(self):
        """Test database error."""
        error = DatabaseError("Connection failed")

        assert isinstance(error, BenchboxCLIError)
        assert error.message == "Connection failed"
        _assert_version_metadata(error.details)

    def test_execution_error(self):
        """Test execution error."""
        error = ExecutionError("Benchmark failed", {"stage": "execution"})

        assert isinstance(error, BenchboxCLIError)
        assert error.message == "Benchmark failed"
        assert error.details.get("stage") == "execution"
        _assert_version_metadata(error.details)

    def test_validation_error(self):
        """Test validation error."""
        error = ValidationError("Invalid input", {"field": "scale_factor"})

        assert isinstance(error, BenchboxCLIError)
        assert error.message == "Invalid input"
        assert error.details.get("field") == "scale_factor"
        _assert_version_metadata(error.details)

    def test_cloud_storage_error(self):
        """Test cloud storage error."""
        error = CloudStorageError("Credentials invalid", {"provider": "s3"})

        assert isinstance(error, BenchboxCLIError)
        assert error.message == "Credentials invalid"
        assert error.details.get("provider") == "s3"
        _assert_version_metadata(error.details)

    def test_platform_error(self):
        """Test platform error."""
        error = PlatformError("Platform unavailable", {"platform": "duckdb"})

        assert isinstance(error, BenchboxCLIError)
        assert error.message == "Platform unavailable"
        assert error.details.get("platform") == "duckdb"
        _assert_version_metadata(error.details)


class TestErrorContext:
    """Test ErrorContext dataclass."""

    def test_error_context_creation(self):
        """Test creating ErrorContext."""
        context = ErrorContext(
            operation="test_operation",
            stage="validation",
            benchmark_name="tpch",
            database_type="duckdb",
            user_input={"scale_factor": 0.01},
            system_info={"memory_gb": 16},
        )

        assert context.operation == "test_operation"
        assert context.stage == "validation"
        assert context.benchmark_name == "tpch"
        assert context.database_type == "duckdb"
        assert context.user_input == {"scale_factor": 0.01}
        assert context.system_info.get("memory_gb") == 16
        _assert_version_metadata(context.system_info)

    def test_error_context_minimal(self):
        """Test ErrorContext with minimal information."""
        context = ErrorContext(operation="test_operation", stage="execution")

        assert context.operation == "test_operation"
        assert context.stage == "execution"
        assert context.benchmark_name is None
        assert context.database_type is None
        assert context.user_input is None
        assert context.system_info is not None
        _assert_version_metadata(context.system_info)


class TestErrorHandler:
    """Test ErrorHandler functionality."""

    def test_error_handler_creation(self):
        """Test creating ErrorHandler."""
        console = Console(file=StringIO(), force_terminal=True)
        handler = ErrorHandler(console)

        assert handler.console == console
        assert handler.logger is not None

    def test_handle_configuration_error(self):
        """Test handling configuration error."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        handler = ErrorHandler(console)

        error = ConfigurationError("Invalid benchmark config", {"benchmark": "invalid"})
        context = ErrorContext("benchmark_setup", "configuration")

        handler.handle_error(error, context, show_traceback=False)

        output_text = output.getvalue()
        assert "Configuration Error" in output_text
        assert "Invalid benchmark config" in output_text
        assert "Configuration Help" in output_text

    def test_handle_database_error(self):
        """Test handling database error."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        handler = ErrorHandler(console)

        error = DatabaseError("Connection refused", {"database": "postgresql"})
        context = ErrorContext("database_connect", "connection", database_type="postgresql")

        handler.handle_error(error, context, show_traceback=False)

        output_text = output.getvalue()
        assert "Database Error" in output_text
        assert "Connection refused" in output_text
        assert "Database Help" in output_text
        assert "postgresql" in output_text

    def test_handle_cloud_storage_error(self):
        """Test handling cloud storage error."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        handler = ErrorHandler(console)

        error = CloudStorageError("Credentials missing", {"provider": "s3"})
        context = ErrorContext("cloud_validation", "setup")

        handler.handle_error(error, context, show_traceback=False)

        output_text = output.getvalue()
        assert "Cloud Storage Error" in output_text
        assert "Credentials missing" in output_text
        assert "Cloud Storage Help" in output_text
        assert "AWS S3" in output_text

    def test_handle_generic_error(self):
        """Test handling generic Python exception."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        handler = ErrorHandler(console)

        error = RuntimeError("Something went wrong")
        context = ErrorContext("test_operation", "execution")

        handler.handle_error(error, context, show_traceback=False)

        output_text = output.getvalue()
        assert "Unexpected Error" in output_text
        assert "Something went wrong" in output_text
        assert "report this issue" in output_text
        assert f"Release Tag: v{benchbox.__version__}" in output_text

    def test_create_error_handler_factory(self):
        """Test error handler factory function."""
        console = Console()
        handler = create_error_handler(console)

        assert isinstance(handler, ErrorHandler)
        assert handler.console == console


class TestValidationRules:
    """Test ValidationRules functionality."""

    def test_validate_scale_factor_positive(self):
        """Test scale factor validation with positive value."""
        # Should not raise exception
        ValidationRules.validate_scale_factor(0.01)
        ValidationRules.validate_scale_factor(1.0)
        ValidationRules.validate_scale_factor(10.0)

    def test_validate_scale_factor_zero(self):
        """Test scale factor validation with zero."""
        with pytest.raises(ValidationError) as exc_info:
            ValidationRules.validate_scale_factor(0.0)

        assert "Scale factor must be positive" in str(exc_info.value)
        assert exc_info.value.details["provided_value"] == 0.0

    def test_validate_scale_factor_negative(self):
        """Test scale factor validation with negative value."""
        with pytest.raises(ValidationError) as exc_info:
            ValidationRules.validate_scale_factor(-1.0)

        assert "Scale factor must be positive" in str(exc_info.value)
        assert exc_info.value.details["provided_value"] == -1.0

    def test_validate_scale_factor_large(self):
        """Test scale factor validation with very large value."""
        with pytest.raises(ValidationError) as exc_info:
            ValidationRules.validate_scale_factor(200.0)

        assert "Scale factor is very large" in str(exc_info.value)
        assert exc_info.value.details["provided_value"] == 200.0
        assert "recommended_range" in exc_info.value.details

    def test_validate_benchmark_name_valid(self):
        """Test benchmark name validation with valid names."""
        available = ["tpch", "tpcds", "ssb"]

        # Should not raise exceptions
        ValidationRules.validate_benchmark_name("tpch", available)
        ValidationRules.validate_benchmark_name("TPCH", available)  # Case insensitive
        ValidationRules.validate_benchmark_name("TpcDs", available)

    def test_validate_benchmark_name_empty(self):
        """Test benchmark name validation with empty name."""
        with pytest.raises(ValidationError) as exc_info:
            ValidationRules.validate_benchmark_name("", ["tpch"])

        assert "Benchmark name cannot be empty" in str(exc_info.value)

    def test_validate_benchmark_name_invalid(self):
        """Test benchmark name validation with invalid name."""
        available = ["tpch", "tpcds"]

        with pytest.raises(ValidationError) as exc_info:
            ValidationRules.validate_benchmark_name("invalid", available)

        assert "Unknown benchmark: invalid" in str(exc_info.value)
        assert exc_info.value.details["provided_name"] == "invalid"
        assert exc_info.value.details["available_benchmarks"] == available

    def test_validate_output_directory_local_valid(self, tmp_path):
        """Test output directory validation with valid local path."""
        # Should not raise exception
        ValidationRules.validate_output_directory(str(tmp_path))

    def test_validate_output_directory_local_invalid(self):
        """Test output directory validation with invalid local path."""
        with pytest.raises(ValidationError) as exc_info:
            ValidationRules.validate_output_directory("/invalid/path/that/cannot/be/created")

        assert "Cannot create output directory" in str(exc_info.value)
        assert exc_info.value.details["path"] == "/invalid/path/that/cannot/be/created"

    def test_validate_output_directory_cloud_invalid_credentials(self):
        """Test output directory validation with cloud path and invalid credentials."""
        # This should fail because we don't have S3 credentials set up
        with pytest.raises(CloudStorageError) as exc_info:
            ValidationRules.validate_output_directory("s3://test-bucket/path")

        assert "Cloud storage credentials validation failed" in str(exc_info.value)
        # Provider can be 's3' (cloudpathlib installed) or 'unknown' (not installed)
        assert exc_info.value.details["provider"] in ("s3", "unknown")

    def test_validate_output_directory_allows_user_stage_for_native_snowflake(self):
        ValidationRules.validate_output_directory("@~/benchbox", platform="snowflake", table_mode="native")

    def test_validate_output_directory_rejects_named_stage_for_native_snowflake(self):
        with pytest.raises(CloudStorageError, match="named or table stage"):
            ValidationRules.validate_output_directory("@my_stage/data", platform="snowflake", table_mode="native")

    def test_validate_output_directory_rejects_stage_for_external_snowflake(self):
        with pytest.raises(CloudStorageError, match="requires a cloud URI"):
            ValidationRules.validate_output_directory("@~/benchbox", platform="snowflake", table_mode="external")
