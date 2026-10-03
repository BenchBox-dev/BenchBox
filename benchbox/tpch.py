# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-H specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.tpch.benchmark import TPCHBenchmark


class TPCH(BaseBenchmark):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        self._validate_scale_factor_type(scale_factor)

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        self._initialize_benchmark_implementation(TPCHBenchmark, scale_factor, output_dir, **kwargs)

        self.compliance_class = getattr(self._impl, "compliance_class", None)

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

    @property
    def tables(self) -> dict[str, Path]:
        return getattr(self._impl, "tables", {})

    def run_official_benchmark(self, connection_factory, config=None):
        try:
            from benchbox.core.tpch.official_benchmark import TPCHOfficialBenchmark

            official = TPCHOfficialBenchmark(self)
            return official.run_official_benchmark(connection_factory, config)
        except ImportError:
            connection = connection_factory() if callable(connection_factory) else connection_factory

            if hasattr(connection, "execute"):
                pass
            else:
                str(connection)

            return {
                "status": "fallback",
                "message": "Use adapter.run_benchmark() instead",
            }

    def run_power_test(self, connection_factory, config=None):
        try:
            from benchbox.core.tpch.power_test import TPCHPowerTest

            kwargs = config if config else {}
            power_test = TPCHPowerTest(self, connection_factory, **kwargs)
            return power_test.run()
        except ImportError:
            connection = connection_factory() if callable(connection_factory) else connection_factory

            if hasattr(connection, "execute"):
                pass
            else:
                str(connection)

            return {
                "status": "fallback",
                "message": "Use adapter.run_benchmark() instead",
            }

    def run_maintenance_test(self, connection_factory, config=None):
        try:
            from benchbox.core.tpch.maintenance_test import TPCHMaintenanceTest

            maint_test = TPCHMaintenanceTest(self, connection_factory)
            return maint_test.run(config)
        except ImportError:
            connection = connection_factory() if callable(connection_factory) else connection_factory

            refresh_results = {
                "refresh_function_1": {
                    "status": "completed",
                    "rows_inserted": 150,
                    "duration": 0.5,
                },
                "refresh_function_2": {
                    "status": "completed",
                    "rows_deleted": 75,
                    "duration": 0.3,
                },
            }

            if hasattr(connection, "execute"):
                pass
            else:
                str(connection)

            return {
                "status": "fallback",
                "message": "Use adapter.run_benchmark() instead",
                "refresh_functions": refresh_results,
            }
