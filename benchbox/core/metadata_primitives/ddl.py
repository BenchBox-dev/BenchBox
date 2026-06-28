"""DDL generation utilities for metadata complexity testing.

Provides platform-agnostic DDL generation for creating test tables,
views, and other database objects across different SQL dialects.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass

from benchbox.core.metadata_primitives.complexity import TypeComplexity
from benchbox.sql_compat.ddl_capabilities import get_metadata_ddl_capabilities


@dataclass
class ColumnDefinition:
    """Definition for a single column."""

    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False


@dataclass
class TableDefinition:
    """Definition for a table to be created."""

    name: str
    columns: list[ColumnDefinition]
    schema_name: str | None = None


@dataclass
class ViewDefinition:
    """Definition for a view to be created."""

    name: str
    source_sql: str
    schema_name: str | None = None


# Type mappings per dialect
# Maps logical type names to platform-specific SQL types
TYPE_MAPPINGS: dict[str, dict[str, str]] = {
    "duckdb": {
        "integer": "INTEGER",
        "bigint": "BIGINT",
        "varchar": "VARCHAR(255)",
        "varchar_short": "VARCHAR(50)",
        "varchar_long": "VARCHAR(1000)",
        "decimal": "DECIMAL(18,4)",
        "decimal_small": "DECIMAL(10,2)",
        "date": "DATE",
        "timestamp": "TIMESTAMP",
        "boolean": "BOOLEAN",
        "double": "DOUBLE",
        "array_int": "INTEGER[]",
        "array_varchar": "VARCHAR[]",
        "struct_simple": "STRUCT(key VARCHAR, value VARCHAR)",
        "struct_nested": "STRUCT(name VARCHAR, data STRUCT(x INTEGER, y INTEGER))",
        "map_simple": "MAP(VARCHAR, INTEGER)",
    },
    "snowflake": {
        "integer": "INTEGER",
        "bigint": "BIGINT",
        "varchar": "VARCHAR(255)",
        "varchar_short": "VARCHAR(50)",
        "varchar_long": "VARCHAR(1000)",
        "decimal": "NUMBER(18,4)",
        "decimal_small": "NUMBER(10,2)",
        "date": "DATE",
        "timestamp": "TIMESTAMP_NTZ",
        "boolean": "BOOLEAN",
        "double": "DOUBLE",
        "array_int": "ARRAY",
        "array_varchar": "ARRAY",
        "struct_simple": "OBJECT",
        "struct_nested": "OBJECT",
        "map_simple": "OBJECT",  # Snowflake uses OBJECT for maps
    },
    "bigquery": {
        "integer": "INT64",
        "bigint": "INT64",
        "varchar": "STRING",
        "varchar_short": "STRING",
        "varchar_long": "STRING",
        "decimal": "NUMERIC",
        "decimal_small": "NUMERIC",
        "date": "DATE",
        "timestamp": "TIMESTAMP",
        "boolean": "BOOL",
        "double": "FLOAT64",
        "array_int": "ARRAY<INT64>",
        "array_varchar": "ARRAY<STRING>",
        "struct_simple": "STRUCT<key STRING, value STRING>",
        "struct_nested": "STRUCT<name STRING, data STRUCT<x INT64, y INT64>>",
        "map_simple": "ARRAY<STRUCT<key STRING, value INT64>>",  # BigQuery doesn't have MAP
    },
    "clickhouse": {
        "integer": "Int32",
        "bigint": "Int64",
        "varchar": "String",
        "varchar_short": "String",
        "varchar_long": "String",
        "decimal": "Decimal(18,4)",
        "decimal_small": "Decimal(10,2)",
        "date": "Date",
        "timestamp": "DateTime",
        "boolean": "Bool",
        "double": "Float64",
        "array_int": "Array(Int32)",
        "array_varchar": "Array(String)",
        "struct_simple": "Tuple(key String, value String)",
        "struct_nested": "Tuple(name String, data Tuple(x Int32, y Int32))",
        "map_simple": "Map(String, Int32)",
    },
    "databricks": {
        "integer": "INT",
        "bigint": "BIGINT",
        "varchar": "STRING",
        "varchar_short": "STRING",
        "varchar_long": "STRING",
        "decimal": "DECIMAL(18,4)",
        "decimal_small": "DECIMAL(10,2)",
        "date": "DATE",
        "timestamp": "TIMESTAMP",
        "boolean": "BOOLEAN",
        "double": "DOUBLE",
        "array_int": "ARRAY<INT>",
        "array_varchar": "ARRAY<STRING>",
        "struct_simple": "STRUCT<key: STRING, value: STRING>",
        "struct_nested": "STRUCT<name: STRING, data: STRUCT<x: INT, y: INT>>",
        "map_simple": "MAP<STRING, INT>",
    },
    "postgres": {
        "integer": "INTEGER",
        "bigint": "BIGINT",
        "varchar": "VARCHAR(255)",
        "varchar_short": "VARCHAR(50)",
        "varchar_long": "VARCHAR(1000)",
        "decimal": "NUMERIC(18,4)",
        "decimal_small": "NUMERIC(10,2)",
        "date": "DATE",
        "timestamp": "TIMESTAMP",
        "boolean": "BOOLEAN",
        "double": "DOUBLE PRECISION",
        "array_int": "INTEGER[]",
        "array_varchar": "VARCHAR[]",
        "struct_simple": "JSONB",  # PostgreSQL uses JSONB for complex types
        "struct_nested": "JSONB",
        "map_simple": "JSONB",
    },
}

# Column type distribution for wide tables
# Determines what percentage of columns use each type
WIDE_TABLE_TYPE_DISTRIBUTION: list[tuple[str, float]] = [
    ("integer", 0.30),  # 30% integers
    ("varchar", 0.25),  # 25% strings
    ("decimal", 0.15),  # 15% decimals
    ("bigint", 0.10),  # 10% big integers
    ("date", 0.08),  # 8% dates
    ("timestamp", 0.05),  # 5% timestamps
    ("boolean", 0.04),  # 4% booleans
    ("double", 0.03),  # 3% doubles
]


def get_type_mapping(dialect: str) -> dict[str, str]:
    """Get type mappings for a dialect.

    Args:
        dialect: Target SQL dialect

    Returns:
        Dictionary mapping logical types to SQL types
    """
    normalized = dialect.lower().strip()
    if normalized not in TYPE_MAPPINGS:
        # Default to DuckDB syntax for unknown dialects
        return TYPE_MAPPINGS["duckdb"]
    return TYPE_MAPPINGS[normalized]


def map_type(logical_type: str, dialect: str) -> str:
    """Map a logical type to platform-specific SQL type.

    Args:
        logical_type: Logical type name (integer, varchar, etc.)
        dialect: Target SQL dialect

    Returns:
        SQL type string for the platform
    """
    mapping = get_type_mapping(dialect)
    return mapping.get(logical_type, mapping.get("varchar", "VARCHAR(255)"))


def generate_wide_table_columns(
    width: int,
    dialect: str,
    type_complexity: TypeComplexity = TypeComplexity.SCALAR,
) -> list[ColumnDefinition]:
    """Generate column definitions for a wide table.

    Creates columns with a realistic distribution of types based on
    common analytics table patterns.

    Args:
        width: Number of columns to generate
        dialect: Target SQL dialect for type mapping
        type_complexity: Level of type complexity to include

    Returns:
        List of ColumnDefinition objects
    """
    columns: list[ColumnDefinition] = []

    # Add primary key column
    columns.append(
        ColumnDefinition(
            name="id",
            data_type=map_type("bigint", dialect),
            nullable=False,
            primary_key=True,
        )
    )

    # Calculate column counts per type based on distribution
    remaining = width - 1  # Subtract 1 for PK
    type_counts: dict[str, int] = {}
    cumulative = 0.0

    for logical_type, percentage in WIDE_TABLE_TYPE_DISTRIBUTION:
        count = int(remaining * percentage)
        type_counts[logical_type] = count
        cumulative += count

    # Assign remaining columns to varchar
    extra = remaining - int(cumulative)
    type_counts["varchar"] = type_counts.get("varchar", 0) + extra

    # Generate columns for each type
    col_index = 1
    for logical_type, count in type_counts.items():
        sql_type = map_type(logical_type, dialect)
        for i in range(count):
            columns.append(
                ColumnDefinition(
                    name=f"col_{logical_type}_{col_index:04d}",
                    data_type=sql_type,
                    nullable=True,
                )
            )
            col_index += 1

    # Add complex type columns if requested
    if type_complexity in (TypeComplexity.BASIC, TypeComplexity.NESTED):
        # Add array columns
        columns.append(
            ColumnDefinition(
                name="col_array_int",
                data_type=map_type("array_int", dialect),
                nullable=True,
            )
        )
        columns.append(
            ColumnDefinition(
                name="col_array_varchar",
                data_type=map_type("array_varchar", dialect),
                nullable=True,
            )
        )

    if type_complexity == TypeComplexity.NESTED:
        # Add struct columns
        columns.append(
            ColumnDefinition(
                name="col_struct_simple",
                data_type=map_type("struct_simple", dialect),
                nullable=True,
            )
        )
        columns.append(
            ColumnDefinition(
                name="col_struct_nested",
                data_type=map_type("struct_nested", dialect),
                nullable=True,
            )
        )
        # Add map column when the dialect capability table says it is renderable.
        if get_metadata_ddl_capabilities(dialect).supports_map_columns:
            columns.append(
                ColumnDefinition(
                    name="col_map",
                    data_type=map_type("map_simple", dialect),
                    nullable=True,
                )
            )

    return columns


def generate_create_table_sql(
    table_def: TableDefinition,
    dialect: str,
    if_not_exists: bool = True,
) -> str:
    """Generate CREATE TABLE SQL statement.

    Args:
        table_def: Table definition
        dialect: Target SQL dialect
        if_not_exists: Whether to add IF NOT EXISTS clause

    Returns:
        CREATE TABLE SQL statement
    """
    parts: list[str] = []

    # Table name with optional schema
    if table_def.schema_name:
        full_name = f"{table_def.schema_name}.{table_def.name}"
    else:
        full_name = table_def.name

    # Start CREATE TABLE
    if if_not_exists:
        parts.append(f"CREATE TABLE IF NOT EXISTS {full_name} (")
    else:
        parts.append(f"CREATE TABLE {full_name} (")

    # Column definitions
    col_defs: list[str] = []
    pk_columns: list[str] = []

    for col in table_def.columns:
        col_sql = f"    {col.name} {col.data_type}"
        if not col.nullable:
            col_sql += " NOT NULL"
        col_defs.append(col_sql)
        if col.primary_key:
            pk_columns.append(col.name)

    capabilities = get_metadata_ddl_capabilities(dialect)

    # Add primary key constraint if applicable.
    if pk_columns and capabilities.supports_primary_key_clause:
        pk_constraint = f"    PRIMARY KEY ({', '.join(pk_columns)})"
        col_defs.append(pk_constraint)

    parts.append(",\n".join(col_defs))
    parts.append(")")

    if capabilities.table_engine_clause_template:
        # Keyed tables wrap the key list in parens, e.g. ``ORDER BY (a, b)``; the
        # no-key case renders the empty-order expression verbatim (``ORDER BY
        # tuple()``), so the parens belong to the key list, not the template — wrapping
        # the template would emit ``ORDER BY (tuple())`` and break byte-identical DDL.
        order_by = f"({', '.join(pk_columns)})" if pk_columns else capabilities.table_engine_empty_order_by
        parts.append(capabilities.table_engine_clause_template.format(order_by=order_by))

    return "\n".join(parts) + ";"


def generate_create_view_sql(
    view_def: ViewDefinition,
    dialect: str,
    or_replace: bool = True,
) -> str:
    """Generate CREATE VIEW SQL statement.

    Args:
        view_def: View definition
        dialect: Target SQL dialect
        or_replace: Whether to add OR REPLACE clause

    Returns:
        CREATE VIEW SQL statement
    """
    # View name with optional schema
    if view_def.schema_name:
        full_name = f"{view_def.schema_name}.{view_def.name}"
    else:
        full_name = view_def.name

    capabilities = get_metadata_ddl_capabilities(dialect)
    prefix = capabilities.create_or_replace_view_prefix if or_replace else capabilities.create_view_if_not_exists_prefix
    return f"{prefix} {full_name} AS\n{view_def.source_sql};"


def generate_drop_table_sql(
    table_name: str,
    dialect: str,
    schema_name: str | None = None,
    if_exists: bool = True,
) -> str:
    """Generate DROP TABLE SQL statement.

    Args:
        table_name: Name of the table
        dialect: Target SQL dialect
        schema_name: Optional schema name
        if_exists: Whether to add IF EXISTS clause

    Returns:
        DROP TABLE SQL statement
    """
    if schema_name:
        full_name = f"{schema_name}.{table_name}"
    else:
        full_name = table_name

    if if_exists:
        return f"DROP TABLE IF EXISTS {full_name};"
    return f"DROP TABLE {full_name};"


def generate_drop_view_sql(
    view_name: str,
    dialect: str,
    schema_name: str | None = None,
    if_exists: bool = True,
) -> str:
    """Generate DROP VIEW SQL statement.

    Args:
        view_name: Name of the view
        dialect: Target SQL dialect
        schema_name: Optional schema name
        if_exists: Whether to add IF EXISTS clause

    Returns:
        DROP VIEW SQL statement
    """
    if schema_name:
        full_name = f"{schema_name}.{view_name}"
    else:
        full_name = view_name

    if if_exists:
        return f"DROP VIEW IF EXISTS {full_name};"
    return f"DROP VIEW {full_name};"


def generate_simple_table_columns(
    column_count: int,
    dialect: str,
) -> list[ColumnDefinition]:
    """Generate simple table columns for catalog size testing.

    Creates a simpler table structure than wide tables, focused
    on testing catalog scanning rather than column enumeration.

    Args:
        column_count: Number of columns (typically 5-15)
        dialect: Target SQL dialect

    Returns:
        List of ColumnDefinition objects
    """
    columns: list[ColumnDefinition] = [
        ColumnDefinition(
            name="id",
            data_type=map_type("bigint", dialect),
            nullable=False,
            primary_key=True,
        ),
        ColumnDefinition(
            name="name",
            data_type=map_type("varchar", dialect),
            nullable=True,
        ),
        ColumnDefinition(
            name="created_at",
            data_type=map_type("timestamp", dialect),
            nullable=True,
        ),
        ColumnDefinition(
            name="amount",
            data_type=map_type("decimal", dialect),
            nullable=True,
        ),
        ColumnDefinition(
            name="is_active",
            data_type=map_type("boolean", dialect),
            nullable=True,
        ),
    ]

    # Add more columns if requested
    for i in range(5, column_count):
        columns.append(
            ColumnDefinition(
                name=f"field_{i:02d}",
                data_type=map_type("varchar", dialect),
                nullable=True,
            )
        )

    return columns


def supports_complex_types(dialect: str) -> bool:
    """Check if dialect supports complex types (ARRAY, STRUCT, MAP).

    Args:
        dialect: SQL dialect name

    Returns:
        True if complex types are supported
    """
    return get_metadata_ddl_capabilities(dialect).supports_complex_types


def supports_views(dialect: str) -> bool:
    """Check if dialect supports views in INFORMATION_SCHEMA.

    Args:
        dialect: SQL dialect name

    Returns:
        True if views are queryable via INFORMATION_SCHEMA
    """
    return get_metadata_ddl_capabilities(dialect).supports_views


def supports_foreign_keys(dialect: str) -> bool:
    """Check if dialect supports foreign key constraints.

    Args:
        dialect: SQL dialect name

    Returns:
        True if FK constraints are supported
    """
    return get_metadata_ddl_capabilities(dialect).supports_foreign_keys


# =============================================================================
# ACL (Access Control) Support Functions
# =============================================================================


def supports_acl(dialect: str) -> bool:
    """Check if dialect supports ACL operations (CREATE ROLE, GRANT/REVOKE).

    Note: This checks for basic GRANT/REVOKE support. Even platforms that
    return True may have limited introspection capabilities.

    Args:
        dialect: SQL dialect name

    Returns:
        True if GRANT/REVOKE statements are supported
    """
    # Tier 4 platforms (no ACL support)
    no_acl = {"sqlite", "datafusion", "spark", "polars", "duckdb"}
    return dialect.lower() not in no_acl


def supports_acl_introspection(dialect: str) -> bool:
    """Check if dialect supports queryable ACL metadata.

    Platforms with this support have INFORMATION_SCHEMA.table_privileges
    or equivalent system tables for querying granted permissions.

    Args:
        dialect: SQL dialect name

    Returns:
        True if ACL metadata is queryable via SQL
    """
    # Tier 1 and 2 platforms support introspection
    introspection_platforms = {
        "postgresql",
        "postgres",
        "redshift",
        "firebolt",
        "synapse",
        "fabric",
        "databricks",
        "clickhouse",
    }
    return dialect.lower() in introspection_platforms


def supports_role_hierarchy(dialect: str) -> bool:
    """Check if dialect supports role-to-role grants (GRANT role TO role).

    Args:
        dialect: SQL dialect name

    Returns:
        True if role hierarchy is supported
    """
    hierarchy_platforms = {
        "postgresql",
        "postgres",
        "redshift",
        "clickhouse",
        "snowflake",
        "databricks",
        "synapse",
        "fabric",
        "firebolt",
    }
    return dialect.lower() in hierarchy_platforms


def supports_column_grants(dialect: str) -> bool:
    """Check if dialect supports column-level GRANT statements.

    Args:
        dialect: SQL dialect name

    Returns:
        True if column-level privileges are supported
    """
    column_grant_platforms = {
        "postgresql",
        "postgres",
        "redshift",
        "synapse",
        "fabric",
        "snowflake",
        "databricks",
    }
    return dialect.lower() in column_grant_platforms


def generate_create_role_sql(
    role_name: str,
    dialect: str,
    if_not_exists: bool = True,
) -> str:
    """Generate CREATE ROLE SQL statement.

    Args:
        role_name: Name of the role to create
        dialect: Target SQL dialect
        if_not_exists: Add IF NOT EXISTS (where supported)

    Returns:
        CREATE ROLE SQL statement
    """
    d = dialect.lower()

    if d in ("synapse", "fabric"):
        # T-SQL syntax
        return f"CREATE ROLE [{role_name}];"
    elif d == "bigquery":
        # BigQuery doesn't support SQL roles
        return "-- BigQuery: Role creation not supported via SQL (IAM-based)"
    elif d == "snowflake":
        # Snowflake uses IF NOT EXISTS
        if if_not_exists:
            return f"CREATE ROLE IF NOT EXISTS {role_name};"
        return f"CREATE ROLE {role_name};"
    elif d in ("postgresql", "postgres", "redshift"):
        # PostgreSQL family - no IF NOT EXISTS for roles
        return f"CREATE ROLE {role_name};"
    elif d == "clickhouse" or d == "databricks":
        if if_not_exists:
            return f"CREATE ROLE IF NOT EXISTS {role_name};"
        return f"CREATE ROLE {role_name};"
    elif d == "duckdb":
        # DuckDB has basic role support
        return f"CREATE ROLE {role_name};"
    else:
        # Default/fallback
        return f"CREATE ROLE {role_name};"


def generate_drop_role_sql(
    role_name: str,
    dialect: str,
    if_exists: bool = True,
) -> str:
    """Generate DROP ROLE SQL statement.

    Args:
        role_name: Name of the role to drop
        dialect: Target SQL dialect
        if_exists: Add IF EXISTS clause

    Returns:
        DROP ROLE SQL statement
    """
    d = dialect.lower()

    if d in ("synapse", "fabric"):
        # T-SQL syntax
        return f"DROP ROLE IF EXISTS [{role_name}];"
    elif d == "bigquery":
        return "-- BigQuery: Role drop not supported via SQL (IAM-based)"
    elif d in ("postgresql", "postgres", "redshift"):
        if if_exists:
            return f"DROP ROLE IF EXISTS {role_name};"
        return f"DROP ROLE {role_name};"
    else:
        # Standard SQL / DuckDB / Snowflake / ClickHouse / Databricks
        if if_exists:
            return f"DROP ROLE IF EXISTS {role_name};"
        return f"DROP ROLE {role_name};"


def generate_grant_sql(
    grantee: str,
    object_name: str,
    privileges: list[str],
    dialect: str,
    object_type: str = "TABLE",
    with_grant_option: bool = False,
    column_name: str | None = None,
) -> str:
    """Generate GRANT SQL statement.

    Args:
        grantee: Role or user to grant to
        object_name: Object being granted on
        privileges: List of privileges (SELECT, INSERT, UPDATE, DELETE, etc.)
        dialect: Target SQL dialect
        object_type: Type of object (TABLE, VIEW, etc.)
        with_grant_option: Include WITH GRANT OPTION
        column_name: For column-level grants

    Returns:
        GRANT SQL statement
    """
    d = dialect.lower()
    priv_str = ", ".join(privileges)

    # Build the grant target
    if column_name:
        # Column-level grant
        if d in ("synapse", "fabric"):
            grant_target = f"{priv_str} ({column_name}) ON {object_type} [{object_name}]"
        else:
            grant_target = f"{priv_str} ({column_name}) ON {object_type} {object_name}"
    else:
        if d in ("synapse", "fabric"):
            grant_target = f"{priv_str} ON {object_type} [{object_name}]"
        else:
            grant_target = f"{priv_str} ON {object_type} {object_name}"

    # Build grantee reference
    if d in ("synapse", "fabric"):
        grantee_ref = f"[{grantee}]"
    else:
        grantee_ref = grantee

    # Build WITH GRANT OPTION clause
    grant_option = ""
    if with_grant_option:
        if d in ("synapse", "fabric"):
            grant_option = " WITH GRANT OPTION"
        else:
            grant_option = " WITH GRANT OPTION"

    return f"GRANT {grant_target} TO {grantee_ref}{grant_option};"


def generate_revoke_sql(
    grantee: str,
    object_name: str,
    privileges: list[str],
    dialect: str,
    object_type: str = "TABLE",
    column_name: str | None = None,
) -> str:
    """Generate REVOKE SQL statement.

    Args:
        grantee: Role or user to revoke from
        object_name: Object being revoked on
        privileges: List of privileges to revoke
        dialect: Target SQL dialect
        object_type: Type of object (TABLE, VIEW, etc.)
        column_name: For column-level revokes

    Returns:
        REVOKE SQL statement
    """
    d = dialect.lower()
    priv_str = ", ".join(privileges)

    # Build the revoke target
    if column_name:
        if d in ("synapse", "fabric"):
            revoke_target = f"{priv_str} ({column_name}) ON {object_type} [{object_name}]"
        else:
            revoke_target = f"{priv_str} ({column_name}) ON {object_type} {object_name}"
    else:
        if d in ("synapse", "fabric"):
            revoke_target = f"{priv_str} ON {object_type} [{object_name}]"
        else:
            revoke_target = f"{priv_str} ON {object_type} {object_name}"

    # Build grantee reference
    if d in ("synapse", "fabric"):
        grantee_ref = f"[{grantee}]"
    else:
        grantee_ref = grantee

    return f"REVOKE {revoke_target} FROM {grantee_ref};"


def generate_grant_role_sql(
    parent_role: str,
    child_role: str,
    dialect: str,
) -> str:
    """Generate GRANT role TO role SQL statement for role hierarchy.

    Args:
        parent_role: Role being granted (the parent)
        child_role: Role receiving the grant (the child)
        dialect: Target SQL dialect

    Returns:
        GRANT role TO role SQL statement
    """
    d = dialect.lower()

    if d in ("synapse", "fabric"):
        # T-SQL uses different syntax
        return f"ALTER ROLE [{parent_role}] ADD MEMBER [{child_role}];"
    elif d == "bigquery":
        return "-- BigQuery: Role grants not supported via SQL"
    elif d == "clickhouse":
        return f"GRANT {parent_role} TO {child_role};"
    else:
        # Standard SQL / PostgreSQL / Snowflake / Databricks / DuckDB
        return f"GRANT {parent_role} TO {child_role};"


def generate_revoke_role_sql(
    parent_role: str,
    child_role: str,
    dialect: str,
) -> str:
    """Generate REVOKE role FROM role SQL statement.

    Args:
        parent_role: Role being revoked
        child_role: Role losing the grant
        dialect: Target SQL dialect

    Returns:
        REVOKE role FROM role SQL statement
    """
    d = dialect.lower()

    if d in ("synapse", "fabric"):
        return f"ALTER ROLE [{parent_role}] DROP MEMBER [{child_role}];"
    elif d == "bigquery":
        return "-- BigQuery: Role revokes not supported via SQL"
    elif d == "clickhouse":
        return f"REVOKE {parent_role} FROM {child_role};"
    else:
        return f"REVOKE {parent_role} FROM {child_role};"


__all__ = [
    "ColumnDefinition",
    "TableDefinition",
    "ViewDefinition",
    "TYPE_MAPPINGS",
    "WIDE_TABLE_TYPE_DISTRIBUTION",
    "generate_create_table_sql",
    "generate_create_view_sql",
    "generate_drop_table_sql",
    "generate_drop_view_sql",
    "generate_simple_table_columns",
    "generate_wide_table_columns",
    "get_type_mapping",
    "map_type",
    "supports_complex_types",
    "supports_foreign_keys",
    "supports_views",
    # ACL functions
    "supports_acl",
    "supports_acl_introspection",
    "supports_role_hierarchy",
    "supports_column_grants",
    "generate_create_role_sql",
    "generate_drop_role_sql",
    "generate_grant_sql",
    "generate_revoke_sql",
    "generate_grant_role_sql",
    "generate_revoke_role_sql",
]
