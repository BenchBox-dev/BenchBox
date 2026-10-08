# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
# This implementation extends the TPC-H specification with skew distributions.

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.tpch_skew.benchmark import TPCHSkewBenchmark
from benchbox.core.tpch_skew.skew_config import SkewConfiguration


class TPCHSkew(BaseBenchmark):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        skew_preset: Optional[str] = None,
        skew_config: Optional[SkewConfiguration] = None,
        **kwargs: Any,
    ) -> None:
        self._validate_scale_factor_type(scale_factor)

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        self._initialize_benchmark_implementation(
            TPCHSkewBenchmark,
            scale_factor,
            output_dir,
            skew_preset=skew_preset,
            skew_config=skew_config,
            **kwargs,
        )

    def generate_data(self) -> list[Union[str, Path]]:
        return self._impl.generate_data()

    def get_queries(self, dialect: Optional[str] = None, base_dialect: Optional[str] = None) -> dict[str, str]:
        return self._impl.get_queries(dialect=dialect, base_dialect=base_dialect)

    def get_query(
        self,
        query_id: int,
        *,
        params: Optional[dict[str, Any]] = None,
        seed: Optional[int] = None,
        scale_factor: Optional[float] = None,
        dialect: Optional[str] = None,
        base_dialect: Optional[str] = None,
        **kwargs,
    ) -> str:
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")

        if scale_factor is not None:
            if not isinstance(scale_factor, (int, float)):
                raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")
            if scale_factor <= 0:
                raise ValueError(f"scale_factor must be positive, got {scale_factor}")

        if seed is not None and not isinstance(seed, int):
            raise TypeError(f"seed must be an integer, got {type(seed).__name__}")

        return self._impl.get_query(
            query_id,
            params=params,
            seed=seed,
            scale_factor=scale_factor,
            dialect=dialect,
            base_dialect=base_dialect,
            **kwargs,
        )

    def get_schema(self) -> dict[str, dict[str, Any]]:
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_skew_info(self) -> dict[str, Any]:
        return self._impl.get_skew_info()

    def manifest_matches_datagen_identity(self, manifest: dict[str, Any]) -> bool:
        return self._impl.manifest_matches_datagen_identity(manifest)

    def get_benchmark_info(self) -> dict[str, Any]:
        return self._impl.get_benchmark_info()

    @property
    def tables(self) -> dict[str, Path]:
        return getattr(self._impl, "tables", {})

    @property
    def skew_preset(self) -> str:
        return self._impl.skew_preset

    @property
    def skew_config(self) -> SkewConfiguration:
        return self._impl.skew_config

    def compare_with_uniform(
        self,
        adapter,
        queries: Optional[list[int]] = None,
        iterations: int = 1,
    ) -> dict[str, Any]:
        return self._impl.compare_with_uniform(
            adapter=adapter,
            queries=queries,
            iterations=iterations,
        )

    @staticmethod
    def get_available_presets() -> list[str]:
        return TPCHSkewBenchmark.get_available_presets()

    @staticmethod
    def get_preset_description(preset_name: str) -> str:
        return TPCHSkewBenchmark.get_preset_description(preset_name)
