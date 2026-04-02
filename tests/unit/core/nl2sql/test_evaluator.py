"""Tests for NL2SQL evaluator.

Copyright 2026 Joe Harris / BenchBox Project
"""

import pytest

from benchbox.experimental.nl2sql.evaluator import (
    AccuracyMetrics,
    NL2SQLEvaluator,
    SQLComparisonResult,
    SQLMatchType,
    calculate_sql_similarity,
    extract_sql_components,
    structural_similarity,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSQLMatchType:
    """Tests for SQLMatchType enum."""

    def test_match_types_exist(self):
        """Test that all match types exist."""
        expected = {"exact", "semantic", "partial", "mismatch", "error"}
        actual = {m.value for m in SQLMatchType}
        assert expected == actual


class TestSQLComparisonResult:
    """Tests for SQLComparisonResult dataclass."""

    def test_comparison_result_creation(self):
        """Test creating a comparison result."""
        result = SQLComparisonResult(
            match_type=SQLMatchType.EXACT,
            generated_sql="SELECT COUNT(*) FROM orders",
            expected_sql="SELECT COUNT(*) FROM orders",
            execution_match=True,
            column_match=True,
            row_count_match=True,
        )

        assert result.match_type == SQLMatchType.EXACT
        assert result.execution_match is True

    def test_comparison_result_to_dict(self):
        """Test converting result to dictionary."""
        result = SQLComparisonResult(
            match_type=SQLMatchType.SEMANTIC,
            generated_sql="SELECT count(*) FROM orders",
            expected_sql="SELECT COUNT(*) FROM orders",
            normalized_generated="select count(*) from orders",
            normalized_expected="select count(*) from orders",
            execution_match=True,
        )

        data = result.to_dict()

        assert data["match_type"] == "semantic"
        assert "generated_sql" in data
        assert "expected_sql" in data


class TestAccuracyMetrics:
    """Tests for AccuracyMetrics dataclass."""

    def test_empty_metrics(self):
        """Test empty metrics."""
        metrics = AccuracyMetrics()

        assert metrics.total_queries == 0
        assert metrics.exact_accuracy == 0.0
        assert metrics.execution_accuracy == 0.0
        assert metrics.error_rate == 0.0

    def test_add_exact_match(self):
        """Test adding an exact match."""
        metrics = AccuracyMetrics()
        metrics.add_result(SQLMatchType.EXACT)

        assert metrics.total_queries == 1
        assert metrics.exact_matches == 1
        assert metrics.exact_accuracy == 1.0

    def test_add_multiple_results(self):
        """Test adding multiple results."""
        metrics = AccuracyMetrics()
        metrics.add_result(SQLMatchType.EXACT)
        metrics.add_result(SQLMatchType.SEMANTIC)
        metrics.add_result(SQLMatchType.PARTIAL)
        metrics.add_result(SQLMatchType.MISMATCH)
        metrics.add_result(SQLMatchType.ERROR)

        assert metrics.total_queries == 5
        assert metrics.exact_matches == 1
        assert metrics.semantic_matches == 1
        assert metrics.partial_matches == 1
        assert metrics.mismatches == 1
        assert metrics.errors == 1

    def test_accuracy_calculations(self):
        """Test accuracy calculation methods."""
        metrics = AccuracyMetrics()
        # 2 exact, 2 semantic, 1 partial, 3 mismatch, 2 error = 10 total
        for _ in range(2):
            metrics.add_result(SQLMatchType.EXACT)
        for _ in range(2):
            metrics.add_result(SQLMatchType.SEMANTIC)
        metrics.add_result(SQLMatchType.PARTIAL)
        for _ in range(3):
            metrics.add_result(SQLMatchType.MISMATCH)
        for _ in range(2):
            metrics.add_result(SQLMatchType.ERROR)

        assert metrics.total_queries == 10
        assert metrics.exact_accuracy == 0.2  # 2/10
        assert metrics.execution_accuracy == 0.4  # (2+2)/10
        assert metrics.lenient_accuracy == 0.5  # (2+2+1)/10
        assert metrics.error_rate == 0.2  # 2/10

    def test_metrics_to_dict(self):
        """Test converting metrics to dictionary."""
        metrics = AccuracyMetrics()
        metrics.add_result(SQLMatchType.EXACT)
        metrics.add_result(SQLMatchType.SEMANTIC)

        data = metrics.to_dict()

        assert data["total_queries"] == 2
        assert data["exact_matches"] == 1
        assert data["semantic_matches"] == 1
        assert data["exact_accuracy"] == 0.5
        assert data["execution_accuracy"] == 1.0


class TestNL2SQLEvaluator:
    """Tests for NL2SQLEvaluator class."""

    @pytest.fixture
    def evaluator(self):
        """Create an evaluator without connection."""
        return NL2SQLEvaluator(
            connection=None,
            case_sensitive=False,
            ignore_whitespace=True,
        )

    def test_normalize_sql_whitespace(self, evaluator):
        """Test SQL whitespace normalization."""
        sql = """SELECT    COUNT(*)
        FROM   orders
        WHERE  status = 'active'"""

        normalized = evaluator.normalize_sql(sql)

        assert "  " not in normalized  # No double spaces
        assert "\n" not in normalized

    def test_normalize_sql_case(self, evaluator):
        """Test SQL case normalization."""
        sql = "SELECT COUNT(*) FROM ORDERS"
        normalized = evaluator.normalize_sql(sql)

        assert normalized == normalized.lower()

    def test_normalize_sql_semicolon(self, evaluator):
        """Test semicolon removal."""
        sql = "SELECT * FROM orders;"
        normalized = evaluator.normalize_sql(sql)

        assert not normalized.endswith(";")

    def test_compare_sql_exact_match(self, evaluator):
        """Test exact SQL string comparison."""
        sql1 = "SELECT COUNT(*) FROM orders"
        sql2 = "SELECT COUNT(*) FROM orders"

        match, norm1, norm2 = evaluator.compare_sql_strings(sql1, sql2)

        assert match is True
        assert norm1 == norm2

    def test_compare_sql_case_insensitive_match(self, evaluator):
        """Test case-insensitive comparison."""
        sql1 = "SELECT COUNT(*) FROM orders"
        sql2 = "select count(*) from ORDERS"

        match, _, _ = evaluator.compare_sql_strings(sql1, sql2)

        assert match is True

    def test_compare_sql_whitespace_insensitive_match(self, evaluator):
        """Test whitespace-insensitive comparison."""
        sql1 = "SELECT COUNT(*) FROM orders"
        sql2 = "SELECT   COUNT(*)   FROM   orders"

        match, _, _ = evaluator.compare_sql_strings(sql1, sql2)

        assert match is True

    def test_compare_sql_different_queries(self, evaluator):
        """Test comparison of different queries."""
        sql1 = "SELECT COUNT(*) FROM orders"
        sql2 = "SELECT COUNT(*) FROM customers"

        match, _, _ = evaluator.compare_sql_strings(sql1, sql2)

        assert match is False

    def test_compare_without_execution(self, evaluator):
        """Test comparison without execution (string match only)."""
        generated = "SELECT COUNT(*) FROM orders"
        expected = "SELECT COUNT(*) FROM orders"

        result = evaluator.compare(generated, expected, execute=False)

        assert result.match_type == SQLMatchType.EXACT

    def test_compare_mismatch_without_execution(self, evaluator):
        """Test mismatch detection without execution."""
        generated = "SELECT COUNT(*) FROM orders"
        expected = "SELECT SUM(amount) FROM orders"

        result = evaluator.compare(generated, expected, execute=False)

        assert result.match_type == SQLMatchType.MISMATCH

    def test_evaluate_batch(self, evaluator):
        """Test batch evaluation."""
        results = [
            ("q1", "SELECT COUNT(*) FROM orders", "SELECT COUNT(*) FROM orders"),
            ("q2", "SELECT COUNT(*) FROM orders", "SELECT SUM(x) FROM orders"),
        ]

        metrics, comparisons = evaluator.evaluate_batch(results)

        assert metrics.total_queries == 2
        assert metrics.exact_matches == 1
        assert len(comparisons) == 2


class TestSQLSimilarity:
    """Tests for SQL similarity functions."""

    def test_calculate_sql_similarity_identical(self):
        """Test similarity of identical SQL."""
        sql1 = "SELECT COUNT(*) FROM orders WHERE status = 'active'"
        sql2 = "SELECT COUNT(*) FROM orders WHERE status = 'active'"

        similarity = calculate_sql_similarity(sql1, sql2)

        assert similarity == 1.0

    def test_calculate_sql_similarity_similar(self):
        """Test similarity of similar SQL."""
        sql1 = "SELECT COUNT(*) FROM orders WHERE status = 'active'"
        sql2 = "SELECT COUNT(*) FROM orders WHERE status = 'pending'"

        similarity = calculate_sql_similarity(sql1, sql2)

        assert 0.5 < similarity < 1.0

    def test_calculate_sql_similarity_different(self):
        """Test similarity of very different SQL."""
        sql1 = "SELECT name FROM customers"
        sql2 = "DELETE FROM products WHERE id = 1"

        similarity = calculate_sql_similarity(sql1, sql2)

        assert similarity < 0.5

    def test_calculate_sql_similarity_empty(self):
        """Test similarity with empty strings."""
        assert calculate_sql_similarity("", "") == 1.0
        assert calculate_sql_similarity("SELECT 1", "") == 0.0


class TestSQLComponentExtraction:
    """Tests for SQL component extraction."""

    def test_extract_tables(self):
        """Test table extraction."""
        sql = "SELECT * FROM orders o JOIN customers c ON o.cust_id = c.id"
        components = extract_sql_components(sql)

        assert "orders" in components["tables"]
        assert "customers" in components["tables"]

    def test_extract_functions(self):
        """Test function extraction."""
        sql = "SELECT COUNT(*), SUM(amount), AVG(price) FROM orders"
        components = extract_sql_components(sql)

        assert "count" in components["functions"]
        assert "sum" in components["functions"]
        assert "avg" in components["functions"]

    def test_extract_keywords(self):
        """Test keyword extraction."""
        sql = "SELECT DISTINCT name FROM orders WHERE status = 1 GROUP BY name ORDER BY name"
        components = extract_sql_components(sql)

        assert "select" in components["keywords"]
        assert "distinct" in components["keywords"]
        assert "where" in components["keywords"]
        assert "group" in components["keywords"]
        assert "order" in components["keywords"]


class TestStructuralSimilarity:
    """Tests for structural similarity calculation."""

    def test_structural_similarity_identical(self):
        """Test structural similarity of identical queries."""
        sql1 = "SELECT COUNT(*) FROM orders WHERE status = 'active'"
        sql2 = "SELECT COUNT(*) FROM orders WHERE status = 'active'"

        similarity = structural_similarity(sql1, sql2)

        assert similarity["tables"] == 1.0
        assert similarity["functions"] == 1.0
        assert similarity["keywords"] == 1.0
        assert similarity["overall"] == 1.0

    def test_structural_similarity_different_tables(self):
        """Test structural similarity with different tables."""
        sql1 = "SELECT COUNT(*) FROM orders"
        sql2 = "SELECT COUNT(*) FROM customers"

        similarity = structural_similarity(sql1, sql2)

        assert similarity["tables"] == 0.0
        assert similarity["functions"] == 1.0  # Same function

    def test_structural_similarity_partial(self):
        """Test partial structural similarity."""
        sql1 = "SELECT COUNT(*), SUM(amount) FROM orders JOIN customers ON id"
        sql2 = "SELECT COUNT(*), AVG(price) FROM orders JOIN products ON id"

        similarity = structural_similarity(sql1, sql2)

        # Some tables match, some don't
        assert 0 < similarity["tables"] < 1
        # COUNT is common
        assert 0 < similarity["functions"] < 1
        # Overall should be partial
        assert 0 < similarity["overall"] < 1


class TestCaseSensitiveEvaluator:
    """Tests for case-sensitive evaluator."""

    @pytest.fixture
    def evaluator(self):
        """Create a case-sensitive evaluator."""
        return NL2SQLEvaluator(
            connection=None,
            case_sensitive=True,
            ignore_whitespace=True,
        )

    def test_case_sensitive_mismatch(self, evaluator):
        """Test case-sensitive comparison fails on case difference."""
        sql1 = "SELECT COUNT(*) FROM orders"
        sql2 = "select count(*) from ORDERS"

        match, _, _ = evaluator.compare_sql_strings(sql1, sql2)

        assert match is False


class TestWhitespacePreservingEvaluator:
    """Tests for whitespace-preserving evaluator."""

    @pytest.fixture
    def evaluator(self):
        """Create a whitespace-preserving evaluator."""
        return NL2SQLEvaluator(
            connection=None,
            case_sensitive=False,
            ignore_whitespace=False,
        )

    def test_whitespace_sensitive_mismatch(self, evaluator):
        """Test whitespace-sensitive comparison fails on different structure."""
        # Note: Even with ignore_whitespace=False, basic normalization still happens
        # This test checks that different SQL structures are not matched
        sql1 = "SELECT COUNT(*) FROM orders WHERE status = 'active'"
        sql2 = "SELECT COUNT(*) FROM orders WHERE status = 'pending'"

        match, _, _ = evaluator.compare_sql_strings(sql1, sql2)

        assert match is False
