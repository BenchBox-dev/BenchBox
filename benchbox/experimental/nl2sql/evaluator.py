"""NL2SQL evaluation and accuracy measurement.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from benchbox.core.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class SQLMatchType(Enum):
    """Types of SQL matching results."""

    EXACT = "exact"  # SQL strings are identical
    SEMANTIC = "semantic"  # SQL is different but results are equivalent
    PARTIAL = "partial"  # Some results match
    MISMATCH = "mismatch"  # Results don't match
    ERROR = "error"  # Generated SQL has syntax errors


@dataclass
class SQLComparisonResult:
    """Result of comparing two SQL queries."""

    match_type: SQLMatchType
    generated_sql: str
    expected_sql: str
    normalized_generated: str = ""
    normalized_expected: str = ""
    execution_match: bool = False
    column_match: bool = False
    row_count_match: bool = False
    generated_row_count: int = 0
    expected_row_count: int = 0
    sample_differences: list[dict[str, Any]] = field(default_factory=list)
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "match_type": self.match_type.value,
            "generated_sql": self.generated_sql,
            "expected_sql": self.expected_sql,
            "normalized_generated": self.normalized_generated,
            "normalized_expected": self.normalized_expected,
            "execution_match": self.execution_match,
            "column_match": self.column_match,
            "row_count_match": self.row_count_match,
            "generated_row_count": self.generated_row_count,
            "expected_row_count": self.expected_row_count,
            "sample_differences": self.sample_differences,
            "error_message": self.error_message,
        }


@dataclass
class AccuracyMetrics:
    """Accuracy metrics for NL2SQL evaluation."""

    total_queries: int = 0
    exact_matches: int = 0
    semantic_matches: int = 0
    partial_matches: int = 0
    mismatches: int = 0
    errors: int = 0

    @property
    def exact_accuracy(self) -> float:
        """Get exact match accuracy (strict)."""
        if self.total_queries == 0:
            return 0.0
        return self.exact_matches / self.total_queries

    @property
    def execution_accuracy(self) -> float:
        """Get execution match accuracy (exact + semantic)."""
        if self.total_queries == 0:
            return 0.0
        return (self.exact_matches + self.semantic_matches) / self.total_queries

    @property
    def lenient_accuracy(self) -> float:
        """Get lenient accuracy (exact + semantic + partial)."""
        if self.total_queries == 0:
            return 0.0
        return (self.exact_matches + self.semantic_matches + self.partial_matches) / self.total_queries

    @property
    def error_rate(self) -> float:
        """Get error rate."""
        if self.total_queries == 0:
            return 0.0
        return self.errors / self.total_queries

    def add_result(self, match_type: SQLMatchType) -> None:
        """Add a result to the metrics."""
        self.total_queries += 1
        if match_type == SQLMatchType.EXACT:
            self.exact_matches += 1
        elif match_type == SQLMatchType.SEMANTIC:
            self.semantic_matches += 1
        elif match_type == SQLMatchType.PARTIAL:
            self.partial_matches += 1
        elif match_type == SQLMatchType.MISMATCH:
            self.mismatches += 1
        elif match_type == SQLMatchType.ERROR:
            self.errors += 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_queries": self.total_queries,
            "exact_matches": self.exact_matches,
            "semantic_matches": self.semantic_matches,
            "partial_matches": self.partial_matches,
            "mismatches": self.mismatches,
            "errors": self.errors,
            "exact_accuracy": self.exact_accuracy,
            "execution_accuracy": self.execution_accuracy,
            "lenient_accuracy": self.lenient_accuracy,
            "error_rate": self.error_rate,
        }


class NL2SQLEvaluator:
    """Evaluates NL2SQL generated SQL against expected results."""

    def __init__(
        self,
        connection: DatabaseConnection | None = None,
        case_sensitive: bool = False,
        ignore_whitespace: bool = True,
        max_sample_rows: int = 100,
    ) -> None:
        """Initialize the evaluator.

        Args:
            connection: Database connection for execution-based comparison
            case_sensitive: Whether SQL comparison is case-sensitive
            ignore_whitespace: Whether to normalize whitespace in comparison
            max_sample_rows: Maximum rows to compare for execution matching
        """
        self.connection = connection
        self.case_sensitive = case_sensitive
        self.ignore_whitespace = ignore_whitespace
        self.max_sample_rows = max_sample_rows

    def normalize_sql(self, sql: str) -> str:
        """Normalize SQL for comparison.

        Args:
            sql: SQL string to normalize

        Returns:
            Normalized SQL string
        """
        normalized = sql.strip()

        if self.ignore_whitespace:
            # Normalize whitespace
            normalized = re.sub(r"\s+", " ", normalized)

        if not self.case_sensitive:
            # Lowercase for case-insensitive comparison
            normalized = normalized.lower()

        # Remove trailing semicolons
        normalized = normalized.rstrip(";")

        # Normalize common variations
        normalized = re.sub(r"\s*,\s*", ", ", normalized)
        normalized = re.sub(r"\s*\(\s*", "(", normalized)
        normalized = re.sub(r"\s*\)\s*", ") ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)

        return normalized.strip()

    def compare_sql_strings(self, generated: str, expected: str) -> tuple[bool, str, str]:
        """Compare two SQL strings after normalization.

        Args:
            generated: Generated SQL string
            expected: Expected SQL string

        Returns:
            Tuple of (match, normalized_generated, normalized_expected)
        """
        normalized_generated = self.normalize_sql(generated)
        normalized_expected = self.normalize_sql(expected)

        return (
            normalized_generated == normalized_expected,
            normalized_generated,
            normalized_expected,
        )

    def execute_and_compare(
        self,
        generated_sql: str,
        expected_sql: str,
    ) -> tuple[bool, bool, int, int, list[dict[str, Any]], str]:
        """Execute both queries and compare results.

        Args:
            generated_sql: Generated SQL to execute
            expected_sql: Expected SQL to execute

        Returns:
            Tuple of (execution_match, column_match, gen_rows, exp_rows, differences, error)
        """
        if self.connection is None:
            return False, False, 0, 0, [], "No connection available"

        generated_results: list[Any] = []
        expected_results: list[Any] = []
        generated_columns: list[str] = []
        expected_columns: list[str] = []
        error_message = ""

        # Execute generated SQL
        try:
            cursor = self.connection.execute(generated_sql.strip())
            if hasattr(cursor, "description") and cursor.description:
                generated_columns = [col[0].lower() for col in cursor.description]  # type: ignore[not-iterable]
            generated_results = list(cursor.fetchall()[: self.max_sample_rows])
        except Exception as e:
            error_message = f"Generated SQL error: {str(e)}"
            return False, False, 0, 0, [], error_message

        # Execute expected SQL
        try:
            cursor = self.connection.execute(expected_sql.strip())
            if hasattr(cursor, "description") and cursor.description:
                expected_columns = [col[0].lower() for col in cursor.description]  # type: ignore[not-iterable]
            expected_results = list(cursor.fetchall()[: self.max_sample_rows])
        except Exception as e:
            error_message = f"Expected SQL error: {str(e)}"
            return False, False, len(generated_results), 0, [], error_message

        # Compare columns
        column_match = set(generated_columns) == set(expected_columns)

        # Compare row counts
        gen_rows = len(generated_results)
        exp_rows = len(expected_results)

        # Compare results
        differences: list[dict[str, Any]] = []

        if gen_rows != exp_rows:
            differences.append(
                {
                    "type": "row_count_mismatch",
                    "generated": gen_rows,
                    "expected": exp_rows,
                }
            )

        # Compare row contents (simplified - convert to sets for order-independent comparison)
        gen_set = set(str(row) for row in generated_results)
        exp_set = set(str(row) for row in expected_results)

        if gen_set != exp_set:
            missing = exp_set - gen_set
            extra = gen_set - exp_set
            if missing:
                differences.append(
                    {
                        "type": "missing_rows",
                        "count": len(missing),
                        "sample": list(missing)[:5],
                    }
                )
            if extra:
                differences.append(
                    {
                        "type": "extra_rows",
                        "count": len(extra),
                        "sample": list(extra)[:5],
                    }
                )

        execution_match = len(differences) == 0

        return execution_match, column_match, gen_rows, exp_rows, differences, error_message

    def compare(
        self,
        generated_sql: str,
        expected_sql: str,
        execute: bool = True,
    ) -> SQLComparisonResult:
        """Compare generated SQL against expected SQL.

        Args:
            generated_sql: Generated SQL from NL2SQL
            expected_sql: Expected correct SQL
            execute: Whether to execute queries for result comparison

        Returns:
            SQLComparisonResult with match details
        """
        # First, check for exact string match
        string_match, normalized_generated, normalized_expected = self.compare_sql_strings(generated_sql, expected_sql)

        result = SQLComparisonResult(
            match_type=SQLMatchType.MISMATCH,
            generated_sql=generated_sql,
            expected_sql=expected_sql,
            normalized_generated=normalized_generated,
            normalized_expected=normalized_expected,
        )

        if string_match:
            result.match_type = SQLMatchType.EXACT
            result.execution_match = True
            result.column_match = True
            result.row_count_match = True
            return result

        # If not exact match, try execution-based comparison
        if execute and self.connection is not None:
            (
                execution_match,
                column_match,
                gen_rows,
                exp_rows,
                differences,
                error,
            ) = self.execute_and_compare(generated_sql, expected_sql)

            result.execution_match = execution_match
            result.column_match = column_match
            result.row_count_match = gen_rows == exp_rows
            result.generated_row_count = gen_rows
            result.expected_row_count = exp_rows
            result.sample_differences = differences
            result.error_message = error

            if error and "Generated SQL error" in error:
                result.match_type = SQLMatchType.ERROR
            elif execution_match:
                result.match_type = SQLMatchType.SEMANTIC
            elif column_match and abs(gen_rows - exp_rows) / max(exp_rows, 1) < 0.1:
                # Partial match: columns match and row count is within 10%
                result.match_type = SQLMatchType.PARTIAL

        return result

    def evaluate_batch(
        self,
        results: list[tuple[str, str, str]],
    ) -> tuple[AccuracyMetrics, list[SQLComparisonResult]]:
        """Evaluate a batch of NL2SQL results.

        Args:
            results: List of (query_id, generated_sql, expected_sql) tuples

        Returns:
            Tuple of (AccuracyMetrics, list of SQLComparisonResult)
        """
        metrics = AccuracyMetrics()
        comparisons: list[SQLComparisonResult] = []

        for query_id, generated_sql, expected_sql in results:
            comparison = self.compare(generated_sql, expected_sql)
            metrics.add_result(comparison.match_type)
            comparisons.append(comparison)
            logger.debug(f"Query {query_id}: {comparison.match_type.value}")

        return metrics, comparisons


def calculate_sql_similarity(sql1: str, sql2: str) -> float:
    """Calculate similarity between two SQL strings.

    Uses a simple token-based similarity metric.

    Args:
        sql1: First SQL string
        sql2: Second SQL string

    Returns:
        Similarity score between 0 and 1
    """
    # Tokenize SQL (simple whitespace split)
    tokens1 = set(re.findall(r"\w+", sql1.lower()))
    tokens2 = set(re.findall(r"\w+", sql2.lower()))

    if not tokens1 and not tokens2:
        return 1.0
    if not tokens1 or not tokens2:
        return 0.0

    # Jaccard similarity
    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)

    return intersection / union if union > 0 else 0.0


def extract_sql_components(sql: str) -> dict[str, set[str]]:
    """Extract SQL components for structural comparison.

    Args:
        sql: SQL string to analyze

    Returns:
        Dictionary with extracted components
    """
    sql_lower = sql.lower()

    components: dict[str, set[str]] = {
        "tables": set(),
        "columns": set(),
        "functions": set(),
        "keywords": set(),
        "conditions": set(),
    }

    # Extract table names (after FROM, JOIN)
    from_matches = re.findall(r"from\s+(\w+)", sql_lower)
    join_matches = re.findall(r"join\s+(\w+)", sql_lower)
    components["tables"] = set(from_matches + join_matches)

    # Extract column references
    select_match = re.search(r"select\s+(.+?)\s+from", sql_lower, re.DOTALL)
    if select_match:
        select_clause = select_match.group(1)
        # Simple column extraction (doesn't handle all cases)
        columns = re.findall(r"(\w+\.)?(\w+)", select_clause)
        components["columns"] = set(col[1] for col in columns if col[1] not in {"as", "and", "or"})

    # Extract SQL functions
    functions = re.findall(r"(\w+)\s*\(", sql_lower)
    sql_keywords = {"select", "from", "where", "group", "order", "having", "limit", "offset"}
    components["functions"] = set(f for f in functions if f not in sql_keywords)

    # Extract keywords
    keywords = {
        "select",
        "from",
        "where",
        "join",
        "left",
        "right",
        "inner",
        "outer",
        "on",
        "group",
        "order",
        "by",
        "having",
        "limit",
        "offset",
        "distinct",
        "union",
        "intersect",
        "except",
        "with",
        "as",
        "case",
        "when",
        "then",
        "else",
        "end",
    }
    components["keywords"] = set(re.findall(r"\b(" + "|".join(keywords) + r")\b", sql_lower))

    return components


def structural_similarity(sql1: str, sql2: str) -> dict[str, float]:
    """Calculate structural similarity between two SQL queries.

    Args:
        sql1: First SQL string
        sql2: Second SQL string

    Returns:
        Dictionary with similarity scores for each component
    """
    comp1 = extract_sql_components(sql1)
    comp2 = extract_sql_components(sql2)

    similarities: dict[str, float] = {}

    for component in comp1.keys():
        set1 = comp1[component]
        set2 = comp2[component]

        if not set1 and not set2:
            similarities[component] = 1.0
        elif not set1 or not set2:
            similarities[component] = 0.0
        else:
            intersection = len(set1 & set2)
            union = len(set1 | set2)
            similarities[component] = intersection / union if union > 0 else 0.0

    # Overall weighted similarity
    weights = {"tables": 0.3, "columns": 0.3, "functions": 0.15, "keywords": 0.15, "conditions": 0.1}
    similarities["overall"] = sum(similarities.get(k, 0) * w for k, w in weights.items())

    return similarities
