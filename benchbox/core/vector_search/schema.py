"""Vector search benchmark schema definitions.

Two tables:
- vectors: the searchable corpus (id, embedding, category, doc_id)
- vector_queries: pre-generated query vectors used in benchmark queries

The embedding column type is dialect-specific because each platform uses its
own array/vector type syntax.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------

VECTORS: dict = {
    "name": "vectors",
    "columns": [
        {"name": "id", "type": "BIGINT", "primary_key": True},
        {"name": "embedding", "type": "FLOAT_ARRAY"},  # resolved per dialect
        {"name": "category", "type": "VARCHAR(50)"},
        {"name": "doc_id", "type": "VARCHAR(100)"},
    ],
}

VECTOR_QUERIES: dict = {
    "name": "vector_queries",
    "columns": [
        {"name": "query_id", "type": "INTEGER", "primary_key": True},
        {"name": "query_vector", "type": "FLOAT_ARRAY"},  # resolved per dialect
    ],
}

TABLES: dict[str, dict] = {
    "vectors": VECTORS,
    "vector_queries": VECTOR_QUERIES,
}

# ---------------------------------------------------------------------------
# Dialect-specific embedding type strings
# ---------------------------------------------------------------------------

_EMBEDDING_TYPE_MAP: dict[str, str] = {
    # DuckDB: fixed-size float array (native, no extension needed)
    "duckdb": "FLOAT[{dim}]",
    # PostgreSQL + pgvector extension
    "postgresql": "VECTOR({dim})",
    "postgres": "VECTOR({dim})",
    # Snowflake native vector type
    "snowflake": "VECTOR(FLOAT, {dim})",
    # ClickHouse native array
    "clickhouse": "Array(Float32)",
    # BigQuery
    "bigquery": "ARRAY<FLOAT64>",
    # StarRocks / Doris: ARRAY<FLOAT> without dimension (sized arrays unsupported)
    "starrocks": "ARRAY<FLOAT>",
    "doris": "ARRAY<FLOAT>",
    # SingleStore: native VECTOR type (SingleStore 8.5+)
    "mysql": "VECTOR({dim}, F32)",
    # Default/fallback: use DuckDB syntax for OLAP databases
    "default": "FLOAT[{dim}]",
}


def get_embedding_type(dialect: str = "duckdb", dimensions: int = 128) -> str:
    """Return the SQL type for an embedding column in the given dialect.

    Args:
        dialect: SQL dialect name (duckdb, postgresql, snowflake, clickhouse, …)
        dimensions: Number of dimensions in the embedding vector.

    Returns:
        SQL type string with ``{dim}`` replaced by ``dimensions``.
    """
    template = _EMBEDDING_TYPE_MAP.get(dialect.lower(), _EMBEDDING_TYPE_MAP["default"])
    return template.format(dim=dimensions)


# ---------------------------------------------------------------------------
# DDL generation
# ---------------------------------------------------------------------------


def get_create_table_sql(
    table_name: str,
    dialect: str = "duckdb",
    dimensions: int = 128,
    enable_primary_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for a vector search table.

    Args:
        table_name: One of 'vectors' or 'vector_queries'.
        dialect: Target SQL dialect.
        dimensions: Embedding dimension count.
        enable_primary_keys: Whether to include PRIMARY KEY constraints.

    Returns:
        CREATE TABLE SQL statement.

    Raises:
        ValueError: If ``table_name`` is not recognised.
    """
    if table_name not in TABLES:
        raise ValueError(f"Unknown table: {table_name!r}. Available: {list(TABLES)}")

    table = TABLES[table_name]
    embedding_type = get_embedding_type(dialect, dimensions)

    column_defs: list[str] = []
    for col in table["columns"]:
        col_type = embedding_type if col["type"] == "FLOAT_ARRAY" else col["type"]
        col_def = f"{col['name']} {col_type}"
        if col.get("primary_key") and enable_primary_keys:
            col_def += " PRIMARY KEY"
        column_defs.append(col_def)

    return f"CREATE TABLE {table['name']} (\n" + ",\n".join(f"  {c}" for c in column_defs) + "\n);"


def get_all_create_table_sql(
    dialect: str = "duckdb",
    dimensions: int = 128,
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for all vector search tables.

    Args:
        dialect: Target SQL dialect.
        dimensions: Embedding dimension count.
        enable_primary_keys: Whether to include PRIMARY KEY constraints.
        enable_foreign_keys: Accepted for API symmetry; no FKs in this schema.

    Returns:
        Complete DDL script (two CREATE TABLE statements).
    """
    return "\n\n".join(get_create_table_sql(t, dialect, dimensions, enable_primary_keys) for t in TABLES)
