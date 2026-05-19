"""Input validation schemas for BenchBox MCP server.

Provides Pydantic models for validating and sanitizing tool inputs
to ensure type safety, prevent invalid inputs, and protect against
malicious payloads.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Validation constants
MAX_QUERY_IDS = 100  # Maximum number of query IDs per request (DoS protection)
MAX_QUERY_ID_LENGTH = 64  # Maximum length of a single query ID
QUERY_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")  # Alphanumeric with dash/underscore
PLATFORM_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")  # Alphanumeric platform names
BENCHMARK_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")  # Alphanumeric benchmark names
FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")  # Safe filename characters

# Scale factor limits
MIN_SCALE_FACTOR = 0.001
MAX_SCALE_FACTOR = 10000  # 10TB scale factor is extreme but possible


class MCPValidationError(ValueError):
    """Raised when MCP input validation fails.

    This is distinct from pydantic.ValidationError to avoid confusion
    and provide clearer error handling in MCP tool implementations.
    """


def validate_query_id(query_id: str) -> str:
    """Validate a single query ID.

    Args:
        query_id: Query ID to validate

    Returns:
        Sanitized query ID

    Raises:
        MCPValidationError: If query ID is invalid
    """
    query_id = query_id.strip()

    if not query_id:
        raise MCPValidationError("Query ID cannot be empty")

    if len(query_id) > MAX_QUERY_ID_LENGTH:
        raise MCPValidationError(f"Query ID too long (max {MAX_QUERY_ID_LENGTH} chars): {query_id[:20]}...")

    if not QUERY_ID_PATTERN.match(query_id):
        raise MCPValidationError(f"Query ID contains invalid characters: {query_id}")

    return query_id


def validate_query_list(queries: str | None) -> list[str] | None:
    """Validate and parse a comma-separated query list.

    Args:
        queries: Comma-separated query IDs (e.g., "1,3,6")

    Returns:
        List of validated query IDs, or None if input is None/empty

    Raises:
        MCPValidationError: If any query ID is invalid or list is too long
    """
    if not queries:
        return None

    query_list = [q.strip() for q in queries.split(",") if q.strip()]

    if not query_list:
        return None

    if len(query_list) > MAX_QUERY_IDS:
        raise MCPValidationError(f"Too many query IDs (max {MAX_QUERY_IDS}): got {len(query_list)}")

    return [validate_query_id(q) for q in query_list]


def validate_platform_name(platform: str) -> str:
    """Validate a platform name.

    Args:
        platform: Platform name to validate

    Returns:
        Lowercased, sanitized platform name

    Raises:
        MCPValidationError: If platform name is invalid
    """
    platform = platform.strip().lower()

    if not platform:
        raise MCPValidationError("Platform name cannot be empty")

    if len(platform) > 50:
        raise MCPValidationError(f"Platform name too long (max 50 chars): {platform[:20]}...")

    if not PLATFORM_PATTERN.match(platform):
        raise MCPValidationError(f"Platform name contains invalid characters: {platform}")

    return platform


def validate_benchmark_name(benchmark: str) -> str:
    """Validate a benchmark name.

    Args:
        benchmark: Benchmark name to validate

    Returns:
        Lowercased, sanitized benchmark name

    Raises:
        MCPValidationError: If benchmark name is invalid
    """
    benchmark = benchmark.strip().lower()

    if not benchmark:
        raise MCPValidationError("Benchmark name cannot be empty")

    if len(benchmark) > 50:
        raise MCPValidationError(f"Benchmark name too long (max 50 chars): {benchmark[:20]}...")

    if not BENCHMARK_PATTERN.match(benchmark):
        raise MCPValidationError(f"Benchmark name contains invalid characters: {benchmark}")

    return benchmark


def validate_filename(filename: str) -> str:
    """Validate a result filename.

    Prevents path traversal attacks and other malicious filenames.

    Args:
        filename: Filename to validate

    Returns:
        Sanitized filename

    Raises:
        MCPValidationError: If filename is invalid or potentially malicious
    """
    filename = filename.strip()

    if not filename:
        raise MCPValidationError("Filename cannot be empty")

    if len(filename) > 255:
        raise MCPValidationError(f"Filename too long (max 255 chars): {filename[:20]}...")

    # Check for path traversal attempts
    if ".." in filename or "/" in filename or "\\" in filename:
        raise MCPValidationError(f"Filename cannot contain path components: {filename}")

    # Only allow safe characters
    if not FILENAME_PATTERN.match(filename):
        raise MCPValidationError(f"Filename contains invalid characters: {filename}")

    return filename


MODE_CHOICES = ("sql", "dataframe", "data_only")


def validate_mode(mode: str | None) -> str | None:
    """Validate execution mode value.

    Args:
        mode: Execution mode to validate ('sql', 'dataframe', or 'data_only')

    Returns:
        Lowercased, validated mode or None if input is None

    Raises:
        MCPValidationError: If mode is invalid
    """
    if mode is None:
        return None
    mode_lower = mode.strip().lower()
    # Normalize aliases
    if mode_lower in ("datagen", "generate"):
        mode_lower = "data_only"
    if mode_lower not in MODE_CHOICES:
        raise MCPValidationError(f"Invalid mode: {mode}. Must be 'sql', 'dataframe', or 'data_only'")
    return mode_lower


def validate_scale_factor(scale_factor: float) -> float:
    """Validate a scale factor.

    Args:
        scale_factor: Scale factor to validate

    Returns:
        Validated scale factor

    Raises:
        MCPValidationError: If scale factor is out of valid range
    """
    if scale_factor <= 0:
        raise MCPValidationError(f"Scale factor must be positive: {scale_factor}")

    if scale_factor < MIN_SCALE_FACTOR:
        raise MCPValidationError(f"Scale factor too small (min {MIN_SCALE_FACTOR}): {scale_factor}")

    if scale_factor > MAX_SCALE_FACTOR:
        raise MCPValidationError(f"Scale factor too large (max {MAX_SCALE_FACTOR}): {scale_factor}")

    return scale_factor


# Pydantic Models for Tool Inputs


class RunBenchmarkInput(BaseModel):
    """Input schema for run_benchmark tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    platform: Annotated[str, Field(min_length=1, max_length=50, description="Target database platform")]
    benchmark: Annotated[str, Field(min_length=1, max_length=50, description="Benchmark name")]
    scale_factor: Annotated[float, Field(gt=0, le=MAX_SCALE_FACTOR, default=0.01, description="Data scale factor")]
    queries: Annotated[str | None, Field(default=None, max_length=2000, description="Comma-separated query IDs")]
    phases: Annotated[str | None, Field(default=None, max_length=200, description="Comma-separated phase names")]
    mode: Annotated[
        str | None,
        Field(
            default=None,
            description="Execution mode: 'sql', 'dataframe', or 'data_only'. Uses platform default if not specified.",
        ),
    ] = None

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        return validate_platform_name(v)

    @field_validator("benchmark")
    @classmethod
    def validate_benchmark(cls, v: str) -> str:
        return validate_benchmark_name(v)

    @field_validator("scale_factor")
    @classmethod
    def validate_sf(cls, v: float) -> float:
        return validate_scale_factor(v)

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, v: str | None) -> str | None:
        if v:
            # Validate the query list format (this validates individual IDs)
            validate_query_list(v)
        return v

    @field_validator("mode")
    @classmethod
    def validate_mode_field(cls, v: str | None) -> str | None:
        return validate_mode(v)


