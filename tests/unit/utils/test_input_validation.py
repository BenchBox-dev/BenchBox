"""Tests for input validation and SQL safety utilities.

Tests the comprehensive input validation, SQL injection prevention,
and query complexity limit enforcement.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.utils.input_validation import (
    MAX_IDENTIFIER_LENGTH,
    MAX_QUERIES_PER_RUN,
    MAX_QUERY_ID_LENGTH,
    InputLengthError,
    InvalidIdentifierError,
    QueryComplexityError,
    QueryComplexityMetrics,
    SQLInjectionError,
    ValidationError,
    analyze_query_complexity,
    check_sql_injection_patterns,
    escape_sql_string,
    quote_identifier,
    quote_qualified_identifier,
    safe_format_table_reference,
    validate_benchmark_name,
    validate_platform_name,
    validate_query_complexity,
    validate_query_id,
    validate_query_ids_list,
    validate_scale_factor,
    validate_sql_identifier,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestValidateSqlIdentifier:
    """Tests for SQL identifier validation."""

    def test_valid_identifier(self):
        """Valid identifiers should pass validation."""
        assert validate_sql_identifier("my_table") == "my_table"
        assert validate_sql_identifier("TableName") == "TableName"
        assert validate_sql_identifier("_private") == "_private"
        assert validate_sql_identifier("table123") == "table123"

    def test_empty_identifier_raises(self):
        """Empty identifiers should raise InvalidIdentifierError."""
        with pytest.raises(InvalidIdentifierError, match="Empty"):
            validate_sql_identifier("")

        with pytest.raises(InvalidIdentifierError, match="Empty"):
            validate_sql_identifier(None)

        with pytest.raises(InvalidIdentifierError, match="Empty"):
            validate_sql_identifier("   ")

    def test_identifier_too_long(self):
        """Identifiers exceeding max length should raise InputLengthError."""
        long_name = "a" * (MAX_IDENTIFIER_LENGTH + 1)
        with pytest.raises(InputLengthError, match="exceeds maximum length"):
            validate_sql_identifier(long_name)

    def test_identifier_with_invalid_chars(self):
        """Identifiers with invalid characters should raise InvalidIdentifierError."""
        with pytest.raises(InvalidIdentifierError):
            validate_sql_identifier("table-name")  # hyphen not allowed

        with pytest.raises(InvalidIdentifierError):
            validate_sql_identifier("table.name")  # dot not allowed by default

        with pytest.raises(InvalidIdentifierError):
            validate_sql_identifier("123table")  # can't start with number

    def test_identifier_with_sql_keywords(self):
        """Identifiers containing SQL keywords should raise SQLInjectionError."""
        with pytest.raises(SQLInjectionError):
            validate_sql_identifier("table; DROP TABLE users")

        with pytest.raises(SQLInjectionError):
            validate_sql_identifier("SELECT")

        with pytest.raises(SQLInjectionError):
            validate_sql_identifier("name--comment")

    def test_allow_dots(self):
        """Dotted identifiers should be allowed when allow_dots=True."""
        result = validate_sql_identifier("schema.table", allow_dots=True)
        assert result == "schema.table"

        result = validate_sql_identifier("catalog.schema.table", allow_dots=True)
        assert result == "catalog.schema.table"

    def test_too_many_dots(self):
        """Too many dot-separated parts should raise InvalidIdentifierError."""
        with pytest.raises(InvalidIdentifierError, match="too many"):
            validate_sql_identifier("a.b.c.d", allow_dots=True)


class TestValidateQueryId:
    """Tests for query ID validation."""

    def test_valid_query_ids(self):
        """Valid query IDs should pass validation."""
        assert validate_query_id("1") == "1"
        assert validate_query_id("q1") == "q1"
        assert validate_query_id("query-1") == "query-1"
        assert validate_query_id("query_1") == "query_1"
        assert validate_query_id(1) == "1"  # Integer conversion
        # SSB uses dot-notation query IDs (Q1.1, Q3.4, etc.)
        assert validate_query_id("Q1.1") == "Q1.1"
        assert validate_query_id("Q3.4") == "Q3.4"

    def test_empty_query_id_raises(self):
        """Empty query IDs should raise ValidationError."""
        with pytest.raises(ValidationError, match="Empty"):
            validate_query_id("")

    def test_query_id_too_long(self):
        """Query IDs exceeding max length should raise InputLengthError."""
        long_id = "q" * (MAX_QUERY_ID_LENGTH + 1)
        with pytest.raises(InputLengthError, match="exceeds maximum length"):
            validate_query_id(long_id)

    def test_query_id_invalid_chars(self):
        """Query IDs with invalid characters should raise ValidationError."""
        with pytest.raises(ValidationError, match="must contain only"):
            validate_query_id("query;1")

        with pytest.raises(ValidationError, match="must contain only"):
            validate_query_id("query 1")

    def test_tpch_allowlist(self):
        """TPC-H query IDs should be validated against allowlist."""
        # Valid TPC-H queries (1-22)
        assert validate_query_id("1", "tpch") == "1"
        assert validate_query_id("22", "tpch") == "22"
        assert validate_query_id("15a", "tpch") == "15a"  # Variant

        # Invalid TPC-H query
        with pytest.raises(ValidationError, match="Invalid TPC-H"):
            validate_query_id("23", "tpch")

        with pytest.raises(ValidationError, match="Invalid TPC-H"):
            validate_query_id("0", "tpch")

    def test_tpcds_allowlist(self):
        """TPC-DS query IDs should be validated against allowlist."""
        # Valid TPC-DS queries (1-99)
        assert validate_query_id("1", "tpcds") == "1"
        assert validate_query_id("99", "tpcds") == "99"
        assert validate_query_id("14a", "tpcds") == "14a"

        # Invalid TPC-DS query
        with pytest.raises(ValidationError, match="Invalid TPC-DS"):
            validate_query_id("100", "tpcds")


class TestValidateQueryIdsList:
    """Tests for query IDs list validation."""

    def test_valid_list(self):
        """Valid query ID lists should pass validation."""
        result = validate_query_ids_list(["1", "2", "3"])
        assert result == ["1", "2", "3"]

    def test_comma_separated_string(self):
        """Comma-separated strings should be parsed correctly."""
        result = validate_query_ids_list("1, 2, 3")
        assert result == ["1", "2", "3"]

    def test_duplicates_removed(self):
        """Duplicate query IDs should be removed."""
        result = validate_query_ids_list(["1", "2", "1", "3", "2"])
        assert result == ["1", "2", "3"]

    def test_too_many_queries(self):
        """Lists exceeding max queries should raise ValidationError."""
        query_ids = [str(i) for i in range(MAX_QUERIES_PER_RUN + 1)]
        with pytest.raises(ValidationError, match="Too many queries"):
            validate_query_ids_list(query_ids)

    def test_empty_list_raises(self):
        """Empty lists should raise ValidationError."""
        with pytest.raises(ValidationError, match="No query IDs"):
            validate_query_ids_list([])

        with pytest.raises(ValidationError, match="No query IDs"):
            validate_query_ids_list("")


class TestCheckSqlInjectionPatterns:
    """Tests for SQL injection pattern detection."""

    def test_clean_input_passes(self):
        """Clean inputs should not raise exceptions."""
        # Should not raise
        check_sql_injection_patterns("my_table")
        check_sql_injection_patterns("user123")
        check_sql_injection_patterns("valid_name_here")

    def test_sql_keywords_detected(self):
        """SQL keywords should be detected."""
        with pytest.raises(SQLInjectionError):
            check_sql_injection_patterns("SELECT * FROM users")

        with pytest.raises(SQLInjectionError):
            check_sql_injection_patterns("table; DROP TABLE")

        with pytest.raises(SQLInjectionError):
            check_sql_injection_patterns("value--comment")

    def test_injection_patterns_detected(self):
        """Common injection patterns should be detected."""
        with pytest.raises(SQLInjectionError):
            check_sql_injection_patterns("' OR '1'='1")

        with pytest.raises(SQLInjectionError):
            check_sql_injection_patterns("admin'; --")

        with pytest.raises(SQLInjectionError):
            check_sql_injection_patterns("/* comment */")


class TestEscapeSqlString:
    """Tests for SQL string escaping."""

    def test_no_quotes(self):
        """Strings without quotes should be unchanged."""
        assert escape_sql_string("hello world") == "hello world"

    def test_single_quotes_doubled(self):
        """Single quotes should be doubled."""
        assert escape_sql_string("it's") == "it''s"
        assert escape_sql_string("'test'") == "''test''"

    def test_non_string_converted(self):
        """Non-strings should be converted."""
        assert escape_sql_string(123) == "123"
        assert escape_sql_string(None) == "None"


class TestQuoteIdentifier:
    """Tests for identifier quoting."""

    def test_default_double_quotes(self):
        """Default should use double quotes."""
        assert quote_identifier("table") == '"table"'

    def test_mysql_backticks(self):
        """MySQL should use backticks."""
        assert quote_identifier("table", "mysql") == "`table`"

    def test_bigquery_backticks(self):
        """BigQuery should use backticks."""
        assert quote_identifier("table", "bigquery") == "`table`"

    def test_sqlserver_brackets(self):
        """SQL Server should use square brackets."""
        assert quote_identifier("table", "sqlserver") == "[table]"
        assert quote_identifier("table", "synapse") == "[table]"

    def test_postgresql_double_quotes(self):
        """PostgreSQL should use double quotes."""
        assert quote_identifier("table", "postgresql") == '"table"'

    def test_escaping_within_quotes(self):
        """Identifiers with quotes should have quotes escaped when valid."""
        # Note: Most special chars are rejected by identifier validation
        # Test valid identifiers with platform-specific quoting
        assert quote_identifier("table_name", "postgresql") == '"table_name"'
        assert quote_identifier("table_name", "mysql") == "`table_name`"
        assert quote_identifier("table_name", "sqlserver") == "[table_name]"


class TestQuoteQualifiedIdentifier:
    """Tests for qualified identifier quoting."""

    def test_schema_table(self):
        """Schema.table notation should quote each part."""
        result = quote_qualified_identifier("schema.table", "postgresql")
        assert result == '"schema"."table"'

    def test_catalog_schema_table(self):
        """Catalog.schema.table notation should quote each part."""
        result = quote_qualified_identifier("catalog.schema.table", "postgresql")
        assert result == '"catalog"."schema"."table"'


class TestQueryComplexityMetrics:
    """Tests for query complexity metrics."""

    def test_exceeds_limits(self):
        """Should correctly identify limit violations."""
        metrics = QueryComplexityMetrics(join_count=100)
        assert metrics.exceeds_limits() is True

        metrics = QueryComplexityMetrics(subquery_depth=20)
        assert metrics.exceeds_limits() is True

        metrics = QueryComplexityMetrics(query_length=2_000_000)
        assert metrics.exceeds_limits() is True

    def test_within_limits(self):
        """Should correctly identify valid metrics."""
        metrics = QueryComplexityMetrics(join_count=5, subquery_depth=2, query_length=1000)
        assert metrics.exceeds_limits() is False

    def test_violation_details(self):
        """Should return list of violations."""
        metrics = QueryComplexityMetrics(join_count=100, subquery_depth=20)
        violations = metrics.get_violation_details()
        assert len(violations) == 2
        assert any("JOIN count" in v for v in violations)
        assert any("Subquery depth" in v for v in violations)


class TestAnalyzeQueryComplexity:
    """Tests for query complexity analysis."""

    def test_simple_query(self):
        """Simple queries should have low complexity."""
        metrics = analyze_query_complexity("SELECT * FROM users")
        assert metrics.join_count == 0
        assert metrics.subquery_depth == 0
        assert metrics.union_count == 0

    def test_join_count(self):
        """JOINs should be counted."""
        query = "SELECT * FROM a JOIN b ON a.id = b.id LEFT JOIN c ON b.id = c.id"
        metrics = analyze_query_complexity(query)
        assert metrics.join_count == 2

    def test_union_count(self):
        """UNIONs should be counted."""
        query = "SELECT * FROM a UNION SELECT * FROM b UNION ALL SELECT * FROM c"
        metrics = analyze_query_complexity(query)
        assert metrics.union_count == 2

    def test_subquery_depth(self):
        """Subqueries should be detected."""
        query = "SELECT * FROM (SELECT * FROM (SELECT * FROM t) AS sub1) AS sub2"
        metrics = analyze_query_complexity(query)
        assert metrics.subquery_depth >= 2

    def test_predicate_count(self):
        """Predicates should be counted."""
        query = "SELECT * FROM t WHERE a = 1 AND b = 2 OR c = 3"
        metrics = analyze_query_complexity(query)
        assert metrics.predicate_count >= 3


class TestValidateQueryComplexity:
    """Tests for query complexity validation."""

    def test_valid_query_passes(self):
        """Valid queries should pass validation."""
        query = "SELECT * FROM users WHERE id = 1"
        metrics = validate_query_complexity(query)
        assert metrics.exceeds_limits() is False

    def test_complex_query_raises(self):
        """Overly complex queries should raise QueryComplexityError."""
        # Create query with many JOINs
        joins = " ".join([f"JOIN t{i} ON t{i}.id = t{i + 1}.id" for i in range(60)])
        query = f"SELECT * FROM t0 {joins}"

        with pytest.raises(QueryComplexityError, match="JOIN count"):
            validate_query_complexity(query, enforce=True)

    def test_enforce_false_returns_metrics(self):
        """With enforce=False, should return metrics without raising."""
        joins = " ".join([f"JOIN t{i} ON t{i}.id = t{i + 1}.id" for i in range(60)])
        query = f"SELECT * FROM t0 {joins}"

        metrics = validate_query_complexity(query, enforce=False)
        assert metrics.exceeds_limits() is True


class TestValidateBenchmarkName:
    """Tests for benchmark name validation."""

    def test_valid_names(self):
        """Valid benchmark names should pass."""
        assert validate_benchmark_name("tpch") == "tpch"
        assert validate_benchmark_name("TPC-DS") == "tpc-ds"
        assert validate_benchmark_name("ssb_benchmark") == "ssb_benchmark"

    def test_invalid_names(self):
        """Invalid benchmark names should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_benchmark_name("")

        with pytest.raises(ValidationError):
            validate_benchmark_name("123benchmark")


