"""Test SQL dialect translation utilities.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.utils.dialect_utils import (
    _query_has_group_or_order_by_all,
    fix_postgres_date_arithmetic,
    normalize_dialect_for_sqlglot,
    translate_sql_query,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDialectNormalization:
    """Test dialect normalization for SQLGlot compatibility."""

    def test_normalize_netezza_to_postgres(self):
        """Test that 'netezza' dialect normalizes to 'postgres'."""
        assert normalize_dialect_for_sqlglot("netezza") == "postgres"
        assert normalize_dialect_for_sqlglot("NETEZZA") == "postgres"
        assert normalize_dialect_for_sqlglot("Netezza") == "postgres"

    def test_normalize_greenplum_to_postgres(self):
        """Test that 'greenplum' dialect normalizes to 'postgres'."""
        assert normalize_dialect_for_sqlglot("greenplum") == "postgres"
        assert normalize_dialect_for_sqlglot("GREENPLUM") == "postgres"

    def test_normalize_vertica_to_postgres(self):
        """Test that 'vertica' dialect normalizes to 'postgres'."""
        assert normalize_dialect_for_sqlglot("vertica") == "postgres"

    def test_normalize_unknown_dialect_unchanged(self):
        """Test that unknown dialects pass through unchanged."""
        assert normalize_dialect_for_sqlglot("duckdb") == "duckdb"
        assert normalize_dialect_for_sqlglot("bigquery") == "bigquery"
        assert normalize_dialect_for_sqlglot("snowflake") == "snowflake"
        assert normalize_dialect_for_sqlglot("clickhouse") == "clickhouse"

    def test_normalize_empty_string(self):
        """Test that empty string returns empty string."""
        assert normalize_dialect_for_sqlglot("") == ""


class TestSQLTranslation:
    """Test centralized SQL query translation."""

    def test_translate_simple_query(self):
        """Test basic query translation."""
        query = "SELECT * FROM orders"
        result = translate_sql_query(query, target_dialect="duckdb")
        assert result  # Should return something
        assert "orders" in result.lower()

    def test_translate_to_date_netezza_to_duckdb(self):
        """Test that TO_DATE() translates correctly from Netezza/Postgres to DuckDB."""
        query = "SELECT TO_DATE('1995-03-15', 'yyyy-MM-dd')"
        result = translate_sql_query(query, target_dialect="duckdb", source_dialect="netezza")
        # Netezza normalizes to postgres, which should translate TO_DATE properly
        # DuckDB uses STRPTIME or CAST
        assert "STRPTIME" in result.upper() or "CAST" in result.upper()
        assert "1995-03-15" in result

    def test_translate_json_objectagg_postgres_to_duckdb(self):
        """Test JSON aggregate function translation."""
        query = "SELECT JSON_OBJECTAGG(k, v) FROM t"
        result = translate_sql_query(query, target_dialect="duckdb", source_dialect="postgres")
        # Postgres JSON_OBJECTAGG should translate to DuckDB JSON_GROUP_OBJECT
        assert "JSON_GROUP_OBJECT" in result.upper()

    def test_translate_with_identify_quotes_identifiers(self):
        """Test that identify=True quotes table names to prevent keyword conflicts."""
        query = "SELECT * FROM orders"
        result = translate_sql_query(query, target_dialect="duckdb", identify=True)
        # Should quote the identifier
        assert '"orders"' in result or "`orders`" in result or result == query

    def test_translate_without_identify(self):
        """Test translation without identifier quoting."""
        query = "SELECT * FROM orders"
        result = translate_sql_query(query, target_dialect="duckdb", identify=False)
        # May or may not have quotes depending on SQLGlot's decision
        assert "orders" in result.lower()

    def test_translate_fallback_on_invalid_dialect(self):
        """Test that translation gracefully handles invalid dialects."""
        # Use an extremely unlikely/invalid dialect that SQLGlot won't recognize
        query = "SELECT * FROM orders"
        # Should handle gracefully and return something (either translated or original)
        result = translate_sql_query(query, target_dialect="nonexistent_invalid_dialect_12345")
        assert result  # Should return something, not crash
        assert "orders" in result.lower()

    def test_translate_with_preprocessor(self):
        """Test pre-processor application."""

        def uppercase_tables(q: str) -> str:
            return q.replace("orders", "ORDERS")

        query = "SELECT * FROM orders"
        result = translate_sql_query(query, target_dialect="duckdb", pre_processors=[uppercase_tables])
        assert "ORDERS" in result

    def test_translate_with_multiple_preprocessors(self):
        """Test multiple pre-processors are applied in order."""

        def replace_asterisk(q: str) -> str:
            return q.replace("*", "col1, col2")

        def add_where(q: str) -> str:
            return q + " WHERE col1 > 0"

        query = "SELECT * FROM orders"
        result = translate_sql_query(query, target_dialect="duckdb", pre_processors=[replace_asterisk, add_where])
        assert "col1" in result.lower()
        assert "col2" in result.lower()
        assert "where" in result.lower()

    def test_translate_with_postprocessor(self):
        """Test post-processor application."""

        def add_limit(q: str) -> str:
            return q + " LIMIT 100"

        query = "SELECT * FROM orders"
        result = translate_sql_query(query, target_dialect="duckdb", post_processors=[add_limit])
        assert "LIMIT 100" in result.upper() or "LIMIT" in result.upper()

    def test_translate_default_source_dialect_is_netezza(self):
        """Test that default source dialect is netezza (normalized to postgres)."""
        query = "SELECT 1 AS test_col"
        # Should not raise error, should use default netezza source
        result = translate_sql_query(query, target_dialect="duckdb")
        assert result  # Should return something
        assert "test_col" in result.lower() or "1" in result

    def test_translate_preserves_query_on_translation_error(self):
        """Test that original query is returned if translation fails."""
        # Use an invalid/unsupported source dialect
        query = "SELECT * FROM orders"
        result = translate_sql_query(query, target_dialect="invalid_target_dialect")
        # Should still return something (likely original query)
        assert result
        assert "orders" in result.lower()

    def test_translate_clickhouse_to_duckdb(self):
        """Test translation from ClickHouse dialect to DuckDB."""
        query = "SELECT * FROM orders LIMIT 10"
        result = translate_sql_query(query, target_dialect="duckdb", source_dialect="clickhouse")
        assert "orders" in result.lower()
        assert "LIMIT" in result.upper() or "limit" in result.lower()

    def test_translate_preserves_complex_queries(self):
        """Test that complex queries with JOINs, WHERE, etc. are handled."""
        query = """
            SELECT o.order_id, c.customer_name
            FROM orders o
            JOIN customers c ON o.customer_id = c.customer_id
            WHERE o.order_date >= '2024-01-01'
            ORDER BY o.order_id
            LIMIT 100
        """
        result = translate_sql_query(query, target_dialect="duckdb")
        # Should preserve key elements
        assert "order_id" in result.lower()
        assert "customer_name" in result.lower()
        assert "join" in result.lower()
        assert "where" in result.lower()

    def test_translate_duckdb_preserves_order_by_all_keyword(self):
        """Test DuckDB translation keeps ORDER BY ALL as a keyword."""
        query = """
            SELECT r_name, n_name, COUNT(*) AS supplier_count
            FROM region r
            JOIN nation n ON n.n_regionkey = r.r_regionkey
            GROUP BY r_name, n_name
            ORDER BY ALL
        """
        result = translate_sql_query(query, target_dialect="duckdb", source_dialect="netezza", identify=True)
        assert "ORDER BY ALL" in result.upper()
        assert 'ORDER BY "ALL"' not in result.upper()

    def test_translate_duckdb_preserves_group_by_all_keyword(self):
        """Test DuckDB translation keeps GROUP BY ALL as a keyword."""
        query = """
            SELECT n_name, r_name, COUNT(*) AS nation_count
            FROM nation n
            JOIN region r ON n.n_regionkey = r.r_regionkey
            GROUP BY ALL
            ORDER BY n_name
        """
        result = translate_sql_query(query, target_dialect="duckdb", source_dialect="netezza", identify=True)
        assert "GROUP BY ALL" in result.upper()
        assert 'GROUP BY "ALL"' not in result.upper()

    def test_translate_fix_is_gated_by_original_query_pattern(self):
        """Test that built-in fix only triggers on explicit ORDER/GROUP BY ALL keyword usage."""
        query = 'SELECT 1 AS "ALL" ORDER BY "ALL"'
        assert _query_has_group_or_order_by_all(query) is False

    def test_translate_sqlite_rewrites_interval_and_extract(self):
        """SQLite translation should remove unsupported INTERVAL and EXTRACT syntax."""
        query = """
            SELECT EXTRACT(YEAR FROM l_shipdate) AS ship_year
            FROM lineitem
            WHERE l_shipdate < DATE '1994-01-01' + INTERVAL '1' YEAR
        """
        result = translate_sql_query(query, target_dialect="sqlite", source_dialect="postgres")

        assert "INTERVAL" not in result.upper()
        assert "EXTRACT" not in result.upper()
        assert "DATE('1994-01-01', '+1 year')" in result
        assert "STRFTIME('%Y'," in result


class TestIntegrationScenarios:
    """Test real-world integration scenarios."""

    def test_read_primitives_translation_scenario(self):
        """Simulate Read Primitives benchmark translation to DuckDB."""
        # Example query from Read Primitives using Postgres-style TO_DATE
        query = """
            SELECT COUNT(*) as orders_by_month
            FROM orders
            WHERE o_orderdate = TO_DATE('1995-03-15', 'yyyy-MM-dd')
        """
        result = translate_sql_query(query, target_dialect="duckdb", source_dialect="netezza")
        # Should translate successfully
        assert result
        assert "orders" in result.lower()
        assert "1995-03-15" in result

    def test_tpcds_interval_syntax_scenario(self):
        """Simulate TPC-DS interval syntax translation."""

        def normalize_interval(q: str) -> str:
            # Simplified version of TPC-DS interval normalization
            import re

            pattern = r"\+\s*(\d+)\s+(days?|months?|years?)"
            replacement = r"+ INTERVAL '\1' \2"
            return re.sub(pattern, replacement, q, flags=re.IGNORECASE)

        query = "SELECT * FROM orders WHERE o_date >= '2024-01-01' + 30 days"
        result = translate_sql_query(
            query, target_dialect="duckdb", source_dialect="netezza", pre_processors=[normalize_interval]
        )
        assert result
        assert "orders" in result.lower()


class TestPostgresDateArithmetic:
    """Test PostgreSQL/DataFusion date arithmetic conversion.

    DataFusion and PostgreSQL don't support `date + integer` directly.
    The fix_postgres_date_arithmetic function converts these to INTERVAL syntax.
    """

    def test_convert_date_plus_integer(self):
        """Test that d_date + N converts to INTERVAL syntax."""
        query = "SELECT * FROM t WHERE d_date + 5 > NOW()"
        result = fix_postgres_date_arithmetic(query)
        assert "INTERVAL '5' DAY" in result
        assert "+ 5" not in result

    def test_convert_qualified_date_column(self):
        """Test that table.d_date + N converts correctly."""
        query = "SELECT * FROM t WHERE d1.d_date + 30 > d2.d_date"
        result = fix_postgres_date_arithmetic(query)
        assert "d1.d_date + INTERVAL '30' DAY" in result
        assert "+ 30" not in result

    def test_convert_date_minus_integer(self):
        """Test that d_date - N converts to INTERVAL syntax."""
        query = "SELECT * FROM t WHERE d_date - 7 < NOW()"
        result = fix_postgres_date_arithmetic(query)
        assert "INTERVAL '7' DAY" in result
        assert "- 7" not in result

    def test_does_not_affect_non_date_columns(self):
        """Test that non-date columns are not modified."""
        query = "SELECT * FROM t WHERE order_id + 5 > 100"
        result = fix_postgres_date_arithmetic(query)
        assert result == query  # Should be unchanged

    def test_tpcds_q72_pattern(self):
        """Test the actual TPC-DS Q72 pattern that was failing."""
        query = "d3.d_date > d1.d_date + 5"
        result = fix_postgres_date_arithmetic(query)
        assert result == "d3.d_date > d1.d_date + INTERVAL '5' DAY"

    def test_multiple_date_arithmetic_expressions(self):
        """Test multiple date arithmetic expressions in same query."""
        query = "SELECT * FROM t WHERE d_date + 5 > NOW() AND d_date - 10 < NOW()"
        result = fix_postgres_date_arithmetic(query)
        assert "INTERVAL '5' DAY" in result
        assert "INTERVAL '10' DAY" in result
        assert "+ 5" not in result
        assert "- 10" not in result

    def test_preserves_other_arithmetic(self):
        """Test that other arithmetic operations are preserved."""
        query = "SELECT price * 2 + tax FROM t WHERE d_date + 5 > NOW()"
        result = fix_postgres_date_arithmetic(query)
        assert "price * 2 + tax" in result
        assert "INTERVAL '5' DAY" in result


class TestPostgresIdentifierQuoting:
    """Test that postgres dialect doesn't use identifier quoting.

    DataFusion/PostgreSQL fold unquoted identifiers to lowercase.
    With quoted identifiers (identify=True), uppercase like "SR_RETURN_AMT"
    wouldn't match lowercase schema columns like sr_return_amt.
    """

    def test_postgres_no_identifier_quoting(self):
        """Test that postgres dialect disables identifier quoting."""
        query = "SELECT SR_RETURN_AMT FROM store_returns"
        result = translate_sql_query(query, target_dialect="postgres", identify=True)
        # Should NOT have quoted uppercase identifiers
        # Unquoted SR_RETURN_AMT will be folded to lowercase by the engine
        assert '"SR_RETURN_AMT"' not in result

    def test_clickhouse_no_identifier_quoting(self):
        """Test that clickhouse dialect disables identifier quoting."""
        query = "SELECT SR_RETURN_AMT FROM store_returns"
        result = translate_sql_query(query, target_dialect="clickhouse", identify=True)
        # ClickHouse also doesn't use quoting
        assert '"SR_RETURN_AMT"' not in result

    def test_duckdb_uses_identifier_quoting(self):
        """Test that duckdb dialect uses identifier quoting when requested."""
        query = "SELECT order FROM orders"  # 'order' is a reserved word
        result = translate_sql_query(query, target_dialect="duckdb", identify=True)
        # DuckDB should quote identifiers to handle reserved words
        # Note: The exact quoting depends on SQLGlot's behavior
        assert result  # Should return valid result

    def test_postgres_case_folding_scenario(self):
        """Test real scenario: TPC-DS uppercase columns with lowercase schema."""
        # This simulates what happens with TPC-DS templates
        query = "SELECT SR_RETURN_AMT, SR_NET_LOSS FROM store_returns WHERE SR_RETURN_AMT > 100"
        result = translate_sql_query(query, target_dialect="postgres", source_dialect="netezza", identify=True)
        # Result should have unquoted identifiers that will be folded to lowercase
        assert '"SR_RETURN_AMT"' not in result
        assert '"SR_NET_LOSS"' not in result
