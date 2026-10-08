# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.datavault.benchmark import DataVaultBenchmark


class DataVault(BaseBenchmark):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        self._validate_scale_factor_type(scale_factor)

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        self._initialize_benchmark_implementation(DataVaultBenchmark, scale_factor, output_dir, **kwargs)

    def generate_data(self) -> dict[str, Any]:
        return self._impl.generate_data()

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        queries = self._impl.get_all_queries()
        if not dialect:
            return queries
        return {k: self._impl.translate_for_dialect(v, dialect) for k, v in queries.items()}

    def get_query(
        self,
        query_id: int,
        *,
        params: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")

        return self._impl.get_query(query_id, dialect=kwargs.get("dialect"))

    def get_schema(self) -> dict[str, Any]:
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config: Any = None) -> str:
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_table_loading_order(self, available_tables: Optional[list[str]] = None) -> list[str]:
        return self._impl.get_table_loading_order(available_tables)

    @property
    def tables(self) -> dict[str, Path]:
        return getattr(self._impl, "tables", {})

    @property
    def table_count(self) -> int:
        return self._impl.get_table_count()

    @property
    def query_count(self) -> int:
        return 22
