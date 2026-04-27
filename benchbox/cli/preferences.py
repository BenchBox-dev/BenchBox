"""Persistent preferences and configuration management for BenchBox CLI.

This module handles saving and loading user preferences, last-run configurations,
and quick restart functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from benchbox.utils.printing import quiet_console

console = quiet_console

# Maximum file size for YAML configs (1MB should be more than enough)
MAX_YAML_SIZE_BYTES = 1024 * 1024  # 1MB


def _safe_yaml_load(file_path: Path) -> Optional[dict[str, Any]]:
    """Safely load YAML file with size limits and validation.

    Protects against YAML bombs and malicious input by:
    - Checking file size before loading
    - Using yaml.safe_load() to prevent code execution
    - Validating result is a dictionary

    Args:
        file_path: Path to YAML file to load

    Returns:
        Loaded configuration dictionary, or None if invalid/too large

    Raises:
        ValueError: If file is too large or contains invalid YAML
    """
    try:
        # Check file size before loading
        file_size = file_path.stat().st_size
        if file_size > MAX_YAML_SIZE_BYTES:
            raise ValueError(f"Configuration file too large ({file_size} bytes, max {MAX_YAML_SIZE_BYTES})")

        # Load YAML with safe_load (prevents arbitrary code execution)
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Validate result is a dictionary
        if data is not None and not isinstance(data, dict):
            raise ValueError(f"Expected dictionary, got {type(data).__name__}")

        return data

    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML format: {e}") from e


def get_preferences_dir() -> Path:
    """Get the BenchBox preferences directory.

    Returns:
        Path to ~/.benchbox directory
    """
    preferences_dir = Path.home() / ".benchbox"
    preferences_dir.mkdir(parents=True, exist_ok=True)
    return preferences_dir


def get_last_run_path() -> Path:
    """Get the path to the last run configuration file.

    Returns:
        Path to last_run.yaml
    """
    return get_preferences_dir() / "last_run.yaml"


def save_last_run_config(
    database: str,
    benchmark: str,
    scale: float,
    tuning_mode: str,
    phases: Optional[list[str]] = None,
    concurrency: int = 1,
    compress_data: bool = True,
    compression_type: str = "zstd",
    compression_level: Optional[int] = None,
    test_execution_type: str = "power",
    seed: Optional[int] = None,
    output: Optional[str] = None,
    additional_options: Optional[dict[str, Any]] = None,
) -> None:
    """Save the last run configuration for quick restart.

    Args:
        database: Database platform used
        benchmark: Benchmark name
        scale: Scale factor
        tuning_mode: Tuning mode (tuned, notuning, or file path)
        phases: List of phases executed
        concurrency: Concurrency level
        compress_data: Whether data compression is enabled
        compression_type: Compression algorithm (gzip, zstd, none)
        compression_level: Compression level (algorithm-specific)
        test_execution_type: Test type (power, throughput, combined, etc.)
        seed: RNG seed for reproducibility
        output: Cloud storage output location (for cloud platforms)
        additional_options: Any additional configuration options
    """
    config = {
        "database": database,
        "benchmark": benchmark,
        "scale": scale,
        "tuning_mode": tuning_mode,
        "phases": phases or ["load", "power"],
        "concurrency": concurrency,
        "compress_data": compress_data,
        "compression_type": compression_type,
        "compression_level": compression_level,
        "test_execution_type": test_execution_type,
        "seed": seed,
        "timestamp": datetime.now().isoformat(),
    }

    if output:
        config["output"] = output

    if additional_options:
        config.update(additional_options)

    last_run_path = get_last_run_path()

    try:
        with open(last_run_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        # Don't fail the benchmark if we can't save preferences
        console.print(f"[dim yellow]Warning: Could not save last run config: {e}[/dim yellow]")


def load_last_run_config() -> Optional[dict[str, Any]]:
    """Load the last run configuration.

    Returns:
        Dictionary of last run configuration, or None if not available
    """
    last_run_path = get_last_run_path()

    if not last_run_path.exists():
        return None

    try:
        config = _safe_yaml_load(last_run_path)

        if config is None:
            return None

        # Validate that required fields exist
        required_fields = ["database", "benchmark", "scale"]
        if not all(field in config for field in required_fields):
            return None

        return config

    except (ValueError, OSError) as e:
        # Don't fail if we can't load preferences
        console.print(f"[dim yellow]Warning: Could not load last run config: {e}[/dim yellow]")
        return None


def clear_last_run_config() -> None:
    """Clear the saved last run configuration."""
    last_run_path = get_last_run_path()

    if last_run_path.exists():
        try:
            last_run_path.unlink()
        except Exception as e:
            console.print(f"[dim yellow]Warning: Could not clear last run config: {e}[/dim yellow]")


def _is_safe_tuning_path(tuning_path: str) -> bool:
    """Validate that a tuning path is safe and within allowed directories.

    Prevents path traversal attacks by restricting tuning configs to:
    - Files in the current working directory
    - Files in the examples/ subdirectory
    - Files ending in .yaml or .yml

    Args:
        tuning_path: Path to tuning configuration file

    Returns:
        True if path is safe and exists, False otherwise
    """
    try:
        path = Path(tuning_path)

        # Only accept YAML files
        if path.suffix not in [".yaml", ".yml"]:
            return False

        # Resolve to absolute path to detect traversal attempts
        resolved = path.resolve()

        # Current working directory
        cwd = Path.cwd().resolve()

        # Allow files in CWD or examples/ subdirectory
        allowed_dirs = [
            cwd,
            cwd / "examples",
        ]

        # Check if resolved path is within allowed directories
        for allowed_dir in allowed_dirs:
            try:
                resolved.relative_to(allowed_dir)
                # Path is within allowed directory, check if it exists
                return resolved.exists()
            except ValueError:
                # relative_to raises ValueError if path is not relative
                continue

        # Path is outside allowed directories
        return False

    except (OSError, RuntimeError):
        # Handle path resolution errors
        return False


def _format_relative_time(iso_timestamp: str) -> Optional[str]:
    """Format an ISO timestamp as a human-readable relative time string.

    Args:
        iso_timestamp: ISO 8601 formatted timestamp string

    Returns:
        Relative time string like "(2d ago)" or "(just now)", or None if invalid
    """
    try:
        timestamp = datetime.fromisoformat(iso_timestamp)
    except (ValueError, TypeError):
        return None

    time_diff = datetime.now() - timestamp

    if time_diff.days > 0:
        return f"({time_diff.days}d ago)"
    elif time_diff.seconds > 3600:
        return f"({time_diff.seconds // 3600}h ago)"
    elif time_diff.seconds > 60:
        return f"({time_diff.seconds // 60}m ago)"
    else:
        return "(just now)"


def _format_tuning_label(tuning: str) -> str:
    """Map a tuning mode value to its display label.

    Args:
        tuning: Tuning mode string (e.g., "tuned", "notuning", or a file path)

    Returns:
        Human-readable tuning label
    """
    if tuning == "tuned":
        return "tuned"
    elif tuning == "notuning":
        return "baseline"
    elif _is_safe_tuning_path(tuning):
        return "custom config"
    else:
        return tuning


def format_last_run_summary(config: dict[str, Any]) -> str:
    """Format a human-readable summary of the last run configuration.

    Args:
        config: Last run configuration dictionary

    Returns:
        Formatted summary string
    """
    parts = [
        f"{config['benchmark'].upper()} on {config['database'].upper()}",
        f"SF={config['scale']}",
        _format_tuning_label(config.get("tuning_mode", "tuned")),
    ]

    phases = config.get("phases", [])
    if phases:
        parts.append(f"phases: {'+'.join(phases)}")

    table_mode = str(config.get("table_mode", "native") or "native").lower()
    if table_mode != "native":
        parts.append(f"tables: {table_mode}")

    concurrency = config.get("concurrency", 1)
    if concurrency > 1:
        parts.append(f"{concurrency} streams")

    if "timestamp" in config:
        relative_time = _format_relative_time(config["timestamp"])
        if relative_time:
            parts.append(relative_time)

    return " | ".join(parts)


def save_favorite_config(
    name: str,
    database: str,
    benchmark: str,
    scale: float,
    tuning_mode: str,
    phases: Optional[list[str]] = None,
    concurrency: int = 1,
    description: Optional[str] = None,
) -> None:
    """Save a favorite configuration for quick access.

    Args:
        name: Name for this favorite configuration
        database: Database platform
        benchmark: Benchmark name
        scale: Scale factor
        tuning_mode: Tuning mode
        phases: List of phases
        concurrency: Concurrency level
        description: Optional description
    """
    favorites_path = get_preferences_dir() / "favorites.yaml"

    # Load existing favorites
    favorites = {}
    if favorites_path.exists():
        try:
            favorites = _safe_yaml_load(favorites_path) or {}
        except (ValueError, OSError):
            pass

    # Include new favorite
    favorites[name] = {
        "database": database,
        "benchmark": benchmark,
        "scale": scale,
        "tuning_mode": tuning_mode,
        "phases": phases or ["load", "power"],
        "concurrency": concurrency,
        "description": description or f"{benchmark} on {database}",
        "created": datetime.now().isoformat(),
    }

    # Save favorites
    try:
        with open(favorites_path, "w", encoding="utf-8") as f:
            yaml.dump(favorites, f, default_flow_style=False, sort_keys=False)
        console.print(f"[green]✓ Saved favorite configuration: {name}[/green]")
    except Exception as e:
        console.print(f"[red]Failed to save favorite: {e}[/red]")


def load_favorite_config(name: str) -> Optional[dict[str, Any]]:
    """Load a favorite configuration by name.

    Args:
        name: Name of the favorite configuration

    Returns:
        Configuration dictionary, or None if not found
    """
    favorites_path = get_preferences_dir() / "favorites.yaml"

    if not favorites_path.exists():
        return None

    try:
        favorites = _safe_yaml_load(favorites_path) or {}
        return favorites.get(name)

    except (ValueError, OSError):
        return None


def list_favorite_configs() -> dict[str, dict[str, Any]]:
    """List all saved favorite configurations.

    Returns:
        Dictionary of favorite configurations
    """
    favorites_path = get_preferences_dir() / "favorites.yaml"

    if not favorites_path.exists():
        return {}

    try:
        return _safe_yaml_load(favorites_path) or {}
    except (ValueError, OSError):
        return {}


def delete_favorite_config(name: str) -> bool:
    """Delete a favorite configuration.

    Args:
        name: Name of the favorite to delete

    Returns:
        True if deleted successfully, False otherwise
    """
    favorites_path = get_preferences_dir() / "favorites.yaml"

    if not favorites_path.exists():
        return False

    try:
        favorites = _safe_yaml_load(favorites_path) or {}

        if name not in favorites:
            return False

        del favorites[name]

        with open(favorites_path, "w", encoding="utf-8") as f:
            yaml.dump(favorites, f, default_flow_style=False, sort_keys=False)

        return True

    except (ValueError, OSError):
        return False


__all__ = [
    "save_last_run_config",
    "load_last_run_config",
    "clear_last_run_config",
    "format_last_run_summary",
    "save_favorite_config",
    "load_favorite_config",
    "list_favorite_configs",
    "delete_favorite_config",
    "get_preferences_dir",
]
