"""
Query plan comparison engine.

Implements algorithms for comparing query plans:
- Logical plan structure comparison (tree diff)
- Similarity scoring (tree edit distance)
- Cross-platform comparison
- Cross-run regression detection
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from benchbox.core.results.query_plan_models import (
    LogicalOperator,
    LogicalOperatorType,
    QueryPlanDAG,
    get_join_type_str,
    get_operator_type_str,
    is_operator_type_match,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cross-engine comparable subset (wrapper-stripped structural backbone)
# ---------------------------------------------------------------------------
#
# The raw plan_fingerprint is a PER-ENGINE within-version key and is deliberately
# NOT comparable across engines (see the stability contract in
# query_plan_models.py): engines emit different wrapper/exchange/codegen operators
# and harmonize names differently (ClickHouse Expression -> Project, Presto Output
# -> Project, Spark Exchange -> Other), so the same logical query hashes differently
# on each engine.
#
# This projection provides the SEPARATE, opt-in cross-engine view: it reduces a
# harmonized DAG to its structural backbone — the relational skeleton of base
# scans, joins, aggregates and set operations — by
#   1. dropping engine-variable wrapper nodes (Project/Filter/CTE/Subquery/Other),
#      which carry no cross-engine-stable structural meaning, and
#   2. collapsing a parent->child run of the SAME backbone type into one node, so a
#      partial+final aggregate (Spark/Databend) or a multi-stage sort (Doris) counts
#      once — the single logical operation it represents.
#
# The result is a multiset of backbone operator types that IS comparable across
# engines for the same logical query. It is intentionally kept separate from the
# raw fingerprint, which remains unchanged for within-engine regression detection.

# Operator types that form the cross-engine structural backbone. Everything else
# (Project / Filter / CTE / Subquery / Other) is treated as engine-variable wrapper
# noise and dropped from the comparable subset.
BACKBONE_OPERATOR_TYPES: frozenset[str] = frozenset(
    {
        LogicalOperatorType.SCAN.value,
        LogicalOperatorType.JOIN.value,
        LogicalOperatorType.AGGREGATE.value,
        LogicalOperatorType.SORT.value,
        LogicalOperatorType.LIMIT.value,
        LogicalOperatorType.UNION.value,
        LogicalOperatorType.INTERSECT.value,
        LogicalOperatorType.EXCEPT.value,
        LogicalOperatorType.WINDOW.value,
    }
)

# Backbone operators that engines split into a parent->child run of the SAME type as
# stages of ONE logical operation: a partial+final aggregate (Spark/Databend) or a
# multi-stage / merge sort (Doris). Only these collapse. JOIN, SCAN and the set
# operators are NOT collapsed: a parent Join over a child Join is a multi-table join
# (two distinct joins), and a Scan over a Scan is two distinct base scans — collapsing
# those would undercount the relational skeleton the projection exists to measure.
COLLAPSIBLE_OPERATOR_TYPES: frozenset[str] = frozenset(
    {
        LogicalOperatorType.AGGREGATE.value,
        LogicalOperatorType.SORT.value,
    }
)

# Dropped wrapper types that are pure physical pass-throughs (exchanges, repartitions
# and codegen stages, all harmonized to ``Other``). A collapsible backbone run separated
# only by these still collapses — ``Aggregate -> Exchange -> Aggregate`` is the partial+
# final stages of ONE aggregate. Every other dropped wrapper (Filter/Project/Subquery/CTE)
# is a real relational boundary and is NOT transparent: it resets the collapse context so
# separate aggregations/sorts on either side (e.g. a grouped subquery filtered before an
# outer aggregate, ``Aggregate -> Filter -> Aggregate``) are counted as two operators.
TRANSPARENT_WRAPPER_TYPES: frozenset[str] = frozenset(
    {
        LogicalOperatorType.OTHER.value,
    }
)


def _backbone_type(node: LogicalOperator) -> str | None:
    """Return the backbone operator-type string for a node, or None if it is wrapper noise."""
    type_str = get_operator_type_str(node.operator_type, warn_unknown=False)
    return type_str if type_str in BACKBONE_OPERATOR_TYPES else None


def structural_backbone_counts(
    root: LogicalOperator,
    *,
    only: set[str] | frozenset[str] | None = None,
) -> dict[str, int]:
    """Reduce a harmonized DAG to a cross-engine comparable multiset of backbone operators.

    Wrapper/engine-variable nodes (Project/Filter/CTE/Subquery/Other) are dropped. A
    parent->child run of the same *collapsible* backbone type
    (``COLLAPSIBLE_OPERATOR_TYPES`` — aggregate, sort) is collapsed to a single node,
    so a partial+final aggregate or a multi-stage sort counts once. The collapse looks
    through transparent physical wrappers (exchanges), so ``Aggregate -> Exchange ->
    Aggregate`` still counts as one aggregate, but a semantic boundary resets it, so
    ``Aggregate -> Filter -> Aggregate`` correctly counts two. Non-collapsible backbone
    operators (joins, scans, set
    operators) are always counted per node, so a left-deep 3-table join correctly
    reports two joins.

    Args:
        root: Root of the harmonized logical operator tree.
        only: Optional set of backbone operator-type strings to restrict the result to
            (keys not present are reported as 0). Use to compare a declared invariant
            subset (e.g. {"Scan", "Join", "Aggregate"}) across engines. Must be
            non-empty when provided.

    Returns:
        Mapping of backbone operator-type string -> count.
    """
    if only is not None and not only:
        raise ValueError("`only` must be a non-empty set of operator types, or None to include all")

    counts: dict[str, int] = {}

    def walk(node: LogicalOperator, collapsing_type: str | None) -> None:
        backbone = _backbone_type(node)
        if backbone is None:
            # Wrapper node: drop it. Keep the collapse context only through transparent
            # physical pass-throughs (exchanges harmonized to ``Other``) so a partial+
            # final aggregate still collapses; reset it through semantic relational
            # boundaries (Filter/Project/Subquery/CTE) so separate aggregations/sorts on
            # either side are counted independently.
            wrapper_type = get_operator_type_str(node.operator_type, warn_unknown=False)
            child_collapsing = collapsing_type if wrapper_type in TRANSPARENT_WRAPPER_TYPES else None
            for child in node.children:
                walk(child, child_collapsing)
            return
        # Count the node unless it continues a collapsible same-type run.
        if not (backbone in COLLAPSIBLE_OPERATOR_TYPES and backbone == collapsing_type):
            counts[backbone] = counts.get(backbone, 0) + 1
        # Only propagate a collapse context for collapsible types; otherwise reset it so
        # an unrelated descendant of the same type is still counted.
        next_collapsing = backbone if backbone in COLLAPSIBLE_OPERATOR_TYPES else None
        for child in node.children:
            walk(child, next_collapsing)

    walk(root, None)

    if only is not None:
        return {key: counts.get(key, 0) for key in only}
    return counts


def comparable_subset_signature(
    root: LogicalOperator,
    *,
    only: set[str] | frozenset[str] | None = None,
) -> str:
    """Deterministic string signature of the cross-engine structural backbone.

    Unlike ``QueryPlanDAG.plan_fingerprint`` (per-engine, not cross-engine comparable),
    this signature is stable across engines for the same logical query because it is
    built from the wrapper-stripped, collapsed backbone. Two plans from different
    engines that share a backbone produce the same signature.

    Args:
        root: Root of the harmonized logical operator tree.
        only: Optional restriction set (see ``structural_backbone_counts``).

    Returns:
        Signature like ``"Aggregate:1|Join:1|Scan:2"`` (sorted by operator type).
    """
    counts = structural_backbone_counts(root, only=only)
    return "|".join(f"{op_type}:{counts[op_type]}" for op_type in sorted(counts))


def structural_backbones_match(
    left: LogicalOperator,
    right: LogicalOperator,
    *,
    only: set[str] | frozenset[str] | None = None,
) -> bool:
    """Return True if two plans share the same cross-engine structural backbone.

    This is the cross-engine equivalent of ``plan_fingerprint`` equality: it compares
    the wrapper-stripped backbone multisets, so it is meaningful across engines for the
    same logical query (whereas raw fingerprint equality is not).
    """
    return structural_backbone_counts(left, only=only) == structural_backbone_counts(right, only=only)


@dataclass
class OperatorDiff:
    """Represents a difference between two operators."""

    operator_id_left: str
    operator_id_right: str
    diff_type: str  # "match", "type_mismatch", "property_mismatch", "structure_mismatch"
    differences: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimilarityScore:
    """Similarity score between two query plans."""

    overall_similarity: float  # 0.0 to 1.0
    structural_similarity: float  # Based on tree structure
    operator_similarity: float  # Based on operator types
    property_similarity: float  # Based on operator properties

    # Details
    total_operators_left: int
    total_operators_right: int
    matching_operators: int
    type_mismatches: int
    property_mismatches: int
    structure_mismatches: int


@dataclass
class PlanComparison:
    """Result of comparing two query plans."""

    plan_left: QueryPlanDAG
    plan_right: QueryPlanDAG

    # High-level comparison
    plans_identical: bool
    fingerprints_match: bool

    # Similarity metrics
    similarity: SimilarityScore

    # Detailed differences
    operator_diffs: list[OperatorDiff] = field(default_factory=list)

    # Summary
    summary: str = ""


def _compare_scan(left: LogicalOperator, right: LogicalOperator, diffs: dict[str, Any]) -> None:
    if left.table_name != right.table_name:
        diffs["table_name"] = {"left": left.table_name, "right": right.table_name}


def _compare_join(left: LogicalOperator, right: LogicalOperator, diffs: dict[str, Any]) -> None:
    if left.join_type != right.join_type:
        diffs["join_type"] = {
            "left": get_join_type_str(left.join_type),
            "right": get_join_type_str(right.join_type),
        }


def _compare_set_diff(left: LogicalOperator, right: LogicalOperator, diffs: dict[str, Any], attr: str) -> None:
    """Compare an attribute as an unordered set (membership only, not position).

    Use for attributes where order is irrelevant (filter_expressions, aggregation_functions).
    For order-significant attributes (group_by_keys, projection_expressions), use direct ``!=``.
    """
    left_vals = set(getattr(left, attr) or [])
    right_vals = set(getattr(right, attr) or [])
    if left_vals != right_vals:
        diffs[attr] = {
            "left_only": sorted(left_vals - right_vals),
            "right_only": sorted(right_vals - left_vals),
        }


def _compare_sort(left: LogicalOperator, right: LogicalOperator, diffs: dict[str, Any]) -> None:
    if left.sort_keys != right.sort_keys:
        diffs["sort_keys"] = {"left": left.sort_keys, "right": right.sort_keys}


def _compare_aggregate(left: LogicalOperator, right: LogicalOperator, diffs: dict[str, Any]) -> None:
    _compare_set_diff(left, right, diffs, "aggregation_functions")
    # group_by_keys is order-significant (affects output row grouping)
    if (left.group_by_keys or []) != (right.group_by_keys or []):
        diffs["group_by_keys"] = {"left": left.group_by_keys, "right": right.group_by_keys}


def _compare_limit(left: LogicalOperator, right: LogicalOperator, diffs: dict[str, Any]) -> None:
    if left.limit_count != right.limit_count:
        diffs["limit_count"] = {"left": left.limit_count, "right": right.limit_count}
    if left.offset_count != right.offset_count:
        diffs["offset_count"] = {"left": left.offset_count, "right": right.offset_count}


def _compare_project(left: LogicalOperator, right: LogicalOperator, diffs: dict[str, Any]) -> None:
    # projection_expressions is order-significant (affects output columns)
    if (left.projection_expressions or []) != (right.projection_expressions or []):
        diffs["projection_expressions"] = {
            "left": left.projection_expressions,
            "right": right.projection_expressions,
        }


_OPERATOR_COMPARATORS: dict[str, Callable[[LogicalOperator, LogicalOperator, dict[str, Any]], None]] = {
    "Scan": _compare_scan,
    "Join": _compare_join,
    "Filter": lambda l, r, d: _compare_set_diff(l, r, d, "filter_expressions"),
    "Aggregate": _compare_aggregate,
    "Sort": _compare_sort,
    "Limit": _compare_limit,
    "Project": _compare_project,
}


class QueryPlanComparator:
    """Compares query plans and computes similarity scores."""

    def compare_plans(
        self,
        plan_left: QueryPlanDAG,
        plan_right: QueryPlanDAG,
    ) -> PlanComparison:
        """
        Compare two query plans.

        Uses fingerprint fast-path when both plans have trusted fingerprints.
        Falls back to full tree comparison when fingerprints are unverified or stale.

        Args:
            plan_left: First query plan
            plan_right: Second query plan

        Returns:
            PlanComparison with detailed differences and similarity score
        """
        # Check if fingerprints can be trusted for fast-path comparison
        left_trusted = plan_left.is_fingerprint_trusted()
        right_trusted = plan_right.is_fingerprint_trusted()

        # Quick fingerprint check (only if both are trusted)
        fingerprints_match = False
        if left_trusted and right_trusted:
            fingerprints_match = (
                plan_left.plan_fingerprint == plan_right.plan_fingerprint
                if plan_left.plan_fingerprint and plan_right.plan_fingerprint
                else False
            )

            # If fingerprints match and both are trusted, plans are identical
            if fingerprints_match:
                return self._create_identical_comparison(plan_left, plan_right)
        else:
            # Log a warning about untrusted fingerprints
            if not left_trusted:
                logger.debug(
                    f"Plan {plan_left.query_id} has untrusted fingerprint "
                    f"(integrity={plan_left.fingerprint_integrity}), using full comparison"
                )
            if not right_trusted:
                logger.debug(
                    f"Plan {plan_right.query_id} has untrusted fingerprint "
                    f"(integrity={plan_right.fingerprint_integrity}), using full comparison"
                )

        # Perform detailed tree comparison
        operator_diffs = self._compare_operator_trees(
            plan_left.logical_root,
            plan_right.logical_root,
        )

        # Calculate similarity score
        similarity = self._calculate_similarity(
            plan_left.logical_root,
            plan_right.logical_root,
            operator_diffs,
        )

        # Generate summary
        summary = self._generate_summary(similarity, operator_diffs)

        return PlanComparison(
            plan_left=plan_left,
            plan_right=plan_right,
            plans_identical=False,
            fingerprints_match=fingerprints_match,
            similarity=similarity,
            operator_diffs=operator_diffs,
            summary=summary,
        )

    def _create_identical_comparison(
        self,
        plan_left: QueryPlanDAG,
        plan_right: QueryPlanDAG,
    ) -> PlanComparison:
        """Create comparison result for identical plans."""
        total_ops = self._count_operators(plan_left.logical_root)

        similarity = SimilarityScore(
            overall_similarity=1.0,
            structural_similarity=1.0,
            operator_similarity=1.0,
            property_similarity=1.0,
            total_operators_left=total_ops,
            total_operators_right=total_ops,
            matching_operators=total_ops,
            type_mismatches=0,
            property_mismatches=0,
            structure_mismatches=0,
        )

        return PlanComparison(
            plan_left=plan_left,
            plan_right=plan_right,
            plans_identical=True,
            fingerprints_match=True,
            similarity=similarity,
            operator_diffs=[],
            summary="Plans are identical (fingerprints match)",
        )

    def _compare_operator_trees(
        self,
        left: LogicalOperator,
        right: LogicalOperator,
    ) -> list[OperatorDiff]:
        """
        Compare two operator trees and generate list of differences.

        Uses a top-down traversal to compare structure and properties.

        Args:
            left: Left operator tree
            right: Right operator tree

        Returns:
            List of operator differences
        """
        diffs: list[OperatorDiff] = []

        # Compare using BFS traversal
        queue: deque[tuple[LogicalOperator | None, LogicalOperator | None]] = deque([(left, right)])

        while queue:
            op_left, op_right = queue.popleft()

            # Handle cases where one side is None
            if op_left is None and op_right is None:
                continue

            if op_left is None or op_right is None:
                diffs.append(
                    OperatorDiff(
                        operator_id_left=op_left.operator_id if op_left else "MISSING",
                        operator_id_right=op_right.operator_id if op_right else "MISSING",
                        diff_type="structure_mismatch",
                        differences={"reason": "One tree has operator, other doesn't"},
                    )
                )
                continue

            # Compare operator types (handle both enum and string forms)
            if not is_operator_type_match(op_left.operator_type, op_right.operator_type):
                diffs.append(
                    OperatorDiff(
                        operator_id_left=op_left.operator_id,
                        operator_id_right=op_right.operator_id,
                        diff_type="type_mismatch",
                        differences={
                            "left_type": get_operator_type_str(op_left.operator_type),
                            "right_type": get_operator_type_str(op_right.operator_type),
                        },
                    )
                )
            else:
                # Same type - compare properties
                property_diffs = self._compare_operator_properties(op_left, op_right)
                if property_diffs:
                    diffs.append(
                        OperatorDiff(
                            operator_id_left=op_left.operator_id,
                            operator_id_right=op_right.operator_id,
                            diff_type="property_mismatch",
                            differences=property_diffs,
                        )
                    )
                else:
                    # Exact match
                    diffs.append(
                        OperatorDiff(
                            operator_id_left=op_left.operator_id,
                            operator_id_right=op_right.operator_id,
                            diff_type="match",
                            differences={},
                        )
                    )

            # Compare children
            left_children = op_left.children or []
            right_children = op_right.children or []

            # Check for structure mismatch (different number of children)
            if len(left_children) != len(right_children):
                diffs.append(
                    OperatorDiff(
                        operator_id_left=op_left.operator_id,
                        operator_id_right=op_right.operator_id,
                        diff_type="structure_mismatch",
                        differences={
                            "left_children": len(left_children),
                            "right_children": len(right_children),
                        },
                    )
                )

            # Queue children for comparison
            max_children = max(len(left_children), len(right_children))
            for i in range(max_children):
                left_child = left_children[i] if i < len(left_children) else None
                right_child = right_children[i] if i < len(right_children) else None
                queue.append((left_child, right_child))

        return diffs

    def _compare_operator_properties(
        self,
        left: LogicalOperator,
        right: LogicalOperator,
    ) -> dict[str, Any]:
        """
        Compare properties of two operators of the same type.

        Handles both enum and string operator types gracefully.

        Args:
            left: Left operator
            right: Right operator

        Returns:
            Dictionary of property differences (empty if identical)
        """
        diffs: dict[str, Any] = {}

        op_type_str = get_operator_type_str(left.operator_type)
        comparator = _OPERATOR_COMPARATORS.get(op_type_str)
        if comparator:
            comparator(left, right, diffs)

        # Compare generic properties dictionary
        left_props = left.properties or {}
        right_props = right.properties or {}

        for key in set(left_props.keys()) | set(right_props.keys()):
            if left_props.get(key) != right_props.get(key):
                if "properties" not in diffs:
                    diffs["properties"] = {}
                diffs["properties"][key] = {
                    "left": left_props.get(key),
                    "right": right_props.get(key),
                }

        return diffs

    def _calculate_similarity(
        self,
        left: LogicalOperator,
        right: LogicalOperator,
        diffs: list[OperatorDiff],
    ) -> SimilarityScore:
        """
        Calculate similarity score based on operator diffs.

        Args:
            left: Left operator tree
            right: Right operator tree
            diffs: List of operator differences

        Returns:
            SimilarityScore
        """
        # Count operators
        total_left = self._count_operators(left)
        total_right = self._count_operators(right)

        # Count different types of diffs
        matches = sum(1 for d in diffs if d.diff_type == "match")
        type_mismatches = sum(1 for d in diffs if d.diff_type == "type_mismatch")
        property_mismatches = sum(1 for d in diffs if d.diff_type == "property_mismatch")
        structure_mismatches = sum(1 for d in diffs if d.diff_type == "structure_mismatch")

        # Calculate component similarities
        total_comparisons = max(total_left, total_right)

        # Structural similarity: based on tree structure (presence of operators)
        structural_similarity = 1.0 - (structure_mismatches / total_comparisons) if total_comparisons > 0 else 1.0

        # Operator similarity: based on operator types matching
        operator_similarity = (matches + property_mismatches) / total_comparisons if total_comparisons > 0 else 1.0

        # Property similarity: based on properties matching when types are same
        # Only count matches out of operators with matching types
        operators_with_same_type = matches + property_mismatches
        property_similarity = matches / operators_with_same_type if operators_with_same_type > 0 else 1.0

        # Overall similarity: weighted average
        overall_similarity = 0.4 * structural_similarity + 0.4 * operator_similarity + 0.2 * property_similarity

        return SimilarityScore(
            overall_similarity=overall_similarity,
            structural_similarity=structural_similarity,
            operator_similarity=operator_similarity,
            property_similarity=property_similarity,
            total_operators_left=total_left,
            total_operators_right=total_right,
            matching_operators=matches,
            type_mismatches=type_mismatches,
            property_mismatches=property_mismatches,
            structure_mismatches=structure_mismatches,
        )

    def _count_operators(self, operator: LogicalOperator) -> int:
        """Count total operators in tree."""
        count = 1
        if operator.children:
            for child in operator.children:
                count += self._count_operators(child)
        return count

    def _generate_summary(
        self,
        similarity: SimilarityScore,
        diffs: list[OperatorDiff],
    ) -> str:
        """Generate human-readable summary of comparison."""
        if similarity.overall_similarity >= 0.95:
            level = "nearly identical"
        elif similarity.overall_similarity >= 0.75:
            level = "very similar"
        elif similarity.overall_similarity >= 0.50:
            level = "somewhat similar"
        else:
            level = "significantly different"

        summary_parts = [
            f"Plans are {level} ({similarity.overall_similarity:.1%} similarity)",
        ]

        if similarity.type_mismatches > 0:
            summary_parts.append(f"{similarity.type_mismatches} operator type mismatches")

        if similarity.property_mismatches > 0:
            summary_parts.append(f"{similarity.property_mismatches} property differences")

        if similarity.structure_mismatches > 0:
            summary_parts.append(f"{similarity.structure_mismatches} structural differences")

        return "; ".join(summary_parts)


def compare_query_plans(
    plan_left: QueryPlanDAG,
    plan_right: QueryPlanDAG,
) -> PlanComparison:
    """
    Compare two query plans.

    Convenience function that creates a comparator and performs comparison.

    Args:
        plan_left: First query plan
        plan_right: Second query plan

    Returns:
        PlanComparison with detailed differences and similarity score
    """
    comparator = QueryPlanComparator()
    return comparator.compare_plans(plan_left, plan_right)


@dataclass
class QueryPlanChange:
    """Represents a query plan change between two runs."""

    query_id: str
    change_type: str  # "unchanged", "type_change", "property_change", "structure_change"
    similarity: float
    details: str


@dataclass
class PerformanceCorrelation:
    """Correlation between plan change and performance impact."""

    query_id: str
    plan_changed: bool
    baseline_time_ms: float
    current_time_ms: float
    perf_change_pct: float
    is_regression: bool  # plan changed AND perf degraded >20%


@dataclass
class PlanComparisonSummary:
    """Summary of plan comparison between two benchmark runs."""

    baseline_run_id: str
    current_run_id: str
    plans_compared: int
    plans_unchanged: int
    plans_changed: int
    structural_differences: list[QueryPlanChange]
    performance_correlations: list[PerformanceCorrelation]

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "baseline_run_id": self.baseline_run_id,
            "current_run_id": self.current_run_id,
            "plans_compared": self.plans_compared,
            "plans_unchanged": self.plans_unchanged,
            "plans_changed": self.plans_changed,
            "structural_differences": [
                {
                    "query_id": d.query_id,
                    "change_type": d.change_type,
                    "similarity": d.similarity,
                    "details": d.details,
                }
                for d in self.structural_differences
            ],
            "performance_correlations": [
                {
                    "query_id": c.query_id,
                    "plan_changed": c.plan_changed,
                    "baseline_time_ms": c.baseline_time_ms,
                    "current_time_ms": c.current_time_ms,
                    "perf_change_pct": c.perf_change_pct,
                    "is_regression": c.is_regression,
                }
                for c in self.performance_correlations
            ],
        }


def _build_execution_map(results: Any) -> dict[str, Any]:
    """Collect the first execution per query ID across all phases."""
    execution_map: dict[str, Any] = {}
    for phase_results in results.phases.values():
        for execution in phase_results.queries:
            execution_map.setdefault(execution.query_id, execution)
    return execution_map


def generate_plan_comparison_summary(
    baseline_results: Any,  # BenchmarkResults
    current_results: Any,  # BenchmarkResults
    *,
    regression_threshold_pct: float = 20.0,
) -> PlanComparisonSummary:
    """
    Generate a comparison summary between two benchmark runs.

    Compares query plans and correlates plan changes with performance changes.
    Identifies regressions where plan changed AND performance degraded.

    Args:
        baseline_results: Baseline BenchmarkResults
        current_results: Current BenchmarkResults
        regression_threshold_pct: Performance degradation threshold for regression (default 20%)

    Returns:
        PlanComparisonSummary with detailed comparison information
    """
    # Build execution maps for both runs
    baseline_map = _build_execution_map(baseline_results)
    current_map = _build_execution_map(current_results)

    # Find common queries
    common_queries = set(baseline_map.keys()) & set(current_map.keys())

    plans_compared = 0
    plans_unchanged = 0
    plans_changed = 0
    structural_differences: list[QueryPlanChange] = []
    performance_correlations: list[PerformanceCorrelation] = []

    comparator = QueryPlanComparator()

    for query_id in sorted(common_queries):
        baseline_exec = baseline_map[query_id]
        current_exec = current_map[query_id]

        baseline_plan = getattr(baseline_exec, "query_plan", None)
        current_plan = getattr(current_exec, "query_plan", None)

        # Skip if either run doesn't have a plan
        if not baseline_plan or not current_plan:
            continue

        plans_compared += 1

        # Compare fingerprints first (fast path)
        baseline_fp = getattr(baseline_plan, "plan_fingerprint", None)
        current_fp = getattr(current_plan, "plan_fingerprint", None)

        plan_changed = baseline_fp != current_fp

        if not plan_changed:
            plans_unchanged += 1
            change = QueryPlanChange(
                query_id=query_id,
                change_type="unchanged",
                similarity=1.0,
                details="Plans are identical",
            )
        else:
            plans_changed += 1

            # Perform detailed comparison
            comparison = comparator.compare_plans(baseline_plan, current_plan)

            # Determine primary change type
            if comparison.similarity.structure_mismatches > 0:
                change_type = "structure_change"
            elif comparison.similarity.type_mismatches > 0:
                change_type = "type_change"
            else:
                change_type = "property_change"

            change = QueryPlanChange(
                query_id=query_id,
                change_type=change_type,
                similarity=comparison.similarity.overall_similarity,
                details=comparison.summary,
            )

        structural_differences.append(change)

        # Calculate performance correlation
        baseline_time = getattr(baseline_exec, "execution_time_ms", 0.0) or 0.0
        current_time = getattr(current_exec, "execution_time_ms", 0.0) or 0.0

        if baseline_time > 0:
            perf_change_pct = ((current_time - baseline_time) / baseline_time) * 100
        else:
            perf_change_pct = 0.0

        # Regression: plan changed AND performance degraded beyond threshold
        is_regression = plan_changed and perf_change_pct > regression_threshold_pct

        correlation = PerformanceCorrelation(
            query_id=query_id,
            plan_changed=plan_changed,
            baseline_time_ms=baseline_time,
            current_time_ms=current_time,
            perf_change_pct=perf_change_pct,
            is_regression=is_regression,
        )
        performance_correlations.append(correlation)

    return PlanComparisonSummary(
        baseline_run_id=getattr(baseline_results, "run_id", "unknown"),
        current_run_id=getattr(current_results, "run_id", "unknown"),
        plans_compared=plans_compared,
        plans_unchanged=plans_unchanged,
        plans_changed=plans_changed,
        structural_differences=structural_differences,
        performance_correlations=performance_correlations,
    )
