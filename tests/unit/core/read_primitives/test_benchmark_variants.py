"""Test Read Primitives benchmark integration with query variants.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.read_primitives.benchmark import ReadPrimitivesBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestBenchmarkVariantIntegration:
    """Test benchmark get_queries() integration with variant system."""

    @pytest.fixture
    def mock_catalog_with_variants(self, monkeypatch, tmp_path):
        """Create a mock catalog with variant queries for testing."""
        catalog_yaml = """
version: 1
queries:
  - id: query_base_only
    category: test
    sql: SELECT * FROM orders

  - id: query_with_duckdb_variant
    category: test
    sql: SELECT * FROM orders
    variants:
      duckdb: SELECT order_id FROM orders USING SAMPLE 10%

  - id: query_with_clickhouse_variant
    category: test
    sql: SELECT CARDINALITY(parts) AS part_count FROM supplier_parts
    variants:
      clickhouse: SELECT length(parts) AS part_count FROM supplier_parts

  - id: query_skip_on_duckdb
    category: test
    sql: SELECT JSON_EXTRACT(data, '$.field') FROM table
    skip_on: [duckdb]

  - id: query_with_multiple_variants
    category: test
    sql: SELECT * FROM orders
    variants:
      duckdb: SELECT * FROM orders USING SAMPLE 10%
      bigquery: SELECT * FROM `orders` TABLESAMPLE SYSTEM (10 PERCENT)
"""
        catalog_file = tmp_path / "queries.yaml"
        catalog_file.write_text(catalog_yaml)

        import importlib.resources

        class MockPath:
            def __init__(self, path):
                self.path = path

            def joinpath(self, name):
                return self.path / name

            def open(self, *args, **kwargs):
                return open(self.path / "queries.yaml", *args, **kwargs)

        monkeypatch.setattr(importlib.resources, "files", lambda pkg: MockPath(tmp_path))

    def test_get_queries_without_dialect_returns_all_base_queries(self, mock_catalog_with_variants):
        """Test get_queries() without dialect returns all base queries."""
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries()

        # Should have all 5 queries (no skip_on without dialect)
        assert len(queries) == 5
        assert "query_base_only" in queries
        assert "query_with_duckdb_variant" in queries
        assert "query_with_clickhouse_variant" in queries
        assert "query_skip_on_duckdb" in queries
        assert "query_with_multiple_variants" in queries

        # All should be base SQL (no variants without dialect)
        assert "USING SAMPLE" not in queries["query_with_duckdb_variant"]
        assert "length(parts)" not in queries["query_with_clickhouse_variant"]
        assert "TABLESAMPLE" not in queries["query_with_multiple_variants"]

    def test_get_queries_with_dialect_skips_skip_on_queries(self, mock_catalog_with_variants):
        """Test get_queries() with dialect skips queries marked skip_on."""
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries(dialect="duckdb")

        # Should have 4 queries (skip_on_duckdb excluded)
        assert len(queries) == 4
        assert "query_base_only" in queries
        assert "query_with_duckdb_variant" in queries
        assert "query_with_clickhouse_variant" in queries
        assert "query_with_multiple_variants" in queries
        assert "query_skip_on_duckdb" not in queries  # Skipped!

    def test_get_queries_with_dialect_uses_variants(self, mock_catalog_with_variants):
        """Test get_queries() with dialect returns variant SQL when available."""
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries(dialect="duckdb")

        # Should use DuckDB variant for query_with_duckdb_variant verbatim (final SQL).
        assert "USING SAMPLE" in queries["query_with_duckdb_variant"]
        # Variant is returned as-is - SQLGlot does not re-quote identifiers.
        assert '"order_id"' not in queries["query_with_duckdb_variant"]

        # Should use DuckDB variant for query_with_multiple_variants
        assert "USING SAMPLE" in queries["query_with_multiple_variants"]

        # Should use base SQL for query_base_only (no variant) - still translated.
        assert "orders" in queries["query_base_only"].lower()

    def test_get_queries_with_non_matching_dialect(self, mock_catalog_with_variants):
        """Test get_queries() with dialect that has no variants uses base SQL."""
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries(dialect="snowflake")

        # Should have all queries except skip_on (snowflake not in skip_on list)
        assert len(queries) == 5

        # All should be base SQL (no snowflake variants defined)
        # identify=True adds quotes, so check for "orders" (quoted or not)
        assert "orders" in queries["query_with_duckdb_variant"].lower()
        assert "USING SAMPLE" not in queries["query_with_duckdb_variant"].upper()

    def test_get_queries_with_bigquery_uses_correct_variant(self, mock_catalog_with_variants):
        """Test get_queries() returns correct variant for BigQuery."""
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries(dialect="bigquery")

        # Should use BigQuery variant
        assert "TABLESAMPLE SYSTEM" in queries["query_with_multiple_variants"]
        # Should not use DuckDB variant
        assert "USING SAMPLE" not in queries["query_with_multiple_variants"]

    def test_get_queries_skip_on_case_insensitive(self, mock_catalog_with_variants):
        """Test skip_on matching is case-insensitive."""
        benchmark = ReadPrimitivesBenchmark()

        queries_lower = benchmark.get_queries(dialect="duckdb")
        queries_upper = benchmark.get_queries(dialect="DUCKDB")
        queries_mixed = benchmark.get_queries(dialect="DuckDB")

        # All should skip the same query
        assert "query_skip_on_duckdb" not in queries_lower
        assert "query_skip_on_duckdb" not in queries_upper
        assert "query_skip_on_duckdb" not in queries_mixed

        # All should have the same number of queries
        assert len(queries_lower) == len(queries_upper) == len(queries_mixed) == 4

    def test_get_queries_keeps_clickhouse_variant_verbatim(self, mock_catalog_with_variants):
        """Test ClickHouse variants bypass SQLGlot re-translation."""
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries(dialect="clickhouse")

        assert queries["query_with_clickhouse_variant"] == "SELECT length(parts) AS part_count FROM supplier_parts"
        assert "CHAR_LENGTH" not in queries["query_with_clickhouse_variant"]


class TestBenchmarkVariantEdgeCases:
    """Test edge cases and error handling in benchmark variant integration."""

    def test_get_queries_handles_empty_variants_dict(self, monkeypatch, tmp_path):
        """Test get_queries() handles query with empty variants dict."""
        catalog_yaml = """
