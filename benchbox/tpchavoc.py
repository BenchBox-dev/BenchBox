# Copyright 2026 Joe Harris / BenchBox Project

# This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark


class TPCHavoc(BaseBenchmark):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        if not isinstance(scale_factor, (int, float)):
            raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")
        if scale_factor <= 0:
            raise ValueError(f"scale_factor must be positive, got {scale_factor}")

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        verbose = kwargs.pop("verbose", False)
        self._impl = TPCHavocBenchmark(scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, **kwargs)

    def generate_data(self) -> list[Union[str, Path]]:
        return self._impl.generate_data()

    def get_platform_skip_queries(self, platform_name: str) -> list[str]:
        return self._impl.get_platform_skip_queries(platform_name)

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        return self._impl.get_queries(dialect=dialect)

    def get_query(
        self,
        query_id,
        *,
        params: Optional[dict[str, Any]] = None,
        seed: Optional[int] = None,
        scale_factor: Optional[float] = None,
        dialect: Optional[str] = None,
        base_dialect: Optional[str] = None,
        **kwargs,
    ) -> str:
        if isinstance(query_id, int):
            if not (1 <= query_id <= 22):
                raise ValueError(f"Query ID must be 1-22, got {query_id}")
        elif isinstance(query_id, str):
            if "_v" not in query_id:
                raise ValueError(f"String query ID must be in format 'Q_VID' (e.g., '1_v1'), got {query_id}")
        else:
            raise TypeError(f"query_id must be an integer or string, got {type(query_id).__name__}")

        if scale_factor is not None:
            if not isinstance(scale_factor, (int, float)):
                raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")
            if scale_factor <= 0:
                raise ValueError(f"scale_factor must be positive, got {scale_factor}")

        if seed is not None and not isinstance(seed, int):
            raise TypeError(f"seed must be an integer, got {type(seed).__name__}")

        return self._impl.get_query(
            query_id,
            seed=seed,
            scale_factor=scale_factor,
            dialect=dialect,
            base_dialect=base_dialect,
            **kwargs,
        )

    def get_query_variant(self, query_id: int, variant_id: int, params: Optional[dict[str, Any]] = None) -> str:
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not isinstance(variant_id, int):
            raise TypeError(f"variant_id must be an integer, got {type(variant_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")
        if not (1 <= variant_id <= 10):
            raise ValueError(f"Variant ID must be 1-10, got {variant_id}")

        return self._impl.get_query_variant(query_id, variant_id, params)

    def get_all_variants(self, query_id: int) -> dict[int, str]:
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")

        return self._impl.get_all_variants(query_id)

    def get_variant_description(self, query_id: int, variant_id: int) -> str:
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not isinstance(variant_id, int):
            raise TypeError(f"variant_id must be an integer, got {type(variant_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")
        if not (1 <= variant_id <= 10):
            raise ValueError(f"Variant ID must be 1-10, got {variant_id}")

        return self._impl.get_variant_description(query_id, variant_id)

    def get_implemented_queries(self) -> list[int]:
        return self._impl.get_implemented_queries()

    def get_all_variants_info(self, query_id: int) -> dict[int, dict[str, str]]:
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")

        return self._impl.get_all_variants_info(query_id)

    def get_schema(self) -> dict[str, dict[str, Any]]:
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_benchmark_info(self) -> dict[str, Any]:
        return self._impl.get_benchmark_info()

    def export_variant_queries(
        self, output_dir: Optional[Union[str, Path]] = None, format: str = "sql"
    ) -> dict[str, Path]:
        return self._impl.export_variant_queries(output_dir, format)

    def load_data_to_database(
        self,
        connection_string: str,
        dialect: str = "standard",
        schema: Optional[str] = None,
        drop_existing: bool = False,
    ) -> None:
        self._impl.load_data_to_database(
            connection_string=connection_string,
            dialect=dialect,
            schema=schema,
            drop_existing=drop_existing,
        )

    def run_query(
        self,
        query_id: int,
        connection_string: str,
        params: Optional[dict[str, Any]] = None,
        dialect: str = "standard",
    ) -> dict[str, Any]:
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")

        if not isinstance(connection_string, str) or not connection_string.strip():
            raise ValueError("connection_string must be a non-empty string")

        return self._impl.run_query(
            query_id=query_id,
            connection_string=connection_string,
            params=params,
            dialect=dialect,
        )

    def run_benchmark(
        self,
        connection_string: str,
        queries: Optional[list[int]] = None,
        iterations: int = 1,
        dialect: str = "standard",
        schema: Optional[str] = None,
    ) -> dict[str, Any]:
        if not isinstance(connection_string, str) or not connection_string.strip():
            raise ValueError("connection_string must be a non-empty string")

        if not isinstance(iterations, int):
            raise TypeError(f"iterations must be an integer, got {type(iterations).__name__}")
        if iterations < 1:
            raise ValueError(f"iterations must be positive, got {iterations}")

        if queries is not None:
            if not isinstance(queries, list):
                raise TypeError(f"queries must be a list, got {type(queries).__name__}")
            for query_id in queries:
                if not isinstance(query_id, int):
                    raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
                if not (1 <= query_id <= 22):
                    raise ValueError(f"Query ID must be 1-22, got {query_id}")

        return self._impl.run_benchmark(
            connection_string=connection_string,
            queries=queries,
            iterations=iterations,
            dialect=dialect,
            schema=schema,
        )
