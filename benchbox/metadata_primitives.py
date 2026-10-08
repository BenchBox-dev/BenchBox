# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.benchmark_mixins import QueryCategoryFacadeMixin, QueryFacadeMixin
from benchbox.core.metadata_primitives.benchmark import (
    ComplexityBenchmarkResult,
    MetadataBenchmarkResult,
    MetadataPrimitivesBenchmark,
    MetadataQueryResult,
)
from benchbox.core.metadata_primitives.complexity import (
    GeneratedMetadata,
    MetadataComplexityConfig,
)


class MetadataPrimitives(QueryCategoryFacadeMixin, QueryFacadeMixin, BaseBenchmark):
    SKIP_DATA_LOADING = True

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        self._impl = MetadataPrimitivesBenchmark(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

    def generate_data(self, tables: Optional[list[str]] = None) -> dict[str, str]:
        return self._impl.generate_data(tables)

    def get_schema(self) -> dict[str, dict[str, Any]]:
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config: Any = None) -> str:
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_table_names(self) -> list[str]:
        return self._impl.get_table_names()

    def execute_query(
        self,
        query_id: str,
        connection: Any,
        dialect: Optional[str] = None,
    ) -> MetadataQueryResult:
        return self._impl.execute_query(query_id, connection, dialect=dialect)

    def run_benchmark(
        self,
        connection: Any,
        dialect: Optional[str] = None,
        categories: Optional[list[str]] = None,
        query_ids: Optional[list[str]] = None,
        iterations: int = 1,
    ) -> MetadataBenchmarkResult:
        return self._impl.run_benchmark(
            connection, dialect=dialect, categories=categories, query_ids=query_ids, iterations=iterations
        )

    def setup_complexity(
        self,
        connection: Any,
        dialect: str,
        config: Union[MetadataComplexityConfig, str],
    ) -> GeneratedMetadata:
        return self._impl.setup_complexity(connection, dialect, config)

    def teardown_complexity(
        self,
        connection: Any,
        dialect: str,
        generated: GeneratedMetadata,
    ) -> None:
        return self._impl.teardown_complexity(connection, dialect, generated)

    def run_complexity_benchmark(
        self,
        connection: Any,
        dialect: str,
        config: Union[MetadataComplexityConfig, str],
        iterations: int = 1,
        categories: Optional[list[str]] = None,
    ) -> ComplexityBenchmarkResult:
        return self._impl.run_complexity_benchmark(
            connection, dialect, config, iterations=iterations, categories=categories
        )

    def get_complexity_categories(self) -> list[str]:
        return self._impl.get_complexity_categories()

    def get_benchmark_info(self) -> dict[str, Any]:
        return {
            "name": "Metadata Primitives Benchmark",
            "version": "1.0",
            "description": "Tests database catalog introspection performance",
            "query_count": len(self._impl.get_queries()),
            "categories": self._impl.get_query_categories(),
            "complexity_categories": self._impl.get_complexity_categories(),
        }
