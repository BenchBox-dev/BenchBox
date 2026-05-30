"""Core configuration utilities shared across CLI and unified runner.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Optional, Union

import yaml

from benchbox.platforms.clickhouse.deployment_mode import resolve_clickhouse_deployment_mode
from benchbox.utils.database_naming import generate_database_filename
from benchbox.utils.output_path import normalize_output_root
from benchbox.utils.printing import emit


def deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries, with override values taking precedence.

    Args:
        base: Base dictionary to merge into
        override: Dictionary containing override values

    Returns:
        New dictionary with merged values
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_dicts(result[key], value)
        else:
            result[key] = value

    return result


def load_config_file(config_path: Union[str, Path]) -> dict[str, Any]:
    """Load configuration from YAML or JSON file.

    Args:
        config_path: Path to the configuration file

    Returns:
        Dictionary containing configuration data

    Raises:
        ValueError: If the file cannot be loaded or parsed
        FileNotFoundError: If the file does not exist
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    try:
        with open(config_path, encoding="utf-8") as f:
            file_content = f.read()

        # Try to determine file format and parse
        if config_path.suffix.lower() in [".yaml", ".yml"]:
            config_data = yaml.safe_load(file_content)
        elif config_path.suffix.lower() == ".json":
            config_data = json.loads(file_content)
        else:
            # Try both formats
            try:
                config_data = yaml.safe_load(file_content)
            except yaml.YAMLError:
                config_data = json.loads(file_content)

        return config_data or {}

    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise ValueError(f"Failed to parse configuration file: {e}") from e
    except Exception as e:
        raise ValueError(f"Error loading configuration: {e}") from e


def save_config_file(config_data: dict[str, Any], config_path: Union[str, Path], format: str = "yaml") -> None:
    """Save configuration to YAML or JSON file.

    Args:
        config_data: Configuration data to save
        config_path: Path where to save the configuration
        format: File format ('yaml' or 'json')

    Raises:
        ValueError: If the format is not supported
    """
    config_path = Path(config_path)

    # Create directory if it doesn't exist
    config_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            if format.lower() == "json":
                json.dump(config_data, f, indent=2)
            elif format.lower() in ["yaml", "yml"]:
                yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
            else:
                raise ValueError(f"Unsupported format: {format}")

    except Exception as e:
        raise ValueError(f"Failed to save configuration: {e}") from e


def build_benchmark_config(
    args_or_config: Union[Any, dict[str, Any]], platform: Optional[str] = None
) -> dict[str, Any]:
    """Build benchmark configuration from CLI args or config dict.

    Supports both argparse Namespace objects and plain dictionaries.

    Args:
        args_or_config: Either an argparse Namespace or a config dictionary
        platform: Platform name (optional, used for output dir logic)

    Returns:
        Dictionary containing benchmark configuration
    """
    if isinstance(args_or_config, dict):
        # Dict-based configuration (e.g., from unified runner)
        config = args_or_config
        benchmark_config = {
            "scale_factor": config.get("scale_factor", 0.01),
            "verbose": config.get("very_verbose", False),
            "force_regenerate": config.get("force", False),
        }

        plat = config.get("platform", platform)
        bname = config.get("benchmark")
        out = config.get("output")

        if out:
            benchmark_config["output_dir"] = normalize_output_root(out, bname, config.get("scale_factor", 0.01))
        else:
            benchmark_config["output_dir"] = _get_default_output_dir(
                plat, bname, config.get("scale_factor", 0.01), config.get("data_path")
            )

        if config.get("compress"):
            benchmark_config.update({"compress_data": True, "compression_type": "zstd"})

    else:
        # Argparse Namespace object (e.g., from CLI)
        args = args_or_config
        benchmark_config = {
            "scale_factor": getattr(args, "scale", 0.01),
            "verbose": bool(getattr(args, "verbose", 0)),
            "force_regenerate": bool(getattr(args, "force", False)),
        }

        plat = platform or getattr(args, "platform", None) or "duckdb"
        bname = getattr(args, "benchmark", "bench")
        out = getattr(args, "output", None)

        if out:
            benchmark_config["output_dir"] = normalize_output_root(out, bname, getattr(args, "scale", 0.01))
        else:
            benchmark_config["output_dir"] = _get_default_output_dir(
                plat, bname, getattr(args, "scale", 0.01), getattr(args, "data_path", None)
            )

        if getattr(args, "compress", False):
            benchmark_config.update({"compress_data": True, "compression_type": "zstd"})

    return benchmark_config


