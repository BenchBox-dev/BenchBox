"""Benchmark loading functionality.

This module is an internal runtime loader. Public callers should use the CLI,
top-level benchmark wrappers, or ``benchbox.base.BaseBenchmark`` orchestration
hooks instead of importing loader internals directly.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any

from benchbox.core.benchmark_registry import (
    get_core_benchmark_class_name,
    list_loader_benchmark_ids,
    validate_scale_factor,
)
from benchbox.core.schemas import BenchmarkConfig, SystemProfile

BENCHMARK_LOADER_API_SURFACE = "internal"


def get_benchmark_instance(config: BenchmarkConfig, system_profile: SystemProfile | None) -> Any:
    """Get benchmark instance based on configuration."""
    validate_scale_factor(config.name, config.scale_factor)
    benchmark_class = get_core_benchmark_class(config.name)

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
    optional_kwargs = {"parallel": cpu_cores}
    if benchmark_id in {"tpcds", "joinorder", "joinorder_synthetic"}:
        optional_kwargs["force_regenerate"] = force_regenerate

    return instantiate_benchmark_class(benchmark_class, benchmark_kwargs, optional_kwargs)


def instantiate_benchmark_class(
    benchmark_class: type[Any],
    required_kwargs: dict[str, Any],
    optional_kwargs: dict[str, Any],
) -> Any:
    """Instantiate a benchmark class with only supported optional constructor kwargs."""
    constructor_kwargs = dict(required_kwargs)
    for name, value in optional_kwargs.items():
        if constructor_accepts_argument(benchmark_class, name):
            constructor_kwargs[name] = value
    return benchmark_class(**constructor_kwargs)


def constructor_accepts_argument(benchmark_class: type[Any], argument_name: str) -> bool:
    """Return whether a benchmark constructor accepts a named argument."""
    try:
        parameters = inspect.signature(benchmark_class).parameters
    except (TypeError, ValueError):
        return False
    return argument_name in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )


def get_core_benchmark_class(benchmark_name: str) -> Any:
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


def get_benchmark_class(benchmark_name: str) -> Any:
    """Compatibility alias for :func:`get_core_benchmark_class`."""
    return get_core_benchmark_class(benchmark_name)
