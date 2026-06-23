"""Data models for expected query results.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ValidationMode(str, Enum):
    """Mode for validating query results."""

    EXACT = "exact"  # Exact row count match required
    RANGE = "range"  # Row count must be within min/max range
    LOOSE = "loose"  # Tolerance-based validation (for non-deterministic queries)
    SKIP = "skip"  # Skip validation for this query


@dataclass
class ExpectedQueryResult:
    """Expected result specification for a single query.

    Supports multiple validation strategies:
    - Exact count: expected_row_count must match exactly
    - Range: actual count must be between expected_row_count_min and expected_row_count_max
    - Loose: tolerance-based validation (for queries with non-deterministic parameter substitution)
    - Formula: row_count_formula defines the expected count (e.g., "5" for regions)
    - Skip: validation is skipped (for queries without known expectations)

    Attributes:
        query_id: Identifier for the query (e.g., "1", "2a", "query14")
        scale_factor: Scale factor this expectation applies to (None = any scale)
        expected_row_count: Exact expected row count (for EXACT mode)
        expected_row_count_min: Minimum acceptable row count (for RANGE mode)
        expected_row_count_max: Maximum acceptable row count (for RANGE mode)
        row_count_formula: Formula for calculating expected count (e.g., "5", "SF * 100")
        validation_mode: How to validate this query result
        scale_independent: Whether this result is independent of scale factor
        loose_tolerance_percent: Tolerance percentage for LOOSE mode (default 50%)
        notes: Additional context about this expectation
        value_digest: Optional order-normalized full-result VALUE digest for this
            query at this scale/reference seed (the bounded correctness gate's
            value oracle). When present, the gate asserts the emitted digest
            matches it IN ADDITION to the row count; when absent, only the row
            count is validated (the historical behavior). This is what lets the
            gate catch a wrong-but-same-cardinality answer.
    """

    query_id: str
    scale_factor: float | None = None
    expected_row_count: int | None = None
    expected_row_count_min: int | None = None
    expected_row_count_max: int | None = None
    row_count_formula: str | None = None
    validation_mode: ValidationMode = ValidationMode.EXACT
    scale_independent: bool = False
    loose_tolerance_percent: float = 50.0
    notes: str | None = None
    value_digest: str | None = None

    def __post_init__(self):
        """Validate that the configuration is coherent."""
        if self.validation_mode == ValidationMode.EXACT:
            if self.expected_row_count is None and self.row_count_formula is None:
                raise ValueError(f"Query {self.query_id}: EXACT mode requires expected_row_count or row_count_formula")
        elif self.validation_mode == ValidationMode.RANGE:
            if self.expected_row_count_min is None or self.expected_row_count_max is None:
                raise ValueError(
                    f"Query {self.query_id}: RANGE mode requires expected_row_count_min and expected_row_count_max"
                )
            if self.expected_row_count_min > self.expected_row_count_max:
                raise ValueError(
                    f"Query {self.query_id}: expected_row_count_min ({self.expected_row_count_min}) "
                    f"must be <= expected_row_count_max ({self.expected_row_count_max})"
                )
        elif self.validation_mode == ValidationMode.LOOSE:
            if self.expected_row_count is None and self.row_count_formula is None:
                raise ValueError(f"Query {self.query_id}: LOOSE mode requires expected_row_count or row_count_formula")
            if self.loose_tolerance_percent <= 0:
                raise ValueError(
                    f"Query {self.query_id}: loose_tolerance_percent must be positive, got {self.loose_tolerance_percent}"
                )

    def get_expected_count(self, scale_factor: float | None = None) -> int | None:
        """Calculate the expected row count for this query.

        Args:
            scale_factor: Scale factor to use for formula evaluation

        Returns:
            Expected row count, or None if validation should be skipped
        """
        if self.validation_mode == ValidationMode.SKIP:
            return None

        # Use exact count if provided
        if self.expected_row_count is not None:
            return self.expected_row_count

        # Evaluate formula if provided
        if self.row_count_formula:
            return self._evaluate_formula(self.row_count_formula, scale_factor or self.scale_factor or 1.0)

        return None

    def _evaluate_formula(self, formula: str, scale_factor: float) -> int:
        """Evaluate a row count formula using safe AST evaluation.

        Supports only safe arithmetic operations:
        - Numeric constants: "5" -> 5
        - Scale factor multiplication: "SF * 100" -> scale_factor * 100
        - Arithmetic operators: +, -, *, /, //, %
        - Simple expressions: "SF * 100 + 5"

        Security: Uses AST parsing with whitelisted operations only.
        Rejects: function calls, lambdas, comprehensions, power operations, etc.

        Args:
            formula: Formula string to evaluate
            scale_factor: Scale factor value

        Returns:
            Evaluated row count

        Raises:
            ValueError: If formula contains unsafe operations or invalid syntax
        """
        import ast
        import operator

        # Replace SF with actual scale factor value
        formula_str = formula.replace("SF", str(scale_factor))

        # Parse the formula into an AST
        try:
            node = ast.parse(formula_str, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid formula syntax '{formula}': {e}") from e

        # Whitelist of allowed binary operations
        allowed_ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.FloorDiv: operator.floordiv,
            ast.Div: operator.truediv,
            ast.Mod: operator.mod,
        }

        def eval_node(node):
            """Recursively evaluate AST node with whitelist enforcement."""
            if isinstance(node, ast.Expression):
                return eval_node(node.body)
            elif isinstance(node, ast.Constant):
                # Python 3.8+ uses ast.Constant for all literals
                return node.value
            elif isinstance(node, ast.BinOp):
                # Binary operation (e.g., a + b, a * b)
                if type(node.op) not in allowed_ops:
                    raise ValueError(
                        f"Operation {type(node.op).__name__} not allowed in formula. "
                        f"Only +, -, *, /, //, % are permitted."
                    )
                left = eval_node(node.left)
                right = eval_node(node.right)
                return allowed_ops[type(node.op)](left, right)
            elif isinstance(node, ast.UnaryOp):
                # Unary operation (e.g., -a, +a)
                if isinstance(node.op, ast.UAdd):
                    return eval_node(node.operand)
                elif isinstance(node.op, ast.USub):
                    return -eval_node(node.operand)
                else:
                    raise ValueError(f"Unary operation {type(node.op).__name__} not allowed in formula")
            else:
                raise ValueError(
                    f"AST node type {type(node).__name__} not allowed in formula. "
                    f"Formula must contain only numeric constants and safe arithmetic operations."
                )

        try:
            result = eval_node(node)
            return int(result)
        except (ValueError, TypeError, ZeroDivisionError) as e:
            raise ValueError(f"Failed to evaluate formula '{formula}' with SF={scale_factor}: {e}") from e

    def validate_loose(self, actual_count: int, scale_factor: float | None = None) -> ValidationResult:
        """Validate using loose tolerance-based approach.

        Guards against the critical case where we expect many rows but get 0 rows.
        This indicates a serious query failure rather than acceptable variance.

        Args:
            actual_count: Actual number of rows returned
            scale_factor: Scale factor for formula evaluation

        Returns:
            ValidationResult with pass/fail status and details

        Validation logic:
        1. If expected > 0 and actual == 0: FAIL (critical failure)
        2. Otherwise: Check if actual is within tolerance percentage of expected
        """
        expected_count = self.get_expected_count(scale_factor)

        if expected_count is None:
            return ValidationResult(
                is_valid=False,
                query_id=self.query_id,
                expected_row_count=None,
                actual_row_count=actual_count,
                validation_mode=ValidationMode.LOOSE,
                error_message="Cannot perform loose validation without expected row count",
            )

        # Critical guard: If we expect any rows but get 0, that's always a failure
        if expected_count > 0 and actual_count == 0:
            return ValidationResult(
                is_valid=False,
                query_id=self.query_id,
                expected_row_count=expected_count,
                actual_row_count=actual_count,
                validation_mode=ValidationMode.LOOSE,
                error_message=(
                    f"Query returned 0 rows when expecting {expected_count:,} rows. "
                    f"This indicates a critical query failure."
                ),
            )

        # Calculate tolerance bounds
        tolerance_multiplier = self.loose_tolerance_percent / 100.0
        min_acceptable = int(expected_count * (1.0 - tolerance_multiplier))
        max_acceptable = int(expected_count * (1.0 + tolerance_multiplier))

        # Check if actual is within tolerance
        if min_acceptable <= actual_count <= max_acceptable:
            return ValidationResult(
                is_valid=True,
                query_id=self.query_id,
                expected_row_count=expected_count,
                actual_row_count=actual_count,
                validation_mode=ValidationMode.LOOSE,
            )
        else:
            difference = actual_count - expected_count
            difference_percent = (difference / expected_count * 100.0) if expected_count > 0 else 0.0

            return ValidationResult(
                is_valid=False,
                query_id=self.query_id,
                expected_row_count=expected_count,
                actual_row_count=actual_count,
                validation_mode=ValidationMode.LOOSE,
                error_message=(
                    f"Row count outside tolerance range. "
                    f"Expected: {expected_count:,} ±{self.loose_tolerance_percent}% "
                    f"({min_acceptable:,} to {max_acceptable:,}), "
                    f"Actual: {actual_count:,} ({difference_percent:+.1f}%)"
                ),
            )


@dataclass
class BenchmarkExpectedResults:
    """Collection of expected results for a benchmark.

    Attributes:
        benchmark_name: Name of the benchmark (e.g., "tpch", "tpcds")
        scale_factor: Primary scale factor for these results (e.g., 1.0)
        query_results: Map of query_id -> ExpectedQueryResult
        metadata: Additional metadata about these expectations
    """

    benchmark_name: str
    scale_factor: float
    query_results: dict[str, ExpectedQueryResult]
    metadata: dict[str, Any] | None = None

    def get_expected_result(self, query_id: str) -> ExpectedQueryResult | None:
        """Get expected result for a specific query.

        Args:
            query_id: Query identifier

        Returns:
            Expected result specification, or None if not found
        """
        return self.query_results.get(query_id)


@dataclass
class ValidationResult:
    """Result of validating a query's row count.

    Attributes:
        is_valid: Whether validation passed
        query_id: Query identifier
        expected_row_count: Expected row count (or None if unknown)
        actual_row_count: Actual row count returned
        validation_mode: Mode used for validation
        error_message: Error message if validation failed
        warning_message: Warning message (e.g., for skipped validation)
        difference: Difference between actual and expected (actual - expected)
        difference_percent: Percentage difference ((actual - expected) / expected * 100)
    """

    is_valid: bool
    query_id: str
    expected_row_count: int | None
    actual_row_count: int
    validation_mode: ValidationMode
    error_message: str | None = None
    warning_message: str | None = None
    difference: int | None = None
    difference_percent: float | None = None

    def __post_init__(self):
        """Calculate difference metrics if both counts are available."""
        if self.expected_row_count is not None and self.actual_row_count is not None:
            self.difference = self.actual_row_count - self.expected_row_count
            if self.expected_row_count > 0:
                self.difference_percent = (self.difference / self.expected_row_count) * 100.0
