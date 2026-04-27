"""Unified Pydantic schemas for BenchBox configuration and results.

This module provides validated configuration models using Pydantic for
runtime validation, better error messages, and automatic documentation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from datetime import datetime
from typing import Any, ClassVar, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from benchbox.core.constants import (
    GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS,
    GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS,
)
from benchbox.utils.verbosity import VerbositySettings


class QueryResult(BaseModel):
    """Individual query execution result."""

    query_id: str
    query_name: str
    sql_text: str
    execution_time_seconds: float | None = None
    execution_time_ms: float | None = None
    rows_returned: int
    status: str  # "SUCCESS", "ERROR", "TIMEOUT"
    error_message: Optional[str] = None
    resource_usage: Optional[dict[str, Any]] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status is one of the allowed values."""
        allowed = {"SUCCESS", "ERROR", "TIMEOUT"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}, got: {v}")
        return v

    @field_validator("execution_time_seconds", "execution_time_ms")
    @classmethod
    def validate_execution_time(cls, v: float | None) -> float | None:
        """Validate execution time is non-negative."""
        if v is None:
            return None
        if v < 0:
            raise ValueError(f"execution time must be non-negative, got: {v}")
        return float(v)

    @model_validator(mode="after")
    def normalize_execution_time_fields(self) -> "QueryResult":
        """Use execution_time_seconds as canonical, preserving ms compatibility."""
        if self.execution_time_seconds is None and self.execution_time_ms is None:
            raise ValueError("either execution_time_seconds or execution_time_ms must be provided")
        if self.execution_time_seconds is None and self.execution_time_ms is not None:
            self.execution_time_seconds = float(self.execution_time_ms) / 1000.0
        if self.execution_time_ms is None and self.execution_time_seconds is not None:
            self.execution_time_ms = float(self.execution_time_seconds) * 1000.0
        return self

    @field_validator("rows_returned")
    @classmethod
    def validate_rows_returned(cls, v: int) -> int:
        """Validate rows_returned is non-negative."""
        if v < 0:
            raise ValueError(f"rows_returned must be non-negative, got: {v}")
        return v