class DryRunInput(BaseModel):
    """Input schema for dry_run tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    platform: Annotated[str, Field(min_length=1, max_length=50, description="Target database platform")]
    benchmark: Annotated[str, Field(min_length=1, max_length=50, description="Benchmark name")]
    scale_factor: Annotated[float, Field(gt=0, le=MAX_SCALE_FACTOR, default=0.01, description="Data scale factor")]
    queries: Annotated[str | None, Field(default=None, max_length=2000, description="Comma-separated query IDs")]
    mode: Annotated[
        str | None,
        Field(
            default=None,
            description="Execution mode: 'sql', 'dataframe', or 'data_only'. Uses platform default if not specified.",
        ),
    ] = None

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        return validate_platform_name(v)

    @field_validator("benchmark")
    @classmethod
    def validate_benchmark(cls, v: str) -> str:
        return validate_benchmark_name(v)

    @field_validator("scale_factor")
    @classmethod
    def validate_sf(cls, v: float) -> float:
        return validate_scale_factor(v)

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, v: str | None) -> str | None:
        if v:
            validate_query_list(v)
        return v

    @field_validator("mode")
    @classmethod
    def validate_mode_field(cls, v: str | None) -> str | None:
        return validate_mode(v)


class ValidateConfigInput(BaseModel):
    """Input schema for validate_config tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    platform: Annotated[str, Field(min_length=1, max_length=50, description="Target database platform")]
    benchmark: Annotated[str, Field(min_length=1, max_length=50, description="Benchmark name")]
    scale_factor: Annotated[float, Field(gt=0, le=MAX_SCALE_FACTOR, default=1.0, description="Data scale factor")]
    mode: Annotated[
        str | None,
        Field(
            default=None,
            description="Execution mode: 'sql', 'dataframe', or 'data_only'. Uses platform default if not specified.",
        ),
    ] = None

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        return validate_platform_name(v)

    @field_validator("benchmark")
    @classmethod
    def validate_benchmark(cls, v: str) -> str:
        return validate_benchmark_name(v)

    @field_validator("scale_factor")
    @classmethod
    def validate_sf(cls, v: float) -> float:
        return validate_scale_factor(v)

    @field_validator("mode")
    @classmethod
    def validate_mode_field(cls, v: str | None) -> str | None:
        return validate_mode(v)