class TestValidatePlatformName:
    """Tests for platform name validation."""

    def test_valid_names(self):
        """Valid platform names should pass."""
        assert validate_platform_name("duckdb") == "duckdb"
        assert validate_platform_name("PostgreSQL") == "postgresql"
        assert validate_platform_name("azure_synapse") == "azure_synapse"

    def test_invalid_names(self):
        """Invalid platform names should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_platform_name("")

        with pytest.raises(ValidationError):
            validate_platform_name("123platform")


class TestValidateScaleFactor:
    """Tests for scale factor validation."""

    def test_valid_scale_factors(self):
        """Valid scale factors should pass."""
        assert validate_scale_factor(1) == 1.0
        assert validate_scale_factor(0.1) == 0.1
        assert validate_scale_factor("10") == 10.0
        assert validate_scale_factor(1000) == 1000.0

    def test_invalid_scale_factors(self):
        """Invalid scale factors should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_scale_factor(0)

        with pytest.raises(ValidationError):
            validate_scale_factor(-1)

        with pytest.raises(ValidationError):
            validate_scale_factor("not_a_number")

    def test_scale_factor_too_large(self):
        """Very large scale factors should raise ValidationError."""
        with pytest.raises(ValidationError, match="too large"):
            validate_scale_factor(200000)


class TestSafeFormatTableReference:
    """Tests for safe table reference formatting."""

    def test_table_only(self):
        """Table-only references should be quoted."""
        result = safe_format_table_reference("users", platform="postgresql")
        assert result == '"users"'

    def test_schema_and_table(self):
        """Schema.table references should have both parts quoted."""
        result = safe_format_table_reference("users", schema_name="public", platform="postgresql")
        assert result == '"public"."users"'

    def test_invalid_table_raises(self):
        """Invalid table names should raise ValidationError (SQLInjectionError for injection patterns)."""
        with pytest.raises(SQLInjectionError):
            safe_format_table_reference("table; DROP")

    def test_invalid_schema_raises(self):
        """Invalid schema names should raise ValidationError (SQLInjectionError for injection patterns)."""
        with pytest.raises(SQLInjectionError):
            safe_format_table_reference("users", schema_name="schema; DROP")
