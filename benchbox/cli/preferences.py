# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from benchbox.utils.printing import quiet_console

console = quiet_console

MAX_YAML_SIZE_BYTES = 1024 * 1024


def _safe_yaml_load(file_path: Path) -> Optional[dict[str, Any]]:
    try:
        file_size = file_path.stat().st_size
        if file_size > MAX_YAML_SIZE_BYTES:
            raise ValueError(f"Configuration file too large ({file_size} bytes, max {MAX_YAML_SIZE_BYTES})")

        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is not None and not isinstance(data, dict):
            raise ValueError(f"Expected dictionary, got {type(data).__name__}")

        return data

    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML format: {e}") from e


def get_preferences_dir() -> Path:
    preferences_dir = Path.home() / ".benchbox"
    preferences_dir.mkdir(parents=True, exist_ok=True)
    return preferences_dir


def get_last_run_path() -> Path:
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
    queries: Optional[list[str]] = None,
    mode: Optional[str] = None,
    seed: Optional[int] = None,
    iterations: Optional[int] = None,
    non_replayable_options: Optional[list[str]] = None,
    output: Optional[str] = None,
    additional_options: Optional[dict[str, Any]] = None,
) -> None:
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
        "queries": queries,
        "mode": mode,
        "seed": seed,
        "iterations": iterations,
        "replay_schema_version": 1,
        "non_replayable_options": sorted(set(non_replayable_options or [])),
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
        console.print(f"[dim yellow]Warning: Could not save last run config: {e}[/dim yellow]")


def load_last_run_config() -> Optional[dict[str, Any]]:
    last_run_path = get_last_run_path()

    if not last_run_path.exists():
        return None

    try:
        config = _safe_yaml_load(last_run_path)

        if config is None:
            return None

        required_fields = ["database", "benchmark", "scale"]
        if not all(field in config for field in required_fields):
            return None

        return config

    except (ValueError, OSError) as e:
        console.print(f"[dim yellow]Warning: Could not load last run config: {e}[/dim yellow]")
        return None


def clear_last_run_config() -> None:
    last_run_path = get_last_run_path()

    if last_run_path.exists():
        try:
            last_run_path.unlink()
        except Exception as e:
            console.print(f"[dim yellow]Warning: Could not clear last run config: {e}[/dim yellow]")


def _is_safe_tuning_path(tuning_path: str) -> bool:
    try:
        path = Path(tuning_path)

        if path.suffix not in [".yaml", ".yml"]:
            return False

        resolved = path.resolve()

        cwd = Path.cwd().resolve()

        allowed_dirs = [
            cwd,
            cwd / "examples",
        ]

        for allowed_dir in allowed_dirs:
            try:
                resolved.relative_to(allowed_dir)
                return resolved.exists()
            except ValueError:
                continue

        return False

    except (OSError, RuntimeError):
        return False


def _format_relative_time(iso_timestamp: str) -> Optional[str]:
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
    if tuning == "tuned":
        return "tuned"
    elif tuning == "notuning":
        return "baseline"
    elif _is_safe_tuning_path(tuning):
        return "custom config"
    else:
        return tuning


def format_last_run_summary(config: dict[str, Any]) -> str:
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

    iterations = config.get("iterations")
    if iterations is not None:
        parts.append(f"{iterations} power iterations")

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
    favorites_path = get_preferences_dir() / "favorites.yaml"

    favorites = {}
    if favorites_path.exists():
        try:
            favorites = _safe_yaml_load(favorites_path) or {}
        except (ValueError, OSError):
            pass

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

    try:
        with open(favorites_path, "w", encoding="utf-8") as f:
            yaml.dump(favorites, f, default_flow_style=False, sort_keys=False)
        console.print(f"[green]✓ Saved favorite configuration: {name}[/green]")
    except Exception as e:
        console.print(f"[red]Failed to save favorite: {e}[/red]")


def load_favorite_config(name: str) -> Optional[dict[str, Any]]:
    favorites_path = get_preferences_dir() / "favorites.yaml"

    if not favorites_path.exists():
        return None

    try:
        favorites = _safe_yaml_load(favorites_path) or {}
        return favorites.get(name)

    except (ValueError, OSError):
        return None


def list_favorite_configs() -> dict[str, dict[str, Any]]:
    favorites_path = get_preferences_dir() / "favorites.yaml"

    if not favorites_path.exists():
        return {}

    try:
        return _safe_yaml_load(favorites_path) or {}
    except (ValueError, OSError):
        return {}


def delete_favorite_config(name: str) -> bool:
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