class GetBenchmarkInfoInput(BaseModel):
    """Input schema for get_benchmark_info tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    benchmark: Annotated[str, Field(min_length=1, max_length=50, description="Benchmark name")]

    @field_validator("benchmark")
    @classmethod
    def validate_benchmark(cls, v: str) -> str:
        return validate_benchmark_name(v)


class ListRecentRunsInput(BaseModel):
    """Input schema for list_recent_runs tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    limit: Annotated[int, Field(ge=1, le=100, default=10, description="Maximum results to return")]
    platform: Annotated[str | None, Field(default=None, max_length=50, description="Filter by platform")]
    benchmark: Annotated[str | None, Field(default=None, max_length=50, description="Filter by benchmark")]

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str | None) -> str | None:
        if v:
            return validate_platform_name(v)
        return v

    @field_validator("benchmark")
    @classmethod
    def validate_benchmark(cls, v: str | None) -> str | None:
        if v:
            return validate_benchmark_name(v)
        return v


class GetResultsInput(BaseModel):
    """Input schema for get_results tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    result_file: Annotated[str, Field(min_length=1, max_length=255, description="Result filename")]
    include_queries: Annotated[bool, Field(default=True, description="Include per-query details")]

    @field_validator("result_file")
    @classmethod
    def validate_result_file(cls, v: str) -> str:
        return validate_filename(v)


class CompareResultsInput(BaseModel):
    """Input schema for compare_results tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    file1: Annotated[str, Field(min_length=1, max_length=255, description="Baseline result file")]
    file2: Annotated[str, Field(min_length=1, max_length=255, description="Comparison result file")]
    threshold_percent: Annotated[float, Field(ge=0, le=100, default=10.0, description="Change threshold percentage")]

    @field_validator("file1", "file2")
    @classmethod
    def validate_files(cls, v: str) -> str:
        return validate_filename(v)


class ExportSummaryInput(BaseModel):
    """Input schema for export_summary tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    result_file: Annotated[str, Field(min_length=1, max_length=255, description="Result filename")]
    format: Annotated[Literal["text", "markdown", "json"], Field(default="text", description="Output format")]

    @field_validator("result_file")
    @classmethod
    def validate_result_file(cls, v: str) -> str:
        return validate_filename(v)