def build_platform_adapter_config(
    platform: str,
    args_or_config: Union[Any, dict[str, Any]],
    system_profile: Optional[Any] = None,
    benchmark_name: Optional[str] = None,
    scale_factor: Optional[float] = None,
) -> dict[str, Any]:
    """Build platform adapter configuration from CLI args or config dict.

    Args:
        platform: Platform name (e.g., 'duckdb', 'databricks', 'clickhouse')
        args_or_config: Either an argparse Namespace or a config dictionary
        system_profile: System profile object (optional)
        benchmark_name: Benchmark name (optional)
        scale_factor: Scale factor (optional)

    Returns:
        Dictionary containing platform adapter configuration
    """
    platform = platform.lower()
    cfg = {}

    # Extract values from args or config
    if isinstance(args_or_config, dict):
        config = args_or_config

        def get_value(key, default=None):
            return config.get(key, default)
    else:
        args = args_or_config

        def get_value(key, default=None):
            return getattr(args, key, default)

    if platform == "duckdb":
        # Database path: use provided or generate
        db_path = get_value("duckdb_database_path")
        if not db_path:
            from benchbox.utils.path_utils import get_benchmark_runs_databases_path

            bname = benchmark_name or get_value("benchmark", "bench")
            sf = scale_factor if scale_factor is not None else get_value("scale", 0.01)
            data_dir = get_benchmark_runs_databases_path(bname, sf)
            db_filename = generate_database_filename(
                benchmark_name=bname, scale_factor=sf, platform="duckdb", tuning_config=None
            )
            db_path = str(data_dir / db_filename)

        cfg["database_path"] = db_path
        cfg["memory_limit"] = get_value("memory_limit", "4GB")
        cfg["force_recreate"] = bool(get_value("force", False))

    elif platform == "datafusion":
        # Working directory: use provided or generate
        working_dir = get_value("datafusion_working_dir")
        if working_dir:
            cfg["working_dir"] = working_dir

        # Map DataFusion-specific CLI arguments to config keys
        cfg["memory_limit"] = get_value("datafusion_memory_limit", "16G")
        cfg["partitions"] = get_value("datafusion_partitions")
        cfg["format"] = get_value("datafusion_format", "parquet")
        cfg["temp_dir"] = get_value("datafusion_temp_dir")
        cfg["batch_size"] = get_value("datafusion_batch_size", 8192)
        cfg["force_recreate"] = bool(get_value("force", False))

    elif platform == "databricks":
        cfg.update(
            {
                "server_hostname": get_value("server_hostname"),
                "http_path": get_value("http_path"),
                "access_token": get_value("access_token"),
                "catalog": get_value("catalog", "workspace"),
                "schema": f"{(benchmark_name or get_value('benchmark', 'bench'))}_schema",
            }
        )

    elif platform in {"clickhouse", "clickhouse-local", "clickhouse-server"}:
        if platform == "clickhouse-local":
            cfg["deployment_mode"] = "local"
        elif platform == "clickhouse-server":
            cfg["deployment_mode"] = "server"
        else:
            cfg["deployment_mode"] = resolve_clickhouse_deployment_mode(
                {
                    "deployment_mode": get_value("deployment_mode"),
                    "mode": get_value("mode"),
                    "embedded": get_value("embedded"),
                }
            )
        cfg["data_path"] = get_value("data_path", "/tmp/benchbox_ch_local")
        cfg.setdefault("mode", cfg["deployment_mode"])

        if cfg["deployment_mode"] == "server":
            cfg.update(
                {
                    "host": get_value("host", "localhost"),
                    "port": get_value("port", 9000),
                    "user": get_value("user", "default"),
                    "password": get_value("password"),
                    "secure": bool(get_value("secure", False)),
                }
            )

    return cfg


def validate_config_sections(config: dict[str, Any], required_sections: list) -> bool:
    """Validate that a configuration contains required sections.

    Args:
        config: Configuration dictionary to validate
        required_sections: List of required section names

    Returns:
        True if all required sections are present, False otherwise
    """
    return all(section in config for section in required_sections)


def validate_numeric_config(config: dict[str, Any], validations: dict[str, Any]) -> list:
    """Validate numeric configuration values.

    Args:
        config: Configuration dictionary to validate
        validations: Dictionary of key -> (min_val, max_val, required) tuples

    Returns:
        List of validation error messages (empty if all valid)
    """
    errors = []

    for key, (min_val, max_val, required) in validations.items():
        if key not in config:
            if required:
                errors.append(f"Required configuration key '{key}' is missing")
            continue

        value = config[key]

        if not isinstance(value, (int, float)):
            errors.append(f"Configuration key '{key}' must be numeric, got {type(value).__name__}")
            continue

        if min_val is not None and value < min_val:
            errors.append(f"Configuration key '{key}' must be >= {min_val}, got {value}")

        if max_val is not None and value > max_val:
            errors.append(f"Configuration key '{key}' must be <= {max_val}, got {value}")

    return errors


