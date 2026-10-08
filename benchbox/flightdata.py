# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.flightdata.benchmark import FlightDataBenchmark


class FlightData(BaseBenchmark):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        end_year: int = 2024,
        **kwargs: Any,
    ) -> None:
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        self._initialize_benchmark_implementation(
            FlightDataBenchmark,
            scale_factor,
            output_dir,
            end_year=end_year,
            **kwargs,
        )

    def generate_data(self) -> list[Union[str, Path]]:
        return self._impl.generate_data()

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        return self._impl.get_queries(dialect)

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        return self._impl.get_query(query_id, params=params, **kwargs)

    def get_schema(self) -> dict[str, Any]:
        return self._impl.get_schema()

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        tuning_config: Any = None,
    ) -> str:
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_benchmark_info(self) -> dict[str, Any]:
        return self._impl.get_benchmark_info()

    def get_query_info(self, query_id: str) -> dict[str, Any]:
        return self._impl.get_query_info(query_id)

    def get_queries_by_category(self, category: str) -> list[str]:
        return self._impl.get_queries_by_category(category)

    def get_download_stats(self) -> dict[str, Any]:
        return self._impl.get_download_stats()

    @property
    def tables(self) -> dict[str, Path]:
        return getattr(self._impl, "tables", {})
