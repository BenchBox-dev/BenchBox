"""
SQLite query plan parser.

Parses SQLite's EXPLAIN QUERY PLAN output into QueryPlanDAG structure.
SQLite uses a simple indented text format showing the query execution plan.

Example EXPLAIN QUERY PLAN output:
```
QUERY PLAN
|--SCAN TABLE orders
`--USE TEMP B-TREE FOR ORDER BY
```

Or with joins:
```
QUERY PLAN
|--SCAN TABLE customer
`--SEARCH TABLE orders USING INDEX idx_customer (c_custkey=?)
```
"""

from __future__ import annotations

import logging
import re
from typing import Any

from benchbox.core.query_plans.parsers.base import QueryPlanParser
from benchbox.core.results.query_plan_models import (
    LogicalOperator,
    LogicalOperatorType,
    QueryPlanDAG,
)

logger = logging.getLogger(__name__)


class SQLiteQueryPlanParser(QueryPlanParser):
    """Parser for SQLite EXPLAIN QUERY PLAN output."""

    def __init__(self):
        super().__init__("sqlite")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        """
        Parse SQLite EXPLAIN QUERY PLAN output.

        Args:
            query_id: Query identifier
            explain_output: SQLite EXPLAIN QUERY PLAN output

        Returns:
            QueryPlanDAG

        Raises:
            ValueError: If output cannot be parsed
        """
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")

        # Parse lines
        lines = explain_output.strip().split("\n")

        # Skip header if present
        if lines and "QUERY PLAN" in lines[0]:
            lines = lines[1:]

        if not lines:
            raise ValueError("No plan lines found")

        # Parse operators from text
        operators = self._parse_text_operators(lines)

        if not operators:
            raise ValueError("No operators found in EXPLAIN output")

        # Build operator tree
        root = self._build_operator_tree(operators)

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            estimated_cost=None,  # SQLite EXPLAIN QUERY PLAN doesn't provide cost estimates
            estimated_rows=None,
            raw_explain_output=explain_output,
        )

    def _parse_text_operators(self, lines: list[str]) -> list[dict[str, Any]]:
        """
        Parse operator lines from SQLite output.

        SQLite uses indentation with |-- and `-- prefixes to show hierarchy.

        Returns:
            List of operator dictionaries
        """
        operators = []

        for line in lines:
            if not line.strip():
                continue

            # Extract indentation level
            level = 0
            stripped = line.lstrip("|`- ")
            indent_chars = line[: len(line) - len(stripped)]
            level = indent_chars.count("|") + indent_chars.count("`")

            # Parse operator details
            op_dict = self._parse_operator_line(stripped, level)
            if op_dict:
                operators.append(op_dict)

        return operators

    def _parse_operator_line(self, line: str, level: int) -> dict[str, Any] | None:
        """
        Parse a single operator line.

        Args:
            line: Stripped operator description
            level: Indentation level

        Returns:
            Operator dictionary or None
        """
        line = line.strip()
        if not line:
            return None

        # Common SQLite patterns:
        # - SCAN TABLE tablename
        # - SEARCH TABLE tablename USING INDEX idx_name
        # - USE TEMP B-TREE FOR ORDER BY
        # - USE TEMP B-TREE FOR GROUP BY
        # - EXECUTE CORRELATED SCALAR SUBQUERY

        return {
            "text": line,
            "level": level,
            "type": self._infer_operator_type(line),
            "details": self._extract_details(line),
        }

    def _infer_operator_type(self, line: str) -> str:
        """Infer operator type from line text."""
        upper = line.upper()

        # Handle both old ("SCAN TABLE name") and modern ("SCAN name") SQLite formats
        if "SCAN TABLE" in upper or "SCAN SUBQUERY" in upper or upper.startswith("SCAN "):
            return "SCAN"
        elif "SEARCH TABLE" in upper or upper.startswith("SEARCH "):
            return "INDEX_SCAN"
        elif "ORDER BY" in upper:
            return "SORT"
        elif "GROUP BY" in upper:
            return "AGGREGATE"
        elif "TEMP B-TREE" in upper and "JOIN" not in upper:
            # Temp B-tree without JOIN context is usually for sorting/grouping
            if "ORDER BY" in upper:
                return "SORT"
            elif "GROUP BY" in upper:
                return "AGGREGATE"
            else:
                return "OTHER"
        elif "COMPOUND" in upper or "UNION" in upper:
            return "UNION"
        elif "SUBQUERY" in upper:
            return "SUBQUERY"
        else:
            return "OTHER"

    def _extract_details(self, line: str) -> dict[str, Any]:
        """Extract details from operator line."""
        details: dict[str, Any] = {}

        # Extract table name from SCAN/SEARCH patterns
        # Handles both old ("SCAN TABLE name") and modern ("SCAN name") SQLite formats
        match = re.search(r"(?:SCAN|SEARCH) (?:TABLE |SUBQUERY )?(\w+)", line, re.IGNORECASE)
        if match:
            details["table_name"] = match.group(1)

        # Extract index name
        match = re.search(r"USING INDEX (\w+)", line, re.IGNORECASE)
        if match:
            details["index_name"] = match.group(1)

        # Extract join type if present
        if "LEFT" in line.upper():
            details["join_type"] = "left"
        elif "RIGHT" in line.upper():
            details["join_type"] = "right"
        elif "OUTER" in line.upper():
            details["join_type"] = "full"
        elif "JOIN" in line.upper():
            details["join_type"] = "inner"

        return details

    def _build_operator_tree(self, operators: list[dict[str, Any]]) -> LogicalOperator:
        """
        Build operator tree from parsed operators.

        SQLite output is hierarchical with indentation, but for simplicity
        we'll build a linear chain for now.

        Args:
            operators: List of parsed operators

        Returns:
            Root LogicalOperator
        """
        if not operators:
            raise ValueError("No operators to build tree from")

        # Build operators bottom-up (reverse order)
        logical_operators = []

        for op_dict in reversed(operators):
            logical_op = self._convert_to_logical_operator(op_dict, logical_operators[-1:] if logical_operators else [])
            logical_operators.append(logical_op)

        # Return the top operator
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
        op_type_str = op_dict["type"]
        details = op_dict["details"]
        text = op_dict["text"]

        # Map to logical operator type
        logical_type = self._map_sqlite_operator(op_type_str)

        # Extract operator-specific information
        kwargs: dict[str, Any] = {}

        if logical_type == LogicalOperatorType.SCAN:
            table_name = details.get("table_name")
            if table_name:
                kwargs["table_name"] = table_name

        elif logical_type == LogicalOperatorType.SORT:
            # Extract sort information from text if available
            kwargs["properties"] = {"temp_btree": "TEMP B-TREE" in text.upper()}

        elif logical_type == LogicalOperatorType.AGGREGATE:
            kwargs["properties"] = {"temp_btree": "TEMP B-TREE" in text.upper()}

        # Create physical operator with SQLite-specific details
        physical_op = self._create_physical_operator(
            op_type_str,
            properties=details.copy(),
            platform_metadata={"text": text, "level": op_dict["level"]},
        )

        return self._create_logical_operator(
            operator_type=logical_type,
            children=children,
            physical_operator=physical_op,
            **kwargs,
        )

    def _map_sqlite_operator(self, sqlite_op: str) -> LogicalOperatorType:
        """Map SQLite operator string to LogicalOperatorType."""
        normalized = sqlite_op.upper()

        if normalized == "SCAN" or normalized == "INDEX_SCAN":
            return LogicalOperatorType.SCAN
        elif normalized == "SORT":
            return LogicalOperatorType.SORT
        elif normalized == "AGGREGATE":
            return LogicalOperatorType.AGGREGATE
        elif normalized == "UNION":
            return LogicalOperatorType.UNION
        elif normalized == "SUBQUERY":
            return LogicalOperatorType.SUBQUERY
        else:
            return LogicalOperatorType.OTHER

    def _create_fallback_operator(self) -> LogicalOperator:
        """Create fallback operator when parsing fails."""
        return self._create_logical_operator(
            operator_type=LogicalOperatorType.OTHER,
            properties={"note": "Fallback operator due to parsing failure"},
        )
