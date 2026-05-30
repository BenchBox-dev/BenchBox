"""Configuration management for BenchBox CLI.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field

from benchbox.core.config_utils import (
    deep_merge_dicts,
    load_config_file,
    save_config_file,
)
from benchbox.core.tuning.interface import (
    BenchmarkTunings,
    TableTuning,
    TuningColumn,
    TuningType,
    UnifiedTuningConfiguration,
)
from benchbox.utils.database_naming import generate_database_filename
from benchbox.utils.printing import quiet_console
from benchbox.utils.scale_factor import format_scale_factor

console = quiet_console

# (key_path, default, check_fn, error_msg) - used by validate_config to loop
# over numeric threshold guards. Most require > 0; warm_up_iterations and
# max_retries allow 0 (>= 0).
_CONFIG_VALIDATION_RULES: list[tuple[str, int, Any, str]] = [
    ("benchmarks.default_scale", 0, lambda v: v > 0, "Invalid default scale factor"),
    ("benchmarks.timeout_minutes", 0, lambda v: v > 0, "Invalid timeout value"),
    ("execution.max_workers", 0, lambda v: v > 0, "Invalid max workers value"),
    ("execution.power_run.iterations", 4, lambda v: v > 0, "Invalid power run iterations value"),
    ("execution.power_run.warm_up_iterations", 0, lambda v: v >= 0, "Invalid power run warm-up iterations value"),
    (
        "execution.power_run.timeout_per_iteration_minutes",
        60,
        lambda v: v > 0,
        "Invalid power run timeout value",
    ),
    ("execution.concurrent_queries.max_concurrent", 2, lambda v: v > 0, "Invalid max concurrent queries value"),
    (
        "execution.concurrent_queries.query_timeout_seconds",
        300,
        lambda v: v > 0,
        "Invalid concurrent query timeout value",
    ),
    (
        "execution.concurrent_queries.stream_timeout_seconds",
        3600,
        lambda v: v > 0,
        "Invalid concurrent stream timeout value",
    ),
    ("execution.concurrent_queries.max_retries", 3, lambda v: v >= 0, "Invalid max retries value"),
]


def load_config(
    cli_args: Optional[dict[str, Any]] = None,
    config_file: Optional[Path] = None,
    validate: bool = True,
) -> "BenchBoxConfig":
    """Unified configuration loader with explicit precedence.

    Loads configuration with the following precedence (highest to lowest):
    1. CLI arguments (cli_args parameter)
    2. Environment variables (BENCHBOX_* prefixed)
    3. Configuration file (YAML/JSON)
    4. Default values

    Args:
        cli_args: Dictionary of CLI argument overrides
        config_file: Path to configuration file (optional, will search default locations)
        validate: Whether to validate the configuration after loading

    Returns:
        Loaded and validated BenchBoxConfig instance

    Example:
        >>> # Load with defaults
        >>> config = load_config()
        >>>
        >>> # Load with CLI overrides
        >>> config = load_config(cli_args={'database': {'preferred': 'clickhouse'}})
        >>>
        >>> # Load from specific file
        >>> config = load_config(config_file=Path('my_config.yaml'))
    """
    # Create ConfigManager to handle file loading
    manager = ConfigManager(config_path=config_file)

    # Start with file-based config (already has defaults merged)
    config_dict = manager.config.model_dump()

    # Apply environment variable overrides
    config_dict = _apply_environment_overrides(config_dict)

    # Apply CLI argument overrides (highest priority)
    if cli_args:
        config_dict = deep_merge_dicts(config_dict, cli_args)

    # Create validated config
    config = BenchBoxConfig(**config_dict)

    # Validate if requested
    if validate:
        manager.config = config
        if not manager.validate_config():
            raise ValueError("Configuration validation failed")

    return config


def _apply_environment_overrides(config_dict: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides to configuration.

    Supports the following environment variables:
    - BENCHBOX_DATABASE_PREFERRED: Override database.preferred
    - BENCHBOX_SCALE_FACTOR: Override benchmarks.default_scale
    - BENCHBOX_VERBOSE: Override execution.verbose
    - BENCHBOX_MAX_WORKERS: Override execution.max_workers
    - BENCHBOX_TUNING_ENABLED: Override tuning.enabled
    - BENCHBOX_TUNING_CONFIG: Override tuning.default_config_file

    Args:
        config_dict: Configuration dictionary

    Returns:
        Configuration dictionary with environment overrides applied
    """
    # Define environment variable mappings
    env_mappings = {
        "BENCHBOX_DATABASE_PREFERRED": ("database", "preferred", str),
        "BENCHBOX_SCALE_FACTOR": ("benchmarks", "default_scale", float),
        "BENCHBOX_VERBOSE": ("execution", "verbose", lambda v: v.lower() in ["true", "1", "yes", "on"]),
        "BENCHBOX_MAX_WORKERS": ("execution", "max_workers", int),
        "BENCHBOX_TUNING_ENABLED": ("tuning", "enabled", lambda v: v.lower() in ["true", "1", "yes", "on"]),
        "BENCHBOX_TUNING_CONFIG": ("tuning", "default_config_file", str),
        "BENCHBOX_OUTPUT_DIR": ("output", "directory", str),
        "BENCHBOX_MEMORY_LIMIT_GB": ("execution", "memory_limit_gb", int),
    }

    for env_var, (section, key, converter) in env_mappings.items():
        env_value = os.getenv(env_var)
        if env_value is not None:
            try:
                converted_value = converter(env_value)
                if section not in config_dict:
                    config_dict[section] = {}
                config_dict[section][key] = converted_value
            except (ValueError, TypeError) as e:
                console.print(f"[yellow]Warning: Invalid environment variable {env_var}={env_value}: {e}[/yellow]")

    return config_dict


