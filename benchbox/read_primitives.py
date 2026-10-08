# Copyright 2026 Joe Harris / BenchBox Project

# This benchmark combines queries from multiple sources:

# 1. Apache Impala targeted-perf workload
#    (https://github.com/apache/impala/tree/master/testdata/workloads/targeted-perf)
#    Apache License 2.0, Copyright Apache Software Foundation

# 2. Optimizer sniff test concepts by Justin Jaffray
#    (https://buttondown.com/jaffray/archive/a-sniff-test-for-some-query-optimizers/)

# Data generation uses the TPC-H schema (TPC Benchmark H, Copyright Transaction
# Processing Performance Council).

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.benchmark_mixins import QueryCategoryFacadeMixin, QueryFacadeMixin
from benchbox.core.read_primitives.benchmark import ReadPrimitivesBenchmark


class ReadPrimitives(QueryCategoryFacadeMixin, QueryFacadeMixin, BaseBenchmark):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        verbose = kwargs.pop("verbose", False)
        self._impl = ReadPrimitivesBenchmark(
            scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, **kwargs
        )

    def generate_data(self, tables: Optional[list[str]] = None) -> dict[str, str | list[str]]:
        self._impl.generate_data(tables)
        return self._impl.tables

    def get_schema(self) -> dict[str, dict]:
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def load_data_to_database(self, connection: Any, tables: Optional[list[str]] = None) -> None:
        return self._impl.load_data_to_database(connection, tables)

    def execute_query(self, query_id: str, connection: Any, params: Optional[dict[str, Any]] = None) -> Any:
        return self._impl.execute_query(query_id, connection, params)

    def run_benchmark(
        self,
        connection: Any,
        queries: Optional[list[str]] = None,
        iterations: int = 1,
        categories: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        return self._impl.run_benchmark(connection, queries, iterations, categories)

    def run_category_benchmark(self, connection: Any, category: str, iterations: int = 1) -> dict[str, Any]:
        return self._impl.run_category_benchmark(connection, category, iterations)

    def get_benchmark_info(self) -> dict[str, Any]:
        return self._impl.get_benchmark_info()
