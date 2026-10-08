# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import os
from pathlib import Path

from benchbox.core.runtime_paths import (
    default_benchmark_runs_root as _default_benchmark_runs_root,
    resolve_benchmark_runs_root,
)
from benchbox.utils.scale_factor import format_scale_factor


def get_default_data_directory() -> Path:

    value = os.environ.get("BENCHBOX_DATA_DIR")
    if value:
        return Path(value)

    return Path.cwd() / "data"


def find_work_tree_root(start: Path | None = None) -> Path | None:

    origin = Path.cwd() if start is None else Path(start).resolve()
    for candidate in (origin, *origin.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def default_benchmark_runs_root(start: Path | None = None) -> Path:

    return _default_benchmark_runs_root(start)


def resolve_benchmark_runs_dir() -> Path:

    return resolve_benchmark_runs_root(env=os.environ)


def get_benchmark_runs_datagen_path(
    benchmark_name: str,
    scale_factor: float,
    base_dir: str | Path | None = None,
) -> Path:

    base = Path(base_dir) if base_dir is not None else resolve_benchmark_runs_dir() / "datagen"
    sf_fragment = format_scale_factor(scale_factor)
    return base / f"{benchmark_name}_{sf_fragment}"


def get_benchmark_runs_databases_path(
    benchmark_name: str,
    scale_factor: float,
    base_dir: str | Path | None = None,
) -> Path:

    base = Path(base_dir) if base_dir is not None else resolve_benchmark_runs_dir() / "databases"
    sf_fragment = format_scale_factor(scale_factor)
    return base / f"{benchmark_name}_{sf_fragment}"


def get_benchmark_runs_dataframe_path(base_dir: str | Path | None = None) -> Path:

    if base_dir is not None:
        return Path(base_dir)
    return resolve_benchmark_runs_dir() / "datagen"


def get_results_path(benchmark_name: str, timestamp: str, base_dir: str | Path | None = None) -> Path:

    base_dir = get_default_data_directory() if base_dir is None else Path(base_dir)

    results_dir = base_dir / "results" / f"{benchmark_name}_{timestamp}"
    return results_dir


def ensure_directory(path: str | Path) -> Path:

    path_obj = Path(path)
    path_obj.mkdir(parents=True, exist_ok=True)
    return path_obj