class RunConfig(BaseModel):
    """Configuration for benchmark run execution.

    Benchmark identity contract
    ---------------------------
    ``benchmark`` carries the canonical benchmark slug (e.g. "tpch", "tpcds")
    sourced directly from ``BenchmarkConfig.name``.  It must be populated by the
    runner before ``RunConfig`` is handed to the platform adapter so that the
    adapter never has to infer benchmark identity from object internals.

    Ownership hierarchy (CLI → persistence):
    * ``BenchmarkConfig.name``  - authoritative slug supplied by the CLI/orchestrator
    * ``RunConfig.benchmark``   - propagated copy, carried through SQL execution
    * ``execution_metadata["benchmark_id"]`` - normalised form written to results
    * ``display_name`` / wrapper class names - presentation only, never routing inputs
    """

    # Canonical benchmark slug (e.g. "tpch"). Populated by the runner from
    # BenchmarkConfig.name so adapters can use it for routing and result
    # creation without sniffing benchmark object internals.
    benchmark: Optional[str] = None
    database_type: Optional[str] = None
    query_subset: Optional[list[str]] = None
    concurrent_streams: int = 1
    test_execution_type: str = "standard"
    scale_factor: float = 0.01
    seed: Optional[int] = None
    tuning_config: Optional[dict[str, Any]] = None
    connection: Optional[dict[str, Any]] = None
    options: dict[str, Any] = Field(default_factory=dict)
    enable_postload_validation: bool = False
    capture_plans: bool = False
    strict_plan_capture: bool = False
    # PyPI distribution name (e.g. "psycopg", "duckdb") - no extras markers or version specifiers
    driver_package: Optional[str] = None
    driver_version: Optional[str] = None
    driver_version_resolved: Optional[str] = None
    driver_version_actual: Optional[str] = None
    driver_runtime_strategy: Optional[str] = None
    driver_runtime_path: Optional[str] = None
    driver_runtime_python_executable: Optional[str] = None
    driver_auto_install: bool = False
    driver_auto_install_used: bool = False
    verbose: bool = False
    verbose_level: int = 0
    verbose_enabled: bool = False
    very_verbose: bool = False
    quiet: bool = False
    iterations: int = GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS  # Default: 3 measurement iterations
    warm_up_iterations: int = GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS  # Default: 1 warmup iteration
    power_fail_fast: bool = False

    # Table format fields
    table_format: Optional[str] = None
    table_format_compression: str = "snappy"
    table_format_partition_cols: list[str] = Field(default_factory=list)

    @field_validator("scale_factor")
    @classmethod
    def validate_scale_factor(cls, v: float) -> float:
        """Validate scale factor is positive."""
        if v <= 0:
            raise ValueError(f"scale_factor must be positive, got: {v}")
        if v > 100000:
            raise ValueError(f"scale_factor must be ≤ 100000, got: {v}")
        return v

    @field_validator("iterations")
    @classmethod
    def validate_iterations(cls, v: int) -> int:
        """Validate iterations is at least 1."""
        if v < 1:
            return 1
        return v

    @field_validator("warm_up_iterations")
    @classmethod
    def validate_warm_up_iterations(cls, v: int) -> int:
        """Validate warm_up_iterations is non-negative."""
        if v < 0:
            return 0
        return v

    @field_validator("concurrent_streams")
    @classmethod
    def validate_concurrent_streams(cls, v: int) -> int:
        """Validate concurrent_streams is positive."""
        if v < 1:
            raise ValueError(f"concurrent_streams must be at least 1, got: {v}")
        return v

    @field_validator("test_execution_type")
    @classmethod
    def validate_test_execution_type(cls, v: str) -> str:
        """Validate test_execution_type is one of the allowed values."""
        allowed = {"standard", "power", "throughput", "maintenance", "combined", "data_only", "load_only"}
        if v not in allowed:
            raise ValueError(f"test_execution_type must be one of {allowed}, got: {v}")
        return v

    @field_validator("table_format")
    @classmethod
    def validate_table_format(cls, v: Optional[str]) -> Optional[str]:
        """Validate table_format is supported."""
        if v is not None:
            allowed = {"parquet", "vortex", "delta", "iceberg"}
            v_lower = v.lower()
            if v_lower not in allowed:
                raise ValueError(f"table_format must be one of {allowed}, got: {v}")
            return v_lower
        return v

    # (attr_name, options_key, expected_type) - populated by populate_driver_metadata.
    _DRIVER_OPTION_FIELDS: ClassVar[list[tuple[str, str, type]]] = [
        ("driver_version", "driver_version", str),
        ("driver_package", "driver_package", str),
        ("driver_version_resolved", "driver_version_resolved", str),
        ("driver_version_actual", "driver_version_actual", str),
        ("driver_runtime_strategy", "driver_runtime_strategy", str),
        ("driver_runtime_path", "driver_runtime_path", str),
        ("driver_runtime_python_executable", "driver_runtime_python_executable", str),
    ]

    @model_validator(mode="after")
    def populate_driver_metadata(self) -> "RunConfig":
        """Populate driver metadata from options if not explicitly provided."""
        for attr, option_key, expected_type in self._DRIVER_OPTION_FIELDS:
            if getattr(self, attr) is None:
                value = self.options.get(option_key)
                if isinstance(value, expected_type):
                    setattr(self, attr, value)

        if not self.driver_auto_install:
            auto_install_option = self.options.get("driver_auto_install")
            if isinstance(auto_install_option, bool):
                self.driver_auto_install = auto_install_option

        # Apply verbosity settings normalization
        verbosity_source: dict[str, Any] = {
            "verbose": self.verbose,
            "verbose_level": self.verbose_level,
            "verbose_enabled": self.verbose_enabled,
            "very_verbose": self.very_verbose,
            "quiet": self.quiet,
        }
        verbosity = VerbositySettings.from_mapping(verbosity_source)
        self.verbose = verbosity.verbose
        self.verbose_level = verbosity.level
        self.verbose_enabled = verbosity.verbose_enabled
        self.very_verbose = verbosity.very_verbose
        self.quiet = verbosity.quiet

        return self


class BenchmarkConfig(BaseModel):
    """Benchmark configuration.

    ``name`` is the authoritative benchmark slug (e.g. "tpch", "tpcds").  It is
    the single source of truth for benchmark identity and must be propagated
    explicitly to ``RunConfig.benchmark``, ``execution_metadata["benchmark_id"]``,
    and dry-run extraction paths.  Downstream code must NOT re-derive identity
    from display names, wrapper class names, or benchmark object internals.
    """

    # Authoritative benchmark slug supplied by the CLI / orchestrator.
    # This value flows into RunConfig.benchmark and execution_metadata["benchmark_id"].
    name: str
    display_name: str
    scale_factor: float = 0.01
    queries: Optional[list[str]] = None
    concurrency: int = 1
    capture_plans: bool = False
    strict_plan_capture: bool = False
    options: dict[str, Any] = Field(default_factory=dict)
    compress_data: bool = False
    compression_type: str = "zstd"
    compression_level: Optional[int] = None
    test_execution_type: str = "standard"  # standard, power, throughput, maintenance, combined

    @field_validator("scale_factor")
    @classmethod
    def validate_scale_factor(cls, v: float) -> float:
        """Validate scale factor is positive and within reasonable range."""
        if v <= 0:
            raise ValueError(f"scale_factor must be positive, got: {v}")
        if v > 100000:
            raise ValueError(f"scale_factor must be ≤ 100000, got: {v}")
        return v

    @field_validator("concurrency")
    @classmethod
    def validate_concurrency(cls, v: int) -> int:
        """Validate concurrency is positive."""
        if v < 1:
            raise ValueError(f"concurrency must be at least 1, got: {v}")
        return v

    @field_validator("compression_type")
    @classmethod
    def validate_compression_type(cls, v: str) -> str:
        """Validate compression type is supported."""
        allowed = {"zstd", "gzip", "lz4", "snappy", "none"}
        if v not in allowed:
            raise ValueError(f"compression_type must be one of {allowed}, got: {v}")
        return v

    @field_validator("compression_level")
    @classmethod
    def validate_compression_level(cls, v: Optional[int]) -> Optional[int]:
        """Validate compression level is within range if specified."""
        if v is not None and (v < 1 or v > 22):
            raise ValueError(f"compression_level must be between 1 and 22, got: {v}")
        return v

    @field_validator("test_execution_type")
    @classmethod
    def validate_test_execution_type(cls, v: str) -> str:
        """Validate test_execution_type is one of the allowed values."""
        allowed = {"standard", "power", "throughput", "maintenance", "combined", "data_only", "load_only"}
        if v not in allowed:
            raise ValueError(f"test_execution_type must be one of {allowed}, got: {v}")
        return v


