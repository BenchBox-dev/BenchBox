"""
DuckDB query plan parser.

Parses DuckDB EXPLAIN output into QueryPlanDAG structure.
Supports both JSON format (EXPLAIN FORMAT JSON) and text format with box-drawing.

JSON format is preferred (more stable, machine-readable) with text format as fallback.

Example text EXPLAIN output:
```
┌───────────────────────────┐
│         PROJECTION        │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│             l_returnflag  │
│                           │
│          l_linestatus     │
└─────────────┬─────────────┘
┌─────────────┴─────────────┐
│          ORDER_BY         │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│l_returnflag ASC NULLS LAST│
│                           │
│l_linestatus ASC NULLS LAST│
└─────────────┬─────────────┘
┌─────────────┴─────────────┐
│         HASH_GROUP_BY     │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│             #0            │
│                           │
│             #1            │
└─────────────┬─────────────┘
┌─────────────┴─────────────┐
│         PROJECTION        │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│         l_returnflag      │
│                           │
│         l_linestatus      │
└─────────────┬─────────────┘
┌─────────────┴─────────────┐
│           FILTER          │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│(l_shipdate <= CAST(      │
│'1998-12-01' AS DATE))     │
└─────────────┬─────────────┘
┌─────────────┴─────────────┐
│         SEQ_SCAN          │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│          lineitem         │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│         l_returnflag      │
│                           │
│         l_linestatus      │
│                           │
│          l_shipdate       │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│Filters: l_shipdate<=CAST( │
│'1998-12-01' AS DATE)      │
└───────────────────────────┘
```
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from benchbox.core.query_plans.parsers.base import (
    QueryPlanParser,
    strip_estimate_keys,
    strip_estimates,
)
from benchbox.core.results.query_plan_models import (
    LogicalOperator,
    LogicalOperatorType,
    QueryPlanDAG,
)

logger = logging.getLogger(__name__)


class DuckDBQueryPlanParser(QueryPlanParser):
    """Parser for DuckDB text-based EXPLAIN output."""

    def __init__(self):
        super().__init__("duckdb")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        """
        Parse DuckDB EXPLAIN output with format detection and fallback.

        Automatically detects JSON vs text format and parses accordingly.
        Falls back to text parser if JSON parsing fails.

        Args:
            query_id: Query identifier
            explain_output: DuckDB EXPLAIN output (JSON or text format)

        Returns:
            QueryPlanDAG

        Raises:
            ValueError: If output cannot be parsed in any format
        """
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")

        stripped = explain_output.strip()

        # Detect format and parse accordingly
        if self._is_json_format(stripped):
            try:
                return self._parse_json_format(query_id, explain_output)
            except Exception as e:
                logger.warning(
                    "JSON format parse failed for %s: %s, falling back to text parser",
                    query_id,
                    e,
                )
                # Fall through to text parser

        # Text format (or JSON fallback)
        return self._parse_text_format(query_id, explain_output)

    def _is_json_format(self, explain_output: str) -> bool:
        """Detect if EXPLAIN output is JSON format."""
        stripped = explain_output.strip()
        # JSON format starts with { or [
        return stripped.startswith("{") or stripped.startswith("[")

    def _parse_json_format(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        """
        Parse DuckDB EXPLAIN (FORMAT JSON) output.

        DuckDB JSON format structure (from EXPLAIN ANALYZE / FORMAT JSON):
        {
            "children": [
                {
                    "name": "QUERY_PLAN",
                    "timing": ...,
                    "cardinality": ...,
                    "extra_info": "...",
                    "children": [
                        {
                            "name": "PROJECTION",
                            "children": [...],
                            "extra_info": "..."
                        }
                    ]
                }
            ]
        }

        Args:
            query_id: Query identifier
            explain_output: JSON EXPLAIN output

        Returns:
            QueryPlanDAG

        Raises:
            ValueError: If JSON parsing fails
        """
        try:
            data = json.loads(explain_output)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}") from e

        # Handle different JSON structures
        if isinstance(data, list):
            # Array format - find the plan root
            if not data:
                raise ValueError("Empty JSON array")
            data = data[0] if len(data) == 1 else {"children": data}

        # Find the actual plan tree
        root_node = self._find_plan_root_in_json(data)
        if not root_node:
            raise ValueError("Could not find plan root in JSON structure")

        # Parse the tree recursively
        logical_root = self._parse_json_node(root_node)

        # Extract cost estimates from timing info.
        # EXPLAIN (FORMAT JSON) uses 'timing'/'cardinality'; EXPLAIN (ANALYZE, FORMAT JSON) uses 'latency'/'rows_returned'.
        estimated_cost = None
        estimated_rows = None
        if "timing" in data:
            estimated_cost = data["timing"]
        elif data.get("latency"):
            estimated_cost = data["latency"]
        if "cardinality" in data:
            try:
                estimated_rows = int(data["cardinality"])
            except (ValueError, TypeError):
                pass
        elif "rows_returned" in data:
            try:
                estimated_rows = int(data["rows_returned"])
            except (ValueError, TypeError):
                pass

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=logical_root,
            estimated_cost=estimated_cost,
            estimated_rows=estimated_rows,
            raw_explain_output=explain_output,
        )

    def _find_plan_root_in_json(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Find the actual plan tree root in JSON structure.

        Handles various DuckDB JSON formats:
        - Direct operator: {"name": "SEQ_SCAN", ...}
        - Wrapped in QUERY_PLAN: {"name": "QUERY_PLAN", "children": [...]}
        - Nested structure: {"children": [{"name": "QUERY_PLAN", ...}]}
        - EXPLAIN (ANALYZE, FORMAT JSON): {"operator_type": "EXPLAIN_ANALYZE", "children": [...]}
        """
        # Wrapper nodes to skip through (not real operators).
        # EXPLAIN_ANALYZE is the root wrapper injected by EXPLAIN (ANALYZE, FORMAT JSON).
        wrapper_names = ("QUERY_PLAN", "RESULT", "EXPLAIN", "QUERY", "EXPLAIN_ANALYZE")

        # Support both EXPLAIN FORMAT JSON ('name' key) and EXPLAIN (ANALYZE, FORMAT JSON) ('operator_type' key)
        node_name = data.get("name") or data.get("operator_type", "")

        if node_name:
            name = node_name.upper().strip()
            if name not in wrapper_names:
                # This is an actual operator node
                return data
            # This is a wrapper node, descend into its first child
            if "children" in data and data["children"]:
                return self._find_plan_root_in_json(data["children"][0])

        # No name/operator_type field (e.g. root stats object) - look at children
        if "children" in data and data["children"]:
            return self._find_plan_root_in_json(data["children"][0])

        # No valid root found
        return None

    def _parse_json_node(self, node: dict[str, Any]) -> LogicalOperator:
        """
        Recursively parse JSON node to LogicalOperator.

        Args:
            node: JSON node dictionary

        Returns:
            LogicalOperator instance
        """
        # EXPLAIN (ANALYZE, FORMAT JSON) uses operator_name/operator_type; EXPLAIN (FORMAT JSON) uses name.
        # operator_name (e.g. "SEQ_SCAN ") is preferred over operator_type (e.g. "TABLE_SCAN") for
        # harmonization because it matches the physical operator names expected by _harmonize_duckdb_operator.
        raw_name = node.get("operator_name") or node.get("name") or node.get("operator_type", "UNKNOWN")
        operator_name = raw_name.strip()
        operator_type = self._harmonize_duckdb_operator(operator_name)

        # Parse children recursively
        children = []
        for child_node in node.get("children", []):
            children.append(self._parse_json_node(child_node))

        # Extract operator-specific information
        kwargs: dict[str, Any] = {}
        raw_extra = node.get("extra_info", "")
        # DuckDB returns extra_info as a dict in FORMAT JSON responses; normalise to string.
        # `extra_info` keeps the raw detail (incl. estimates) for platform_metadata / table
        # extraction; `logical_extra` is the estimate-stripped form for signature-bearing
        # fields so the fingerprint stays stats-independent (see strip_estimates docstring).
        if isinstance(raw_extra, dict):
            extra_info = json.dumps(raw_extra)
            stripped_extra = strip_estimate_keys(raw_extra)
            logical_extra = json.dumps(stripped_extra) if stripped_extra else ""
        else:
            extra_info = raw_extra
            logical_extra = strip_estimates(raw_extra)

        if operator_type == LogicalOperatorType.SCAN:
            # Try to extract table name from extra_info
            table_name = self._extract_table_from_extra_info(extra_info)
            if table_name:
                kwargs["table_name"] = table_name

        elif operator_type == LogicalOperatorType.FILTER:
            if logical_extra:
                kwargs["filter_expressions"] = [logical_extra]

        elif operator_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = self._extract_join_type_from_operator(operator_name)
            if logical_extra:
                kwargs["join_conditions"] = [logical_extra]

        elif operator_type == LogicalOperatorType.AGGREGATE:
            if logical_extra:
                kwargs["aggregation_functions"] = [logical_extra]

        elif operator_type == LogicalOperatorType.SORT:
            if logical_extra:
                kwargs["sort_keys"] = [{"expr": logical_extra, "direction": "ASC"}]

        # Create physical operator with DuckDB-specific details.
        # EXPLAIN (ANALYZE, FORMAT JSON) uses operator_timing/operator_cardinality;
        # EXPLAIN (FORMAT JSON) uses timing/cardinality.
        # Use explicit None-check (not falsy `or`) so that 0.0 timing and 0-row
        # cardinality are preserved rather than silently replaced by None.
        _timing = node.get("timing")
        _cardinality = node.get("cardinality")
        physical_op = self._create_physical_operator(
            operator_name,
            properties={
                "timing": _timing if _timing is not None else node.get("operator_timing"),
                "cardinality": _cardinality if _cardinality is not None else node.get("operator_cardinality"),
            },
            platform_metadata={"extra_info": extra_info} if extra_info else {},
        )

        return self._create_logical_operator(
            operator_type=operator_type,
            children=children,
            physical_operator=physical_op,
            **kwargs,
        )

    def _extract_table_from_extra_info(self, extra_info: str) -> str | None:
        """Extract table name from extra_info field.

        Handles both string format (EXPLAIN FORMAT JSON) and JSON-encoded dict format
        (EXPLAIN (ANALYZE, FORMAT JSON) uses {"Table": "tablename", ...}).
        """
        if not extra_info:
            return None
        # EXPLAIN (ANALYZE, FORMAT JSON) encodes extra_info as a JSON dict with a "Table" key
        if extra_info.startswith("{"):
            try:
                parsed = json.loads(extra_info)
                if isinstance(parsed, dict) and "Table" in parsed:
                    return str(parsed["Table"])
            except (json.JSONDecodeError, TypeError):
                pass
        # EXPLAIN (FORMAT JSON): table name is typically the first bare identifier line
        lines = extra_info.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", line):
                return line
        return None

    def _parse_text_format(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        """
        Parse DuckDB text-based EXPLAIN output (box-drawing format).

        WARNING: Text format parsing only supports linear plans (single path from root to leaf).
        Branching plans (joins, unions) cannot be accurately parsed from text format and will
        raise an error. Use EXPLAIN (FORMAT JSON) for full plan fidelity.

        Args:
            query_id: Query identifier
            explain_output: Text EXPLAIN output

        Returns:
            QueryPlanDAG

        Raises:
            ValueError: If output cannot be parsed or contains branching structure
        """
        # Check for branching structure which we cannot parse correctly
        branching_detected = self._detect_branching_structure(explain_output)
        if branching_detected:
            raise ValueError(
                f"DuckDB text plan for '{query_id}' contains branching structure (joins/unions) "
                "that cannot be accurately parsed from box-drawing format. The text parser "
                "would flatten the tree into a linear chain, producing incorrect fingerprints "
                "and misleading comparison results. "
                "Use EXPLAIN (FORMAT JSON) for accurate plan capture. "
                "See: https://duckdb.org/docs/sql/query_syntax/explain "
                f"Branching indicators found: {branching_detected}"
            )

        # Parse operators from text output
        operators = self._parse_text_operators(explain_output)

        if not operators:
            raise ValueError("No operators found in EXPLAIN output")

        # Build operator tree (bottom-up from text representation)
        # Note: This builds a linear chain which is only correct for non-branching plans
        root = self._build_operator_tree(operators)

        # Log warning about limited fidelity
        logger.warning(
            "Query %s: Parsed from text format (limited fidelity). Use EXPLAIN (FORMAT JSON) for full plan structure.",
            query_id,
        )

        # Extract cost estimates if available (DuckDB doesn't always provide them in basic EXPLAIN)
        estimated_cost, estimated_rows = self._extract_estimates_from_output(explain_output)

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            estimated_cost=estimated_cost,
            estimated_rows=estimated_rows,
            raw_explain_output=explain_output,
        )

    def _detect_branching_structure(self, explain_output: str) -> str | None:
        """
        Detect if text EXPLAIN output contains branching structure.

        Branching is indicated by:
        - Multiple boxes at the same level (side-by-side boxes)
        - Fork connectors (┬, ├, ┤) suggesting multiple children
        - Join operators (which always have 2+ children)

        Args:
            explain_output: Text EXPLAIN output

        Returns:
            Description of branching indicators found, or None if linear plan
        """
        indicators = []

        # Look for join operators which always indicate branching
        join_patterns = ["HASH_JOIN", "NESTED_LOOP_JOIN", "PIECEWISE_MERGE_JOIN", "MERGE_JOIN", "CROSS_JOIN", "JOIN"]
        for pattern in join_patterns:
            if pattern in explain_output.upper():
                indicators.append(f"JOIN operator: {pattern}")

        # Look for union/intersect/except operators
        set_patterns = ["UNION", "INTERSECT", "EXCEPT"]
        for pattern in set_patterns:
            if pattern in explain_output.upper():
                indicators.append(f"SET operator: {pattern}")

        # Look for fork/branch connectors in box-drawing
        # The "┬" character indicates a node with multiple children
        if "┬" in explain_output:
            fork_count = explain_output.count("┬")
            if fork_count > 0:
                # Single fork at bottom is normal (root has one child)
                # Multiple forks or specific patterns indicate branching
                pass  # Let join detection handle this

        # Look for horizontal connectors that might indicate side-by-side boxes
        # Pattern: "┌─" appearing twice or more on adjacent lines
        lines = explain_output.split("\n")
        box_starts_by_line = []
        for i, line in enumerate(lines):
            if "┌" in line:
                # Count box starts on this line
                starts = line.count("┌")
                if starts > 1:
                    indicators.append(f"Multiple boxes on line {i + 1} (parallel branches)")
                box_starts_by_line.append((i, starts))

        if indicators:
            return "; ".join(indicators)
        return None

    def _parse_text_operators(self, explain_output: str) -> list[dict[str, Any]]:
        """
        Parse operator boxes from DuckDB text output.

        DuckDB uses box-drawing characters to show operator hierarchy.

        Returns:
            List of operator dictionaries with keys: operator_type, details, level
        """
        operators = []
        lines = explain_output.strip().split("\n")

        current_operator = None
        collecting_details = False

        for line in lines:
            # Check if this is the start of an operator box (top border with operator name)
            if "┌" in line and "┐" in line:
                # Next line should have the operator name
                collecting_details = False
                current_operator = None
            elif "│" in line and not collecting_details:
                # Extract operator name (uppercase, centered)
                content = line.strip("│ \t")
                content = content.strip()

                # Check if this looks like an operator name (uppercase, may have underscores)
                if content and content.replace("_", "").replace(" ", "").isalnum():
                    # Check if mostly uppercase or a known operator pattern
                    if content.isupper() or any(
                        op in content.upper()
                        for op in [
                            "SCAN",
                            "JOIN",
                            "FILTER",
                            "PROJECTION",
                            "AGGREGATE",
                            "GROUP",
                            "SORT",
                            "ORDER",
                            "LIMIT",
                            "HASH",
                            "NESTED",
                            "MERGE",
                        ]
                    ):
                        current_operator = {
                            "operator_type": content,
                            "details": [],
                            "properties": {},
                        }
                        operators.append(current_operator)
                        collecting_details = True
            elif "│" in line and collecting_details and current_operator:
                # Collecting operator details
                content = line.strip("│ \t")
                content = content.strip()

                # Skip separator lines
                if content and "─" not in content:
                    current_operator["details"].append(content)

        return operators

    def _build_operator_tree(self, operators: list[dict[str, Any]]) -> LogicalOperator:
        """
        Build operator tree from parsed operators.

        DuckDB text output is top-down, so we need to reverse it to build bottom-up.

        Args:
            operators: List of parsed operator dicts

        Returns:
            Root LogicalOperator
        """
        if not operators:
            raise ValueError("No operators to build tree from")

        # For now, build a simple linear chain since we don't have nesting info from text
        # In a real implementation, we'd parse the box structure to determine hierarchy
        logical_operators = []

        for op_dict in reversed(operators):  # Bottom-up
            logical_op = self._convert_to_logical_operator(op_dict, logical_operators[-1:] if logical_operators else [])
            logical_operators.append(logical_op)

        # Return the top operator (last in our reversed list)
        return logical_operators[-1] if logical_operators else self._create_fallback_operator()

    def _convert_to_logical_operator(
        self,
        op_dict: dict[str, Any],
        children: list[LogicalOperator],
    ) -> LogicalOperator:
        """
        Convert parsed operator dict to LogicalOperator.

        Args:
            op_dict: Operator dictionary from parsing
            children: Child operators

        Returns:
            LogicalOperator instance
        """
        operator_type_str = op_dict["operator_type"]
        details = op_dict["details"]

        # Harmonize operator type
        logical_type = self._harmonize_duckdb_operator(operator_type_str)

        # Extract operator-specific information
        kwargs: dict[str, Any] = {}

        if logical_type == LogicalOperatorType.SCAN:
            # Extract table name from details (usually first non-empty detail line)
            table_name = self._extract_table_name_from_details(details)
            if table_name:
                kwargs["table_name"] = table_name

        elif logical_type == LogicalOperatorType.FILTER:
            # Extract filter expressions
            filter_exprs = [d for d in details if d and not d.startswith("Filters:")]
            if filter_exprs:
                kwargs["filter_expressions"] = filter_exprs

        elif logical_type == LogicalOperatorType.AGGREGATE:
            # Extract aggregation info from details
            agg_funcs = [
                d for d in details if any(func in d.lower() for func in ["sum(", "count(", "avg(", "min(", "max("])
            ]
            if agg_funcs:
                kwargs["aggregation_functions"] = agg_funcs

        elif logical_type == LogicalOperatorType.SORT:
            # Extract sort keys
            sort_keys = []
            for detail in details:
                if "ASC" in detail or "DESC" in detail:
                    direction = "ASC" if "ASC" in detail else "DESC"
                    expr = (
                        detail.replace("ASC", "")
                        .replace("DESC", "")
                        .replace("NULLS LAST", "")
                        .replace("NULLS FIRST", "")
                        .strip()
                    )
                    sort_keys.append({"expr": expr, "direction": direction})
            if sort_keys:
                kwargs["sort_keys"] = sort_keys

        elif logical_type == LogicalOperatorType.JOIN:
            # Extract join type and conditions
            join_type = self._extract_join_type_from_operator(operator_type_str)
            kwargs["join_type"] = join_type

            # Extract join conditions from details
            join_conds = [d for d in details if "=" in d or "ON" in d]
            if join_conds:
                kwargs["join_conditions"] = join_conds

        # Create physical operator for DuckDB-specific details
        physical_op = self._create_physical_operator(
            operator_type_str,
            properties={},
            platform_metadata={"details": details},
        )

        return self._create_logical_operator(
            operator_type=logical_type,
            children=children,
            physical_operator=physical_op,
            **kwargs,
        )

    def _harmonize_duckdb_operator(self, duckdb_operator: str) -> LogicalOperatorType:
        """
        Convert DuckDB operator to harmonized LogicalOperatorType.

        Args:
            duckdb_operator: DuckDB operator name

        Returns:
            LogicalOperatorType
        """
        normalized = duckdb_operator.upper().strip()

        # Scan types
        if normalized in ["SEQ_SCAN", "INDEX_SCAN", "TABLE_SCAN"]:
            return LogicalOperatorType.SCAN

        # Filter
        if normalized == "FILTER":
            return LogicalOperatorType.FILTER

        # Joins
        if any(
            join_type in normalized for join_type in ["HASH_JOIN", "NESTED_LOOP_JOIN", "PIECEWISE_MERGE_JOIN", "JOIN"]
        ):
            return LogicalOperatorType.JOIN

        # Aggregates
        if normalized in ["HASH_GROUP_BY", "PERFECT_HASH_GROUP_BY", "AGGREGATE"]:
            return LogicalOperatorType.AGGREGATE

        # Sort
        if normalized in ["ORDER_BY", "TOP_N", "SORT"]:
            return LogicalOperatorType.SORT

        # Limit
        if normalized == "LIMIT":
            return LogicalOperatorType.LIMIT

        # Projection
        if normalized in ["PROJECTION", "RESULT_COLLECTOR"]:
            return LogicalOperatorType.PROJECT

        # Set operations
        if "UNION" in normalized:
            return LogicalOperatorType.UNION
        if "INTERSECT" in normalized:
            return LogicalOperatorType.INTERSECT
        if "EXCEPT" in normalized:
            return LogicalOperatorType.EXCEPT

        # Window
        if "WINDOW" in normalized:
            return LogicalOperatorType.WINDOW

        # CTE
        if "CTE" in normalized or "MATERIALIZED" in normalized:
            return LogicalOperatorType.CTE

        # Use base class harmonization as fallback
        return self._harmonize_operator_type(duckdb_operator)

    def _extract_table_name_from_details(self, details: list[str]) -> str | None:
        """Extract table name from operator details."""
        for detail in details:
            # Table name is usually a simple identifier (alphanumeric + underscore)
            if detail and re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", detail):
                return detail
        return None

    def _extract_join_type_from_operator(self, operator_type: str) -> str:
        """Extract join type from DuckDB operator name."""
        normalized = operator_type.upper()

        if "INNER" in normalized:
            return "inner"
        elif "LEFT" in normalized:
            return "left"
        elif "RIGHT" in normalized:
            return "right"
        elif "FULL" in normalized:
            return "full"
        elif "CROSS" in normalized:
            return "cross"
        else:
            # Default to inner for generic JOIN operators
            return "inner"

    def _extract_estimates_from_output(self, explain_output: str) -> tuple[float | None, int | None]:
        """
        Extract cost and row estimates from EXPLAIN output.

        DuckDB's basic EXPLAIN doesn't include cost estimates, so these will typically be None.
        EXPLAIN ANALYZE would provide actual execution stats.

        Returns:
            Tuple of (estimated_cost, estimated_rows)
        """
        # For basic EXPLAIN, we don't get cost estimates
        # Would need EXPLAIN ANALYZE or JSON format for that
        return None, None

    def _create_fallback_operator(self) -> LogicalOperator:
        """Create a fallback operator when parsing fails."""
        return self._create_logical_operator(
            operator_type=LogicalOperatorType.OTHER,
            properties={"note": "Fallback operator due to parsing failure"},
        )