version: 1
queries:
  - id: test_query
    category: test
    sql: SELECT 1
    variants: {}
"""
        catalog_file = tmp_path / "queries.yaml"
        catalog_file.write_text(catalog_yaml)

        import importlib.resources

        class MockPath:
            def __init__(self, path):
                self.path = path

            def joinpath(self, name):
                return self.path / name

            def open(self, *args, **kwargs):
                return open(self.path / "queries.yaml", *args, **kwargs)

        monkeypatch.setattr(importlib.resources, "files", lambda pkg: MockPath(tmp_path))

        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries(dialect="duckdb")

        # Should return base query
        assert "test_query" in queries
        assert queries["test_query"] == "SELECT 1"

    def test_get_queries_handles_empty_skip_on_list(self, monkeypatch, tmp_path):
        """Test get_queries() handles query with empty skip_on list."""
        catalog_yaml = """
version: 1
queries:
  - id: test_query
    category: test
    sql: SELECT 1
    skip_on: []
"""
        catalog_file = tmp_path / "queries.yaml"
        catalog_file.write_text(catalog_yaml)

        import importlib.resources

        class MockPath:
            def __init__(self, path):
                self.path = path

            def joinpath(self, name):
                return self.path / name

            def open(self, *args, **kwargs):
                return open(self.path / "queries.yaml", *args, **kwargs)

        monkeypatch.setattr(importlib.resources, "files", lambda pkg: MockPath(tmp_path))

        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries(dialect="duckdb")

        # Should include query (empty skip_on means no skipping)
        assert "test_query" in queries


class TestBenchmarkWithActualCatalog:
    """Test benchmark behavior with the actual production catalog."""

    def test_get_queries_returns_all_queries_without_dialect(self):
        """Test get_queries() returns all queries when no dialect specified."""
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries()

        # Should have all queries (136 as of December 2025 with modern SQL features)
        assert len(queries) >= 136

    def test_get_queries_with_duckdb_skips_known_non_comparable_queries(self):
        """Test DuckDB skips queries that cannot be compared with base semantics."""
        benchmark = ReadPrimitivesBenchmark()

        queries_duckdb = benchmark.get_queries(dialect="duckdb")

        # json_extract_simple is skipped on DuckDB (TPC-H data contains plain text, not JSON)
        # Fulltext MATCH...AGAINST queries are skipped because LIKE fallbacks are not equivalent.
        duckdb_skipped = {
            "fulltext_simple_search",
            "fulltext_boolean_search",
            "fulltext_phrase_search",
            "json_extract_simple",
        }
        assert duckdb_skipped.isdisjoint(queries_duckdb)

    def test_duckdb_array_of_struct_variant_preserves_inner_order(self):
        """DuckDB reference SQL must sort line-item structs inside each aggregated array."""
        benchmark = ReadPrimitivesBenchmark()

        queries_duckdb = benchmark.get_queries(dialect="duckdb")
        array_sql = queries_duckdb["array_of_struct"].lower()

        assert "struct_pack" in array_sql
        assert "order by l_linenumber" in array_sql

    @pytest.mark.parametrize("dialect", ["bigquery", "databricks", "snowflake"])
    def test_cloud_dialects_skip_mysql_fulltext_queries(self, dialect):
        """MySQL MATCH...AGAINST full-text queries should not reach non-MySQL translators."""
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries(dialect=dialect)

        assert "fulltext_simple_search" not in queries
        assert "fulltext_boolean_search" not in queries
        assert "fulltext_phrase_search" not in queries

    def test_clickhouse_keeps_timeout_only_query_available(self):
        """Timeout-only ClickHouse queries should remain runnable unless truly unsupported."""
        benchmark = ReadPrimitivesBenchmark()

        queries_clickhouse = benchmark.get_queries(dialect="clickhouse")

        assert "aggregation_groupby_large" in queries_clickhouse

    def test_clickhouse_uses_native_array_length_variant(self):
        """ClickHouse variants should preserve native syntax that sqlglot mangles."""
        benchmark = ReadPrimitivesBenchmark()

        queries_clickhouse = benchmark.get_queries(dialect="clickhouse")

        assert "array_length" in queries_clickhouse
        assert "length(parts)" in queries_clickhouse["array_length"]
        assert "CHAR_LENGTH" not in queries_clickhouse["array_length"]

    def test_snowflake_variant_bypasses_translation(self, monkeypatch):
        """Snowflake catalog variants should not be re-run through SQLGlot."""
        benchmark = ReadPrimitivesBenchmark()
        snowflake_variant = benchmark.query_manager.get_query("asof_join_basic", dialect="snowflake")
        translated_inputs: list[tuple[str, str]] = []
        original_translate = benchmark.translate_query_text

        def tracking_translate(query_text: str, target_dialect: str) -> str:
            translated_inputs.append((query_text, target_dialect))
            return original_translate(query_text, target_dialect)

        monkeypatch.setattr(benchmark, "translate_query_text", tracking_translate)

        queries_snowflake = benchmark.get_queries(dialect="snowflake")

        assert translated_inputs
        assert queries_snowflake["asof_join_basic"] == snowflake_variant
        assert (snowflake_variant, "snowflake") not in translated_inputs
        assert "MATCH_CONDITION" in queries_snowflake["asof_join_basic"].upper()

    def test_get_queries_with_duckdb_translates_correctly(self):
        """Test DuckDB dialect translation works."""
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries(dialect="duckdb")

        # Should have translated queries
        assert len(queries) > 0

        # Queries should contain SQL
        for query_id, query_sql in queries.items():
            assert query_sql
            assert len(query_sql) > 0
            assert "SELECT" in query_sql.upper() or "WITH" in query_sql.upper()


class TestModernSQLFeatures:
    """Test the modern SQL features added in December 2025."""

    def test_catalog_has_any_value_queries(self):
        """Test that ANY_VALUE aggregate function queries exist."""
        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries()

        assert "any_value_simple" in queries
        assert "any_value_with_filter" in queries
        assert "ANY_VALUE" in queries["any_value_simple"].upper()

    def test_catalog_has_group_by_all_queries(self):
        """Test that GROUP BY ALL queries exist."""
        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries()

        assert "groupby_all_simple" in queries
        assert "groupby_all_complex" in queries
        assert "GROUP BY ALL" in queries["groupby_all_simple"].upper()

    def test_catalog_has_order_by_all_queries(self):
        """Test that ORDER BY ALL queries exist."""
        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries()

        assert "orderby_all_simple" in queries
        assert "orderby_all_desc" in queries
        assert "ORDER BY ALL" in queries["orderby_all_simple"].upper()

    def test_duckdb_translation_preserves_group_order_by_all_keyword(self):
        """Test DuckDB translation does not quote GROUP/ORDER BY ALL as identifiers."""
        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries(dialect="duckdb")

        assert "groupby_all_simple" in queries
        assert "orderby_all_simple" in queries

        groupby_sql = queries["groupby_all_simple"].upper()
        orderby_sql = queries["orderby_all_simple"].upper()

        assert "GROUP BY ALL" in groupby_sql
        assert 'GROUP BY "ALL"' not in groupby_sql
        assert "ORDER BY ALL" in orderby_sql
        assert 'ORDER BY "ALL"' not in orderby_sql

    def test_catalog_has_array_queries(self):
        """Test that ARRAY type operation queries exist."""
        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries()

        array_queries = [
            "array_agg_simple",
            "array_agg_distinct",
            "array_unnest",
            "array_contains",
            "array_length",
            "array_slice",
            "array_min_max",
            "array_sort",
            "array_distinct",
        ]
        for qid in array_queries:
            assert qid in queries, f"Missing array query: {qid}"

    def test_catalog_has_struct_queries(self):
        """Test that STRUCT type operation queries exist."""
        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries()

        struct_queries = ["struct_construction", "struct_access", "array_of_struct"]
        for qid in struct_queries:
            assert qid in queries, f"Missing struct query: {qid}"

    def test_catalog_has_map_queries(self):
        """Test that MAP type operation queries exist."""
        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries()

        map_queries = ["map_construction", "map_access", "map_keys_values"]
        for qid in map_queries:
            assert qid in queries, f"Missing map query: {qid}"

    def test_catalog_has_lambda_queries(self):
        """Test that higher-order function (lambda) queries exist."""
        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries()

        lambda_queries = ["list_transform", "list_filter", "list_reduce"]
        for qid in lambda_queries:
            assert qid in queries, f"Missing lambda query: {qid}"

    def test_catalog_has_asof_join_query(self):
        """Test that ASOF JOIN query exists."""
        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries()

        assert "asof_join_basic" in queries
        assert "ASOF JOIN" in queries["asof_join_basic"].upper()

    def test_catalog_has_pivot_queries(self):
        """Test that PIVOT/UNPIVOT queries exist."""
        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries()

        assert "pivot_basic" in queries
        assert "unpivot_basic" in queries
        assert "PIVOT" in queries["pivot_basic"].upper()
        assert "UNPIVOT" in queries["unpivot_basic"].upper()

    def test_bigquery_skips_unsupported_queries(self):
        """Test that BigQuery dialect skips unsupported modern SQL features."""
        benchmark = ReadPrimitivesBenchmark()
        queries_bigquery = benchmark.get_queries(dialect="bigquery")

        # BigQuery should skip MAP, lambda, and some array functions
        bigquery_skipped = [
            "fulltext_simple_search",
            "fulltext_boolean_search",
            "fulltext_phrase_search",
            "map_construction",
            "map_access",
            "map_keys_values",
            "list_transform",
            "list_filter",
            "list_reduce",
            "array_min_max",
            "array_sort",
            "array_distinct",
            "asof_join_basic",  # ASOF JOIN not supported
        ]
        for qid in bigquery_skipped:
            assert qid not in queries_bigquery, f"BigQuery should skip: {qid}"

    def test_clickhouse_skips_pivot_queries(self):
        """Test that ClickHouse dialect skips PIVOT/UNPIVOT queries."""
        benchmark = ReadPrimitivesBenchmark()
        queries_clickhouse = benchmark.get_queries(dialect="clickhouse")

        # ClickHouse should skip PIVOT/UNPIVOT
        clickhouse_skipped = ["pivot_basic", "unpivot_basic"]
        for qid in clickhouse_skipped:
            assert qid not in queries_clickhouse, f"ClickHouse should skip: {qid}"

    def test_clickhouse_skips_non_comparable_scalar_fallbacks(self):
        """ClickHouse should skip scalar rewrites that change the measured capability."""
        benchmark = ReadPrimitivesBenchmark()
        queries_clickhouse = benchmark.get_queries(dialect="clickhouse")

        clickhouse_skipped = [
            "intrinsic_appx_median",
            "window_moving_frame",
            "fulltext_simple_search",
            "fulltext_boolean_search",
            "fulltext_phrase_search",
            "statistical_percentiles",
        ]
        for qid in clickhouse_skipped:
            assert qid not in queries_clickhouse, f"ClickHouse should skip: {qid}"

    def test_datafusion_skips_non_comparable_any_value_fallbacks(self):
        """DataFusion should skip MIN fallbacks for arbitrary-value aggregate queries."""
        benchmark = ReadPrimitivesBenchmark()
        queries_datafusion = benchmark.get_queries(dialect="datafusion")

        assert "any_value_simple" not in queries_datafusion
        assert "any_value_with_filter" not in queries_datafusion

    def test_duckdb_uses_list_functions_for_arrays(self):
        """Test that DuckDB dialect uses list_* functions for array operations."""
        benchmark = ReadPrimitivesBenchmark()
        queries_duckdb = benchmark.get_queries(dialect="duckdb")

        # DuckDB should use list_contains instead of ARRAY_CONTAINS
        array_contains_sql = queries_duckdb.get("array_contains", "")
        assert "list_contains" in array_contains_sql.lower()

        # DuckDB should use list_min/list_max
        array_min_max_sql = queries_duckdb.get("array_min_max", "")
        assert "list_min" in array_min_max_sql.lower()
        assert "list_max" in array_min_max_sql.lower()

    def test_redshift_skips_only_semantically_inexact_window_queries(self):
        """Test Redshift skips window queries whose exact semantics cannot be preserved."""
        benchmark = ReadPrimitivesBenchmark()
        queries_redshift = benchmark.get_queries(dialect="redshift")

        assert "window_moving_frame" not in queries_redshift
        assert "window_running_sum" not in queries_redshift

    def test_redshift_skips_unsupported_statistical_functions(self):
        """Test Redshift skips queries using CORR/COVAR/REGR_* - absent from Redshift catalog."""
        benchmark = ReadPrimitivesBenchmark()
        queries_redshift = benchmark.get_queries(dialect="redshift")

        assert "statistical_correlation" not in queries_redshift
        assert "timeseries_trend_analysis" not in queries_redshift

    def test_redshift_percentile_variant_preserves_group_cardinality(self):
        """Redshift percentile window rewrite should still emit one row per base group."""
        benchmark = ReadPrimitivesBenchmark()
        queries_redshift = benchmark.get_queries(dialect="redshift")

        percentile_sql = queries_redshift["statistical_percentiles"].upper()

        assert "SELECT DISTINCT" in percentile_sql
        assert "OVER (PARTITION BY" in percentile_sql

    def test_redshift_skips_non_comparable_array_scalar_fallbacks(self):
        """Redshift should skip array queries when only scalar rewrites are available."""
        benchmark = ReadPrimitivesBenchmark()
        queries_redshift = benchmark.get_queries(dialect="redshift")

        redshift_skipped = [
            "array_contains",
            "array_length",
            "array_min_max",
        ]
        for qid in redshift_skipped:
            assert qid not in queries_redshift, f"Redshift should skip: {qid}"

    def test_datafusion_skips_non_comparable_semistructured_fallbacks(self):
        """DataFusion should skip variants that do not exercise nested/list semantics."""
        benchmark = ReadPrimitivesBenchmark()
        queries_datafusion = benchmark.get_queries(dialect="datafusion")

        datafusion_skipped = [
            "array_contains",
            "array_length",
            "array_min_max",
            "array_distinct",
            "list_transform",
            "list_filter",
            "list_reduce",
            "asof_join_basic",
        ]
        for qid in datafusion_skipped:
            assert qid not in queries_datafusion, f"DataFusion should skip: {qid}"

    def test_duckdb_uses_row_for_struct(self):
        """Test that DuckDB dialect uses ROW() for struct construction."""
        benchmark = ReadPrimitivesBenchmark()
        queries_duckdb = benchmark.get_queries(dialect="duckdb")

        struct_sql = queries_duckdb.get("struct_construction", "")
        assert "ROW(" in struct_sql

    def test_new_categories_exist(self):
        """Test that new categories are properly indexed."""
        from benchbox.core.read_primitives.catalog.loader import load_primitives_catalog

        catalog = load_primitives_catalog()

        categories = set(q.category for q in catalog.queries.values())

        new_categories = ["array", "struct", "map", "lambda", "pivot"]
        for cat in new_categories:
            assert cat in categories, f"Missing category: {cat}"

    def test_all_new_queries_have_valid_sql(self):
        """Test that all new queries have valid SQL structure."""
        benchmark = ReadPrimitivesBenchmark()
        queries = benchmark.get_queries()

        new_query_ids = [
            "any_value_simple",
            "any_value_with_filter",
            "groupby_all_simple",
            "groupby_all_complex",
            "orderby_all_simple",
            "orderby_all_desc",
            "array_agg_simple",
            "array_agg_distinct",
            "array_unnest",
            "array_contains",
            "array_length",
            "array_slice",
            "array_min_max",
            "array_sort",
            "array_distinct",
            "struct_construction",
            "struct_access",
            "array_of_struct",
            "map_construction",
            "map_access",
            "map_keys_values",
            "list_transform",
            "list_filter",
            "list_reduce",
            "asof_join_basic",
            "pivot_basic",
            "unpivot_basic",
        ]

        for qid in new_query_ids:
            assert qid in queries, f"Missing query: {qid}"
            sql = queries[qid]
            assert sql and len(sql.strip()) > 0, f"Empty SQL for: {qid}"
            # All queries should have SELECT (directly or in CTE)
            assert "SELECT" in sql.upper(), f"No SELECT in: {qid}"
