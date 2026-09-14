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
from pathlib import Path
from typing import Any, Union

from benchbox.core.benchmark_registry import (
    get_core_benchmark_class_name,
    get_family_plugin,
    list_loader_benchmark_ids,
    validate_scale_factor,
)
from benchbox.core.schemas import BenchmarkConfig, SystemProfile

BENCHMARK_LOADER_API_SURFACE = "internal"


# Benchmarks whose result carries a compliance classification. Only these accept
# `official`; passing it wholesale is unsafe because constructor_accepts_argument()
# is satisfied by a bare **kwargs, so any benchmark with one would swallow it.
COMPLIANCE_GATED_BENCHMARKS = frozenset({"tpcds"})


def compliance_mode_kwargs(config: BenchmarkConfig) -> dict[str, Any]:
    """Return constructor kwargs that carry compliance mode for *config*.

    Both construction paths -- :func:`get_benchmark_instance` and the CLI
    orchestrator's own builder -- must apply this. A run that does not receive
    `official` classifies as ``unofficial_nonstandard`` and is then refused by
    ``benchbox submit``, so dropping it silently makes results unpublishable.
    """
    if config.name.lower() not in COMPLIANCE_GATED_BENCHMARKS:
        return {}
    return {"official": bool(getattr(config, "official", False))}


def get_benchmark_instance(
    config: BenchmarkConfig,
    system_profile: SystemProfile | None = None,
    *,
    benchmark_class: type[Any] | None = None,
    output_dir: Union[str, Path] | None = None,
    verbose: Union[int, bool] | None = None,
    quiet: bool | None = None,
    benchmark_options: dict[str, Any] | None = None,
    extra_kwargs: dict[str, Any] | None = None,
    instantiate_fn: Any | None = None,
) -> Any:
    """Get benchmark instance based on configuration."""
    if benchmark_class is None:
        validate_scale_factor(config.name, config.scale_factor)
        plugin = get_family_plugin(config.name)
        if plugin is not None:
            return plugin.create(config, system_profile)
        benchmark_class = get_core_benchmark_class(config.name)

    cpu_cores = 1
    if system_profile:
        cpu_cores = getattr(system_profile, "cpu_cores_logical", 1)

    benchmark_kwargs: dict[str, Any] = {
        "scale_factor": getattr(config, "scale_factor", 1.0),
        "compress_data": getattr(config, "compress_data", False),
        "compression_type": getattr(config, "compression_type", None),
        "compression_level": getattr(config, "compression_level", None),
    }

    opts = getattr(config, "options", {}) or {}
    optional_kwargs: dict[str, Any] = {"parallel": cpu_cores}

    if output_dir is not None:
        optional_kwargs["output_dir"] = output_dir

    if verbose is not None:
        optional_kwargs["verbose"] = verbose
    if quiet is not None:
        optional_kwargs["quiet"] = quiet

    force_regenerate = bool(opts.get("force_regenerate"))
    benchmark_id = config.name.lower()
    if benchmark_id in {"tpcds", "joinorder", "joinorder_synthetic"}:
        optional_kwargs["force_regenerate"] = force_regenerate

    # Forward benchmark-specific options
    options_to_forward = (
        dict(benchmark_options) if benchmark_options is not None else dict(opts.get("benchmark_options", {}))
    )
    optional_kwargs.update(options_to_forward)

    if extra_kwargs:
        optional_kwargs.update(extra_kwargs)

    optional_kwargs.update(compliance_mode_kwargs(config))

    instantiate = instantiate_fn or instantiate_benchmark_class
    return instantiate(benchmark_class, benchmark_kwargs, optional_kwargs)


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
    if argument_name in parameters:
        return True
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        try:
            from unittest.mock import NonCallableMock

            if isinstance(benchmark_class, NonCallableMock) or (
                isinstance(benchmark_class, type) and issubclass(benchmark_class, NonCallableMock)
            ):
                return True
        except (ImportError, TypeError):
            pass
    return False


def get_core_benchmark_class(benchmark_name: str) -> Any:
    """Dynamically load benchmark class using importlib."""
    benchmark_name = benchmark_name.lower()
    plugin = get_family_plugin(benchmark_name)
    if plugin is not None:
        return plugin.core_class
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