def _get_default_output_dir(
    platform: Optional[str], benchmark_name: Optional[str], scale_factor: float, data_path: Optional[str] = None
) -> Optional[str]:
    """Get default output directory based on platform.

    Args:
        platform: Platform name
        benchmark_name: Benchmark name
        scale_factor: Scale factor
        data_path: Custom data path (for ClickHouse)

    Returns:
        Default output directory path or None
    """
    if not platform or not benchmark_name:
        return None

    if platform.lower() in ["duckdb", "sqlite"]:
        from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

        data_dir = get_benchmark_runs_datagen_path(benchmark_name, scale_factor)
        return str(data_dir)
    elif platform.lower() in {"clickhouse", "clickhouse-local"}:
        return data_path or "/tmp/benchbox_ch_local"
    else:
        return None


def load_platform_config(platform: str, config_path: Optional[str] = None, verbose: bool = False) -> dict[str, Any]:
    """Load platform configuration from YAML file or use defaults.

    Args:
        platform: Platform name
        config_path: Optional explicit config file path
        verbose: Whether to print configuration choices

    Returns:
        Platform configuration dictionary
    """
    config = {}

    if config_path:
        # Explicit config file specified
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Platform config file not found: {config_path}")
        source = f"file: {config_path}"
    else:
        # Try to find default config file
        config_file = Path(f"examples/config/{platform}.yaml")
        if config_file.exists():
            source = f"default file: {config_file}"
        else:
            if verbose:
                emit("Platform config using built-in defaults")
            return config

    try:
        with open(config_file, encoding="utf-8") as f:
            yaml_config = yaml.safe_load(f)
            if yaml_config and isinstance(yaml_config, dict):
                # Extract connection and settings from YAML structure
                connection_config = yaml_config.get("connection", {})
                settings_config = yaml_config.get("settings", {})

                # Merge connection extra_params into main config
                config.update(connection_config)
                if "extra_params" in connection_config:
                    config.update(connection_config["extra_params"])

                # Add settings
                config.update(settings_config)

                if verbose:
                    emit(f"Platform config loaded from {source}")
    except Exception as e:
        if verbose:
            emit(f"Warning: Failed to load platform config from {config_file}: {e}")
            emit(f"Using built-in defaults for {platform}")

    return config


def load_tuning_config(
    platform: str, benchmark: str, tuning_mode: str, verbose: bool = False
) -> Optional[dict[str, Any]]:
    """Load tuning configuration based on mode.

    Args:
        platform: Platform name
        benchmark: Benchmark name
        tuning_mode: Either 'tuned', 'notuning', or path to custom config file
        verbose: Whether to print configuration choices

    Returns:
        Tuning configuration dictionary or None
    """
    if tuning_mode in ["tuned", "notuning"]:
        # Auto-select based on platform/benchmark
        config_file = Path(f"examples/tunings/{platform}/{benchmark}_{tuning_mode}.yaml")
        if not config_file.exists():
            if verbose:
                emit(f"Warning: Tuning config not found: {config_file}")
                emit("Proceeding without tuning configuration")
            return None
        source = f"auto-selected: {config_file}"
    else:
        # Custom file path provided
        config_file = Path(tuning_mode)
        if not config_file.exists():
            raise FileNotFoundError(f"Tuning config file not found: {tuning_mode}")
        source = f"custom file: {tuning_mode}"

    try:
        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
            if verbose and config:
                tuning_type = config.get("_metadata", {}).get("configuration_type", "unknown")
                emit(f"Tuning config loaded from {source} (type: {tuning_type})")
            return config
    except Exception as e:
        if verbose:
            emit(f"Warning: Failed to load tuning config from {config_file}: {e}")
        return None


