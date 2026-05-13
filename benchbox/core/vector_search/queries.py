"""Vector search benchmark query manager.

Six queries covering the core RAG workload patterns:

  Q1  kNN cosine similarity exact search  (top-10)
  Q2  kNN L2-distance exact search        (top-10, lower distance = closer)
  Q3  Filtered kNN cosine                 (WHERE category='category_01', top-10)
  Q4  Large-k cosine search               (top-100, used for recall@10)
  Q5  ANN cosine via index                (same SQL as Q1; a HNSW index in the
                                           load phase makes it approximate)
  Q6  Multi-category filtered search      (3 categories ORed together, top-20)

Default SQL targets DuckDB 1.x built-in array functions
(``array_cosine_similarity`` and ``array_distance``).  Per-dialect variants
are provided in ``QUERY_VARIANTS`` for StarRocks, Doris, pgvector, ClickHouse,
and Snowflake.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from benchbox.core.query_catalog_base import QuerySkippedError

# ---------------------------------------------------------------------------
# Default (DuckDB) query SQL
# ---------------------------------------------------------------------------

_QUERIES: dict[str, str] = {
    # Q1: exact kNN using cosine similarity - higher is more similar
    "Q1": """
SELECT v.id,
       array_cosine_similarity(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 10
""".strip(),
    # Q2: exact kNN using Euclidean (L2) distance - lower is more similar
    "Q2": """
SELECT v.id,
       array_distance(v.embedding, q.query_vector) AS distance
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY distance ASC
LIMIT 10
""".strip(),
    # Q3: filtered kNN - only search within category_01
    "Q3": """
SELECT v.id,
       array_cosine_similarity(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
WHERE v.category = 'category_01'
ORDER BY similarity DESC
LIMIT 10
""".strip(),
    # Q4: large-k cosine search (ground truth for recall@10)
    "Q4": """
SELECT v.id,
       array_cosine_similarity(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 100
""".strip(),
    # Q5: ANN cosine search - identical SQL to Q1, but an HNSW index created
    #     during the load phase will accelerate it on supporting platforms
    "Q5": """
SELECT v.id,
       array_cosine_similarity(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 10
""".strip(),
    # Q6: multi-category filtered search
    "Q6": """
SELECT v.id,
       array_cosine_similarity(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 2) q
WHERE v.category IN ('category_01', 'category_02', 'category_03')
ORDER BY similarity DESC
LIMIT 20
""".strip(),
}

# ---------------------------------------------------------------------------
# Per-dialect variants (override default SQL for specific platforms)
# ---------------------------------------------------------------------------

QUERY_VARIANTS: dict[str, dict[str, str]] = {
    # Spark-family engines do not expose DuckDB's array_cosine_similarity /
    # array_distance helpers, but can express the same exact search with
    # higher-order array functions.
    "spark": {
        "Q1": """
SELECT v.id,
       aggregate(zip_with(v.embedding, q.query_vector, (x, y) -> x * y), 0D, (acc, z) -> acc + z)
       / NULLIF(
           sqrt(aggregate(v.embedding, 0D, (acc, x) -> acc + x * x))
           * sqrt(aggregate(q.query_vector, 0D, (acc, x) -> acc + x * x)),
           0D
         ) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q2": """
SELECT v.id,
       sqrt(aggregate(zip_with(v.embedding, q.query_vector, (x, y) -> (x - y) * (x - y)), 0D, (acc, z) -> acc + z)) AS distance
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY distance ASC
LIMIT 10
""".strip(),
        "Q3": """
SELECT v.id,
       aggregate(zip_with(v.embedding, q.query_vector, (x, y) -> x * y), 0D, (acc, z) -> acc + z)
       / NULLIF(
           sqrt(aggregate(v.embedding, 0D, (acc, x) -> acc + x * x))
           * sqrt(aggregate(q.query_vector, 0D, (acc, x) -> acc + x * x)),
           0D
         ) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
WHERE v.category = 'category_01'
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q4": """
SELECT v.id,
       aggregate(zip_with(v.embedding, q.query_vector, (x, y) -> x * y), 0D, (acc, z) -> acc + z)
       / NULLIF(
           sqrt(aggregate(v.embedding, 0D, (acc, x) -> acc + x * x))
           * sqrt(aggregate(q.query_vector, 0D, (acc, x) -> acc + x * x)),
           0D
         ) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 100
""".strip(),
        "Q5": """
SELECT v.id,
       aggregate(zip_with(v.embedding, q.query_vector, (x, y) -> x * y), 0D, (acc, z) -> acc + z)
       / NULLIF(
           sqrt(aggregate(v.embedding, 0D, (acc, x) -> acc + x * x))
           * sqrt(aggregate(q.query_vector, 0D, (acc, x) -> acc + x * x)),
           0D
         ) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q6": """
SELECT v.id,
       aggregate(zip_with(v.embedding, q.query_vector, (x, y) -> x * y), 0D, (acc, z) -> acc + z)
       / NULLIF(
           sqrt(aggregate(v.embedding, 0D, (acc, x) -> acc + x * x))
           * sqrt(aggregate(q.query_vector, 0D, (acc, x) -> acc + x * x)),
           0D
         ) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 2) q
WHERE v.category IN ('category_01', 'category_02', 'category_03')
ORDER BY similarity DESC
LIMIT 20
""".strip(),
    },
    # StarRocks 3.x: cosine_similarity on ARRAY<FLOAT> works from 3.0+.
    # l2_distance (Q2) requires StarRocks ≥3.2; older builds return a parse
    # error and the query is skipped (benchmark reports PARTIAL).
    "starrocks": {
        "Q1": """
SELECT v.id,
       cosine_similarity(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q2": """
SELECT v.id,
       l2_distance(v.embedding, q.query_vector) AS distance
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY distance ASC
LIMIT 10
""".strip(),
        "Q3": """
SELECT v.id,
       cosine_similarity(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
WHERE v.category = 'category_01'
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q4": """
SELECT v.id,
       cosine_similarity(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 100
""".strip(),
        "Q5": """
SELECT v.id,
       cosine_similarity(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q6": """
SELECT v.id,
       cosine_similarity(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 2) q
WHERE v.category IN ('category_01', 'category_02', 'category_03')
ORDER BY similarity DESC
LIMIT 20
""".strip(),
    },
    # Doris 2.x: no cosine_similarity; use 1 - cosine_distance (cosine_similarity = 1 - cosine_distance).
    # l2_distance is available natively.
    "doris": {
        "Q1": """
SELECT v.id,
       1 - cosine_distance(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q2": """
SELECT v.id,
       l2_distance(v.embedding, q.query_vector) AS distance
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY distance ASC
LIMIT 10
""".strip(),
        "Q3": """
SELECT v.id,
       1 - cosine_distance(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
WHERE v.category = 'category_01'
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q4": """
SELECT v.id,
       1 - cosine_distance(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 100
""".strip(),
        "Q5": """
SELECT v.id,
       1 - cosine_distance(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q6": """
SELECT v.id,
       1 - cosine_distance(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 2) q
WHERE v.category IN ('category_01', 'category_02', 'category_03')
ORDER BY similarity DESC
LIMIT 20
""".strip(),
    },
    # PostgreSQL + pgvector extension
    "postgresql": {
        "Q1": """
SELECT v.id,
       1 - (v.embedding <=> q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY v.embedding <=> q.query_vector ASC
LIMIT 10
""".strip(),
        "Q2": """
SELECT v.id,
       v.embedding <-> q.query_vector AS distance
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY distance ASC
LIMIT 10
""".strip(),
        "Q3": """
SELECT v.id,
       1 - (v.embedding <=> q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
WHERE v.category = 'category_01'
ORDER BY v.embedding <=> q.query_vector ASC
LIMIT 10
""".strip(),
        "Q4": """
SELECT v.id,
       1 - (v.embedding <=> q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY v.embedding <=> q.query_vector ASC
LIMIT 100
""".strip(),
        "Q5": """
SELECT v.id,
       1 - (v.embedding <=> q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY v.embedding <=> q.query_vector ASC
LIMIT 10
""".strip(),
        "Q6": """
SELECT v.id,
       1 - (v.embedding <=> q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 2) q
WHERE v.category IN ('category_01', 'category_02', 'category_03')
ORDER BY v.embedding <=> q.query_vector ASC
LIMIT 20
""".strip(),
    },
    # ClickHouse (uses cosineDistance; lower = more similar)
    "clickhouse": {
        "Q1": """
SELECT v.id,
       1 - cosineDistance(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY cosineDistance(v.embedding, q.query_vector) ASC
LIMIT 10
""".strip(),
        "Q2": """
SELECT v.id,
       L2Distance(v.embedding, q.query_vector) AS distance
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY distance ASC
LIMIT 10
""".strip(),
        "Q3": """
SELECT v.id,
       1 - cosineDistance(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
WHERE v.category = 'category_01'
ORDER BY cosineDistance(v.embedding, q.query_vector) ASC
LIMIT 10
""".strip(),
        "Q4": """
SELECT v.id,
       1 - cosineDistance(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY cosineDistance(v.embedding, q.query_vector) ASC
LIMIT 100
""".strip(),
        "Q5": """
SELECT v.id,
       1 - cosineDistance(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY cosineDistance(v.embedding, q.query_vector) ASC
LIMIT 10
""".strip(),
        "Q6": """
SELECT v.id,
       1 - cosineDistance(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 2) q
WHERE v.category IN ('category_01', 'category_02', 'category_03')
ORDER BY cosineDistance(v.embedding, q.query_vector) ASC
LIMIT 20
""".strip(),
    },
    # Snowflake (native VECTOR type)
    "snowflake": {
        "Q1": """
SELECT v.id,
       VECTOR_COSINE_SIMILARITY(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q2": """
SELECT v.id,
       VECTOR_L2_DISTANCE(v.embedding, q.query_vector) AS distance
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY distance ASC
LIMIT 10
""".strip(),
        "Q3": """
SELECT v.id,
       VECTOR_COSINE_SIMILARITY(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
WHERE v.category = 'category_01'
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q4": """
SELECT v.id,
       VECTOR_COSINE_SIMILARITY(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 100
""".strip(),
        "Q5": """
SELECT v.id,
       VECTOR_COSINE_SIMILARITY(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 1) q
ORDER BY similarity DESC
LIMIT 10
""".strip(),
        "Q6": """
SELECT v.id,
       VECTOR_COSINE_SIMILARITY(v.embedding, q.query_vector) AS similarity
FROM vectors v
CROSS JOIN (SELECT query_vector FROM vector_queries WHERE query_id = 2) q
WHERE v.category IN ('category_01', 'category_02', 'category_03')
ORDER BY similarity DESC
LIMIT 20
""".strip(),
    },
}

for _spark_alias in ("lakesail", "pyspark", "velox", "databricks"):
    QUERY_VARIANTS[_spark_alias] = QUERY_VARIANTS["spark"]


# ---------------------------------------------------------------------------
# Query manager
# ---------------------------------------------------------------------------


class VectorSearchQueryManager:
    """Manager for vector search benchmark queries.

    By default returns DuckDB-flavoured SQL.  Pass a ``dialect`` to
    :meth:`get_query` or :meth:`get_all_queries` to get platform-specific SQL.
    """

    ALL_QUERY_IDS = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]

    # Human-readable descriptions
    DESCRIPTIONS: dict[str, str] = {
        "Q1": "kNN cosine similarity exact search (top-10)",
        "Q2": "kNN L2-distance exact search (top-10)",
        "Q3": "Filtered kNN cosine - single category (top-10)",
        "Q4": "Large-k cosine search for recall@10 ground truth (top-100)",
        "Q5": "ANN cosine search - uses HNSW index when available (top-10)",
        "Q6": "Multi-category filtered cosine search (top-20)",
    }

    def __init__(self) -> None:
        self._queries = dict(_QUERIES)

    def get_query(self, query_id: str, *, dialect: str | None = None, platform_version: str | None = None) -> str:
        """Return SQL for *query_id*, optionally translated to *dialect*.

        Args:
            query_id: One of Q1-Q6.
            dialect: Optional platform dialect (for example starrocks, doris,
                     postgresql, clickhouse, snowflake). Falls back to DuckDB
                     default if dialect is not supported.
            platform_version: Optional platform version string for version-gated rules.

        Returns:
            SQL string.

        Raises:
            ValueError: If *query_id* is not recognised.
            QuerySkippedError: If the compat registry marks *query_id* unsupported
                for the requested platform version.
        """
        key = str(query_id).upper()
        if key not in self._queries:
            available = ", ".join(sorted(self._queries.keys()))
            raise ValueError(f"Invalid query ID: {query_id!r}. Available: {available}")

        if dialect:
            dialect_lower = dialect.lower()
            legacy_sql = QUERY_VARIANTS.get(dialect_lower, {}).get(key)
            if legacy_sql is None:
                legacy_sql = self._queries[key]

            import benchbox.sql_compat.rules.query_source.vector_search_variants  # noqa: F401
            from benchbox.sql_compat.actions import CompatAction
            from benchbox.sql_compat.context import CompatibilityContext, Phase
            from benchbox.sql_compat.registry import REGISTRY

            ctx = CompatibilityContext(
                platform=dialect_lower,
                platform_version=platform_version,
                benchmark="vector_search",
                query_id=key,
                phase=Phase.QUERY_SOURCE,
                mode="sql",
                dialect=dialect,
            )
            registry_decision = REGISTRY.resolve(ctx)
            if registry_decision is not None:
                if registry_decision.action is CompatAction.SELECT_VARIANT:
                    return registry_decision.payload.variant_sql  # type: ignore[union-attr]
                if registry_decision.action is CompatAction.SKIP_QUERY:
                    reason = getattr(registry_decision.payload, "reason", None) or registry_decision.reason
                    raise QuerySkippedError(
                        f"Query '{key}' is not supported on dialect '{dialect}' "
                        f"for platform version '{platform_version or 'unknown'}': {reason}"
                    )
                # Other actions are not used at QUERY_SOURCE for vector_search yet.

            return legacy_sql  # type: ignore[return-value]

        return self._queries[key]

    def get_all_queries(self, *, dialect: str | None = None, platform_version: str | None = None) -> dict[str, str]:
        """Return all queries as a ``{query_id: sql}`` dict.

        Args:
            dialect: Optional platform dialect override.
            platform_version: Optional platform version string for version-gated rules.

        Returns:
            Dict mapping query IDs to SQL strings.
        """
        queries: dict[str, str] = {}
        for qid in self.ALL_QUERY_IDS:
            try:
                queries[qid] = self.get_query(qid, dialect=dialect, platform_version=platform_version)
            except QuerySkippedError:
                continue
        return queries

    def get_description(self, query_id: str) -> str:
        """Return a human-readable description for *query_id*."""
        return self.DESCRIPTIONS.get(str(query_id).upper(), "Unknown query")

    def supported_dialects(self) -> list[str]:
        """Return list of dialects with explicit variant SQL."""
        return list(QUERY_VARIANTS.keys())