class DatabaseConfig(BaseModel):
    """Database connection configuration.

    This model allows extra fields to support platform-specific configuration
    parameters (e.g., server_hostname for Databricks, account for Snowflake).
    """

    model_config = ConfigDict(extra="allow")

    type: str
    name: str
    connection_string: Optional[str] = None
    options: dict[str, Any] = Field(default_factory=dict)
    # PyPI distribution name (e.g. "psycopg", "duckdb") - no extras markers or version specifiers
    driver_package: Optional[str] = None
    driver_version: Optional[str] = None
    driver_version_resolved: Optional[str] = None
    driver_version_actual: Optional[str] = None
    driver_runtime_strategy: Optional[str] = None
    driver_runtime_path: Optional[str] = None
    driver_runtime_python_executable: Optional[str] = None
    driver_auto_install: bool = False
    driver_auto_install_used: bool = False
    execution_mode: Optional[Literal["sql", "dataframe", "data_only"]] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate database type is not empty."""
        if not v or not v.strip():
            raise ValueError("database type cannot be empty")
        return v.strip()

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate database name is not empty."""
        if not v or not v.strip():
            raise ValueError("database name cannot be empty")
        return v.strip()


class SystemProfile(BaseModel):
    """System profile information for benchmarking."""

    os_name: str
    os_version: str
    architecture: str
    cpu_model: str
    cpu_cores_physical: int
    cpu_cores_logical: int
    memory_total_gb: float
    memory_available_gb: float
    python_version: str
    disk_space_gb: float
    timestamp: datetime
    hostname: Optional[str] = None

    @field_validator("cpu_cores_physical", "cpu_cores_logical")
    @classmethod
    def validate_cpu_cores(cls, v: int) -> int:
        """Validate CPU core count is positive."""
        if v < 1:
            raise ValueError(f"CPU cores must be at least 1, got: {v}")
        return v

    @field_validator("memory_total_gb", "memory_available_gb", "disk_space_gb")
    @classmethod
    def validate_sizes(cls, v: float) -> float:
        """Validate size values are non-negative."""
        if v < 0:
            raise ValueError(f"Size values must be non-negative, got: {v}")
        return v


class LibraryInfo(BaseModel):
    """Information about a detected library."""

    name: str
    version: Optional[str]
    installed: bool
    import_error: Optional[str] = None


class PlatformInfo(BaseModel):
    """Comprehensive information about a platform."""

    name: str
    display_name: str
    description: str
    libraries: list[LibraryInfo]
    available: bool
    enabled: bool
    requirements: list[str]
    installation_command: str
    adoption: str = "niche"  # One of: mainstream, established, emerging, niche
    category: str = "database"
    supports: list[str] = Field(default_factory=list)
    driver_package: Optional[str] = None
    driver_version_requested: Optional[str] = None
    driver_version_resolved: Optional[str] = None
    driver_version_actual: Optional[str] = None
    driver_runtime_strategy: Optional[str] = None