def merge_all_configs(
    platform: str,
    benchmark: str,
    args: argparse.Namespace,
    tuning_mode: str = "tuned",
    platform_config_path: Optional[str] = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Merge configurations from all sources with proper precedence.

    Precedence order (highest to lowest):
    1. CLI arguments (highest priority)
    2. Tuning YAML files
    3. Platform YAML files
    4. Built-in defaults (lowest priority)

    Args:
        platform: Platform name
        benchmark: Benchmark name
        args: Parsed command line arguments
        tuning_mode: Tuning mode ('tuned', 'notuning', or file path)
        platform_config_path: Optional explicit platform config path
        verbose: Whether to print merge details

    Returns:
        Unified configuration dictionary
    """
    config = {}

    # 1. Start with built-in defaults (lowest priority)
    defaults = get_builtin_defaults(platform, benchmark)
    config.update(defaults)
    if verbose:
        emit("✅ Applied built-in defaults")

    # 2. Apply platform configuration
    platform_config = load_platform_config(platform, platform_config_path, verbose)
    config.update(platform_config)

    # 3. Apply tuning configuration
    tuning_config = load_tuning_config(platform, benchmark, tuning_mode, verbose)
    if tuning_config:
        config.update(tuning_config)
        config["tuning_config"] = tuning_config  # Keep original for compatibility

    # 4. Apply CLI arguments (highest priority)
    cli_config = extract_cli_config(args)
    config.update(cli_config)
    # Normalize CLI aliases
    if "scale" in config:
        # Map CLI --scale to internal scale_factor
        config["scale_factor"] = config["scale"]
    if verbose:
        emit("✅ Applied CLI arguments")

    # Add convenience fields
    config["platform"] = platform
    config["benchmark"] = benchmark
    config["verbose_enabled"] = config.get("verbose", 0) > 0
    config["very_verbose"] = config.get("verbose", 0) > 1
    # Quiet mode suppresses all verbosity
    if config.get("quiet", False):
        config["verbose_enabled"] = False
        config["very_verbose"] = False

    return config


def get_builtin_defaults(platform: str, benchmark: str) -> dict[str, Any]:
    """Get built-in default configuration values."""
    defaults = {
        # Common defaults
        "scale_factor": 0.01,
        "phases": "power",
        "verbose": 0,
        "force": False,
        "compress": False,
        "streams": 2,
        "compression_type": "zstd",
        "force_recreate": False,
        "force_regenerate": False,
    }

    # Platform-specific defaults
    if platform == "duckdb":
        defaults.update(
            {
                "memory_limit": "4GB",
                "database_path": None,
            }
        )
    elif platform == "databricks":
        defaults.update(
            {
                "catalog": "workspace",
                "schema": "benchbox",
                "server_hostname": None,
                "http_path": None,
                "access_token": None,
            }
        )
    elif platform in {"clickhouse", "clickhouse-local", "clickhouse-server"}:
        defaults.update(
            {
                "deployment_mode": "local" if platform in {"clickhouse", "clickhouse-local"} else "server",
                "data_path": "/tmp/benchbox_ch_local",
            }
        )
    elif platform == "sqlite":
        defaults.update(
            {
                "timeout": 30.0,
                "database_path": None,
            }
        )
    elif platform == "bigquery":
        defaults.update(
            {
                "location": "US",
                "dataset_id": "benchbox",
                "storage_prefix": "benchbox-data",
                "project_id": None,
                "credentials_path": None,
                "storage_bucket": None,
            }
        )
    elif platform == "redshift":
        defaults.update(
            {
                "port": 5439,
                "database": "dev",
                "host": None,
                "username": None,
                "password": None,
                "cluster_identifier": None,
            }
        )
    elif platform == "snowflake":
        defaults.update(
            {
                "warehouse": "COMPUTE_WH",
                "database": "BENCHBOX",
                "schema": "PUBLIC",
                "account": None,
                "username": None,
                "password": None,
                "role": None,
            }
        )

    return defaults


def extract_cli_config(args: argparse.Namespace) -> dict[str, Any]:
    """Extract configuration values from CLI arguments."""
    config = {}

    # Convert namespace to dict, filtering out None values
    for key, value in vars(args).items():
        if value is not None:
            config[key] = value

    # Handle special mappings for consistency
    if "duckdb_database_path" in config:
        config["database_path"] = config["duckdb_database_path"]
    if "sqlite_database_path" in config:
        config["database_path"] = config["sqlite_database_path"]
    if "data_path" in config:
        config["data_path"] = config["data_path"]

    # Map platform-specific arguments to standard names
    platform_mappings = {
        "server_hostname": "server_hostname",
        "http_path": "http_path",
        "access_token": "access_token",
        "redshift_host": "host",
        "redshift_port": "port",
        "redshift_database": "database",
        "redshift_username": "username",
        "redshift_password": "password",
        "snowflake_database": "database",
        "snowflake_schema": "schema",
        "snowflake_username": "username",
        "snowflake_password": "password",
        "project_id": "project_id",
        "dataset_id": "dataset_id",
        "credentials_path": "credentials_path",
        "storage_bucket": "storage_bucket",
        "storage_prefix": "storage_prefix",
    }

    for old_key, new_key in platform_mappings.items():
        if old_key in config:
            config[new_key] = config[old_key]

    return config
