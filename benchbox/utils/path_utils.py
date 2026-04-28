"""Core path utilities without CLI dependencies.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import os
from pathlib import Path

from benchbox.core.runtime_paths import (
    DEFAULT_BENCHMARK_RUNS_ROOT,
    resolve_benchmark_runs_root,
)
from benchbox.utils.scale_factor import format_scale_factor


def get_default_data_directory() -> Path:
    """Get default data directory for BenchBox."""
    # Try environment variable first
    value = os.environ.get("BENCHBOX_DATA_DIR")
    if value:
        return Path(value)

    # Use current directory data/ subdirectory
    return Path.cwd() / "data"


def resolve_benchmark_runs_dir() -> Path:
    """Return the resolved ``benchmark_runs/`` root.

    Honors ``BENCHBOX_OUTPUT_DIR``; otherwise anchors the historical
    ``benchmark_runs`` default to :func:`Path.cwd` so callers using the result
    for filesystem operations get an absolute path.
    """
    root = resolve_benchmark_runs_root(env=os.environ)
    if root == DEFAULT_BENCHMARK_RUNS_ROOT:
        return Path.cwd() / DEFAULT_BENCHMARK_RUNS_ROOT
    return root


def get_benchmark_runs_datagen_path(
    benchmark_name: str,
    scale_factor: float,
    base_dir: str | Path | None = None,
) -> Path:
    """Get the canonical benchmark_runs/datagen directory for a benchmark.

    Args:
        benchmark_name: Normalized benchmark identifier (e.g., "tpch").
        scale_factor: Scale factor used for data generation.
        base_dir: Optional override for the datagen root. When omitted, the
            root is resolved via :func:`resolve_benchmark_runs_dir` so
            ``BENCHBOX_OUTPUT_DIR`` redirects datagen output alongside results.

    Returns:
        Path pointing to ``<root>/datagen/{benchmark_name}_{sf}`` where
        ``sf`` is rendered via :func:`format_scale_factor`.
    """

    base = Path(base_dir) if base_dir is not None else resolve_benchmark_runs_dir() / "datagen"
    sf_fragment = format_scale_factor(scale_factor)
    return base / f"{benchmark_name}_{sf_fragment}"


def get_benchmark_runs_databases_path(
    benchmark_name: str,
    scale_factor: float,
    base_dir: str | Path | None = None,
) -> Path:
    """Get the canonical benchmark_runs/databases path for local DB artifacts.

    Args:
        benchmark_name: Normalized benchmark identifier (e.g., "tpch").
        scale_factor: Scale factor used for data generation.
        base_dir: Optional override for the databases root. When omitted, the
            root is resolved via :func:`resolve_benchmark_runs_dir` so
            ``BENCHBOX_OUTPUT_DIR`` redirects local DB artifacts alongside
            results.

    Returns:
        Path pointing to ``<root>/databases/{benchmark_name}_{sf}`` where
        ``sf`` is rendered via :func:`format_scale_factor`.
    """
    base = Path(base_dir) if base_dir is not None else resolve_benchmark_runs_dir() / "databases"
    sf_fragment = format_scale_factor(scale_factor)
    return base / f"{benchmark_name}_{sf_fragment}"


def get_benchmark_runs_dataframe_path(base_dir: str | Path | None = None) -> Path:
    """Get the canonical benchmark_runs/datagen directory for DataFrame cached data.

    DataFrame cached data lives alongside SQL datagen output under the unified
    ``<root>/datagen/`` directory, enabling efficient reuse of generated data
    across execution modes. The root honors ``BENCHBOX_OUTPUT_DIR``.
    """
    if base_dir is not None:
        return Path(base_dir)
    return resolve_benchmark_runs_dir() / "datagen"


def get_results_path(benchmark_name: str, timestamp: str, base_dir: str | Path | None = None) -> Path:
    """Get results path for a benchmark run.

    Args:
        benchmark_name: Name of the benchmark
        timestamp: Timestamp string for the run
        base_dir: Base directory (defaults to get_default_data_directory())

    Returns:
        Path for results storage
    """
    base_dir = get_default_data_directory() if base_dir is None else Path(base_dir)

    # Create path: {base_dir}/results/{benchmark}_{timestamp}
    results_dir = base_dir / "results" / f"{benchmark_name}_{timestamp}"
    return results_dir


def ensure_directory(path: str | Path) -> Path:
    """Ensure directory exists, create if needed.

    Args:
        path: Directory path to ensure

    Returns:
        Path object for the directory
    """
    path_obj = Path(path)
    path_obj.mkdir(parents=True, exist_ok=True)
    return path_obj
