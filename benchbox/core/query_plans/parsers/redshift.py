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


class RedshiftQueryPlanParser(QueryPlanParser):
    OPERATOR_MAP = {
        "seq scan": LogicalOperatorType.SCAN,
        "index scan": LogicalOperatorType.SCAN,
        "bitmap heap scan": LogicalOperatorType.SCAN,
        "bitmap index scan": LogicalOperatorType.SCAN,
        "nested loop": LogicalOperatorType.JOIN,
        "hash join": LogicalOperatorType.JOIN,
        "merge join": LogicalOperatorType.JOIN,
        "aggregate": LogicalOperatorType.AGGREGATE,
        "hashaggregate": LogicalOperatorType.AGGREGATE,
        "groupaggregate": LogicalOperatorType.AGGREGATE,
        "sort": LogicalOperatorType.SORT,
        "merge": LogicalOperatorType.SORT,
        "limit": LogicalOperatorType.LIMIT,
        "result": LogicalOperatorType.PROJECT,
        "subquery scan": LogicalOperatorType.SUBQUERY,
        "append": LogicalOperatorType.UNION,
        "unique": LogicalOperatorType.OTHER,
        "window": LogicalOperatorType.WINDOW,
        "windowagg": LogicalOperatorType.WINDOW,
        "network": LogicalOperatorType.OTHER,
        "ds_dist_all_none": LogicalOperatorType.OTHER,
        "ds_dist_inner": LogicalOperatorType.OTHER,
        "ds_dist_all_inner": LogicalOperatorType.OTHER,
        "ds_dist_both": LogicalOperatorType.OTHER,
        "ds_bcast_inner": LogicalOperatorType.OTHER,
        "hash": LogicalOperatorType.OTHER,
        "materialize": LogicalOperatorType.OTHER,
    }

    OPERATOR_PATTERN = re.compile(
        r"^(?P<indent>\s*)"
        r"(?:->)?\s*"
        r"(?:XN\s+)?"
        r"(?P<operator>[A-Za-z][A-Za-z0-9 ]+?)(?=\s+on\s+\w|\s+DS_|\s*\(|\s*$)"
        r"(?:\s+(?P<dist>DS_[A-Z_]+))?"
        r"(?:\s+on\s+(?P<table>[\w.]+))?"
        r"(?:\s+(?P<alias>\w+))?"
        r"\s*"
        r"(?:\(cost=(?P<startup_cost>[\d.]+)\.\.(?P<total_cost>[\d.]+)\s+"
        r"rows=(?P<rows>\d+)\s+width=(?P<width>\d+)\))?"
        r".*$",
        re.IGNORECASE,
    )

    FILTER_PATTERN = re.compile(r"^\s*(?:Filter|Join Filter|Hash Cond|Merge Cond|Index Cond):\s*(.+)$")

    def __init__(self):
        super().__init__("redshift")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")

        lines = explain_output.strip().split("\n")

        parsed_nodes = self._parse_lines(lines)

        if not parsed_nodes:
            raise ValueError("No operators found in EXPLAIN output")

        root = self._build_tree(parsed_nodes)

        estimated_cost = None
        estimated_rows = None
        if parsed_nodes:
            estimated_cost = parsed_nodes[0].get("total_cost")
            estimated_rows = parsed_nodes[0].get("rows")

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            estimated_cost=estimated_cost,
            estimated_rows=estimated_rows,
            raw_explain_output=explain_output,
        )

    def _parse_lines(self, lines: list[str]) -> list[dict[str, Any]]:
        parsed = []
        current_node: dict[str, Any] | None = None

        for line in lines:
            if not line.strip():
                continue

            filter_match = self.FILTER_PATTERN.match(line)
            if filter_match and current_node:
                if "filters" not in current_node:
                    current_node["filters"] = []
                current_node["filters"].append(filter_match.group(1))
                continue

            op_match = self.OPERATOR_PATTERN.match(line)
            if op_match:
                indent = len(op_match.group("indent") or "")
                operator = op_match.group("operator").strip()

                if not operator or operator == "->":
                    continue

                node: dict[str, Any] = {
                    "indent": indent,
                    "operator": operator,
                    "table": op_match.group("table"),
                    "alias": op_match.group("alias"),
                }

                if op_match.group("startup_cost"):
                    node["startup_cost"] = float(op_match.group("startup_cost"))
                if op_match.group("total_cost"):
                    node["total_cost"] = float(op_match.group("total_cost"))
                if op_match.group("rows"):
                    node["rows"] = int(op_match.group("rows"))
                if op_match.group("width"):
                    node["width"] = int(op_match.group("width"))

                parsed.append(node)
                current_node = node

        return parsed

    def _build_tree(self, parsed_nodes: list[dict[str, Any]]) -> LogicalOperator:
        if not parsed_nodes:
            raise ValueError("No nodes to build tree from")

        stack: list[tuple[int, LogicalOperator]] = []

        root: LogicalOperator | None = None

        for node in parsed_nodes:
            logical_op = self._convert_to_logical_operator(node)

            while stack and stack[-1][0] >= node["indent"]:
                stack.pop()

            if not stack:
                root = logical_op
            else:
                parent_indent, parent_op = stack[-1]
                parent_op.children.append(logical_op)

            stack.append((node["indent"], logical_op))

        if root is None:
            raise ValueError("Could not determine root operator")

        return root

    def _convert_to_logical_operator(self, node: dict[str, Any]) -> LogicalOperator:
        operator_str = node["operator"]
        logical_type = self._map_operator_type(operator_str)

        kwargs: dict[str, Any] = {}

        if logical_type == LogicalOperatorType.SCAN:
            if node.get("table"):
                kwargs["table_name"] = node["table"]

        elif logical_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = self._extract_join_type(operator_str)
            if node.get("filters"):
                kwargs["join_conditions"] = node["filters"]

        elif logical_type == LogicalOperatorType.AGGREGATE or logical_type == LogicalOperatorType.SORT:
            pass

        if node.get("filters") and logical_type != LogicalOperatorType.JOIN:
            kwargs["filter_expressions"] = node["filters"]

        properties: dict[str, Any] = {}
        for key in ["startup_cost", "total_cost", "rows", "width"]:
            if node.get(key) is not None:
                properties[key] = node[key]

        physical_op = self._create_physical_operator(
            operator_str,
            properties=properties,
            platform_metadata={
                "table": node.get("table"),
                "alias": node.get("alias"),
            },
        )

        return self._create_logical_operator(
            operator_type=logical_type,
            children=[],
            physical_operator=physical_op,
            properties=properties,
            **kwargs,
        )

    def _map_operator_type(self, operator_str: str) -> LogicalOperatorType:
        normalized = operator_str.lower().strip()

        if normalized.startswith("xn "):
            normalized = normalized[3:]

        for key, value in self.OPERATOR_MAP.items():
            if key in normalized:
                return value

        return self._harmonize_operator_type(operator_str)

    def _extract_join_type(self, operator_str: str) -> JoinType:
        normalized = operator_str.lower()

        if "left" in normalized:
            return JoinType.LEFT
        elif "right" in normalized:
            return JoinType.RIGHT
        elif "full" in normalized:
            return JoinType.FULL
        elif "cross" in normalized:
            return JoinType.CROSS
        elif "semi" in normalized:
            return JoinType.SEMI
        elif "anti" in normalized:
            return JoinType.ANTI
        else:
            return JoinType.INNER
