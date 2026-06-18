"""
Base parser interface for query plan parsing.

Platform-specific parsers extend this base class to convert native EXPLAIN output
into the harmonized QueryPlanDAG structure.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, TypeVar

from benchbox.core.errors import PlanParseError
from benchbox.core.results.query_plan_models import (
    JoinType,
    LogicalOperator,
    LogicalOperatorType,
    PhysicalOperator,
    QueryPlanDAG,
    validate_plan_tree,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signature hygiene: keeping cost/cardinality estimates out of the fingerprint
# ---------------------------------------------------------------------------
#
# The plan fingerprint is a LOGICAL, stats-independent structural hash (see the
# stability contract in ``query_plan_models.py``). A parser that folds an
# operator's raw EXPLAIN detail into a signature-bearing logical field
# (join_conditions, filter_expressions, aggregation_functions, sort_keys, ...)
# leaks any cost/cardinality estimate carried in that text into the hash, so a
# stats refresh or a different table size silently changes the fingerprint.
#
# The helpers below are the single place that strips estimate/cost tokens before
# such text reaches a signature-bearing field. Raw detail (including estimates)
# may still be retained in ``physical_operator.platform_metadata``, which is not
# hashed. A registry-wide invariant test enforces that no parser leaks these
# tokens (tests/unit/query_plans/test_fingerprint_hygiene.py).

# Substrings that mark a structured (dict) EXPLAIN key as estimate-bearing.
# Matched case-insensitively against the lower-cased key name. Deliberately
# avoids short ambiguous fragments (e.g. "ec") that collide with structural keys
# such as "Projections".
_ESTIMATE_KEY_SUBSTRINGS: tuple[str, ...] = (
    "cardinality",
    "estimated",
    "cost",
    "selectivity",
)

# Exact (normalized) key names that hold estimates without matching the
# substrings above. Deliberately omits schema-dependent names (e.g. "width")
# that could be a genuine structural field rather than a statistic.
_ESTIMATE_KEY_EXACT: frozenset[str] = frozenset(
    {
        "rows",
        "ec",
        "output_rows",
        "row_count",
        "num_rows",
        "plan_rows",
        "output_bytes",
        "output_batches",
    }
)

# DataFusion EXPLAIN ANALYZE appends a ``metrics=[...]`` block (output_rows,
# elapsed_compute, selectivity, ...) at the END of operator detail lines. The
# inner value list can itself contain brackets (e.g. ``partitioning=[Hash([a],4)]``),
# so match greedily to the final ``]`` rather than the first inner one.
_METRICS_BLOCK_RE = re.compile(r",?\s*metrics=\[.*\]", re.IGNORECASE)

# PostgreSQL / Redshift style cost parenthetical: ``(cost=1.0..2.0 rows=5 width=4)``.
# Anchored to the ``cost=N..N`` range form so a genuine predicate that merely
# starts with a column named ``cost`` (e.g. ``(cost=5 AND x=1)``) is NOT removed.
_COST_PAREN_RE = re.compile(
    r"\s*\(\s*cost=[\d.]+\.\.[\d.]+(?:\s+rows=\d+)?(?:\s+width=\d+)?\s*\)",
    re.IGNORECASE,
)

# Inline estimate tokens with an explicit estimate phrasing followed by a number.
# Restricted to unambiguous estimate wording (``Estimated Cardinality``, ``EC:``)
# so genuine predicates are never corrupted -- a column literally named ``cost``,
# ``rows``, ``num_rows``, ``cardinality`` or ``ec`` (e.g. ``ec = 7``) is left
# intact. DataFusion's ``output_rows``/``selectivity`` estimates only ever appear
# inside the ``metrics=[...]`` block removed above, and DuckDB's structured
# estimate keys are removed by ``strip_estimate_keys``.
_INLINE_ESTIMATE_RE = re.compile(
    r"""
    (?:
        (?:estimated\s+cardinality | estimated\s+cost | estimated\s+rows)
        \s*[:=]\s*\d[\d.,]*%?
        | \bEC:\s*\d[\d.,]*%?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

T = TypeVar("T")


def _key_is_estimate(key: str) -> bool:
    """Return True if a structured EXPLAIN key holds a cost/cardinality estimate."""
    normalized = str(key).strip().lower()
    if normalized in _ESTIMATE_KEY_EXACT:
        return True
    return any(token in normalized for token in _ESTIMATE_KEY_SUBSTRINGS)


def strip_estimate_keys(mapping: Mapping[str, T]) -> dict[str, T]:
    """
    Drop estimate-bearing keys from a structured EXPLAIN ``extra_info`` dict.

    Used by parsers (e.g. DuckDB FORMAT JSON) whose ``extra_info`` is a dict that
    mixes structural fields (``Conditions``, ``Groups``, ``Aggregates``) with
    estimate fields (``Estimated Cardinality``). Only the structural keys should
    reach a signature-bearing logical field; the estimate keys are removed here.

    The input mapping is not mutated; a new dict is returned.
    """
    return {key: value for key, value in mapping.items() if not _key_is_estimate(key)}


def strip_estimates(text: str) -> str:
    """
    Remove cost/cardinality/estimate tokens from a free-text EXPLAIN detail string.

    This is the single rule for keeping estimates out of signature-bearing fields
    in text-format parsers. It removes:

    - DataFusion ``metrics=[...]`` blocks (``output_rows``, ``selectivity``, ...)
    - PostgreSQL/Redshift ``(cost=N..N rows=N width=N)`` cost parentheticals
    - inline ``Estimated Cardinality: N`` / ``EC: N`` tokens

    Genuine predicate text is preserved: removal is anchored to explicit estimate
    wording, so a predicate on a column literally named ``cost``, ``rows`` or
    ``num_rows`` (e.g. ``(cost=5 AND x=1)`` or ``num_rows = 5``) is left intact.
    Returns the cleaned, whitespace-normalized string.
    """
    if not text:
        return text
    cleaned = _METRICS_BLOCK_RE.sub("", text)
    cleaned = _COST_PAREN_RE.sub("", cleaned)
    cleaned = _INLINE_ESTIMATE_RE.sub("", cleaned)
    # Tidy separators left behind by removals (trailing commas, empty brackets).
    cleaned = re.sub(r"\[\s*\]", "", cleaned)
    cleaned = re.sub(r"\s*,\s*(?=,|$)", "", cleaned)
    cleaned = re.sub(r",\s*$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip().strip(",").strip()


class QueryPlanParser(ABC):
    """
    Abstract base class for platform-specific query plan parsers.

    Subclasses implement parse_explain_output() to convert platform-specific
    EXPLAIN output into a harmonized QueryPlanDAG structure.
    """

    def __init__(self, platform_name: str):
        """
        Initialize parser.

        Args:
            platform_name: Name of the database platform (e.g., "duckdb", "postgres")
        """
        self.platform_name = platform_name
        self._operator_id_counter = 0

    def parse_explain_output(self, query_id: str, explain_output: str) -> QueryPlanDAG | None:
        """
        Parse EXPLAIN output into QueryPlanDAG.

        Args:
            query_id: Identifier of the query being explained
            explain_output: Raw EXPLAIN output from the database

        Returns:
            Parsed QueryPlanDAG or None if parsing fails

        Raises:
            PlanParseError: If parsing fails and raise_on_error is True
        """
        # Reset operator ID counter for each parse to ensure per-plan consistency
        self._operator_id_counter = 0

        # Store explain output for error context
        self._current_explain_output = explain_output
        self._current_query_id = query_id

        try:
            plan = self._parse_impl(query_id, explain_output)

            # Validate the parsed plan
            if plan and plan.logical_root:
                validation_errors = validate_plan_tree(plan.logical_root)
                if validation_errors:
                    logger.warning(
                        "Plan validation warnings for %s: %s",
                        query_id,
                        "; ".join(validation_errors),
                    )

            return plan
        except PlanParseError:
            # Re-raise PlanParseError as-is
            raise
        except Exception as e:
            # Detect format and get recovery hint
            detected_format = self._detect_explain_format(explain_output)
            recovery_hint = self._get_recovery_hint(detected_format, str(e))

            # Wrap in PlanParseError with enhanced context
            error = PlanParseError(
                query_id=query_id,
                platform=self.platform_name,
                error_message=str(e),
                explain_sample=self._get_explain_sample(),
                detected_format=detected_format,
                recovery_hint=recovery_hint,
            )
            logger.warning("Failed to parse query plan: %s", error)
            return None

    def _detect_explain_format(self, explain_output: str) -> str:
        """
        Detect the format of EXPLAIN output.

        Args:
            explain_output: Raw EXPLAIN output

        Returns:
            Format identifier: "json", "text", "xml", or "unknown"
        """
        if not explain_output:
            return "empty"

        stripped = explain_output.strip()
        if not stripped:
            return "empty"

        # JSON format detection
        if stripped.startswith("{") or stripped.startswith("["):
            return "json"

        # XML format detection
        if stripped.startswith("<?xml") or stripped.startswith("<"):
            return "xml"

        # Box-drawing characters indicate text format
        if any(char in stripped for char in "┌┐└┘│─├┤┬┴┼"):
            return "text-box"

        # Indented tree format (common in PostgreSQL)
        if any(keyword in stripped.lower() for keyword in ["->", "seq scan", "index scan", "hash join", "sort"]):
            return "text-tree"

        return "unknown"

    def _get_recovery_hint(self, detected_format: str, error_message: str) -> str | None:
        """
        Get a recovery hint based on the format and error.

        Args:
            detected_format: Detected format of the EXPLAIN output
            error_message: The error message from parsing

        Returns:
            Recovery hint string or None
        """
        hints = {
            "empty": "EXPLAIN output is empty. Check if the query executed successfully.",
            "unknown": f"Unknown EXPLAIN format for {self.platform_name}. Ensure EXPLAIN was run correctly.",
            "xml": "XML format detected. This parser may not support XML EXPLAIN output.",
        }

        if detected_format in hints:
            return hints[detected_format]

        # Error-specific hints
        error_lower = error_message.lower()
        if "json" in error_lower or "decode" in error_lower:
            return "JSON parsing failed. Check that the EXPLAIN output is valid JSON."
        if "no operators" in error_lower:
            return "No plan operators found. The EXPLAIN output may be truncated or in an unexpected format."

        return None

    def _get_explain_sample(self, max_length: int = 500) -> str | None:
        """Get a sample of the EXPLAIN output for error context."""
        if not hasattr(self, "_current_explain_output") or not self._current_explain_output:
            return None
        output = self._current_explain_output
        if len(output) > max_length:
            return output[:max_length] + "..."
        return output

    @abstractmethod
    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        """
        Platform-specific parsing implementation.

        Args:
            query_id: Identifier of the query being explained
            explain_output: Raw EXPLAIN output from the database

        Returns:
            Parsed QueryPlanDAG

        Raises:
            Exception: If parsing fails
        """
        raise NotImplementedError

    def _generate_operator_id(self, operator_type: str) -> str:
        """
        Generate unique operator ID.

        Args:
            operator_type: Type of operator (for naming)

        Returns:
            Unique operator ID (e.g., "scan_1", "join_2")
        """
        self._operator_id_counter += 1
        # Normalize operator type for ID
        normalized = re.sub(r"[^a-z0-9]+", "_", operator_type.lower())
        return f"{normalized}_{self._operator_id_counter}"

    def _harmonize_join_type(self, native_join_type: str) -> JoinType:
        """
        Convert platform-specific join type to harmonized JoinType enum.

        Args:
            native_join_type: Platform-specific join type string

        Returns:
            Harmonized JoinType enum value
        """
        # Normalize to lowercase for comparison
        normalized = native_join_type.lower().strip()

        # Handle common variations
        if "inner" in normalized:
            return JoinType.INNER
        elif "left" in normalized or "left outer" in normalized:
            return JoinType.LEFT
        elif "right" in normalized or "right outer" in normalized:
            return JoinType.RIGHT
        elif "full" in normalized or "full outer" in normalized:
            return JoinType.FULL
        elif "cross" in normalized:
            return JoinType.CROSS
        elif "semi" in normalized:
            return JoinType.SEMI
        elif "anti" in normalized:
            return JoinType.ANTI
        else:
            # Default to INNER for unknown join types
            logger.debug("Unknown join type '%s', defaulting to INNER", native_join_type)
            return JoinType.INNER

    def _harmonize_operator_type(self, native_operator: str) -> LogicalOperatorType:
        """
        Convert platform-specific operator to harmonized LogicalOperatorType.

        This method provides common harmonization patterns. Subclasses can override
        for platform-specific mappings.

        Args:
            native_operator: Platform-specific operator name

        Returns:
            Harmonized LogicalOperatorType enum value
        """
        # Normalize to lowercase for comparison
        normalized = native_operator.lower().strip()

        # Scan operators
        if any(keyword in normalized for keyword in ["scan", "seq scan", "index scan", "bitmap scan", "table scan"]):
            return LogicalOperatorType.SCAN

        # Filter operators
        if any(keyword in normalized for keyword in ["filter", "selection", "predicate"]):
            return LogicalOperatorType.FILTER

        # Join operators
        if any(keyword in normalized for keyword in ["join", "nested loop", "hash join", "merge join"]):
            return LogicalOperatorType.JOIN

        # Aggregate operators
        if any(keyword in normalized for keyword in ["aggregate", "group", "hash aggregate", "group by"]):
            return LogicalOperatorType.AGGREGATE

        # Sort operators
        if any(keyword in normalized for keyword in ["sort", "order by"]):
            return LogicalOperatorType.SORT

        # Limit operators
        if any(keyword in normalized for keyword in ["limit", "top", "fetch"]):
            return LogicalOperatorType.LIMIT

        # Project operators
        if any(keyword in normalized for keyword in ["project", "projection", "select", "compute"]):
            return LogicalOperatorType.PROJECT

        # Union operators
        if "union" in normalized:
            return LogicalOperatorType.UNION

        # Intersect operators
        if "intersect" in normalized:
            return LogicalOperatorType.INTERSECT

        # Except operators
        if any(keyword in normalized for keyword in ["except", "minus"]):
            return LogicalOperatorType.EXCEPT

        # Window operators
        if "window" in normalized:
            return LogicalOperatorType.WINDOW

        # CTE operators
        if any(keyword in normalized for keyword in ["cte", "with", "materialized"]):
            return LogicalOperatorType.CTE

        # Subquery operators
        if "subquery" in normalized or "subplan" in normalized:
            return LogicalOperatorType.SUBQUERY

        # Default to OTHER for unknown operators
        logger.debug("Unknown operator type '%s', categorized as OTHER", native_operator)
        return LogicalOperatorType.OTHER

    def _extract_table_name(self, operator_details: dict[str, Any]) -> str | None:
        """
        Extract table name from operator details.

        This is a helper method for common table name extraction patterns.

        Args:
            operator_details: Dictionary of operator properties

        Returns:
            Table name if found, None otherwise
        """
        # Common keys for table names across platforms
        for key in ["table", "table_name", "relation", "relation_name", "object_name"]:
            if key in operator_details:
                return str(operator_details[key])
        return None

    def _extract_cost_estimates(self, operator_details: dict[str, Any]) -> tuple[float | None, int | None]:
        """
        Extract cost and row estimates from operator details.

        Args:
            operator_details: Dictionary of operator properties

        Returns:
            Tuple of (estimated_cost, estimated_rows), either may be None
        """
        cost = None
        rows = None

        # Try to extract cost
        for key in ["cost", "total_cost", "estimated_cost", "plan_cost"]:
            if key in operator_details:
                try:
                    cost = float(operator_details[key])
                    break
                except (ValueError, TypeError):
                    pass

        # Try to extract row estimate
        for key in ["rows", "estimated_rows", "row_count", "plan_rows", "cardinality"]:
            if key in operator_details:
                try:
                    rows = int(operator_details[key])
                    break
                except (ValueError, TypeError):
                    pass

        return cost, rows

    def _create_physical_operator(
        self,
        native_operator_type: str,
        properties: dict[str, Any] | None = None,
        platform_metadata: dict[str, Any] | None = None,
    ) -> PhysicalOperator:
        """
        Create a PhysicalOperator with platform-specific details.

        Args:
            native_operator_type: Platform-specific operator type
            properties: Execution properties (cost, rows, etc.)
            platform_metadata: Additional platform-specific metadata

        Returns:
            PhysicalOperator instance
        """
        return PhysicalOperator(
            operator_type=native_operator_type,
            operator_id=self._generate_operator_id(native_operator_type),
            properties=properties or {},
            platform_metadata=platform_metadata or {},
        )

    def _create_logical_operator(
        self,
        operator_type: LogicalOperatorType,
        children: list[LogicalOperator] | None = None,
        physical_operator: PhysicalOperator | None = None,
        **kwargs: Any,
    ) -> LogicalOperator:
        """
        Create a LogicalOperator with harmonized type.

        Args:
            operator_type: Harmonized logical operator type
            children: Child operators
            physical_operator: Optional physical operator details
            **kwargs: Additional operator-specific fields (table_name, join_type, etc.)

        Returns:
            LogicalOperator instance
        """
        operator_id = self._generate_operator_id(operator_type.value)

        return LogicalOperator(
            operator_type=operator_type,
            operator_id=operator_id,
            children=children or [],
            physical_operator=physical_operator,
            **kwargs,
        )
