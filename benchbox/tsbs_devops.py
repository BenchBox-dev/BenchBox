# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.tsbs_devops.benchmark import TSBSDevOpsBenchmark


class TSBSDevOps(BaseBenchmark):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        num_hosts: Optional[int] = None,
        duration_days: Optional[int] = None,
        interval_seconds: int = 10,
        **kwargs: Any,
    ) -> None:
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        self._initialize_benchmark_implementation(
            TSBSDevOpsBenchmark,
            scale_factor,
            output_dir,
            num_hosts=num_hosts,
            duration_days=duration_days,
            interval_seconds=interval_seconds,
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
        **kwargs,
    ) -> str:
        return self._impl.get_query(query_id, params=params, **kwargs)

    def get_schema(self) -> dict[str, dict[str, Any]]:
        return self._impl.get_schema()

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        tuning_config: Any = None,
    ) -> str:
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_benchmark_info(self) -> dict[str, Any]:
        return self._impl.get_benchmark_info()

    @property
    def tables(self) -> dict[str, Path]:
        return getattr(self._impl, "tables", {})

    @property
    def num_hosts(self) -> int:
        return self._impl.num_hosts

    @property
    def duration_days(self) -> int:
        return self._impl.duration_days

    @property
    def interval_seconds(self) -> int:
        return self._impl.interval_seconds

    def get_query_info(self, query_id: str) -> dict[str, Any]:
        return self._impl.get_query_info(query_id)

    def get_queries_by_category(self, category: str) -> list[str]:
        return self._impl.get_queries_by_category(category)

    def get_generation_stats(self) -> dict:
        return self._impl.get_generation_stats()
