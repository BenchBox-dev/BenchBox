"""Input validation schemas for BenchBox MCP server.

Provides Pydantic models for validating and sanitizing tool inputs
to ensure type safety, prevent invalid inputs, and protect against
malicious payloads.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Validation constants
MAX_QUERY_IDS = 100  # Maximum number of query IDs per request (DoS protection)
MAX_QUERY_ID_LENGTH = 64  # Maximum length of a single query ID
QUERY_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")  # Alphanumeric with dash/underscore
PLATFORM_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")  # Alphanumeric platform names
BENCHMARK_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")  # Alphanumeric benchmark names
FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")  # Safe filename characters
PLATFORM_OPTION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MEMORY_LIMIT_PATTERN = re.compile(r"^(?:[1-9]\d{0,5}(?:\.\d{1,2})?)(?:B|KB|MB|GB|TB)$", re.IGNORECASE)
IDENTIFIER_LIST_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(?:,[a-zA-Z_][a-zA-Z0-9_]*)*$")

MAX_PLATFORM_OPTIONS = 16
MAX_PLATFORM_OPTION_VALUE_LENGTH = 256
MAX_MEMORY_LIMIT_BYTES = 1 << 40

# Scale factor limits
MIN_SCALE_FACTOR = 0.001
MAX_SCALE_FACTOR = 10000  # 10TB scale factor is extreme but possible


class MCPValidationError(ValueError):
    """Raised when MCP input validation fails.

    This is distinct from pydantic.ValidationError to avoid confusion
    and provide clearer error handling in MCP tool implementations.
    """


@dataclass(frozen=True, slots=True)
class MCPPlatformOptionSpec:
    """Bounded, non-secret option accepted by the MCP benchmark surface."""

    kind: Literal["bool", "int", "float", "string"]
    choices: tuple[str, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None

    def parse(self, name: str, value: object) -> bool | int | float | str:
        """Validate and normalize one JSON option value without echoing it."""
        if self.kind == "bool":
            if not isinstance(value, bool):
                raise MCPValidationError(f"Platform option '{name}' must be a boolean")
            return value
        if self.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise MCPValidationError(f"Platform option '{name}' must be an integer")
            normalized: int | float | str = value
        elif self.kind == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise MCPValidationError(f"Platform option '{name}' must be a number")
            normalized = float(value)
            if not math.isfinite(normalized):
                raise MCPValidationError(f"Platform option '{name}' must be finite")
        else:
            if not isinstance(value, str):
                raise MCPValidationError(f"Platform option '{name}' must be a string")
            normalized = value.strip()
            if not normalized or len(normalized) > MAX_PLATFORM_OPTION_VALUE_LENGTH:
                raise MCPValidationError(f"Platform option '{name}' has an invalid length")

        if self.choices and normalized not in self.choices:
            raise MCPValidationError(f"Platform option '{name}' has an unsupported value")
        if self.minimum is not None and normalized < self.minimum:
            raise MCPValidationError(f"Platform option '{name}' is below the permitted minimum")
        if self.maximum is not None and normalized > self.maximum:
            raise MCPValidationError(f"Platform option '{name}' exceeds the permitted maximum")
        return normalized


_MCP_OPTION = MCPPlatformOptionSpec


@dataclass(frozen=True, slots=True)
class MCPPlatformOptionContract:
    """Review metadata for one accepted MCP option.

    The contract is deliberately separate from the Pydantic-like value spec:
    bounds validate syntax, while this record documents the effective consumer,
    security class, compatibility aliases, and rejected alternatives.  The
    validator requires both records to agree so a new allow-listed option
    cannot bypass the review matrix accidentally.
    """

    consumer: str
    security_class: Literal["execution", "resource", "device", "layout", "connection"]
    aliases: tuple[str, ...] = ()
    rejected_alternatives: tuple[str, ...] = ()


# This is deliberately narrower than the CLI registry.  MCP callers cannot
# change credentials, destinations, filesystem locations, package installation,
# or other tenant-owned connection state through request arguments.
MCP_PLATFORM_OPTION_ALLOWLIST: dict[str, dict[str, MCPPlatformOptionSpec]] = {
    "clickhouse": {
        "deployment_mode": _MCP_OPTION("string", choices=("local", "server")),
        "port": _MCP_OPTION("int", minimum=1, maximum=65_535),
        "secure": _MCP_OPTION("bool"),
    },
    "clickhouse-server": {
        "port": _MCP_OPTION("int", minimum=1, maximum=65_535),
        "secure": _MCP_OPTION("bool"),
    },
    "cudf": {
        "device_id": _MCP_OPTION("int", minimum=0, maximum=255),
        "spill_to_host": _MCP_OPTION("bool"),
    },
    "dask": {
        "memory_limit": _MCP_OPTION("string"),
        "n_workers": _MCP_OPTION("int", minimum=1, maximum=256),
        "threads_per_worker": _MCP_OPTION("int", minimum=1, maximum=256),
        "use_distributed": _MCP_OPTION("bool"),
    },
    "datafusion": {
        "batch_size": _MCP_OPTION("int", minimum=1, maximum=1_000_000),
        "memory_limit": _MCP_OPTION("string"),
        "parquet_pushdown": _MCP_OPTION("bool"),
        "repartition_joins": _MCP_OPTION("bool"),
        "target_partitions": _MCP_OPTION("int", minimum=1, maximum=1_024),
    },
    "duckdb": {
        "memory_limit": _MCP_OPTION("string"),
        "threads": _MCP_OPTION("int", minimum=1, maximum=256),
    },
    "firebolt": {
        "disable_result_cache": _MCP_OPTION("bool"),
        "strict_validation": _MCP_OPTION("bool"),
    },
    "databricks": {
        "databricks_clustering_strategy": _MCP_OPTION(
            "string", choices=("z_order", "liquid_clustering", "liquid_clustering_auto", "none")
        ),
        "liquid_clustering_columns": _MCP_OPTION("string"),
    },
    "modin": {"engine": _MCP_OPTION("string", choices=("ray", "dask"))},
    "pandas": {"dtype_backend": _MCP_OPTION("string", choices=("numpy_nullable", "pyarrow"))},
    "polars": {
        "n_rows": _MCP_OPTION("int", minimum=1, maximum=10_000_000),
        "rechunk": _MCP_OPTION("bool"),
        "streaming": _MCP_OPTION("bool"),
    },
    "spark": {"adaptive_enabled": _MCP_OPTION("bool")},
    "sqlite": {
        "check_same_thread": _MCP_OPTION("bool"),
        "timeout": _MCP_OPTION("float", minimum=0, maximum=300),
    },
    "velox": {
        "adaptive_enabled": _MCP_OPTION("bool"),
        "deployment": _MCP_OPTION("string", choices=("local", "remote")),
        "driver_memory": _MCP_OPTION("string"),
        "offheap_size": _MCP_OPTION("string"),
        "shuffle_partitions": _MCP_OPTION("int", minimum=1, maximum=1_024),
    },
}


def _contract(
    consumer: str,
    security_class: Literal["execution", "resource", "device", "layout", "connection"],
    *,
    aliases: tuple[str, ...] = (),
    rejected_alternatives: tuple[str, ...] = (),
) -> MCPPlatformOptionContract:
    return MCPPlatformOptionContract(
        consumer=consumer,
        security_class=security_class,
        aliases=aliases,
        rejected_alternatives=rejected_alternatives,
    )


# Canonical option-to-consumer matrix.  Keep this map explicit instead of
# deriving it from the allow-list: an accepted option must have a reviewed
# consumer and security classification before it can cross the MCP boundary.
MCP_PLATFORM_OPTION_CONTRACT: dict[str, dict[str, MCPPlatformOptionContract]] = {
    "clickhouse": {
        "deployment_mode": _contract("ClickHouseAdapter.from_config(deployment_mode)", "execution"),
        "port": _contract(
            "ClickHouseAdapter.from_config(port)",
            "connection",
            rejected_alternatives=("server-owned port", "arbitrary destination selection"),
        ),
        "secure": _contract(
            "ClickHouseAdapter.from_config(secure)",
            "connection",
            rejected_alternatives=("server-owned TLS policy", "transport downgrade"),
        ),
    },
    "clickhouse-server": {
        "port": _contract(
            "ClickHouseAdapter.from_config(port)",
            "connection",
            rejected_alternatives=("server-owned port", "arbitrary destination selection"),
        ),
        "secure": _contract(
            "ClickHouseAdapter.from_config(secure)",
            "connection",
            rejected_alternatives=("server-owned TLS policy", "transport downgrade"),
        ),
    },
    "cudf": {
        "device_id": _contract("cuDF runtime device selection", "device"),
        "spill_to_host": _contract("cuDF memory policy", "resource"),
    },
    "dask": {
        "memory_limit": _contract("Dask worker resource envelope", "resource"),
        "n_workers": _contract("Dask LocalCluster worker count", "resource"),
        "threads_per_worker": _contract("Dask LocalCluster thread count", "resource"),
        "use_distributed": _contract("Dask execution-mode selector", "execution"),
    },
    "datafusion": {
        "batch_size": _contract("DataFusion execution configuration", "resource"),
        "memory_limit": _contract("DataFusion memory policy", "resource"),
        "parquet_pushdown": _contract("DataFusion parquet execution options", "execution"),
        "repartition_joins": _contract("DataFusion join execution options", "execution"),
        "target_partitions": _contract("DataFusion partition configuration", "resource"),
    },
    "duckdb": {
        "memory_limit": _contract("DuckDB thread/memory adapter settings", "resource"),
        "threads": _contract(
            "DuckDBAdapter.thread_limit",
            "resource",
            aliases=("thread_limit",),
        ),
    },
    "firebolt": {
        "disable_result_cache": _contract("Firebolt query execution options", "execution"),
        "strict_validation": _contract("Firebolt validation options", "execution"),
    },
    "databricks": {
        "databricks_clustering_strategy": _contract(
            "Databricks PlatformOptimizationConfiguration clustering strategy", "layout"
        ),
        "liquid_clustering_columns": _contract(
            "Databricks PlatformOptimizationConfiguration clustering columns", "layout"
        ),
    },
    "modin": {"engine": _contract("Modin dataframe backend selector", "execution")},
    "pandas": {"dtype_backend": _contract("pandas dataframe dtype backend", "execution")},
    "polars": {
        "n_rows": _contract("Polars input row limit", "resource"),
        "rechunk": _contract("Polars dataframe memory layout", "resource"),
        "streaming": _contract("Polars dataframe execution mode", "execution"),
    },
    "spark": {"adaptive_enabled": _contract("Spark adaptive execution setting", "execution")},
    "sqlite": {
        "check_same_thread": _contract("SQLite connection safety setting", "execution"),
        "timeout": _contract("SQLite connection timeout", "resource"),
    },
    "velox": {
        "adaptive_enabled": _contract("Velox execution options", "execution"),
        "deployment": _contract("Velox local/remote deployment selector", "connection"),
        "driver_memory": _contract("Velox driver resource envelope", "resource"),
        "offheap_size": _contract("Velox off-heap resource envelope", "resource"),
        "shuffle_partitions": _contract("Velox shuffle resource envelope", "resource"),
    },
}


def _validate_memory_limit(name: str, value: str) -> str:
    """Validate a bounded memory-size option without accepting paths or expressions."""
    if not MEMORY_LIMIT_PATTERN.fullmatch(value):
        raise MCPValidationError(f"Platform option '{name}' must use a bounded memory size")
    number, unit = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]+)", value).groups()  # type: ignore[union-attr]
    multipliers = {"B": 1, "KB": 1 << 10, "MB": 1 << 20, "GB": 1 << 30, "TB": 1 << 40}
    if float(number) * multipliers[unit.upper()] > MAX_MEMORY_LIMIT_BYTES:
        raise MCPValidationError(f"Platform option '{name}' exceeds the permitted memory limit")
    return value


def validate_platform_options(platform: str, options: Mapping[str, object] | None) -> dict[str, object]:
    """Return canonical, bounded MCP platform options or fail closed."""
    if options is None:
        return {}
    if not isinstance(options, Mapping):
        raise MCPValidationError("platform_options must be an object")
    if len(options) > MAX_PLATFORM_OPTIONS:
        raise MCPValidationError(f"Too many platform options (maximum {MAX_PLATFORM_OPTIONS})")

    platform_name = validate_platform_name(platform)
    specs = MCP_PLATFORM_OPTION_ALLOWLIST.get(platform_name)
    if specs is None and platform_name.endswith("-df"):
        specs = MCP_PLATFORM_OPTION_ALLOWLIST.get(platform_name[:-3])
    specs = specs or {}
    contracts = MCP_PLATFORM_OPTION_CONTRACT.get(platform_name)
    if contracts is None and platform_name.endswith("-df"):
        contracts = MCP_PLATFORM_OPTION_CONTRACT.get(platform_name[:-3])
    contracts = contracts or {}
    normalized: dict[str, object] = {}
    for raw_name, raw_value in options.items():
        if not isinstance(raw_name, str) or not PLATFORM_OPTION_NAME_PATTERN.fullmatch(raw_name):
            raise MCPValidationError("Platform option names must use lowercase snake_case")
        name = raw_name.lower()
        spec = specs.get(name)
        contract = contracts.get(name)
        if spec is None or contract is None:
            raise MCPValidationError(f"Platform option '{name}' is not authorized for MCP")
        parsed = spec.parse(name, raw_value)
        if spec.kind == "string" and name in {"memory_limit", "driver_memory", "offheap_size"}:
            parsed = _validate_memory_limit(name, parsed)  # type: ignore[arg-type]
        if name == "liquid_clustering_columns" and not IDENTIFIER_LIST_PATTERN.fullmatch(str(parsed)):
            raise MCPValidationError(f"Platform option '{name}' contains invalid identifiers")
        normalized[name] = parsed
    return normalized


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

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

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
    platform_options: Annotated[
        dict[str, object] | None,
        Field(
            default=None,
            description="Bounded, non-secret platform settings approved for this MCP platform.",
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

    @model_validator(mode="after")
    def validate_platform_options_field(self) -> RunBenchmarkInput:
        self.platform_options = validate_platform_options(self.platform, self.platform_options)
        return self


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
