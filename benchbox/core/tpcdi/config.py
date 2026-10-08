# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-DI specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

import logging
import multiprocessing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class TPCDIConfig:
    scale_factor: float = 1.0
    output_dir: Optional[Path] = None

    enable_parallel: bool = False
    max_workers: Optional[int] = None
    chunk_size: int = 10000

    generation_seed: int = 42

    enable_validation: bool = True
    strict_validation: bool = False

    optimize_memory: bool = True
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if self.output_dir is None:
            from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

            self.output_dir = get_benchmark_runs_datagen_path("tpcdi", self.scale_factor)
        else:
            from benchbox.utils.cloud_storage import normalize_output_dir

            self.output_dir = normalize_output_dir(self.output_dir)

        if self.max_workers is None:
            cpu_count = multiprocessing.cpu_count()
            self.max_workers = min(8, cpu_count + 2) if self.enable_parallel else 1
        elif self.max_workers < 1:
            self.max_workers = 1
        elif self.max_workers > 16:
            self.max_workers = 16

        if self.chunk_size < 1000:
            self.chunk_size = 1000
        elif self.chunk_size > 50000:
            self.chunk_size = 50000

        if self.scale_factor <= 0:
            self.scale_factor = 1.0

        log_levels = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        logging.basicConfig(level=log_levels.get(self.log_level.upper(), logging.INFO))

    def get_streaming_config(self) -> dict[str, Any]:
        return {
            "chunk_size": self.chunk_size,
            "max_workers": self.max_workers,
            "enable_parallel": self.enable_parallel,
            "buffer_size": 8192,
        }

    def get_validation_config(self) -> dict[str, Any]:
        return {
            "strict_mode": self.strict_validation,
            "max_violations_per_rule": 1000,
            "enable_cross_table_validation": self.enable_validation,
            "enable_performance_monitoring": True,
        }

    def get_etl_config(self) -> dict[str, Any]:
        return {
            "enable_parallel_extract": self.enable_parallel,
            "enable_parallel_transform": self.enable_parallel,
            "enable_parallel_load": self.enable_parallel,
            "chunk_size": self.chunk_size,
            "max_workers": self.max_workers,
            "worker_timeout": 300.0,
            "memory_optimization": self.optimize_memory,
        }

    def get_batch_config(self) -> dict[str, Any]:
        return {
            "parallel_processing": self.enable_parallel,
            "max_workers": self.max_workers,
            "chunk_size": self.chunk_size,
            "enable_validation": self.enable_validation,
            "strict_mode": self.strict_validation,
        }

    @property
    def source_dir(self) -> Path:
        assert self.output_dir is not None
        return self.output_dir / "source"

    @property
    def staging_dir(self) -> Path:
        assert self.output_dir is not None
        return self.output_dir / "staging"

    @property
    def warehouse_dir(self) -> Path:
        assert self.output_dir is not None
        return self.output_dir / "warehouse"

    def create_directories(self) -> None:
        assert self.output_dir is not None
        directories = [
            self.output_dir,
            self.source_dir,
            self.staging_dir,
            self.warehouse_dir,
            self.output_dir / "logs",
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def get_performance_profile(self) -> str:
        assert self.max_workers is not None
        if not self.enable_parallel:
            return "single_threaded"
        elif self.max_workers <= 2:
            return "light"
        elif self.max_workers <= 4:
            return "standard"
        elif self.max_workers <= 8:
            return "heavy"
        else:
            return "maximum"

    def adjust_for_scale_factor(self) -> None:
        if self.scale_factor >= 10.0:
            self.chunk_size = min(25000, int(self.chunk_size * 1.5))
            self.max_workers = min(16, self.max_workers + 2)
            self.optimize_memory = True
        elif self.scale_factor >= 5.0:
            self.chunk_size = min(20000, int(self.chunk_size * 1.2))
            self.max_workers = min(12, self.max_workers + 1)
        elif self.scale_factor <= 0.1:
            self.chunk_size = max(1000, int(self.chunk_size * 0.5))
            self.max_workers = min(4, self.max_workers)

    def get_memory_settings(self) -> dict[str, Any]:
        if self.optimize_memory:
            return {
                "enable_chunked_processing": True,
                "clear_cache_between_chunks": True,
                "use_memory_efficient_dtypes": True,
                "limit_concurrent_operations": True,
            }
        else:
            return {
                "enable_chunked_processing": False,
                "clear_cache_between_chunks": False,
                "use_memory_efficient_dtypes": False,
                "limit_concurrent_operations": False,
            }

    def to_dict(self) -> dict[str, Any]:
        return {
            "scale_factor": self.scale_factor,
            "output_dir": str(self.output_dir),
            "enable_parallel": self.enable_parallel,
            "max_workers": self.max_workers,
            "chunk_size": self.chunk_size,
            "enable_validation": self.enable_validation,
            "strict_validation": self.strict_validation,
            "optimize_memory": self.optimize_memory,
            "log_level": self.log_level,
            "performance_profile": self.get_performance_profile(),
        }

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> "TPCDIConfig":
        valid_keys = {
            "scale_factor",
            "output_dir",
            "enable_parallel",
            "max_workers",
            "chunk_size",
            "enable_validation",
            "strict_validation",
            "optimize_memory",
            "log_level",
        }

        filtered_dict = {k: v for k, v in config_dict.items() if k in valid_keys}

        if "output_dir" in filtered_dict and isinstance(filtered_dict["output_dir"], str):
            filtered_dict["output_dir"] = Path(filtered_dict["output_dir"])

        return cls(**filtered_dict)

    @classmethod
    def for_development(cls) -> "TPCDIConfig":
        return cls(
            scale_factor=0.1,
            enable_parallel=False,
            max_workers=1,
            chunk_size=1000,
            enable_validation=True,
            strict_validation=False,
            optimize_memory=False,
            log_level="DEBUG",
        )

    @classmethod
    def for_production(cls, scale_factor: float = 1.0) -> "TPCDIConfig":
        config = cls(
            scale_factor=scale_factor,
            enable_parallel=False,
            chunk_size=15000,
            enable_validation=True,
            strict_validation=True,
            optimize_memory=True,
            log_level="INFO",
        )
        config.adjust_for_scale_factor()
        return config

    @classmethod
    def for_performance_testing(cls, scale_factor: float = 1.0) -> "TPCDIConfig":
        return cls(
            scale_factor=scale_factor,
            enable_parallel=False,
            max_workers=multiprocessing.cpu_count(),
            chunk_size=25000,
            enable_validation=False,
            strict_validation=False,
            optimize_memory=True,
            log_level="WARNING",
        )


def get_simple_config(scale_factor: float = 1.0, parallel: bool = True, validation: bool = True) -> TPCDIConfig:
    return TPCDIConfig(
        scale_factor=scale_factor,
        enable_parallel=parallel,
        enable_validation=validation,
    )


def get_fast_config(scale_factor: float = 1.0) -> TPCDIConfig:
    return TPCDIConfig(
        scale_factor=scale_factor,
        enable_parallel=False,
        enable_validation=False,
        strict_validation=False,
        optimize_memory=False,
    )


def get_safe_config(scale_factor: float = 1.0) -> TPCDIConfig:
    return TPCDIConfig(
        scale_factor=scale_factor,
        enable_parallel=False,
        enable_validation=True,
        strict_validation=True,
        optimize_memory=True,
    )
