"""Vector Search Benchmark implementation.

Top-level wrapper that follows the standard BenchBox wrapper pattern,
delegating to ``benchbox.core.vector_search.benchmark.VectorSearchBenchmark``.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.vector_search.benchmark import VectorSearchBenchmark


class VectorSearch(BaseBenchmark):
    """Vector Search Benchmark.

    Benchmarks similarity-search performance across OLAP databases that
    support vector/embedding operations.  Covers kNN exact search, ANN
    approximate search (via platform indexes), and filtered vector search
    (metadata predicate + distance ordering).

    Scale factors and approximate corpus sizes:
      SF=0.01  →  ~10 K vectors  (quick integration test)
      SF=0.1   → ~100 K vectors
      SF=1     →   ~1 M vectors  (standard run)
      SF=10    →  ~10 M vectors

    Queries:
      Q1  kNN cosine similarity (top-10, exact)
      Q2  kNN L2 distance (top-10, exact)
      Q3  Filtered kNN cosine, single category (top-10)
      Q4  Large-k cosine (top-100, recall ground truth)
      Q5  ANN cosine via HNSW index (top-10, approximate when index present)
      Q6  Multi-category filtered cosine (top-20)
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        *,
        dimensions: int = 128,
        **kwargs: Any,
    ) -> None:
        """Initialise the Vector Search Benchmark.

        Args:
            scale_factor: Data scale factor (0.01 - 100).
            output_dir: Directory for generated data files.
            dimensions: Embedding vector dimension count (default 128).
            **kwargs: Additional options forwarded to BaseBenchmark.
        """
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
        """Generate synthetic vector search benchmark data.

        Args:
            tables: Optional subset of tables (``vectors``, ``vector_queries``).
            output_format: Ignored; files are always written to disk.

        Returns:
            Dict mapping table names to file paths.
        """
        return self._impl.data_generator.generate_data(tables)

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: Optional[dict[str, Any]] = None,
    ) -> str:
        """Return SQL for *query_id* (Q1-Q6).

        Args:
            query_id: Query identifier.
            params: Accepted for API symmetry; queries are static.

        Returns:
            SQL string.
        """
        return self._impl.get_query(query_id, params=params)

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Return all queries, optionally in a platform-specific dialect.

        Args:
            dialect: One of ``postgresql``, ``clickhouse``, ``snowflake``.
                     Returns DuckDB SQL if *None* or unsupported.

        Returns:
            Dict mapping Q1-Q6 to SQL strings.
        """
        return self._impl.get_queries(dialect=dialect)

    def get_all_queries(self) -> dict[str, str]:
        """Return all queries in the default (DuckDB) dialect."""
        return self._impl.get_all_queries()

    def get_schema(self, dialect: str = "duckdb") -> dict[str, dict]:
        """Return the schema table definitions."""
        return self._impl.get_schema(dialect)

    def get_create_tables_sql(
        self,
        dialect: str = "duckdb",
        tuning_config: Any = None,
    ) -> str:
        """Return CREATE TABLE DDL for both vector search tables.

        Args:
            dialect: SQL dialect (duckdb, postgresql, snowflake, …).
            tuning_config: Unified tuning configuration.

        Returns:
            DDL script as a string.
        """
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)
