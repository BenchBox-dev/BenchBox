"""Benchmark loading functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import importlib
from typing import Any

from benchbox.core.benchmark_registry import (
    get_core_benchmark_class_name,
    list_loader_benchmark_ids,
    validate_scale_factor,
)
from benchbox.core.schemas import BenchmarkConfig, SystemProfile


def get_benchmark_instance(config: BenchmarkConfig, system_profile: SystemProfile | None) -> Any:
    """Get benchmark instance based on configuration."""
    validate_scale_factor(config.name, config.scale_factor)
    benchmark_class = get_benchmark_class(config.name)

    cpu_cores = 1
    if system_profile:
        cpu_cores = getattr(system_profile, "cpu_cores_logical", 1)

    benchmark_kwargs = {
        "scale_factor": config.scale_factor,
        "compress_data": config.compress_data,
        "compression_type": config.compression_type,
        "compression_level": config.compression_level,
    }

    options = getattr(config, "options", {}) or {}
    force_regenerate = bool(options.get("force_regenerate"))
    benchmark_id = config.name.lower()
    if benchmark_id == "tpcds":
        return benchmark_class(
            parallel=cpu_cores,
            force_regenerate=force_regenerate,
            **benchmark_kwargs,
        )
    elif benchmark_id in {"joinorder", "joinorder_synthetic"}:
        try:
            return benchmark_class(
                parallel=cpu_cores,
                force_regenerate=force_regenerate,
                **benchmark_kwargs,
            )
        except TypeError:
            return benchmark_class(**benchmark_kwargs)
    else:
        try:
            return benchmark_class(parallel=cpu_cores, **benchmark_kwargs)
        except TypeError:
            return benchmark_class(**benchmark_kwargs)


def get_benchmark_class(benchmark_name: str) -> Any:
    """Dynamically load benchmark class using importlib."""
    benchmark_name = benchmark_name.lower()
    module_name = f"benchbox.core.{benchmark_name}.benchmark"
    class_name = get_core_benchmark_class_name(benchmark_name) or f"{benchmark_name.capitalize()}Benchmark"

    try:
        module = importlib.import_module(module_name)
        benchmark_class = getattr(module, class_name)
        return benchmark_class
    except (ImportError, AttributeError) as e:
        available = list_loader_benchmark_ids()
        raise ValueError(f"Benchmark '{benchmark_name}' not supported yet. Available: {', '.join(available)}") from e
