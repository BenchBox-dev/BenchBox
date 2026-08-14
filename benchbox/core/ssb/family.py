"""Star Schema Benchmark family plugin.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SSBFamily:
    """Registry-backed SSB plugin. Not a BaseBenchmark subclass."""

    benchmark_id: str = "ssb"

    @property
    def core_class(self) -> type[Any]:
        from benchbox.core.ssb.benchmark import SSBBenchmark

        return SSBBenchmark

    @property
    def public_class_name(self) -> str | None:
        from benchbox.core.benchmark_registry import get_benchmark_class_name

        return get_benchmark_class_name(self.benchmark_id)

    @property
    def surface(self) -> str:
        from benchbox.core.benchmark_registry import get_benchmark_surface

        return get_benchmark_surface(self.benchmark_id)

    def default_scale(self, scale_factor: float | None = None) -> float:
        from benchbox.core.benchmark_registry import get_benchmark_default_scale, validate_scale_factor

        resolved = get_benchmark_default_scale(self.benchmark_id) if scale_factor is None else float(scale_factor)
        validate_scale_factor(self.benchmark_id, resolved)
        return resolved

    def create(self, config: Any, system_profile: Any) -> Any:
        from benchbox.core.benchmark_loader import instantiate_benchmark_class

        cpu_cores = 1
        if system_profile is not None:
            cpu_cores = getattr(system_profile, "cpu_cores_logical", 1)
        required_kwargs = {
            "scale_factor": self.default_scale(config.scale_factor),
            "compress_data": config.compress_data,
            "compression_type": config.compression_type,
            "compression_level": config.compression_level,
        }
        return instantiate_benchmark_class(self.core_class, required_kwargs, {"parallel": cpu_cores})

    def phases(self) -> tuple[str, ...]:
        return ("generate", "load", "execute")

    def result_metadata(self) -> dict[str, Any]:
        return {
            "benchmark": "Star Schema Benchmark",
            "query_count": 13,
            "query_flights": 4,
            "supports_streams": False,
            "supports_dataframe": True,
        }
