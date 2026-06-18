"""
Query plan data models for structured representation and analysis.

This module provides a two-tier DAG structure for query plans:
- Logical operators: Cross-platform normalized representation
- Physical operators: Platform-specific execution details

The models support fingerprinting for fast comparison and JSON serialization
for storage alongside benchmark results.

Plan fingerprint stability contract
------------------------------------
``QueryPlanDAG.plan_fingerprint`` is a SHA256 hash of the *logical* operator
tree's structural signature (see ``LogicalOperator.get_structural_signature``).
It is the canonical answer to "did the shape of this plan change?" and its
stability is defined as follows.

What the fingerprint hashes (structural shape only):
  - operator types and the recursive child structure (tree shape)
  - table names (Scan), join types and join conditions
  - filter expressions, aggregation functions, group-by / sort / projection
    expressions, and LIMIT / OFFSET counts

What the fingerprint deliberately EXCLUDES:
  - costs, estimated/actual row counts, and timing (execution statistics)
  - operator IDs and any other non-structural physical-operator properties

Stability guarantees (what a stable fingerprint means):
  - **Stats-independent.** The signature excludes the dedicated cost / row-estimate
    fields (``estimated_cost``, ``estimated_rows``, and the per-operator
    ``properties`` that hold cost/cardinality/timing). A ``VACUUM``/``ANALYZE`` or
    other statistics refresh that only changes row estimates does NOT change the
    fingerprint. Parsers that fold an operator's raw EXPLAIN detail into a
    signature-bearing field (e.g. the DuckDB FORMAT JSON ``extra_info`` dict, which
    carries an ``Estimated Cardinality``) strip the cost/cardinality tokens before
    the text reaches the hashed field, via the shared helpers in
    ``benchbox/core/query_plans/parsers/base.py`` (``strip_estimates`` /
    ``strip_estimate_keys``). A registry-wide invariant
    (``tests/unit/query_plans/test_fingerprint_hygiene.py``) enforces that no
    parser leaks estimate text into the signature, so this guarantee holds for
    every registered engine rather than needing per-engine verification.
  - **Logical, not physical — with an engine-dependent caveat.** The signature is
    built from the *logical* operator tree, so the physical access method is
    generally NOT reflected: an index scan and a sequential scan of the same table
    both normalize to a logical ``Scan``. On engines where the predicate is the
    same regardless of access method, adding an index does NOT change the
    fingerprint. **However, index-addition stability is not universal:** some
    engines expose the predicate differently per access method, and the parser
    captures only one form. On **PostgreSQL**, a sequential scan exposes the
    predicate as ``Filter`` (which the parser records in ``filter_expressions`` —
    structural and hashed) while an index scan exposes it as ``Index Cond`` (which
    the parser does NOT record), so adding an index that flips ``Filter`` →
    ``Index Cond`` for the same table/predicate *does* change the fingerprint, and
    bitmap plans can add child nodes that further change it. Treat index-addition
    stability as a property to verify per engine, not a guarantee.
  - **Logical-shape sensitive.** What DOES change the fingerprint is a change in
    the logical tree: join order or join type, an added aggregation (GROUP BY),
    sort, projection change, LIMIT/OFFSET, or filter predicates *where the
    engine's EXPLAIN exposes them*. That logical-shape change is the intended
    regression signal. Note that predicate sensitivity is engine-dependent: some
    EXPLAIN formats (e.g. SQLite ``EXPLAIN QUERY PLAN``) do not surface filter
    expressions, so two queries differing only in a WHERE constant may hash the
    same on those engines.

What fingerprint equality does NOT guarantee, and explicit non-guarantees:
  - **Not stable across engine versions.** A minor/major engine upgrade
    (PostgreSQL, DuckDB, etc.) can change EXPLAIN wording, operator naming, or
    default plan shapes, which may change the fingerprint even for an unchanged
    query. Cross-version fingerprint equality is therefore NOT promised — compare
    fingerprints only within the same engine version.
  - **Not cross-engine comparable.** Fingerprints from different platforms are
    not comparable: normalization is best-effort and operator vocabularies differ.
  - **Equality does not imply equal performance** (costs/timing are excluded),
    and inequality does not imply a regression (it may be a benign shape change).

Recommended use: stable for structural plan comparison and within-run
deduplication on a single engine version. Suitable for "did the plan shape
change?" regression detection when the engine version is held constant; not
suitable as a cross-version or cross-engine equality key.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from benchbox.core.errors import SerializationError

logger = logging.getLogger(__name__)

# Track unknown operator types that have been logged to avoid log flooding
_logged_unknown_operator_types: set[str] = set()
_logged_unknown_join_types: set[str] = set()


class LogicalOperatorType(str, Enum):
    """Normalized logical operator types across all platforms."""

    SCAN = "Scan"
    FILTER = "Filter"
    JOIN = "Join"
    AGGREGATE = "Aggregate"
    SORT = "Sort"
    LIMIT = "Limit"
    PROJECT = "Project"
    UNION = "Union"
    INTERSECT = "Intersect"
    EXCEPT = "Except"
    WINDOW = "Window"
    CTE = "CTE"
    SUBQUERY = "Subquery"
    OTHER = "Other"


class JoinType(str, Enum):
    """Standard join types."""

    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    FULL = "full"
    CROSS = "cross"
    SEMI = "semi"
    ANTI = "anti"


class AggregateFunction(str, Enum):
    """Common aggregate functions."""

    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    STDDEV = "stddev"
    VARIANCE = "variance"
    COUNT_DISTINCT = "count_distinct"
    ARRAY_AGG = "array_agg"
    STRING_AGG = "string_agg"
    OTHER = "other"


@dataclass
class PhysicalOperator:
    """
    Platform-specific physical operator with execution details.

    Attributes:
        operator_type: Platform-specific operator name (e.g., "HashAggregate", "SeqScan")
        operator_id: Unique identifier for this operator in the plan
        properties: Execution properties (estimated cost, rows, memory, etc.)
        platform_metadata: Additional platform-specific details
    """

    operator_type: str
    operator_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    platform_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "operator_type": self.operator_type,
            "operator_id": self.operator_id,
            "properties": self.properties,
            "platform_metadata": self.platform_metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhysicalOperator:
        """Reconstruct from dictionary."""
        return cls(
            operator_type=data["operator_type"],
            operator_id=data["operator_id"],
            properties=data.get("properties", {}),
            platform_metadata=data.get("platform_metadata", {}),
        )


@dataclass
class LogicalOperator:
    """
    Cross-platform logical operator with recursive tree structure.

    Attributes:
        operator_type: Normalized operator type from LogicalOperatorType enum
        operator_id: Unique identifier for this operator in the plan
        properties: Generic properties (cardinality estimates, selectivity, etc.)
        children: Child operators in the plan tree
        physical_operator: Optional platform-specific physical implementation
        table_name: For Scan operators - table being scanned
        join_type: For Join operators - type of join
        join_conditions: For Join operators - join predicates
        filter_expressions: For Filter operators - filter predicates
        aggregation_functions: For Aggregate operators - aggregate functions used
        group_by_keys: For Aggregate operators - grouping columns
        sort_keys: For Sort operators - sort expressions and directions
        projection_expressions: For Project operators - output columns
        limit_count: For Limit operators - row limit
        offset_count: For Limit/Offset operators - rows to skip
    """

    operator_type: LogicalOperatorType | str
    operator_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    children: list[LogicalOperator] = field(default_factory=list)
    physical_operator: PhysicalOperator | None = None

    # Operator-specific fields
    table_name: str | None = None
    join_type: JoinType | str | None = None
    join_conditions: list[str] | None = None
    filter_expressions: list[str] | None = None
    aggregation_functions: list[str] | None = None
    group_by_keys: list[str] | None = None
    sort_keys: list[dict[str, Any]] | None = None  # [{expr: "column", direction: "ASC"}]
    projection_expressions: list[str] | None = None
    limit_count: int | None = None
    offset_count: int | None = None

    def to_dict(self, max_depth: int | None = None, current_depth: int = 0) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary with optional depth guard."""
        if max_depth is not None and current_depth > max_depth:
            raise SerializationError(f"Max depth {max_depth} exceeded")

        # Handle enum conversion
        operator_type_value = (
            self.operator_type.value if isinstance(self.operator_type, LogicalOperatorType) else self.operator_type
        )
        join_type_value = self.join_type.value if isinstance(self.join_type, JoinType) else self.join_type

        return {
            "operator_type": operator_type_value,
            "operator_id": self.operator_id,
            "properties": self.properties,
            "children": [
                child.to_dict(max_depth=max_depth, current_depth=current_depth + 1) for child in self.children
            ],
            "physical_operator": self.physical_operator.to_dict() if self.physical_operator else None,
            "table_name": self.table_name,
            "join_type": join_type_value,
            "join_conditions": self.join_conditions,
            "filter_expressions": self.filter_expressions,
            "aggregation_functions": self.aggregation_functions,
            "group_by_keys": self.group_by_keys,
            "sort_keys": self.sort_keys,
            "projection_expressions": self.projection_expressions,
            "limit_count": self.limit_count,
            "offset_count": self.offset_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LogicalOperator:
        """Reconstruct from dictionary."""
        # Convert string back to enum if valid
        operator_type_str = data["operator_type"]
        try:
            operator_type = LogicalOperatorType(operator_type_str)
        except ValueError:
            operator_type = operator_type_str

        # Convert join_type string back to enum if present and valid
        join_type_str = data.get("join_type")
        join_type = None
        if join_type_str:
            try:
                join_type = JoinType(join_type_str)
            except ValueError:
                join_type = join_type_str

        return cls(
            operator_type=operator_type,
            operator_id=data["operator_id"],
            properties=data.get("properties", {}),
            children=[cls.from_dict(child) for child in data.get("children", [])],
            physical_operator=PhysicalOperator.from_dict(data["physical_operator"])
            if data.get("physical_operator")
            else None,
            table_name=data.get("table_name"),
            join_type=join_type,
            join_conditions=data.get("join_conditions"),
            filter_expressions=data.get("filter_expressions"),
            aggregation_functions=data.get("aggregation_functions"),
            group_by_keys=data.get("group_by_keys"),
            sort_keys=data.get("sort_keys"),
            projection_expressions=data.get("projection_expressions"),
            limit_count=data.get("limit_count"),
            offset_count=data.get("offset_count"),
        )

    def get_structural_signature(self) -> str:
        """
        Get structural signature for fingerprinting.

        Returns only structural elements that affect query semantics:
        - operator_type: Type of logical operation
        - table_name: For Scan operators
        - join_type: For Join operators
        - join_conditions: Predicates that affect join semantics (sorted for determinism)
        - filter_expressions: Filter predicates (sorted for determinism)
        - aggregation_functions: Aggregate functions (sorted for determinism)
        - group_by_keys: Grouping columns (order preserved - affects semantics)
        - sort_keys: Sort expressions (order preserved - affects output order)
        - projection_expressions: Output columns (order preserved - affects output)
        - limit_count: Row limit for LIMIT operations
        - offset_count: Row offset for OFFSET operations
        - children: Recursive child signatures

        Excludes non-structural properties like costs, row estimates, and operator IDs.

        Normalization rules:
        - Expressions compared as unordered sets: join_conditions, filter_expressions, aggregation_functions
        - Expressions with order significance: group_by_keys, sort_keys, projection_expressions
        - Numeric values included directly: limit_count, offset_count
        """
        # Build signature from structural elements only
        operator_type_str = get_operator_type_str(self.operator_type)
        signature_parts = [operator_type_str]

        # Table name for Scan operators
        if self.table_name:
            signature_parts.append(f"table:{self.table_name}")

        # Join type for Join operators
        if self.join_type:
            join_type_str = get_join_type_str(self.join_type)
            signature_parts.append(f"join:{join_type_str}")

        # Join conditions - sorted for set-like semantics (order doesn't affect result)
        if self.join_conditions:
            conditions_str = ",".join(sorted(self.join_conditions))
            signature_parts.append(f"join_cond:{conditions_str}")

        # Filter expressions - sorted for set-like semantics
        if self.filter_expressions:
            filters_str = ",".join(sorted(self.filter_expressions))
            signature_parts.append(f"filters:{filters_str}")

        # Aggregation functions - sorted for set-like semantics
        if self.aggregation_functions:
            aggs_str = ",".join(sorted(self.aggregation_functions))
            signature_parts.append(f"aggs:{aggs_str}")

        # Group by keys - order preserved (affects output row grouping)
        if self.group_by_keys:
            group_str = ",".join(self.group_by_keys)
            signature_parts.append(f"group:{group_str}")

        # Sort keys - order preserved (affects output ordering)
        if self.sort_keys:
            # Sort keys is a list of dicts, convert to deterministic string
            # Sort items within each dict for consistent representation
            sort_str = ",".join(str(sorted(sk.items())) for sk in self.sort_keys)
            signature_parts.append(f"sort:{sort_str}")

        # Projection expressions - order preserved (affects output columns)
        if self.projection_expressions:
            proj_str = ",".join(self.projection_expressions)
            signature_parts.append(f"proj:{proj_str}")

        # Limit count - affects result set size
        if self.limit_count is not None:
            signature_parts.append(f"limit:{self.limit_count}")

        # Offset count - affects which rows are returned
        if self.offset_count is not None:
            signature_parts.append(f"offset:{self.offset_count}")

        # Recursively include children signatures
        if self.children:
            for child in self.children:
                signature_parts.append(child.get_structural_signature())

        return "|".join(signature_parts)


class FingerprintIntegrity:
    """Fingerprint verification states."""

    VERIFIED = "verified"  # Fingerprint matches current tree structure
    STALE = "stale"  # Stored fingerprint doesn't match tree (possibly corrupted/tampered)
    UNVERIFIED = "unverified"  # Fingerprint not yet verified
    RECOMPUTED = "recomputed"  # Fingerprint was missing/stale and has been recomputed


@dataclass
class QueryPlanDAG:
    """
    Complete query plan representation with logical and physical layers.

    Attributes:
        query_id: Identifier of the query this plan is for
        platform: Database platform that generated this plan
        logical_root: Root of the logical operator tree
        estimated_cost: Overall estimated cost (if available)
        estimated_rows: Estimated result set size (if available)
        plan_fingerprint: SHA256 hash of logical structure for fast comparison
        raw_explain_output: Original EXPLAIN output for debugging (optional)
        fingerprint_integrity: Verification state of the fingerprint
    """

    query_id: str
    platform: str
    logical_root: LogicalOperator
    estimated_cost: float | None = None
    estimated_rows: int | None = None
    plan_fingerprint: str | None = None
    raw_explain_output: str | None = None
    fingerprint_integrity: str = field(default=FingerprintIntegrity.UNVERIFIED)

    def __post_init__(self) -> None:
        """Compute plan fingerprint after initialization."""
        if self.plan_fingerprint is None:
            self.plan_fingerprint = self.compute_plan_fingerprint()
            self.fingerprint_integrity = FingerprintIntegrity.VERIFIED

    def compute_plan_fingerprint(self) -> str:
        """
        Compute SHA256 hash of logical operator tree structure.

        Only includes structural elements (operator types, join types, table names).
        Excludes costs, row counts, operator IDs, and other non-structural properties.

        Returns:
            Hexadecimal SHA256 hash string
        """
        if self.logical_root is None:
            return hashlib.sha256(b"EMPTY_PLAN").hexdigest()
        structural_signature = self.logical_root.get_structural_signature()
        return hashlib.sha256(structural_signature.encode("utf-8")).hexdigest()

    def verify_fingerprint(self) -> bool:
        """
        Verify that the stored fingerprint matches the current tree structure.

        Returns:
            True if fingerprint is valid, False if it doesn't match
        """
        current = self.compute_plan_fingerprint()
        matches = current == self.plan_fingerprint
        if matches:
            self.fingerprint_integrity = FingerprintIntegrity.VERIFIED
        else:
            self.fingerprint_integrity = FingerprintIntegrity.STALE
        return matches

    def is_fingerprint_trusted(self) -> bool:
        """
        Check if the fingerprint can be trusted for comparison.

        A fingerprint is trusted if it has been verified or was computed fresh.
        Stale or unverified fingerprints should not be used for fast-path comparison.

        Returns:
            True if fingerprint is verified or recomputed
        """
        return self.fingerprint_integrity in (
            FingerprintIntegrity.VERIFIED,
            FingerprintIntegrity.RECOMPUTED,
        )

    def refresh_fingerprint(self) -> None:
        """
        Recompute and update the fingerprint based on current tree structure.

        Call this after modifying the tree structure to keep the fingerprint
        consistent with the actual tree.
        """
        self.plan_fingerprint = self.compute_plan_fingerprint()
        self.fingerprint_integrity = FingerprintIntegrity.VERIFIED

    def to_dict(self, max_depth: int | None = 50) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary with depth protection."""
        return {
            "query_id": self.query_id,
            "platform": self.platform,
            "logical_root": self.logical_root.to_dict(max_depth=max_depth, current_depth=0)
            if self.logical_root
            else None,
            "estimated_cost": self.estimated_cost,
            "estimated_rows": self.estimated_rows,
            "plan_fingerprint": self.plan_fingerprint,
            "raw_explain_output": self.raw_explain_output,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        verify_fingerprint: bool = True,
        refresh_on_mismatch: bool = False,
    ) -> QueryPlanDAG:
        """
        Reconstruct from dictionary with optional fingerprint verification.

        Args:
            data: Dictionary containing plan data
            verify_fingerprint: If True, verify stored fingerprint against tree
            refresh_on_mismatch: If True, recompute fingerprint when verification fails
                                 instead of keeping stale fingerprint

        Returns:
            QueryPlanDAG instance with fingerprint_integrity set appropriately
        """
        logical_root_data = data.get("logical_root")
        stored_fingerprint = data.get("plan_fingerprint")

        # Build the plan without setting fingerprint yet
        plan = cls(
            query_id=data["query_id"],
            platform=data["platform"],
            logical_root=LogicalOperator.from_dict(logical_root_data) if logical_root_data else None,
            estimated_cost=data.get("estimated_cost"),
            estimated_rows=data.get("estimated_rows"),
            plan_fingerprint=stored_fingerprint,
            raw_explain_output=data.get("raw_explain_output"),
            fingerprint_integrity=FingerprintIntegrity.UNVERIFIED,
        )

        # Verify fingerprint if requested
        if verify_fingerprint and stored_fingerprint is not None:
            computed = plan.compute_plan_fingerprint()
            if computed == stored_fingerprint:
                plan.fingerprint_integrity = FingerprintIntegrity.VERIFIED
            else:
                if refresh_on_mismatch:
                    plan.plan_fingerprint = computed
                    plan.fingerprint_integrity = FingerprintIntegrity.RECOMPUTED
                else:
                    plan.fingerprint_integrity = FingerprintIntegrity.STALE

        return plan

    def to_json(self, indent: int | None = 2, *, max_depth: int | None = 50) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(max_depth=max_depth), indent=indent)

    def estimate_serialized_size(self, *, max_depth: int | None = 50) -> int:
        """Estimate JSON serialized size in bytes."""
        return len(json.dumps(self.to_dict(max_depth=max_depth), indent=None))

    @classmethod
    def from_json(
        cls,
        json_str: str,
        *,
        verify_fingerprint: bool = True,
        refresh_on_mismatch: bool = False,
    ) -> QueryPlanDAG:
        """
        Deserialize from JSON string with optional fingerprint verification.

        Args:
            json_str: JSON string containing plan data
            verify_fingerprint: If True, verify stored fingerprint against tree
            refresh_on_mismatch: If True, recompute fingerprint when verification fails

        Returns:
            QueryPlanDAG instance with fingerprint_integrity set appropriately
        """
        return cls.from_dict(
            json.loads(json_str),
            verify_fingerprint=verify_fingerprint,
            refresh_on_mismatch=refresh_on_mismatch,
        )


def compute_plan_fingerprint(logical_root: LogicalOperator) -> str:
    """
    Compute SHA256 hash of logical operator tree structure.

    This is a standalone function for computing fingerprints without
    requiring a full QueryPlanDAG object.

    Args:
        logical_root: Root of the logical operator tree

    Returns:
        Hexadecimal SHA256 hash string
    """
    structural_signature = logical_root.get_structural_signature()
    return hashlib.sha256(structural_signature.encode("utf-8")).hexdigest()


def validate_plan_tree(root: LogicalOperator) -> list[str]:
    """
    Validate the structural integrity of a plan tree.

    Checks for:
    - Cycles in the tree structure
    - Duplicate operator IDs
    - Missing required fields
    - Empty operator types

    Args:
        root: Root of the logical operator tree

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []
    visited: set[int] = set()
    operator_ids: set[str] = set()

    def validate_node(node: LogicalOperator, path: list[str]) -> None:
        # Check for cycles using object identity
        node_id = id(node)
        if node_id in visited:
            errors.append(f"Cycle detected at {node.operator_id} (path: {' -> '.join(path)})")
            return
        visited.add(node_id)

        # Check for duplicate operator IDs
        if node.operator_id in operator_ids:
            errors.append(f"Duplicate operator_id: {node.operator_id}")
        operator_ids.add(node.operator_id)

        # Check required fields
        if not node.operator_type:
            errors.append(f"Missing operator_type for {node.operator_id}")

        if not node.operator_id:
            errors.append("Found operator with empty operator_id")

        # Recursively validate children
        for child in node.children:
            validate_node(child, path + [node.operator_id])

    validate_node(root, [])
    return errors


def validate_root_operator(root: LogicalOperator) -> list[str]:
    """
    Validate that the root operator is appropriate for a complete plan.

    Root operators should typically be result-producing operators like
    Project, Sort, or Limit. Having a Scan or Filter as root may indicate
    an incomplete or malformed plan.

    Args:
        root: Root of the logical operator tree

    Returns:
        List of warning messages (empty if valid)
    """
    warnings: list[str] = []

    # Get operator type string
    op_type = (
        root.operator_type.value if isinstance(root.operator_type, LogicalOperatorType) else str(root.operator_type)
    )

    # Scan or Filter as root is unusual (indicates incomplete plan)
    unusual_roots = {"Scan", "Filter", "SCAN", "FILTER"}
    if op_type in unusual_roots:
        warnings.append(
            f"Root operator is {op_type}, which is unusual. Plan may be incomplete. "
            "Expected: Project, Sort, Limit, or similar result-producing operator."
        )

    return warnings


def describe_tree(root: LogicalOperator, max_depth: int = 5) -> str:
    """
    Generate a brief text description of the plan tree structure.

    Useful for error messages and debugging.

    Args:
        root: Root of the logical operator tree
        max_depth: Maximum depth to describe

    Returns:
        String description of tree structure
    """
    lines: list[str] = []

    def describe_node(node: LogicalOperator, depth: int, prefix: str) -> None:
        if depth > max_depth:
            lines.append(f"{prefix}... (truncated)")
            return

        op_type = get_operator_type_str(node.operator_type)
        lines.append(f"{prefix}{op_type}[{node.operator_id}]")

        for i, child in enumerate(node.children):
            is_last = i == len(node.children) - 1
            child_prefix = prefix + ("  " if is_last else "  ")
            describe_node(child, depth + 1, child_prefix)

    describe_node(root, 0, "")
    return "\n".join(lines)


def get_operator_type_str(operator_type: LogicalOperatorType | str, *, warn_unknown: bool = True) -> str:
    """
    Safely extract string value from an operator type.

    Works with both LogicalOperatorType enum values and raw strings,
    enabling graceful handling of unknown/unmapped operator types from parsers.

    Args:
        operator_type: Either a LogicalOperatorType enum or string
        warn_unknown: If True, log a warning for unknown string operator types (default: True).
                      The warning is only logged once per unique operator type to avoid log flooding.

    Returns:
        String representation of the operator type
    """
    if isinstance(operator_type, LogicalOperatorType):
        return operator_type.value

    # String operator type - check if it's a known enum value
    op_str = str(operator_type)
    try:
        # If it matches a known enum value, it's not truly unknown
        LogicalOperatorType(op_str)
    except ValueError:
        # Unknown operator type - log warning if not already logged
        if warn_unknown and op_str not in _logged_unknown_operator_types:
            _logged_unknown_operator_types.add(op_str)
            logger.warning(
                f"Unknown operator type '{op_str}' encountered. "
                "Consider adding a mapping in the parser or extending LogicalOperatorType enum."
            )
    return op_str


def get_join_type_str(join_type: JoinType | str | None, *, warn_unknown: bool = True) -> str | None:
    """
    Safely extract string value from a join type.

    Works with both JoinType enum values and raw strings,
    enabling graceful handling of unknown/unmapped join types from parsers.

    Args:
        join_type: Either a JoinType enum, string, or None
        warn_unknown: If True, log a warning for unknown string join types (default: True).
                      The warning is only logged once per unique join type to avoid log flooding.

    Returns:
        String representation of the join type, or None if input is None
    """
    if join_type is None:
        return None
    if isinstance(join_type, JoinType):
        return join_type.value

    # String join type - check if it's a known enum value
    jt_str = str(join_type)
    try:
        # If it matches a known enum value, it's not truly unknown
        JoinType(jt_str)
    except ValueError:
        # Unknown join type - log warning if not already logged
        if warn_unknown and jt_str not in _logged_unknown_join_types:
            _logged_unknown_join_types.add(jt_str)
            logger.warning(
                f"Unknown join type '{jt_str}' encountered. "
                "Consider adding a mapping in the parser or extending JoinType enum."
            )
    return jt_str


def normalize_operator_type(operator_type: LogicalOperatorType | str) -> LogicalOperatorType | str:
    """
    Normalize an operator type for comparison purposes.

    If the input is already a LogicalOperatorType, returns it as-is.
    If it's a string that matches a known enum value, returns the enum.
    Otherwise returns the string to allow unknown operators.

    Args:
        operator_type: Either a LogicalOperatorType enum or string

    Returns:
        Normalized operator type (enum if known, string if unknown)
    """
    if isinstance(operator_type, LogicalOperatorType):
        return operator_type
    # Try to convert string to enum
    try:
        return LogicalOperatorType(operator_type)
    except ValueError:
        return operator_type


def is_operator_type_match(left: LogicalOperatorType | str, right: LogicalOperatorType | str) -> bool:
    """
    Check if two operator types match, handling both enum and string forms.

    Two operator types match if their string representations are equal,
    regardless of whether they are enums or strings.

    Args:
        left: First operator type
        right: Second operator type

    Returns:
        True if the operator types match
    """
    # Disable warnings during comparison to avoid duplicate warnings
    return get_operator_type_str(left, warn_unknown=False) == get_operator_type_str(right, warn_unknown=False)


def clear_unknown_type_warnings() -> None:
    """
    Clear the set of logged unknown operator and join types.

    This is primarily useful for testing to reset the warning state between tests.
    In normal usage, warnings are logged once per unique unknown type.
    """
    _logged_unknown_operator_types.clear()
    _logged_unknown_join_types.clear()