class ExecutionContext(BaseModel):
    """Execution context for reproducibility - constructed by all entry points.

    This model captures all execution parameters needed to reproduce a benchmark run.
    It is constructed at each entry point (CLI, MCP, Python API) and flows through
    core execution to be embedded in results.

    Example:
        >>> ctx = ExecutionContext(
        ...     entry_point="cli",
        ...     phases=["load", "power"],
        ...     seed=42,
        ...     compression_type="zstd",
        ... )
        >>> ctx.to_cli_string("duckdb", "tpch", 1.0)
        'benchbox run --platform duckdb --benchmark tpch --scale 1.0 --phases load,power --seed 42 --compression zstd'
    """

    model_config = ConfigDict(extra="forbid")

    # Identity & provenance
    entry_point: Literal["cli", "mcp", "python_api"] = "python_api"
    invocation_timestamp: datetime = Field(default_factory=datetime.now)

    # Phases
    phases: list[str] = Field(default_factory=lambda: ["power"])

    # Determinism
    seed: Optional[int] = None

    # Compression
    compression_enabled: bool = False
    compression_type: str = "none"
    compression_level: Optional[int] = None

    # Execution mode
    mode: Literal["sql", "dataframe"] = "sql"

    # TPC compliance
    official: bool = False

    # Validation
    validation_mode: Optional[str] = None

    # Force flags
    force_datagen: bool = False
    force_upload: bool = False

    # Query subset (also in RunConfig, but included for complete CLI reconstruction)
    query_subset: Optional[list[str]] = None

    # Plan capture
    capture_plans: bool = False
    strict_plan_capture: bool = False

    # Non-interactive
    non_interactive: bool = False

    # Tuning
    tuning_mode: Optional[str] = None  # "tuned", "notuning", "auto", or path

    def to_cli_args(self) -> list[str]:
        """Reconstruct CLI arguments from non-default values.

        Returns:
            List of CLI arguments like ["--phases", "load,power", "--seed", "42"]
        """
        args: list[str] = []

        if self.phases != ["power"]:
            args.extend(["--phases", ",".join(self.phases)])
        if self.seed is not None:
            args.extend(["--seed", str(self.seed)])

        # Compression (nested logic)
        if self.compression_enabled and self.compression_type != "none":
            comp = self.compression_type
            if self.compression_level is not None:
                comp = f"{comp}:{self.compression_level}"
            args.extend(["--compression", comp])

        # Simple value flags
        _VALUE_FLAGS: list[tuple[str, str, Any]] = [
            ("mode", "--mode", "sql"),
            ("validation_mode", "--validation", None),
        ]
        for attr, flag, default in _VALUE_FLAGS:
            value = getattr(self, attr)
            if value and value != default:
                args.extend([flag, value])

        # Boolean flags
        _BOOL_FLAGS = [
            ("official", "--official"),
            ("capture_plans", "--capture-plans"),
            ("non_interactive", "--non-interactive"),
        ]
        for attr, flag in _BOOL_FLAGS:
            if getattr(self, attr):
                args.append(flag)

        # Force flags
        force_parts = [
            f for f, attr in [("datagen", "force_datagen"), ("upload", "force_upload")] if getattr(self, attr)
        ]
        if force_parts:
            args.extend(["--force", ",".join(force_parts)])

        if self.query_subset:
            args.extend(["--queries", ",".join(self.query_subset)])
        if self.strict_plan_capture:
            args.extend(["--plan-config", "strict:true"])
        if self.tuning_mode and self.tuning_mode != "notuning":
            args.extend(["--tuning", self.tuning_mode])

        return args

    def to_cli_string(self, platform: str, benchmark: str, scale: float) -> str:
        """Generate complete CLI command string.

        Args:
            platform: Target platform name
            benchmark: Benchmark name
            scale: Scale factor

        Returns:
            Complete CLI command like "benchbox run --platform duckdb --benchmark tpch --scale 1.0"
        """
        base = f"benchbox run --platform {platform} --benchmark {benchmark} --scale {scale}"
        args = self.to_cli_args()
        return f"{base} {' '.join(args)}" if args else base


class DryRunResult(BaseModel):
    """Contains all information gathered during a dry run."""

    benchmark_config: dict[str, Any]
    database_config: dict[str, Any]
    system_profile: dict[str, Any]
    platform_config: dict[str, Any]
    queries: dict[str, str]
    execution_mode: str = "sql"  # "sql" or "dataframe"
    schema_sql: Optional[str] = None  # SQL CREATE TABLE statements (sql mode)
    dataframe_schema: Optional[str] = None  # Python Polars schema code (dataframe mode)
    ddl_preview: Optional[dict[str, dict[str, Any]]] = None  # Per-table DDL with tuning clauses
    post_load_statements: Optional[dict[str, list[str]]] = None  # Per-table post-load operations
    tuning_config: Optional[dict[str, Any]] = None
    constraint_config: Optional[dict[str, Any]] = None
    estimated_resources: Optional[dict[str, Any]] = None
    query_preview: Optional[dict[str, Any]] = None
    warnings: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)


__all__ = [
    "QueryResult",
    "RunConfig",
    "BenchmarkConfig",
    "DatabaseConfig",
    "SystemProfile",
    "LibraryInfo",
    "PlatformInfo",
    "ExecutionContext",
    "DryRunResult",
]
