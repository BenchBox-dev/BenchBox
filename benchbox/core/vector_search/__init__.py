"""Vector search benchmark package.

Benchmarks similarity-search performance (kNN exact, ANN approximate,
filtered search) across OLAP databases with vector/embedding support.

Supported platforms (out of the box):
  - DuckDB ≥ 1.0  (built-in array_cosine_similarity / array_distance)
  - DuckDB + VSS extension  (HNSW indexes for ANN queries)
  - PostgreSQL + pgvector   (<=> cosine, <-> L2 operators)
  - ClickHouse               (cosineDistance, L2Distance, usearch/annoy indexes)
  - Snowflake                (VECTOR type, VECTOR_COSINE_SIMILARITY)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from .benchmark import VectorSearchBenchmark
from .generator import VectorSearchDataGenerator
from .metrics import latency_percentiles, mean_latency, queries_per_second, recall_at_k
from .queries import VectorSearchQueryManager
from .schema import (
    TABLES,
    VECTOR_QUERIES,
    VECTORS,
    get_all_create_table_sql,
    get_create_table_sql,
    get_embedding_type,
)

__all__ = [
    "VectorSearchBenchmark",
    "VectorSearchDataGenerator",
    "VectorSearchQueryManager",
    "VECTORS",
    "VECTOR_QUERIES",
    "TABLES",
    "get_create_table_sql",
    "get_all_create_table_sql",
    "get_embedding_type",
    "recall_at_k",
    "latency_percentiles",
    "queries_per_second",
    "mean_latency",
]
