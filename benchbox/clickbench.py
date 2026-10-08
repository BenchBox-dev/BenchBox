# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.clickbench.benchmark import ClickBenchBenchmark


class ClickBench(BaseBenchmark):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs,
    ) -> None:
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        self._initialize_benchmark_implementation(ClickBenchBenchmark, scale_factor, output_dir, **kwargs)

    def generate_data(self) -> list[Union[str, Path]]:
        result = self._impl.generate_data()
        return list(result.values()) if isinstance(result, dict) else result

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        return self._impl.get_queries(dialect=dialect)

    def get_query(self, query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None) -> str:
        return self._impl.get_query(query_id, params=params)

    def get_schema(self) -> list[dict]:
        schema_dict = self._impl.get_schema()
        return list(schema_dict.values())

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def translate_query(self, query_id: str, dialect: str) -> str:
        return super().translate_query(query_id, dialect)

    def get_query_categories(self) -> dict[str, list[str]]:
        return self._impl.get_query_categories()
