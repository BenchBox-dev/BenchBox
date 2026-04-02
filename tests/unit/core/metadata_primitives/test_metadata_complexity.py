"""Unit tests for Metadata Primitives complexity testing functionality.

This module contains unit tests for:
- TestMetadataComplexityConfig: Tests for complexity configuration and presets
- TestDDLGeneration: Tests for DDL generation utilities
- TestMetadataGenerator: Tests for metadata structure generation
- TestComplexityCategories: Tests for complexity-specific query categories

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.metadata_primitives import (
    COMPLEXITY_PRESETS,
    ComplexityBenchmarkResult,
    ConstraintDensity,
    GeneratedMetadata,
    MetadataComplexityConfig,
    MetadataGenerator,
    MetadataPrimitivesBenchmark,
    PermissionDensity,
    RoleHierarchyDepth,
    TypeComplexity,
    get_complexity_preset,
)
from benchbox.core.metadata_primitives.ddl import (
    TYPE_MAPPINGS,
    ColumnDefinition,
    TableDefinition,
    ViewDefinition,
    generate_create_table_sql,
    generate_create_view_sql,
    generate_drop_table_sql,
    generate_drop_view_sql,
    generate_simple_table_columns,
    generate_wide_table_columns,
    get_type_mapping,
    map_type,
    supports_complex_types,
    supports_foreign_keys,
    supports_views,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# =============================================================================
# MetadataComplexityConfig Tests
# =============================================================================


@pytest.mark.unit
class TestMetadataComplexityConfig:
    """Test MetadataComplexityConfig dataclass and validation."""

    def test_default_config(self):
        """Test default configuration values."""
        config = MetadataComplexityConfig()
        assert config.width_factor == 50
        assert config.view_depth == 1
        assert config.type_complexity == TypeComplexity.SCALAR
        assert config.catalog_size == 10
        assert config.constraint_density == ConstraintDensity.NONE
        assert config.schema_count == 1
        assert config.prefix == "benchbox_"

    def test_custom_config(self):
        """Test custom configuration values."""
        config = MetadataComplexityConfig(
            width_factor=200,
            view_depth=3,
            type_complexity=TypeComplexity.NESTED,
            catalog_size=50,
            constraint_density=ConstraintDensity.DENSE,
        )
        assert config.width_factor == 200
        assert config.view_depth == 3
        assert config.type_complexity == TypeComplexity.NESTED
        assert config.catalog_size == 50
        assert config.constraint_density == ConstraintDensity.DENSE

    def test_width_factor_validation_min(self):
        """Test that width_factor minimum is validated."""
        with pytest.raises(ValueError, match="width_factor must be >= 1"):
            MetadataComplexityConfig(width_factor=0)

    def test_width_factor_validation_max(self):
        """Test that width_factor maximum is validated."""
        with pytest.raises(ValueError, match="width_factor must be <= 10000"):
            MetadataComplexityConfig(width_factor=20000)

    def test_view_depth_validation_min(self):
        """Test that view_depth minimum is validated."""
        with pytest.raises(ValueError, match="view_depth must be >= 0"):
            MetadataComplexityConfig(view_depth=-1)

    def test_view_depth_validation_max(self):
        """Test that view_depth maximum is validated."""
        with pytest.raises(ValueError, match="view_depth must be <= 10"):
            MetadataComplexityConfig(view_depth=15)

    def test_catalog_size_validation_min(self):
        """Test that catalog_size minimum is validated."""
        with pytest.raises(ValueError, match="catalog_size must be >= 1"):
            MetadataComplexityConfig(catalog_size=0)

    def test_catalog_size_validation_max(self):
        """Test that catalog_size maximum is validated."""
        with pytest.raises(ValueError, match="catalog_size must be <= 5000"):
            MetadataComplexityConfig(catalog_size=10000)

    def test_schema_count_validation(self):
        """Test that schema_count minimum is validated."""
        with pytest.raises(ValueError, match="schema_count must be >= 1"):
            MetadataComplexityConfig(schema_count=0)

    def test_type_complexity_from_string(self):
        """Test that string type_complexity values are converted."""
        config = MetadataComplexityConfig(type_complexity="nested")  # type: ignore
        assert config.type_complexity == TypeComplexity.NESTED

    def test_constraint_density_from_string(self):
        """Test that string constraint_density values are converted."""
        config = MetadataComplexityConfig(constraint_density="sparse")  # type: ignore
        assert config.constraint_density == ConstraintDensity.SPARSE

    def test_to_dict(self):
        """Test serialization to dictionary."""
        config = MetadataComplexityConfig(
            width_factor=100,
            view_depth=2,
            type_complexity=TypeComplexity.BASIC,
        )
        d = config.to_dict()

        assert d["width_factor"] == 100
        assert d["view_depth"] == 2
        assert d["type_complexity"] == "basic"
        assert d["prefix"] == "benchbox_"

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        d = {
            "width_factor": 150,
            "view_depth": 3,
            "type_complexity": "nested",
            "catalog_size": 25,
        }
        config = MetadataComplexityConfig.from_dict(d)

        assert config.width_factor == 150
        assert config.view_depth == 3
        assert config.type_complexity == TypeComplexity.NESTED
        assert config.catalog_size == 25

    def test_from_dict_defaults(self):
        """Test that from_dict uses defaults for missing keys."""
        config = MetadataComplexityConfig.from_dict({})
        assert config.width_factor == 50
        assert config.view_depth == 1


# =============================================================================
# Complexity Presets Tests
# =============================================================================


@pytest.mark.unit
class TestComplexityPresets:
    """Test predefined complexity presets."""

    def test_all_presets_exist(self):
        """Test that all expected presets exist."""
        expected = [
            "minimal",
            "baseline",
            "wide_tables",
            "deep_views",
            "complex_types",
            "large_catalog",
            "full",
            "stress",
        ]
        for preset_name in expected:
            assert preset_name in COMPLEXITY_PRESETS

    def test_get_preset_valid(self):
        """Test getting a valid preset."""
        config = get_complexity_preset("wide_tables")
        assert isinstance(config, MetadataComplexityConfig)
        assert config.width_factor == 500

    def test_get_preset_invalid(self):
        """Test getting an invalid preset raises error."""
        with pytest.raises(ValueError, match="Unknown complexity preset"):
            get_complexity_preset("nonexistent")

    def test_minimal_preset(self):
        """Test minimal preset values."""
        config = get_complexity_preset("minimal")
        assert config.width_factor == 20
        assert config.catalog_size == 5

    def test_stress_preset(self):
        """Test stress preset values."""
        config = get_complexity_preset("stress")
        assert config.width_factor == 1000
        assert config.view_depth == 5
        assert config.type_complexity == TypeComplexity.NESTED
        assert config.catalog_size == 200
        assert config.constraint_density == ConstraintDensity.DENSE


# =============================================================================
# Generated Metadata Tests
# =============================================================================


@pytest.mark.unit
class TestGeneratedMetadata:
    """Test GeneratedMetadata tracking class."""

    def test_default_values(self):
        """Test default values."""
        generated = GeneratedMetadata()
        assert generated.tables == []
        assert generated.views == []
        assert generated.schemas == []
        assert generated.prefix == "benchbox_"
        assert generated.config is None

    def test_total_objects(self):
        """Test total_objects property."""
        generated = GeneratedMetadata(
            tables=["t1", "t2", "t3"],
            views=["v1", "v2"],
            schemas=["s1"],
        )
        assert generated.total_objects == 6

    def test_summary(self):
        """Test summary method."""
        generated = GeneratedMetadata(
            tables=["t1", "t2"],
            views=["v1"],
            prefix="test_",
        )
        summary = generated.summary()

        assert summary["tables"] == 2
        assert summary["views"] == 1
        assert summary["schemas"] == 0
        assert summary["total"] == 3
        assert summary["prefix"] == "test_"


# =============================================================================
# Type Complexity Enum Tests
# =============================================================================


@pytest.mark.unit
class TestTypeComplexity:
    """Test TypeComplexity enum."""

    def test_enum_values(self):
        """Test enum values."""
        assert TypeComplexity.SCALAR.value == "scalar"
        assert TypeComplexity.BASIC.value == "basic"
        assert TypeComplexity.NESTED.value == "nested"


@pytest.mark.unit
class TestConstraintDensity:
    """Test ConstraintDensity enum."""

    def test_enum_values(self):
        """Test enum values."""
        assert ConstraintDensity.NONE.value == "none"
        assert ConstraintDensity.SPARSE.value == "sparse"
        assert ConstraintDensity.DENSE.value == "dense"


# =============================================================================
# DDL Generation Tests
# =============================================================================


@pytest.mark.unit
class TestTypeMappings:
    """Test type mapping functionality."""

    def test_all_dialects_have_mappings(self):
        """Test that all expected dialects have type mappings."""
        expected_dialects = ["duckdb", "snowflake", "bigquery", "clickhouse", "databricks", "postgres"]
        for dialect in expected_dialects:
            assert dialect in TYPE_MAPPINGS

    def test_get_type_mapping_known_dialect(self):
        """Test getting type mapping for known dialect."""
        mapping = get_type_mapping("duckdb")
        assert "integer" in mapping
        assert "varchar" in mapping
        assert mapping["integer"] == "INTEGER"

    def test_get_type_mapping_unknown_dialect(self):
        """Test that unknown dialect falls back to duckdb."""
        mapping = get_type_mapping("unknown_dialect")
        assert mapping == TYPE_MAPPINGS["duckdb"]

    def test_get_type_mapping_case_insensitive(self):
        """Test that dialect lookup is case insensitive."""
        mapping = get_type_mapping("DuckDB")
        assert mapping == TYPE_MAPPINGS["duckdb"]

    def test_map_type_basic(self):
        """Test basic type mapping."""
        assert map_type("integer", "duckdb") == "INTEGER"
        assert map_type("varchar", "snowflake") == "VARCHAR(255)"

    def test_map_type_complex(self):
        """Test complex type mapping."""
        assert map_type("array_int", "duckdb") == "INTEGER[]"
        assert map_type("array_int", "clickhouse") == "Array(Int32)"
        assert map_type("struct_simple", "bigquery") == "STRUCT<key STRING, value STRING>"

    def test_map_type_unknown(self):
        """Test that unknown types fall back to varchar."""
        result = map_type("unknown_type", "duckdb")
        assert result == "VARCHAR(255)"


@pytest.mark.unit
class TestColumnDefinition:
    """Test ColumnDefinition dataclass."""

    def test_default_values(self):
        """Test default column definition values."""
        col = ColumnDefinition(name="test", data_type="INTEGER")
        assert col.name == "test"
        assert col.data_type == "INTEGER"
        assert col.nullable is True
        assert col.primary_key is False

    def test_primary_key_column(self):
        """Test primary key column definition."""
        col = ColumnDefinition(name="id", data_type="BIGINT", nullable=False, primary_key=True)
        assert col.primary_key is True
        assert col.nullable is False


@pytest.mark.unit
class TestTableDefinition:
    """Test TableDefinition dataclass."""

    def test_basic_table(self):
        """Test basic table definition."""
        table = TableDefinition(
            name="test_table",
            columns=[
                ColumnDefinition("id", "BIGINT", nullable=False, primary_key=True),
                ColumnDefinition("name", "VARCHAR(255)"),
            ],
        )
        assert table.name == "test_table"
        assert len(table.columns) == 2
        assert table.schema_name is None


@pytest.mark.unit
class TestGenerateWideTableColumns:
    """Test wide table column generation."""

    def test_generate_columns_count(self):
        """Test that correct number of columns is generated."""
        columns = generate_wide_table_columns(100, "duckdb")
        assert len(columns) == 100

    def test_generate_columns_has_pk(self):
        """Test that generated columns have a primary key."""
        columns = generate_wide_table_columns(50, "duckdb")
        pk_columns = [c for c in columns if c.primary_key]
        assert len(pk_columns) == 1
        assert pk_columns[0].name == "id"

    def test_generate_columns_type_distribution(self):
        """Test that columns have varied types."""
        columns = generate_wide_table_columns(100, "duckdb")
        types = {c.data_type for c in columns}
        # Should have at least 3 different types
        assert len(types) >= 3

    def test_generate_columns_with_complex_types(self):
        """Test generating columns with complex types."""
        columns = generate_wide_table_columns(50, "duckdb", TypeComplexity.BASIC)
        type_names = [c.data_type for c in columns]
        # Should have array types
        assert any("[]" in t for t in type_names)

    def test_generate_columns_with_nested_types(self):
        """Test generating columns with nested types."""
        columns = generate_wide_table_columns(50, "duckdb", TypeComplexity.NESTED)
        type_names = [c.data_type for c in columns]
        # Should have struct types
        assert any("STRUCT" in t for t in type_names)


@pytest.mark.unit
class TestGenerateSimpleTableColumns:
    """Test simple table column generation."""

    def test_generate_minimum_columns(self):
        """Test generating minimum columns."""
        columns = generate_simple_table_columns(5, "duckdb")
        assert len(columns) == 5
        assert columns[0].name == "id"
        assert columns[1].name == "name"

    def test_generate_extra_columns(self):
        """Test generating extra columns beyond base set."""
        columns = generate_simple_table_columns(10, "duckdb")
        assert len(columns) == 10
        # Extra columns should be named field_XX
        extra_names = [c.name for c in columns[5:]]
        assert all(name.startswith("field_") for name in extra_names)


@pytest.mark.unit
class TestGenerateCreateTableSQL:
    """Test CREATE TABLE SQL generation."""

    def test_basic_table(self):
        """Test basic CREATE TABLE generation."""
        columns = [
            ColumnDefinition("id", "BIGINT", nullable=False, primary_key=True),
            ColumnDefinition("name", "VARCHAR(255)"),
        ]
        table = TableDefinition(name="test_table", columns=columns)
        sql = generate_create_table_sql(table, "duckdb")

        assert "CREATE TABLE IF NOT EXISTS test_table" in sql
        assert "id BIGINT NOT NULL" in sql
        assert "name VARCHAR(255)" in sql
        assert "PRIMARY KEY (id)" in sql

    def test_table_without_if_not_exists(self):
        """Test CREATE TABLE without IF NOT EXISTS."""
        columns = [ColumnDefinition("id", "BIGINT")]
        table = TableDefinition(name="test", columns=columns)
        sql = generate_create_table_sql(table, "duckdb", if_not_exists=False)

        assert "IF NOT EXISTS" not in sql
        assert "CREATE TABLE test" in sql

    def test_table_with_schema(self):
        """Test CREATE TABLE with schema name."""
        columns = [ColumnDefinition("id", "BIGINT")]
        table = TableDefinition(name="test", columns=columns, schema_name="myschema")
        sql = generate_create_table_sql(table, "duckdb")

        assert "myschema.test" in sql

    def test_clickhouse_engine(self):
        """Test ClickHouse-specific ENGINE clause."""
        columns = [
            ColumnDefinition("id", "Int64", nullable=False, primary_key=True),
        ]
        table = TableDefinition(name="test", columns=columns)
        sql = generate_create_table_sql(table, "clickhouse")

        assert "ENGINE = MergeTree()" in sql
        assert "ORDER BY (id)" in sql


@pytest.mark.unit
class TestGenerateCreateViewSQL:
    """Test CREATE VIEW SQL generation."""

    def test_basic_view(self):
        """Test basic CREATE VIEW generation."""
        view = ViewDefinition(name="test_view", source_sql="SELECT * FROM base_table")
        sql = generate_create_view_sql(view, "duckdb")

        assert "CREATE OR REPLACE VIEW test_view" in sql
        assert "SELECT * FROM base_table" in sql

    def test_view_without_replace(self):
        """Test CREATE VIEW without OR REPLACE."""
        view = ViewDefinition(name="test_view", source_sql="SELECT 1")
        sql = generate_create_view_sql(view, "duckdb", or_replace=False)

        assert "IF NOT EXISTS" in sql
        assert "OR REPLACE" not in sql


@pytest.mark.unit
class TestDropSQL:
    """Test DROP statement generation."""

    def test_drop_table(self):
        """Test DROP TABLE generation."""
        sql = generate_drop_table_sql("test_table", "duckdb")
        assert sql == "DROP TABLE IF EXISTS test_table;"

    def test_drop_table_without_if_exists(self):
        """Test DROP TABLE without IF EXISTS."""
        sql = generate_drop_table_sql("test_table", "duckdb", if_exists=False)
        assert sql == "DROP TABLE test_table;"

    def test_drop_table_with_schema(self):
        """Test DROP TABLE with schema."""
        sql = generate_drop_table_sql("test_table", "duckdb", schema_name="myschema")
        assert "myschema.test_table" in sql

    def test_drop_view(self):
        """Test DROP VIEW generation."""
        sql = generate_drop_view_sql("test_view", "duckdb")
        assert sql == "DROP VIEW IF EXISTS test_view;"


@pytest.mark.unit
class TestDialectSupport:
    """Test dialect support checks."""

    def test_supports_complex_types(self):
        """Test complex type support detection."""
        assert supports_complex_types("duckdb") is True
        assert supports_complex_types("snowflake") is True
        assert supports_complex_types("bigquery") is True
        assert supports_complex_types("clickhouse") is True
        assert supports_complex_types("databricks") is True
        # Unknown dialect should not support complex types
        assert supports_complex_types("mysql") is False

    def test_supports_views(self):
        """Test view support detection."""
        assert supports_views("duckdb") is True
        assert supports_views("snowflake") is True
        # ClickHouse has limited view support
        assert supports_views("clickhouse") is False

    def test_supports_foreign_keys(self):
        """Test foreign key support detection."""
        assert supports_foreign_keys("duckdb") is True
        assert supports_foreign_keys("snowflake") is True
        assert supports_foreign_keys("bigquery") is False
        assert supports_foreign_keys("clickhouse") is False


# =============================================================================
# MetadataGenerator Tests
# =============================================================================


@pytest.mark.unit
class TestMetadataGenerator:
    """Test MetadataGenerator class (unit tests, no database)."""

    def test_generator_instantiation(self):
        """Test that generator can be instantiated."""
        generator = MetadataGenerator()
        assert isinstance(generator, MetadataGenerator)
        assert hasattr(generator, "setup")


# =============================================================================
# Benchmark Complexity Methods Tests
# =============================================================================


@pytest.mark.unit
class TestBenchmarkComplexityMethods:
    """Test MetadataPrimitivesBenchmark complexity methods."""

    def test_get_complexity_categories(self):
        """Test getting complexity category list."""
        benchmark = MetadataPrimitivesBenchmark()
        categories = benchmark.get_complexity_categories()

        expected = ["wide_table", "view_hierarchy", "complex_type", "large_catalog", "constraint", "acl"]
        assert categories == expected

    def test_get_complexity_categories_for_wide_tables(self):
        """Test auto-selection of categories for wide_tables preset."""
        benchmark = MetadataPrimitivesBenchmark()
        config = get_complexity_preset("wide_tables")
        categories = benchmark._get_complexity_categories(config)

        assert "wide_table" in categories
        assert "large_catalog" in categories

    def test_get_complexity_categories_for_full(self):
        """Test auto-selection of categories for full preset."""
        benchmark = MetadataPrimitivesBenchmark()
        config = get_complexity_preset("full")
        categories = benchmark._get_complexity_categories(config)

        assert "wide_table" in categories
        assert "view_hierarchy" in categories
        assert "large_catalog" in categories
        assert "complex_type" in categories
        assert "constraint" in categories


# =============================================================================
# ComplexityBenchmarkResult Tests
# =============================================================================


@pytest.mark.unit
class TestComplexityBenchmarkResult:
    """Test ComplexityBenchmarkResult dataclass."""

    def test_result_creation(self):
        """Test creating a complexity benchmark result."""
        config = MetadataComplexityConfig()
        generated = GeneratedMetadata(tables=["t1"], views=["v1"])

        result = ComplexityBenchmarkResult(
            complexity_config=config,
            generated_metadata=generated,
            setup_time_ms=100.5,
            teardown_time_ms=50.2,
        )

        assert result.complexity_config == config
        assert result.generated_metadata == generated
        assert result.setup_time_ms == 100.5
        assert result.teardown_time_ms == 50.2
        assert result.benchmark_result is None


# =============================================================================
# Query Category Tests
# =============================================================================


@pytest.mark.unit
class TestComplexityQueryCategories:
    """Test that complexity query categories are properly defined."""

    def test_wide_table_category_exists(self):
        """Test that wide_table category has queries."""
        benchmark = MetadataPrimitivesBenchmark()
        queries = benchmark.get_queries_by_category("wide_table")
        assert len(queries) > 0

    def test_view_hierarchy_category_exists(self):
        """Test that view_hierarchy category has queries."""
        benchmark = MetadataPrimitivesBenchmark()
        queries = benchmark.get_queries_by_category("view_hierarchy")
        assert len(queries) > 0

    def test_complex_type_category_exists(self):
        """Test that complex_type category has queries."""
        benchmark = MetadataPrimitivesBenchmark()
        queries = benchmark.get_queries_by_category("complex_type")
        assert len(queries) > 0

    def test_large_catalog_category_exists(self):
        """Test that large_catalog category has queries."""
        benchmark = MetadataPrimitivesBenchmark()
        queries = benchmark.get_queries_by_category("large_catalog")
        assert len(queries) > 0

    def test_constraint_category_exists(self):
        """Test that constraint category has queries."""
        benchmark = MetadataPrimitivesBenchmark()
        queries = benchmark.get_queries_by_category("constraint")
        assert len(queries) > 0

    def test_all_categories_available(self):
        """Test that all expected categories are available."""
        benchmark = MetadataPrimitivesBenchmark()
        categories = benchmark.get_query_categories()

        # Original categories
        assert "schema" in categories
        assert "column" in categories
        assert "stats" in categories
        assert "query" in categories

        # New complexity categories
        assert "wide_table" in categories
        assert "view_hierarchy" in categories
        assert "complex_type" in categories
        assert "large_catalog" in categories
        assert "constraint" in categories

    def test_acl_category_exists(self):
        """Test that acl category has queries."""
        benchmark = MetadataPrimitivesBenchmark()
        queries = benchmark.get_queries_by_category("acl")
        assert len(queries) > 0
        # Verify expected ACL queries exist
        query_ids = list(queries.keys())
        assert any("privilege" in q for q in query_ids)


# =============================================================================
# ACL Complexity Configuration Tests
# =============================================================================


@pytest.mark.unit
class TestAclComplexityConfig:
    """Test ACL-specific complexity configuration."""

    def test_default_acl_config(self):
        """Test default ACL configuration values."""
        config = MetadataComplexityConfig()
        assert config.acl_role_count == 0
        assert config.acl_permission_density == PermissionDensity.NONE
        assert config.acl_hierarchy_depth == RoleHierarchyDepth.FLAT
        assert config.acl_column_grants is False
        assert config.acl_grant_with_grant_option is False

    def test_acl_config_with_roles(self):
        """Test ACL configuration with roles enabled."""
        config = MetadataComplexityConfig(
            acl_role_count=10,
            acl_permission_density=PermissionDensity.MODERATE,
            acl_hierarchy_depth=RoleHierarchyDepth.SHALLOW,
        )
        assert config.acl_role_count == 10
        assert config.acl_permission_density == PermissionDensity.MODERATE
        assert config.acl_hierarchy_depth == RoleHierarchyDepth.SHALLOW

    def test_acl_config_validation(self):
        """Test ACL configuration validation."""
        # Negative role count should raise
        with pytest.raises(ValueError):
            MetadataComplexityConfig(acl_role_count=-1)

        # Too many roles should raise
        with pytest.raises(ValueError):
            MetadataComplexityConfig(acl_role_count=501)

    def test_acl_config_serialization(self):
        """Test ACL configuration serialization."""
        config = MetadataComplexityConfig(
            acl_role_count=20,
            acl_permission_density=PermissionDensity.DENSE,
            acl_hierarchy_depth=RoleHierarchyDepth.DEEP,
            acl_column_grants=True,
            acl_grant_with_grant_option=True,
        )
        data = config.to_dict()

        assert data["acl_role_count"] == 20
        assert data["acl_permission_density"] == "dense"
        assert data["acl_hierarchy_depth"] == "deep"
        assert data["acl_column_grants"] is True
        assert data["acl_grant_with_grant_option"] is True

    def test_acl_config_deserialization(self):
        """Test ACL configuration deserialization."""
        data = {
            "acl_role_count": 15,
            "acl_permission_density": "sparse",
            "acl_hierarchy_depth": "moderate",
        }
        config = MetadataComplexityConfig.from_dict(data)

        assert config.acl_role_count == 15
        assert config.acl_permission_density == PermissionDensity.SPARSE
        assert config.acl_hierarchy_depth == RoleHierarchyDepth.MODERATE


@pytest.mark.unit
class TestAclPresets:
    """Test ACL complexity presets."""

    def test_acl_sparse_preset(self):
        """Test acl_sparse preset."""
        config = get_complexity_preset("acl_sparse")
        assert config.acl_role_count == 5
        assert config.acl_permission_density == PermissionDensity.SPARSE
        assert config.acl_hierarchy_depth == RoleHierarchyDepth.FLAT

    def test_acl_moderate_preset(self):
        """Test acl_moderate preset."""
        config = get_complexity_preset("acl_moderate")
        assert config.acl_role_count == 20
        assert config.acl_permission_density == PermissionDensity.MODERATE
        assert config.acl_hierarchy_depth == RoleHierarchyDepth.SHALLOW

    def test_acl_dense_preset(self):
        """Test acl_dense preset."""
        config = get_complexity_preset("acl_dense")
        assert config.acl_role_count == 50
        assert config.acl_permission_density == PermissionDensity.DENSE
        assert config.acl_grant_with_grant_option is True

    def test_acl_hierarchy_preset(self):
        """Test acl_hierarchy preset."""
        config = get_complexity_preset("acl_hierarchy")
        assert config.acl_role_count == 30
        assert config.acl_hierarchy_depth == RoleHierarchyDepth.DEEP

    def test_acl_full_preset(self):
        """Test acl_full preset."""
        config = get_complexity_preset("acl_full")
        assert config.acl_role_count == 30
        assert config.acl_column_grants is True
        assert config.acl_grant_with_grant_option is True


@pytest.mark.unit
class TestGeneratedMetadataWithAcl:
    """Test GeneratedMetadata with ACL fields."""

    def test_generated_metadata_with_roles(self):
        """Test GeneratedMetadata includes roles in count."""

        metadata = GeneratedMetadata(
            tables=["t1", "t2"],
            roles=["r1", "r2", "r3"],
        )
        # total_objects includes tables + roles
        assert metadata.total_objects == 5

    def test_generated_metadata_with_grants(self):
        """Test GeneratedMetadata tracks grants."""
        from benchbox.core.metadata_primitives import AclGrant

        grants = [
            AclGrant("r1", "table", "t1", ["SELECT"]),
            AclGrant("r2", "table", "t1", ["SELECT", "INSERT"]),
        ]
        metadata = GeneratedMetadata(
            tables=["t1"],
            grants=grants,
        )
        assert metadata.total_grants == 2
        assert metadata.summary()["grants"] == 2

    def test_generated_metadata_summary_with_acl(self):
        """Test GeneratedMetadata summary includes ACL info."""
        from benchbox.core.metadata_primitives import AclGrant

        metadata = GeneratedMetadata(
            tables=["t1"],
            views=["v1"],
            roles=["r1"],
            grants=[AclGrant("r1", "table", "t1", ["SELECT"])],
        )
        summary = metadata.summary()

        assert summary["tables"] == 1
        assert summary["views"] == 1
        assert summary["roles"] == 1
        assert summary["grants"] == 1
        assert summary["total"] == 3  # tables + views + roles
