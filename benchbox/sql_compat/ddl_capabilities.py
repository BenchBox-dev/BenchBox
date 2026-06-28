"""Metadata DDL capability data used by schema-rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetadataDdlCapabilities:
    """Rendering policy for metadata-primitives DDL generation."""

    supports_complex_types: bool
    supports_map_columns: bool
    supports_primary_key_clause: bool
    supports_views: bool
    supports_foreign_keys: bool
    create_or_replace_view_prefix: str = "CREATE OR REPLACE VIEW"
    create_view_if_not_exists_prefix: str = "CREATE VIEW IF NOT EXISTS"
    table_engine_clause_template: str | None = None
    table_engine_empty_order_by: str = "tuple()"


_DEFAULT_CAPABILITIES = MetadataDdlCapabilities(
    supports_complex_types=False,
    supports_map_columns=True,
    supports_primary_key_clause=True,
    supports_views=True,
    supports_foreign_keys=True,
)

_DIALECT_CAPABILITIES: dict[str, MetadataDdlCapabilities] = {
    "duckdb": MetadataDdlCapabilities(
        supports_complex_types=True,
        supports_map_columns=True,
        supports_primary_key_clause=True,
        supports_views=True,
        supports_foreign_keys=True,
    ),
    "snowflake": MetadataDdlCapabilities(
        supports_complex_types=True,
        supports_map_columns=False,
        supports_primary_key_clause=True,
        supports_views=True,
        supports_foreign_keys=True,
    ),
    "bigquery": MetadataDdlCapabilities(
        supports_complex_types=True,
        supports_map_columns=False,
        supports_primary_key_clause=True,
        supports_views=True,
        supports_foreign_keys=False,
    ),
    "clickhouse": MetadataDdlCapabilities(
        supports_complex_types=True,
        supports_map_columns=True,
        supports_primary_key_clause=False,
        supports_views=False,
        supports_foreign_keys=False,
        table_engine_clause_template=" ENGINE = MergeTree() ORDER BY ({order_by})",
    ),
    "databricks": MetadataDdlCapabilities(
        supports_complex_types=True,
        supports_map_columns=True,
        supports_primary_key_clause=True,
        supports_views=True,
        supports_foreign_keys=True,
    ),
    "postgres": MetadataDdlCapabilities(
        supports_complex_types=False,
        supports_map_columns=True,
        supports_primary_key_clause=True,
        supports_views=True,
        supports_foreign_keys=True,
    ),
    "doris": MetadataDdlCapabilities(
        supports_complex_types=False,
        supports_map_columns=True,
        supports_primary_key_clause=False,
        supports_views=True,
        supports_foreign_keys=True,
    ),
}


def get_metadata_ddl_capabilities(dialect: str) -> MetadataDdlCapabilities:
    """Return metadata DDL rendering capabilities for *dialect*."""
    normalized = dialect.lower().strip()
    return _DIALECT_CAPABILITIES.get(normalized, _DEFAULT_CAPABILITIES)
