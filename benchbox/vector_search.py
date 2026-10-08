# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.vector_search.benchmark import VectorSearchBenchmark


class VectorSearch(BaseBenchmark):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        *,
        dimensions: int = 128,
        **kwargs: Any,
    ) -> None:
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)
        self._initialize_benchmark_implementation(
            VectorSearchBenchmark,
            scale_factor,
            output_dir,
            dimensions=dimensions,
            **kwargs,
        )

    def generate_data(
        self,
        tables: Optional[list[str]] = None,
        output_format: str = "memory",
    ) -> dict[str, Any]:
        return self._impl.data_generator.generate_data(tables)

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: Optional[dict[str, Any]] = None,
    ) -> str:
        return self._impl.get_query(query_id, params=params)

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        return self._impl.get_queries(dialect=dialect)

    def get_all_queries(self) -> dict[str, str]:
        return self._impl.get_all_queries()

    def validate_query_result(self, query_id: Union[int, str], rows: Sequence[Sequence[object]]) -> None:
        self._impl.validate_query_result(query_id, rows)

    def get_schema(self, dialect: str = "duckdb") -> dict[str, dict]:
        return self._impl.get_schema(dialect)

    def get_create_tables_sql(
        self,
        dialect: str = "duckdb",
        tuning_config: Any = None,
    ) -> str:
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)