class BenchBoxConfig(BaseModel):
    """Main configuration model."""

    model_config = ConfigDict(extra="allow")

    system: dict[str, Any] = Field(default_factory=dict)
    database: dict[str, Any] = Field(default_factory=dict)
    benchmarks: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    tuning: dict[str, Any] = Field(default_factory=dict)


class ConfigManager:
    """Configuration file and settings management."""

    def __init__(self, config_path: Optional[Path] = None):
        self.console = quiet_console
        self.config_path = config_path or self._get_default_config_path()
        self.config = self._load_config()
        # Apply environment variable overrides for tuning settings
        self.apply_environment_overrides()

    def _get_default_config_path(self) -> Path:
        """Get default configuration file path."""
        # Check for config in current directory first
        current_config = Path("benchbox.yaml")
        if current_config.exists():
            return current_config

        # Check user home directory
        home_config = Path.home() / ".benchbox" / "config.yaml"
        return home_config

    def _load_config(self) -> BenchBoxConfig:
        """Load configuration from file or create default."""
        try:
            if self.config_path.exists():
                try:
                    with open(self.config_path, encoding="utf-8") as f:
                        config_data = yaml.safe_load(f) or {}

                    # If config file is empty or doesn't have any of our main sections,
                    # return default config
                    if not config_data or not any(
                        key in config_data
                        for key in [
                            "system",
                            "database",
                            "benchmarks",
                            "output",
                            "execution",
                        ]
                    ):
                        return self._get_default_config()

                    # Merge with defaults to ensure all required fields exist
                    default_config = self._get_default_config()
                    merged_config = deep_merge_dicts(default_config.model_dump(), config_data)
                    return BenchBoxConfig(**merged_config)
                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to load config from {self.config_path}: {e}[/yellow]")
                    return self._get_default_config()
            else:
                return self._get_default_config()
        except (PermissionError, OSError) as e:
            console.print(f"[yellow]Warning: Permission denied accessing {self.config_path}: {e}[/yellow]")
            return self._get_default_config()

    def _get_default_config(self) -> BenchBoxConfig:
        """Get default configuration."""
        return BenchBoxConfig(
            system={
                "auto_profile": True,
                "save_profile": True,
                "profile_cache_hours": 24,
            },
            database={
                "preferred": "duckdb",
                "connection_timeout": 30,
                "auto_detect": True,
            },
            benchmarks={
                "default_scale": 0.01,
                "timeout_minutes": 60,
                "max_memory_gb": 8,
                "continue_on_error": False,
            },
            output={
                "formats": ["json", "console"],
                "directory": "./benchmark_runs/results",
                "timestamp_format": "%Y%m%d_%H%M%S",
                "submit_to_service": False,
                "service_url": "https://api.benchbox.dev/v1",
                "compression": {
                    "enabled": True,
                    "type": "zstd",
                    "level": None,  # Use algorithm defaults
                },
            },
            execution={
                "parallel_queries": False,
                "max_workers": 4,
                "memory_limit_gb": 0,  # 0 = auto
                "verbose": True,
                "power_run": {
                    "iterations": 3,  # Changed from 1 to 3: run 3 measurement iterations
                    "warm_up_iterations": 1,
                    "timeout_per_iteration_minutes": 60,
                    "fail_fast": False,
                    "collect_metrics": True,
                },
                "concurrent_queries": {
                    "enabled": False,
                    "max_concurrent": 2,
                    "query_timeout_seconds": 300,
                    "stream_timeout_seconds": 3600,
                    "retry_failed_queries": True,
                    "max_retries": 3,
                },
            },
            tuning={
                "enabled": False,
                "default_config_file": None,
                "validate_on_load": True,
                "allow_platform_incompatible": False,
                "environment_overrides": {
                    "BENCHBOX_TUNING_ENABLED": "enabled",
                    "BENCHBOX_TUNING_CONFIG": "default_config_file",
                },
            },
        )

    def save_config(self):
        """Save current configuration to file."""
        try:
            # Create directory if it doesn't exist
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Convert to dict and save
            config_dict = self.config.model_dump()

            # Add metadata
            config_dict["_metadata"] = {
                "version": "1.0",
                "created": datetime.now().isoformat(),
                "generated_by": "benchbox-cli",
            }

            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)

            console.print(f"[green]✅ Configuration saved to {self.config_path}[/green]")
        except Exception as e:
            console.print(f"[red]❌ Failed to save configuration: {e}[/red]")

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation."""
        keys = key.split(".")
        value = self.config.model_dump()

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any):
        """Set configuration value using dot notation."""
        keys = key.split(".")
        config_dict = self.config.model_dump()
        current = config_dict

        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        current[keys[-1]] = value
        self.config = BenchBoxConfig(**config_dict)

    def update_from_system_profile(self, profile):
        """Update configuration based on system profile."""
        self.set("system.detected_os", profile.os_name)
        self.set("system.detected_arch", profile.architecture)
        self.set("system.detected_memory_gb", profile.memory_total_gb)
        self.set("system.detected_cpu_cores", profile.cpu_cores_logical)
        self.set("system.available_databases", profile.available_databases)
        self.set("system.last_profile_time", profile.timestamp.isoformat())

        # Auto-configure based on system
        if profile.memory_total_gb > 0:
            # Set memory limit to 75% of available memory
            memory_limit = max(1, int(profile.memory_total_gb * 0.75))
            self.set("benchmarks.max_memory_gb", memory_limit)
            self.set("execution.memory_limit_gb", memory_limit)

        # Set max workers based on CPU cores
        max_workers = min(8, max(2, profile.cpu_cores_logical // 2))
        self.set("execution.max_workers", max_workers)

        # Auto-configure concurrent queries based on system resources
        concurrent_max = min(max_workers, max(2, profile.cpu_cores_logical // 4))
        self.set("execution.concurrent_queries.max_concurrent", concurrent_max)

        # Scale timeouts based on available memory (lower memory = longer timeouts)
        if profile.memory_total_gb < 8:
            # Low memory systems need longer timeouts
            self.set("execution.power_run.timeout_per_iteration_minutes", 120)
            self.set("execution.concurrent_queries.query_timeout_seconds", 600)
        elif profile.memory_total_gb > 16:
            # High memory systems can use shorter timeouts
            self.set("execution.power_run.timeout_per_iteration_minutes", 45)
            self.set("execution.concurrent_queries.query_timeout_seconds", 180)

        # Prefer DuckDB if available
        if "duckdb" in profile.available_databases:
            self.set("database.preferred", "duckdb")
        elif profile.available_databases:
            self.set("database.preferred", profile.available_databases[0])

    def validate_config(self) -> bool:
        """Validate current configuration."""
        try:
            for key_path, default, check_fn, error_msg in _CONFIG_VALIDATION_RULES:
                if not check_fn(self.get(key_path, default)):
                    console.print(f"[red]❌ {error_msg}[/red]")
                    return False

            console.print("[green]✅ Configuration validation passed[/green]")
            return True
        except Exception as e:
            console.print(f"[red]❌ Configuration validation failed: {e}[/red]")
            return False

    def show_config(self):
        """Display current configuration."""
        from rich.syntax import Syntax

        config_yaml = yaml.dump(self.config.model_dump(), default_flow_style=False, sort_keys=False)
        syntax = Syntax(config_yaml, "yaml", theme="monokai", line_numbers=True)

        console.print("\n[bold]Current Configuration:[/bold]")
        console.print(f"Config file: [cyan]{self.config_path}[/cyan]")
        console.print(syntax)

    def create_sample_config(self, path: Optional[Path] = None):
        """Create a sample configuration file."""
        if path is None:
            path = Path("benchbox.yaml")

        sample_config = self._get_default_config()

        # Add comments for better understanding
        config_dict = sample_config.model_dump()
        config_dict["_comments"] = {
            "system": "System profiling and detection settings",
            "database": "Database connection and preference settings",
            "benchmarks": "Default benchmark execution parameters",
            "output": "Result formatting and export settings",
            "execution": "Performance and execution control settings",
            "execution.power_run": "Configuration for power run test iterations and metrics collection",
            "execution.concurrent_queries": "Configuration for concurrent query execution and throughput testing",
            "tuning": "Table tuning and optimization settings",
        }

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)

        console.print(f"[green]✅ Sample configuration created at {path}[/green]")
        console.print("Edit this file to customize BenchBox behavior.")

    def load_tuning_config(self, config_path: Union[str, Path]) -> dict[str, BenchmarkTunings]:
        """Load tuning configuration from YAML or JSON file.

        Args:
            config_path: Path to the tuning configuration file

        Returns:
            Dictionary mapping benchmark names to their tuning configurations

        Raises:
            ValueError: If the configuration file is invalid or cannot be loaded
        """
        config_path = Path(config_path)

        try:
            config_data = load_config_file(config_path)
            if not config_data:
                raise ValueError("Configuration file is empty")

            # Parse tuning configurations
            benchmark_tunings = {}

            for benchmark_name, benchmark_data in config_data.items():
                # Skip metadata sections
                if benchmark_name.startswith("_"):
                    continue

                if not isinstance(benchmark_data, dict):
                    raise ValueError(f"Invalid benchmark configuration for '{benchmark_name}': must be a dictionary")

                # Create BenchmarkTunings object
                tunings = BenchmarkTunings(benchmark_name=benchmark_name)

                # Parse table tunings
                for table_name, table_data in benchmark_data.items():
                    if table_name.startswith("_"):  # Skip metadata fields
                        continue

                    table_tuning = self._parse_table_tuning(table_name, table_data)
                    tunings.add_table_tuning(table_tuning)

                benchmark_tunings[benchmark_name] = tunings

            # Validate configurations if enabled
            if self.get("tuning.validate_on_load", True):
                self._validate_tuning_configs(benchmark_tunings)

            return benchmark_tunings

        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to parse tuning configuration file: {e}") from e
        except Exception as e:
            raise ValueError(f"Error loading tuning configuration: {e}") from e

    def _parse_table_tuning(self, table_name: str, table_data: dict[str, Any]) -> TableTuning:
        """Parse table tuning configuration from dictionary data.

        Args:
            table_name: Name of the table
            table_data: Dictionary containing tuning configuration

        Returns:
            TableTuning object
        """
        # Parse optional tuning type columns
        partitioning: Optional[list[TuningColumn]] = None
        clustering: Optional[list[TuningColumn]] = None
        distribution: Optional[list[TuningColumn]] = None
        sorting: Optional[list[TuningColumn]] = None

        for tuning_type_str in [
            "partitioning",
            "clustering",
            "distribution",
            "sorting",
        ]:
            if tuning_type_str in table_data:
                columns_data = table_data[tuning_type_str]
                if not isinstance(columns_data, list):
                    raise ValueError(f"'{tuning_type_str}' must be a list of column configurations")

                columns = []
                for i, col_data in enumerate(columns_data):
                    if isinstance(col_data, str):
                        # Simple format: just column name, infer order
                        columns.append(TuningColumn(name=col_data, type="UNKNOWN", order=i + 1))
                    elif isinstance(col_data, dict):
                        # Full format with name, type, and order
                        columns.append(TuningColumn.from_dict(col_data))
                    else:
                        raise ValueError(f"Invalid column configuration at index {i} in {tuning_type_str}")

                # Assign to the appropriate variable
                if tuning_type_str == "partitioning":
                    partitioning = columns
                elif tuning_type_str == "clustering":
                    clustering = columns
                elif tuning_type_str == "distribution":
                    distribution = columns
                elif tuning_type_str == "sorting":
                    sorting = columns

        # Create TableTuning with explicit parameters (helps type checker)
        return TableTuning(
            table_name=table_name,
            partitioning=partitioning,
            clustering=clustering,
            distribution=distribution,
            sorting=sorting,
        )

    def _validate_tuning_configs(self, benchmark_tunings: dict[str, BenchmarkTunings]) -> None:
        """Validate loaded tuning configurations.

        Args:
            benchmark_tunings: Dictionary of benchmark tuning configurations
        """
        for benchmark_name, tunings in benchmark_tunings.items():
            if not tunings.has_valid_tunings():
                validation_results = tunings.validate_all()

                error_messages = []
                for table_name, errors in validation_results.items():
                    if errors:
                        error_messages.extend([f"{table_name}: {error}" for error in errors])

                if error_messages:
                    console.print(f"[red]⚠️ Tuning validation errors in '{benchmark_name}':[/red]")
                    for msg in error_messages:
                        console.print(f"  - {msg}")

                    if not self.get("tuning.allow_platform_incompatible", False):
                        raise ValueError(f"Invalid tuning configuration for benchmark '{benchmark_name}'")

    def save_tuning_config(
        self,
        benchmark_tunings: dict[str, BenchmarkTunings],
        config_path: Union[str, Path],
        format: str = "yaml",
    ) -> None:
        """Save tuning configurations to file.

        Args:
            benchmark_tunings: Dictionary of benchmark tuning configurations
            config_path: Path where to save the configuration
            format: File format ('yaml' or 'json')
        """
        config_path = Path(config_path)

        # Convert to serializable format
        config_data = {}
        for benchmark_name, tunings in benchmark_tunings.items():
            config_data[benchmark_name] = tunings.to_dict()["table_tunings"]

        # Add metadata
        config_data["_metadata"] = {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "generated_by": "benchbox-cli",
        }

        # Save to file
        try:
            save_config_file(config_data, config_path, format)
            console.print(f"[green]✅ Tuning configuration saved to {config_path}[/green]")

        except Exception as e:
            console.print(f"[red]❌ Failed to save tuning configuration: {e}[/red]")
            raise

    def apply_environment_overrides(self) -> None:
        """Apply environment variable overrides for tuning settings."""
        env_overrides = self.get("tuning.environment_overrides", {})

        for env_var, config_key in env_overrides.items():
            env_value = os.getenv(env_var)
            if env_value is not None:
                # Convert environment variable values to appropriate types
                if config_key == "enabled":
                    value = env_value.lower() in ["true", "1", "yes", "on", "enabled"]
                    self.set(f"tuning.{config_key}", value)
                else:
                    self.set(f"tuning.{config_key}", env_value)

                console.print(f"[yellow]Applied environment override: {env_var}={env_value}[/yellow]")

    def load_unified_tuning_config(
        self, config_path: Union[str, Path], platform: Optional[str] = None
    ) -> UnifiedTuningConfiguration:
        """Load unified tuning configuration from YAML or JSON file.

        Args:
            config_path: Path to the unified tuning configuration file
            platform: Platform to validate against (default: uses configured preferred platform)

        Returns:
            UnifiedTuningConfiguration instance

        Raises:
            ValueError: If the configuration file is invalid or cannot be loaded
        """
        config_path = Path(config_path)

        try:
            config_data = load_config_file(config_path)
            if not config_data:
                raise ValueError("Configuration file is empty")

            # Create unified configuration from data
            unified_config = UnifiedTuningConfiguration.from_dict(config_data)

            # Validate configuration if enabled
            if self.get("tuning.validate_on_load", True):
                self._validate_unified_tuning_config(unified_config, platform)

            return unified_config

        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to parse unified tuning configuration file: {e}") from e
        except Exception as e:
            raise ValueError(f"Error loading unified tuning configuration: {e}") from e

    def save_unified_tuning_config(
        self,
        config: UnifiedTuningConfiguration,
        config_path: Union[str, Path],
        format: str = "yaml",
    ) -> None:
        """Save unified tuning configuration to file.

        Args:
            config: UnifiedTuningConfiguration to save
            config_path: Path where to save the configuration
            format: File format ('yaml' or 'json')
        """
        config_path = Path(config_path)

        # Convert to serializable format
        config_data = config.to_dict()

        # Add metadata
        config_data["_metadata"] = {
            "version": "2.0",
            "format": "unified_tuning",
            "created": datetime.now().isoformat(),
            "generated_by": "benchbox-cli",
        }

        # Save to file
        try:
            save_config_file(config_data, config_path, format)
            console.print(f"[green]✅ Unified tuning configuration saved to {config_path}[/green]")

        except Exception as e:
            console.print(f"[red]❌ Failed to save unified tuning configuration: {e}[/red]")
            raise

    def _validate_unified_tuning_config(
        self, config: UnifiedTuningConfiguration, platform: Optional[str] = None
    ) -> None:
        """Validate unified tuning configuration.

        Args:
            config: UnifiedTuningConfiguration to validate
            platform: Platform to validate against (default: uses configured preferred platform)
        """
        if platform is None:
            platform = self.get("database.preferred", "duckdb")

        # Validate constraint settings are explicitly specified
        constraint_errors = []

        if config.primary_keys.enabled is None:
            constraint_errors.append("primary_keys.enabled must be explicitly specified (true or false)")

        if config.foreign_keys.enabled is None:
            constraint_errors.append("foreign_keys.enabled must be explicitly specified (true or false)")

        # Validate platform-specific configuration
        platform_errors = config.validate_for_platform(platform)

        all_errors = constraint_errors + platform_errors

        if all_errors:
            console.print(f"[red]⚠️ Unified tuning validation errors for platform '{platform}':[/red]")
            for error in all_errors:
                console.print(f"  - {error}")

            if not self.get("tuning.allow_platform_incompatible", False):
                raise ValueError(f"Invalid unified tuning configuration for platform '{platform}'")

    def create_sample_unified_tuning_config(self, path: Optional[Path] = None, platform: Optional[str] = None) -> None:
        """Create a sample unified tuning configuration file.

        Args:
            path: Path where to create the sample configuration (default: unified_tuning.yaml)
            platform: Target platform for compatibility (default: uses configured preferred platform)
        """
        if path is None:
            path = Path("unified_tuning.yaml")

        if platform is None:
            platform = self.get("database.preferred", "duckdb")

        # Create a sample configuration with platform-compatible options
        sample_config = UnifiedTuningConfiguration()

        # Configure constraints (supported by most platforms)
        sample_config.primary_keys.enabled = True
        sample_config.foreign_keys.enabled = True
        sample_config.foreign_keys.on_delete_action = "CASCADE"

        sample_config.unique_constraints.enabled = True
        sample_config.check_constraints.enabled = True

        # Configure platform-specific optimizations based on target platform
        if platform.lower() == "databricks":
            sample_config.platform_optimizations.z_ordering_enabled = True
            sample_config.platform_optimizations.z_ordering_columns = [
                "date_col",
                "partition_col",
            ]
            sample_config.platform_optimizations.databricks_clustering_strategy = "z_order"
            sample_config.platform_optimizations.liquid_clustering_enabled = False
            sample_config.platform_optimizations.liquid_clustering_columns = []
            sample_config.platform_optimizations.sorted_ingestion_mode = "off"
            sample_config.platform_optimizations.sorted_ingestion_method = "auto"
            sample_config.platform_optimizations.auto_optimize_enabled = True
            sample_config.platform_optimizations.bloom_filters_enabled = True
            sample_config.platform_optimizations.bloom_filter_columns = [
                "customer_id",
                "product_id",
            ]
        elif platform.lower() in ["snowflake", "bigquery"]:
            sample_config.platform_optimizations.materialized_views_enabled = True
        elif platform.lower() in ["postgresql", "redshift"]:
            sample_config.platform_optimizations.bloom_filters_enabled = True
            sample_config.platform_optimizations.bloom_filter_columns = ["customer_id"]
            sample_config.platform_optimizations.materialized_views_enabled = True

        # Add platform-compatible table tunings
        from benchbox.core.tuning.interface import TableTuning, TuningColumn

        if TuningType.PARTITIONING.is_compatible_with_platform(platform):
            sample_config.table_tunings["orders"] = TableTuning(
                table_name="orders",
                partitioning=[TuningColumn(name="order_date", type="DATE", order=1)],
            )

            sample_config.table_tunings["lineitem"] = TableTuning(
                table_name="lineitem",
                partitioning=[TuningColumn(name="shipdate", type="DATE", order=1)],
            )

        if TuningType.CLUSTERING.is_compatible_with_platform(platform):
            if "orders" in sample_config.table_tunings:
                sample_config.table_tunings["orders"].clustering = [
                    TuningColumn(name="customer_id", type="INTEGER", order=1)
                ]

        if TuningType.SORTING.is_compatible_with_platform(platform):
            if "lineitem" not in sample_config.table_tunings:
                sample_config.table_tunings["lineitem"] = TableTuning(table_name="lineitem")

            sample_config.table_tunings["lineitem"].sorting = [
                TuningColumn(name="orderkey", type="INTEGER", order=1),
                TuningColumn(name="linenumber", type="INTEGER", order=2),
            ]

        self.save_unified_tuning_config(sample_config, path)
        console.print(
            f"[green]✅ Sample unified tuning configuration created for platform '{platform}' at {path}[/green]"
        )

        enabled_types = sample_config.get_enabled_tuning_types()
        console.print("This configuration includes:")
        console.print("  • Schema constraints (primary keys, foreign keys, unique, check)")
        if any(t.value.startswith(("z_ordering", "auto_", "bloom_", "materialized_")) for t in enabled_types):
            console.print(f"  • Platform optimizations for {platform}")
        if any(
            t
            in [
                TuningType.PARTITIONING,
                TuningType.CLUSTERING,
                TuningType.SORTING,
                TuningType.DISTRIBUTION,
            ]
            for t in enabled_types
        ):
            console.print("  • Table-level tunings (partitioning, clustering, sorting)")
        console.print(f"All settings are compatible with {platform}.")
        console.print("Edit this file to customize your tuning settings.")


class DirectoryManager:
    """Manages BenchBox directory structure and file organization."""

    def __init__(self, base_dir: Optional[str] = None):
        """Initialize directory manager with configurable base directory.

        When ``base_dir`` is omitted, the root is resolved via
        :func:`resolve_benchmark_runs_dir`, which honors
        ``BENCHBOX_OUTPUT_DIR`` and falls back to ``Path.cwd() / "benchmark_runs"``.
        """
        from benchbox.utils.path_utils import resolve_benchmark_runs_dir

        self.base_dir = Path(base_dir) if base_dir else resolve_benchmark_runs_dir()
        self.results_dir = self.base_dir / "results"
        self.datagen_dir = self.base_dir / "datagen"
        self.databases_dir = self.base_dir / "databases"

        # Create directories if they don't exist
        self._ensure_directories()

    def _ensure_directories(self):
        """Create all required directories."""
        for directory in [
            self.base_dir,
            self.results_dir,
            self.datagen_dir,
            self.databases_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)

    def _format_scale_factor(self, scale_factor: float) -> str:
        """Format scale factor for filenames using centralized utility."""
        return format_scale_factor(scale_factor)

    def get_result_filename(
        self,
        benchmark_name: str,
        scale_factor: float,
        platform: str,
        timestamp: str,
        execution_id: str,
        mode: str | None = None,
    ) -> str:
        """Generate standardized result filename."""
        from benchbox.core.results.filenames import build_result_filename

        return build_result_filename(
            benchmark_id=benchmark_name,
            scale_factor=scale_factor,
            platform=platform,
            timestamp=timestamp,
            execution_id=execution_id,
            mode=mode,
        )

    def get_result_path(
        self,
        benchmark_name: str,
        scale_factor: float,
        platform: str,
        timestamp: str,
        execution_id: str,
        mode: str | None = None,
    ) -> Path:
        """Get full path for result file."""
        filename = self.get_result_filename(benchmark_name, scale_factor, platform, timestamp, execution_id, mode=mode)
        return self.results_dir / filename

    def get_database_filename(
        self,
        benchmark_name: str,
        scale_factor: float,
        platform: str,
        tuning_config: Optional[dict[str, Any]] = None,
        custom_name: Optional[str] = None,
    ) -> str:
        """Generate database filename with configuration characteristics.

        Args:
            benchmark_name: Name of the benchmark
            scale_factor: Scale factor value
            platform: Platform name
            tuning_config: Unified tuning configuration (optional)
            custom_name: Custom database name override (optional)

        Returns:
            Database filename with appropriate extension
        """
        return generate_database_filename(
            benchmark_name=benchmark_name,
            scale_factor=scale_factor,
            platform=platform,
            tuning_config=tuning_config,
            custom_name=custom_name,
        )

    def get_database_path(
        self,
        benchmark_name: str,
        scale_factor: float,
        platform: str,
        tuning_config: Optional[dict[str, Any]] = None,
        custom_name: Optional[str] = None,
    ) -> Path:
        """Get full path for database file with configuration characteristics.

        Args:
            benchmark_name: Name of the benchmark
            scale_factor: Scale factor value
            platform: Platform name
            tuning_config: Unified tuning configuration (optional)
            custom_name: Custom database name override (optional)

        Returns:
            Full path to database file
        """
        filename = self.get_database_filename(benchmark_name, scale_factor, platform, tuning_config, custom_name)
        return self.databases_dir / filename

    def get_datagen_path(self, benchmark_name: str, scale_factor: float) -> Path:
        """Get path for generated data directory."""
        sf_str = self._format_scale_factor(scale_factor)
        return self.datagen_dir / f"{benchmark_name}_{sf_str}"

    def clean_old_files(self, benchmark_name: Optional[str] = None, max_age_days: int = 30):
        """Clean old files from all directories."""
        import time

        current_time = time.time()
        cutoff_time = current_time - (max_age_days * 24 * 60 * 60)

        cleaned_files = []

        for directory in [self.results_dir, self.datagen_dir, self.databases_dir]:
            if not directory.exists():
                continue

            for file_path in directory.rglob("*"):
                if file_path.is_file():
                    # Check if file matches benchmark filter
                    if benchmark_name and not file_path.name.startswith(benchmark_name):
                        continue

                    # Check file age
                    if file_path.stat().st_mtime < cutoff_time:
                        try:
                            file_path.unlink()
                            cleaned_files.append(str(file_path))
                        except Exception as e:
                            console.print(f"[yellow]Warning: Could not delete {file_path}: {e}[/yellow]")

        return cleaned_files

    def list_files(self, file_type: str = "all") -> dict[str, list[Path]]:
        """List files by type."""
        files = {
            "results": list(self.results_dir.glob("*.json")) if self.results_dir.exists() else [],
            "databases": list(self.databases_dir.glob("*")) if self.databases_dir.exists() else [],
            "datagen": list(self.datagen_dir.glob("*")) if self.datagen_dir.exists() else [],
        }

        if file_type == "all":
            return files
        else:
            return {file_type: files.get(file_type, [])}

    def get_directory_sizes(self) -> dict[str, float]:
        """Get size of each directory in MB."""

        def get_dir_size(path: Path) -> float:
            if not path.exists():
                return 0.0
            total = 0
            for file_path in path.rglob("*"):
                if file_path.is_file():
                    total += file_path.stat().st_size
            return total / (1024 * 1024)  # Convert to MB

        return {
            "results": get_dir_size(self.results_dir),
            "datagen": get_dir_size(self.datagen_dir),
            "databases": get_dir_size(self.databases_dir),
            "total": get_dir_size(self.base_dir),
        }
