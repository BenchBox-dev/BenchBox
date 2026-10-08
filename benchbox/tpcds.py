# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-DS specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from benchbox.core.tpcds.generator.manager import TPCDSDataGenerator
    from benchbox.core.tpcds.queries import TPCDSQueryManager

from benchbox.base import BaseBenchmark
from benchbox.core.tpcds.benchmark import TPCDSBenchmark


class TPCDS(BaseBenchmark):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        self._validate_scale_factor_type(scale_factor)

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        self._initialize_benchmark_implementation(TPCDSBenchmark, scale_factor, output_dir, **kwargs)

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
        **kwargs,
    ) -> str:
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 99):
            raise ValueError(f"Query ID must be 1-99, got {query_id}")

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
            **kwargs,
        )

    @property
    def queries(self) -> "TPCDSQueryManager":
        return self._impl.query_manager

    @property
    def generator(self) -> "TPCDSDataGenerator":
        return self._impl.data_generator

    def get_available_tables(self) -> list[str]:
        return self._impl.get_available_tables()

    def get_available_queries(self) -> list[int]:
        return self._impl.get_available_queries()

    def generate_table_data(self, table_name: str, output_dir: Optional[str] = None) -> str:
        return self._impl.generate_table_data(table_name, output_dir)

    def get_schema(self) -> list[dict]:
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def generate_streams(
        self,
        num_streams: int = 1,
        rng_seed: Optional[int] = None,
        streams_output_dir: Optional[Union[str, Path]] = None,
    ) -> list[Path]:
        return self._impl.generate_streams(
            num_streams=num_streams,
            rng_seed=rng_seed,
            streams_output_dir=streams_output_dir,
        )

    def get_stream_info(self, stream_id: int) -> dict[str, Any]:
        return self._impl.get_stream_info(stream_id)

    def get_all_streams_info(self) -> list[dict[str, Any]]:
        return self._impl.get_all_streams_info()

    def get_benchmark_info(self) -> dict[str, Any]:
        return self._impl.get_benchmark_info()
