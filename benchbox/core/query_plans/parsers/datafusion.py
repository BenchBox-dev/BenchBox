"""
DataFusion query plan parser.

Parses DataFusion's text-based EXPLAIN output into QueryPlanDAG structure.
DataFusion uses indentation to show operator hierarchy in its default indent format.

Example EXPLAIN output:
```
logical_plan  | Sort: wid ASC NULLS LAST, ip DESC NULLS FIRST, fetch=5
              |   Projection: hits.parquet.WatchID AS wid, hits.parquet.ClientIP AS ip
              |     Filter: starts_with(hits.parquet.URL, Utf8("http://example.com/"))
              |       TableScan: hits.parquet projection=[WatchID, ClientIP, URL]
physical_plan | SortPreservingMergeExec: [wid@0 ASC NULLS LAST,ip@1 DESC], fetch=5
              |   SortExec: TopK(fetch=5), expr=[wid@0 ASC NULLS LAST,ip@1 DESC]
              |     ProjectionExec: expr=[WatchID@0 as wid, ClientIP@1 as ip]
              |       FilterExec: starts_with(URL@2, http://example.com/)
              |         DataSourceExec: file_groups={16 groups...}
```

DataFusion operators in physical plans end with "Exec" suffix.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from benchbox.core.query_plans.parsers.base import QueryPlanParser
from benchbox.core.results.query_plan_models import (
    JoinType,
    LogicalOperator,
    LogicalOperatorType,
    QueryPlanDAG,
)

logger = logging.getLogger(__name__)


class DataFusionQueryPlanParser(QueryPlanParser):
    """Parser for DataFusion text-based EXPLAIN output."""

    # DataFusion operator to LogicalOperatorType mapping
    # Physical operators end with "Exec"
    OPERATOR_MAP = {
        # Scan operators
        "tablescan": LogicalOperatorType.SCAN,
        "datasourceexec": LogicalOperatorType.SCAN,
        "parquetexec": LogicalOperatorType.SCAN,
        "csvexec": LogicalOperatorType.SCAN,
        "memoryexec": LogicalOperatorType.SCAN,
        "emptymemoryexec": LogicalOperatorType.SCAN,
        # Join operators
        "hashjoinexec": LogicalOperatorType.JOIN,
        "nestedloopjoinexec": LogicalOperatorType.JOIN,
        "sortmergejoinexec": LogicalOperatorType.JOIN,
        "crossjoinexec": LogicalOperatorType.JOIN,
        "join": LogicalOperatorType.JOIN,
        "inner join": LogicalOperatorType.JOIN,
        "left join": LogicalOperatorType.JOIN,
        "right join": LogicalOperatorType.JOIN,
        "full join": LogicalOperatorType.JOIN,
        "cross join": LogicalOperatorType.JOIN,
        # Aggregate operators
        "aggregateexec": LogicalOperatorType.AGGREGATE,
        "aggregate": LogicalOperatorType.AGGREGATE,
        # Sort operators
        "sortexec": LogicalOperatorType.SORT,
        "sortpreservingmergeexec": LogicalOperatorType.SORT,
        "sort": LogicalOperatorType.SORT,
        # Limit operators
        "globalimitexec": LogicalOperatorType.LIMIT,
        "locallimitexec": LogicalOperatorType.LIMIT,
        "limit": LogicalOperatorType.LIMIT,
        # Project operators
        "projectionexec": LogicalOperatorType.PROJECT,
        "projection": LogicalOperatorType.PROJECT,
        # Filter operators
        "filterexec": LogicalOperatorType.FILTER,
        "filter": LogicalOperatorType.FILTER,
        "coalescebatchesexec": LogicalOperatorType.OTHER,
        # Window
        "windowaggexec": LogicalOperatorType.WINDOW,
        "boundedwindowaggexec": LogicalOperatorType.WINDOW,
        "windowagg": LogicalOperatorType.WINDOW,
        # Set operations
        "unionexec": LogicalOperatorType.UNION,
        "interleaveexec": LogicalOperatorType.UNION,
        "union": LogicalOperatorType.UNION,
        # Repartition/Distribution
        "repartitionexec": LogicalOperatorType.OTHER,
        "coalesceexec": LogicalOperatorType.OTHER,
        "coalescepartitionsexec": LogicalOperatorType.OTHER,
        # Other
        "explainexec": LogicalOperatorType.OTHER,
        "analyzeexec": LogicalOperatorType.OTHER,
        "hashpartitionexec": LogicalOperatorType.OTHER,
        # Subquery
        "subqueryscan": LogicalOperatorType.SUBQUERY,
        "subquery": LogicalOperatorType.SUBQUERY,
        # CTE
        "ctescan": LogicalOperatorType.CTE,
    }

    # Pattern to extract operator from a line
    # Matches: "OperatorExec: details" or "Operator: details" or just "Operator"
    OPERATOR_PATTERN = re.compile(
        r"^\s*(?:\|\s*)?"  # Optional prefix and pipe
        r"(?P<indent>\s*)"  # Leading whitespace (indentation)
        r"(?P<operator>[A-Za-z][A-Za-z0-9_]*(?:Exec)?)"  # Operator name (optionally ending with Exec)
        r"(?::\s*(?P<details>.+))?"  # Optional details after colon
        r"\s*$"
    )

    # Pattern to match logical/physical plan section headers
    SECTION_PATTERN = re.compile(r"^(logical_plan|physical_plan)\s*\|?\s*(.*)$", re.IGNORECASE)

    # Pattern to extract metrics from EXPLAIN ANALYZE output
    METRICS_PATTERN = re.compile(r"metrics=\[([^\]]+)\]")

    def __init__(self):
        super().__init__("datafusion")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        """
        Parse DataFusion EXPLAIN output.

        Args:
            query_id: Query identifier
            explain_output: DataFusion EXPLAIN output

        Returns:
            QueryPlanDAG

        Raises:
            ValueError: If output cannot be parsed
        """
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")

        # Prefer physical plan if available, fall back to logical plan
        physical_lines = self._extract_plan_section(explain_output, "physical_plan")
        logical_lines = self._extract_plan_section(explain_output, "logical_plan")

        # Use physical plan if available (more detailed), otherwise use logical
        plan_lines = physical_lines if physical_lines else logical_lines

        if not plan_lines:
            # Try parsing as raw plan without section headers
            plan_lines = self._extract_raw_plan(explain_output)

        if not plan_lines:
            raise ValueError("No plan found in EXPLAIN output")

        # Parse lines into operator nodes
        parsed_nodes = self._parse_lines(plan_lines)

        if not parsed_nodes:
            raise ValueError("No operators found in EXPLAIN output")

        # Build tree from parsed nodes
        root = self._build_tree(parsed_nodes)

        # Extract estimates from root (DataFusion doesn't always provide cost)
        estimated_cost = None
        estimated_rows = None
        if parsed_nodes and parsed_nodes[0].get("metrics"):
            metrics = parsed_nodes[0]["metrics"]
            estimated_rows = metrics.get("output_rows")

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            estimated_cost=estimated_cost,
            estimated_rows=estimated_rows,
            raw_explain_output=explain_output,
        )

    def _extract_plan_section(self, explain_output: str, section_name: str) -> list[str]:
        """
        Extract lines for a specific plan section (logical_plan or physical_plan).

        Preserves relative indentation for hierarchy parsing.

        Args:
            explain_output: Full EXPLAIN output
            section_name: Section to extract ("logical_plan" or "physical_plan")

        Returns:
            List of lines for that section with preserved indentation
        """
        lines = explain_output.strip().split("\n")
        section_lines = []
        in_section = False

        for line in lines:
            # Check for section header
            section_match = self.SECTION_PATTERN.match(line)
            if section_match:
                current_section = section_match.group(1).lower()
                if current_section == section_name.lower():
                    in_section = True
                    # Include the rest of this line if it has content (first operator, no indent)
                    rest = section_match.group(2).strip()
                    if rest:
                        section_lines.append(rest)  # Root operator, no leading spaces
                else:
                    in_section = False
            elif in_section:
                # Continue collecting lines for this section
                # Preserve indentation relative to the pipe character
                # Format: "              |   SortExec: ..."
                # We need to find the pipe and extract content after it with preserved indent
                pipe_idx = line.find("|")
                if pipe_idx >= 0:
                    # Extract everything after the pipe, preserving indentation
                    content = line[pipe_idx + 1 :]
                    if content.strip():  # Only add non-empty lines
                        section_lines.append(content)
                elif line.strip():
                    # No pipe found, might be a raw line - use as-is
                    section_lines.append(line)

        return section_lines

    def _extract_raw_plan(self, explain_output: str) -> list[str]:
        """
        Extract plan from output without section headers.

        Args:
            explain_output: Full EXPLAIN output

        Returns:
            List of plan lines
        """
        lines = []
        for line in explain_output.strip().split("\n"):
            line = line.strip()
            # Skip empty lines and section headers
            if not line or self.SECTION_PATTERN.match(line):
                continue
            # Remove leading pipe if present
            if line.startswith("|"):
                line = line[1:].strip()
            if line:
                lines.append(line)
        return lines

    def _parse_lines(self, lines: list[str]) -> list[dict[str, Any]]:
        """
        Parse plan lines into operator dictionaries.

        Args:
            lines: Lines from plan section

        Returns:
            List of operator dictionaries with indent levels
        """
        parsed = []

        for line in lines:
            # Measure indentation
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            # Try to extract operator name
            op_match = self.OPERATOR_PATTERN.match(line)
            if op_match:
                operator = op_match.group("operator")
                details = op_match.group("details") or ""
            else:
                # Fallback: extract first word as operator
                parts = stripped.split(":", 1)
                operator = parts[0].strip()
                details = parts[1].strip() if len(parts) > 1 else ""

            # Skip empty operators
            if not operator:
                continue

            # Parse metrics if present
            metrics = {}
            metrics_match = self.METRICS_PATTERN.search(details)
            if metrics_match:
                metrics = self._parse_metrics(metrics_match.group(1))

            node: dict[str, Any] = {
                "indent": indent,
                "operator": operator,
                "details": details,
                "metrics": metrics,
            }

            # Extract operator-specific information from details
            self._extract_operator_info(node)

            parsed.append(node)

        return parsed

    def _parse_metrics(self, metrics_str: str) -> dict[str, Any]:
        """
        Parse metrics string from EXPLAIN ANALYZE.

        Args:
            metrics_str: Metrics string like "output_rows=5, elapsed_compute=2.375µs"

        Returns:
            Dictionary of parsed metrics
        """
        metrics = {}
        for part in metrics_str.split(","):
            part = part.strip()
            if "=" in part:
                key, value = part.split("=", 1)
                key = key.strip()
                value = value.strip()

                # Try to parse numeric values
                try:
                    if "." in value or "µ" in value or "ms" in value:
                        # Keep as string for timing values
                        metrics[key] = value
                    else:
                        metrics[key] = int(value)
                except ValueError:
                    metrics[key] = value

        return metrics

    def _extract_operator_info(self, node: dict[str, Any]) -> None:
        """
        Extract operator-specific information from details string.

        Args:
            node: Operator node dictionary (modified in place)
        """
        details = node.get("details", "")
        operator = node.get("operator", "").lower()

        if "scan" in operator or "datasource" in operator or "parquet" in operator:
            self._extract_scan_info(node, details)
        if "join" in operator:
            self._extract_join_info(node, operator, details)
        if "filter" in operator and details:
            node["filter_expression"] = details
        if "sort" in operator:
            self._extract_sort_info(node, details)
        if "projection" in operator:
            self._extract_projection_info(node, details)
        if "aggregate" in operator:
            self._extract_aggregate_info(node, details)
        if "limit" in operator:
            self._extract_limit_info(node, details)

    @staticmethod
    def _extract_scan_info(node: dict[str, Any], details: str) -> None:
        table_match = re.search(r"(?:^|:\s*)(\w+)(?:\s+projection|\s*$)", details)
        if table_match:
            node["table"] = table_match.group(1)

    @staticmethod
    def _classify_join_type(operator: str, details_lower: str) -> JoinType:
        for keyword, join_type in (
            ("left", JoinType.LEFT),
            ("right", JoinType.RIGHT),
            ("full", JoinType.FULL),
            ("cross", JoinType.CROSS),
        ):
            if keyword in details_lower or keyword in operator:
                return join_type
        if "semi" in details_lower:
            return JoinType.SEMI
        if "anti" in details_lower:
            return JoinType.ANTI
        return JoinType.INNER

    @classmethod
    def _extract_join_info(cls, node: dict[str, Any], operator: str, details: str) -> None:
        details_lower = details.lower()
        node["join_type"] = cls._classify_join_type(operator, details_lower)
        if "on=" in details_lower or "filter=" in details_lower:
            cond_match = re.search(r"(?:on|filter)=\[?([^\]]+)\]?", details, re.IGNORECASE)
            if cond_match:
                node["join_condition"] = cond_match.group(1).strip()

    @staticmethod
    def _extract_sort_info(node: dict[str, Any], details: str) -> None:
        sort_match = re.search(r"\[([^\]]+)\]", details)
        if sort_match:
            node["sort_keys"] = sort_match.group(1)

    @staticmethod
    def _extract_projection_info(node: dict[str, Any], details: str) -> None:
        expr_match = re.search(r"expr=\[([^\]]+)\]", details)
        if expr_match:
            node["projection_exprs"] = expr_match.group(1)

    @staticmethod
    def _extract_aggregate_info(node: dict[str, Any], details: str) -> None:
        gby_match = re.search(r"gby=\[([^\]]*)\]", details)
        if gby_match:
            node["group_by"] = gby_match.group(1)
        aggr_match = re.search(r"aggr=\[([^\]]*)\]", details)
        if aggr_match:
            node["aggregates"] = aggr_match.group(1)

    @staticmethod
    def _extract_limit_info(node: dict[str, Any], details: str) -> None:
        fetch_match = re.search(r"fetch=(\d+)", details)
        if fetch_match:
            node["limit_count"] = int(fetch_match.group(1))

    def _build_tree(self, parsed_nodes: list[dict[str, Any]]) -> LogicalOperator:
        """
        Build operator tree from parsed nodes based on indentation.

        Args:
            parsed_nodes: List of parsed operator dictionaries

        Returns:
            Root LogicalOperator
        """
        if not parsed_nodes:
            raise ValueError("No nodes to build tree from")

        # Stack to track parent operators at each indent level
        # Each entry is (indent_level, operator)
        stack: list[tuple[int, LogicalOperator]] = []

        root: LogicalOperator | None = None

        for node in parsed_nodes:
            logical_op = self._convert_to_logical_operator(node)

            # Pop stack until we find a parent with smaller indent
            while stack and stack[-1][0] >= node["indent"]:
                stack.pop()

            # If stack is empty, this is the root
            if not stack:
                root = logical_op
            else:
                # Add as child of current top of stack
                parent_indent, parent_op = stack[-1]
                parent_op.children.append(logical_op)

            # Push this operator onto stack
            stack.append((node["indent"], logical_op))

        if root is None:
            raise ValueError("Could not determine root operator")

        return root

    def _convert_to_logical_operator(self, node: dict[str, Any]) -> LogicalOperator:
        """
        Convert parsed node to LogicalOperator.

        Args:
            node: Parsed operator dictionary

        Returns:
            LogicalOperator
        """
        operator_str = node["operator"]
        logical_type = self._map_operator_type(operator_str)

        # Extract operator-specific info
        kwargs: dict[str, Any] = {}

        if logical_type == LogicalOperatorType.SCAN:
            if node.get("table"):
                kwargs["table_name"] = node["table"]

        elif logical_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = node.get("join_type", JoinType.INNER)
            if node.get("join_condition"):
                kwargs["join_conditions"] = [node["join_condition"]]

        elif logical_type == LogicalOperatorType.AGGREGATE:
            if node.get("group_by"):
                kwargs["group_by_keys"] = [k.strip() for k in node["group_by"].split(",")]

        elif logical_type == LogicalOperatorType.SORT:
            if node.get("sort_keys"):
                # Parse sort keys into structured format
                sort_keys = []
                for key in node["sort_keys"].split(","):
                    key = key.strip()
                    direction = "DESC" if "DESC" in key.upper() else "ASC"
                    expr = re.sub(r"\s*(ASC|DESC).*$", "", key, flags=re.IGNORECASE).strip()
                    sort_keys.append({"expr": expr, "direction": direction})
                kwargs["sort_keys"] = sort_keys

        elif logical_type == LogicalOperatorType.LIMIT:
            if node.get("limit_count") is not None:
                kwargs["limit_count"] = node["limit_count"]

        elif logical_type == LogicalOperatorType.FILTER:
            if node.get("filter_expression"):
                kwargs["filter_expressions"] = [node["filter_expression"]]

        elif logical_type == LogicalOperatorType.PROJECT:
            if node.get("projection_exprs"):
                kwargs["projection_expressions"] = [node["projection_exprs"]]

        # Build properties from metrics
        properties: dict[str, Any] = {}
        if node.get("metrics"):
            properties.update(node["metrics"])

        # Create physical operator for DataFusion-specific details
        physical_op = self._create_physical_operator(
            operator_str,
            properties=properties,
            platform_metadata={
                "details": node.get("details"),
            },
        )

        return self._create_logical_operator(
            operator_type=logical_type,
            children=[],  # Will be populated by _build_tree
            physical_operator=physical_op,
            properties=properties,
            **kwargs,
        )

    def _map_operator_type(self, operator_str: str) -> LogicalOperatorType:
        """
        Map DataFusion operator string to LogicalOperatorType.

        Args:
            operator_str: DataFusion operator string

        Returns:
            LogicalOperatorType
        """
        normalized = operator_str.lower().strip()

        # Check direct mappings first
        if normalized in self.OPERATOR_MAP:
            return self.OPERATOR_MAP[normalized]

        # Check for partial matches (e.g., "HashJoinExec" -> "hashjoinexec")
        for key, value in self.OPERATOR_MAP.items():
            if key in normalized:
                return value

        # Use base class harmonization as fallback
        return self._harmonize_operator_type(operator_str)
