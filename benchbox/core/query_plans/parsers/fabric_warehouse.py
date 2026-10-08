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

_CONNECTOR = "|--"
_OBJECT_RE = re.compile(r"OBJECT:\(([^)]+)\)", re.IGNORECASE)


class FabricWarehouseQueryPlanParser(QueryPlanParser):
    _OPERATOR_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("indexseek", LogicalOperatorType.SCAN),
        ("indexscan", LogicalOperatorType.SCAN),
        ("tablescan", LogicalOperatorType.SCAN),
        ("clusteredindexscan", LogicalOperatorType.SCAN),
        ("ridlookup", LogicalOperatorType.SCAN),
        ("keylookup", LogicalOperatorType.SCAN),
        ("columnstoreindexscan", LogicalOperatorType.SCAN),
        ("scan", LogicalOperatorType.SCAN),
        ("nestedloops", LogicalOperatorType.JOIN),
        ("mergejoin", LogicalOperatorType.JOIN),
        ("streamaggregate", LogicalOperatorType.AGGREGATE),
        ("aggregate", LogicalOperatorType.AGGREGATE),
        ("sort", LogicalOperatorType.SORT),
        ("top", LogicalOperatorType.LIMIT),
        ("filter", LogicalOperatorType.FILTER),
        ("computescalar", LogicalOperatorType.PROJECT),
        ("project", LogicalOperatorType.PROJECT),
        ("concatenation", LogicalOperatorType.UNION),
        ("merge", LogicalOperatorType.JOIN),
    )

    def __init__(self):
        super().__init__("fabric_warehouse")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty SHOWPLAN_TEXT output")

        parsed = self._parse_lines(explain_output)
        if not parsed:
            raise ValueError("No operators found in SHOWPLAN_TEXT output")

        root = self._build_tree(parsed)
        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            raw_explain_output=explain_output,
        )

    def _parse_lines(self, explain_output: str) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for raw in explain_output.splitlines():
            idx = raw.find(_CONNECTOR)
            if idx < 0:
                continue
            content = raw[idx + len(_CONNECTOR) :].strip()
            if not content:
                continue
            name = content.split("(", 1)[0].strip()
            args = ""
            if "(" in content:
                args = content[content.find("(") + 1 : content.rfind(")")] if ")" in content else ""
            parsed.append({"depth": idx, "operator": name, "args": args})
        return parsed

    def _build_tree(self, parsed: list[dict[str, Any]]) -> LogicalOperator:
        stack: list[tuple[int, LogicalOperator]] = []
        root: LogicalOperator | None = None

        for node in parsed:
            operator = self._convert(node)
            while stack and stack[-1][0] >= node["depth"]:
                stack.pop()
            if not stack:
                root = operator
            else:
                stack[-1][1].children.append(operator)
            stack.append((node["depth"], operator))

        if root is None:
            raise ValueError("Could not determine root operator")
        return root

    def _convert(self, node: dict[str, Any]) -> LogicalOperator:
        operator_str = node["operator"]
        args = node["args"]
        logical_type = self._map_operator_type(operator_str, args)

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN:
            table = self._extract_table(args)
            if table:
                kwargs["table_name"] = table
        elif logical_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = self._classify_join_type(args)

        physical_op = self._create_physical_operator(
            operator_str or "Unknown",
            properties={},
            platform_metadata={"arguments": args or None},
        )
        return self._create_logical_operator(
            operator_type=logical_type,
            children=[],
            physical_operator=physical_op,
            **kwargs,
        )

    @classmethod
    def _map_operator_type(cls, operator: str, args: str) -> LogicalOperatorType:
        normalized = operator.lower().replace(" ", "").replace("_", "")
        if "hashmatch" in normalized:
            first_arg = args.split(",", 1)[0].lower()
            if "join" in first_arg or "semi" in first_arg or "anti" in first_arg:
                return LogicalOperatorType.JOIN
            return LogicalOperatorType.AGGREGATE
        for keyword, logical_type in cls._OPERATOR_KEYWORDS:
            if keyword in normalized:
                return logical_type
        return LogicalOperatorType.OTHER

    @staticmethod
    def _extract_table(args: str) -> str | None:
        match = _OBJECT_RE.search(args)
        if not match:
            return None
        parts = re.findall(r"\[([^\]]+)\]", match.group(1))
        if not parts:
            return match.group(1).strip()
        if len(parts) >= 3:
            return ".".join(parts[1:3])
        return ".".join(parts)

    @staticmethod
    def _classify_join_type(args: str) -> JoinType:
        lowered = args.lower()
        if "semi" in lowered:
            return JoinType.SEMI
        if "anti" in lowered:
            return JoinType.ANTI
        if "left" in lowered:
            return JoinType.LEFT
        if "right" in lowered:
            return JoinType.RIGHT
        if "full" in lowered:
            return JoinType.FULL
        return JoinType.INNER
