# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.joinorder.benchmark import JoinOrderBenchmark


class JoinOrder(BaseBenchmark):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        verbose = kwargs.pop("verbose", False)
        self._impl = JoinOrderBenchmark(scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, **kwargs)

    def generate_data(self) -> list[Path]:
        return self._impl.generate_data()

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        return self._impl.get_queries(dialect=dialect)

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: Optional[dict[str, Any]] = None,
        dialect: Optional[str] = None,
    ) -> str:
        return self._impl.get_query(query_id, params=params, dialect=dialect)

    def get_schema(self, dialect: str = "sqlite") -> str:
        return self._impl.get_create_tables_sql(dialect=dialect)

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config: Any = None) -> str:
        return self._impl.get_create_tables_sql(dialect=dialect)


__all__ = ["JoinOrder"]
