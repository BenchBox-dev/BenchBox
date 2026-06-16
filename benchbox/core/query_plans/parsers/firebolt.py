"""Firebolt query plan parser.

Parses Firebolt's ``EXPLAIN`` plan, which is returned as an indented operator
tree (one operator per line). Nesting is encoded by leading whitespace and/or
tree connectors (``\\_``, ``|-``, ``+-``); each operator line optionally carries
a ``[n]`` index prefix and a trailing ``[detail]`` / ``(detail)`` description::

    [0] Projection [revenue]
     \\_[1] Sort [revenue DESC]
        \\_[2] Aggregate [groupBy: l_orderkey] [aggs: sum(revenue)]
           \\_[3] Join [type=inner] [condition: o_orderkey = l_orderkey]
              \\_[4] TableScan [table: orders]
              \\_[5] TableScan [table: lineitem]

Depth is the column at which the operator token starts (after stripping leading
whitespace, connector characters, and the optional index prefix); a stack keyed
by that column reconstructs the parent/child tree.
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

# Leading whitespace + tree-connector characters that encode nesting depth.
_CONNECTOR_CHARS = " \t\\_|+-"
# Optional "[12] " operator index prefix.
_INDEX_PREFIX_RE = re.compile(r"^\[\d+\]\s*")
# Bracketed or parenthesized detail group, e.g. "[table: orders]" or "(inner)".
# Square brackets and parens are matched as separate alternatives (never crossed)
# so a detail whose value contains nested parens — "[aggs: sum(x)]" — is captured
# whole rather than truncated at the first inner ")".
_DETAIL_RE = re.compile(r"\[([^\]]*)\]|\(([^)]*)\)")
# A "key: value" / "key = value" detail; compiled once and reused per call.
_KEYED_DETAIL_RE = re.compile(r"\s*(\w+)\s*[:=]\s*(.+)", re.IGNORECASE)


class FireboltQueryPlanParser(QueryPlanParser):
    """Parser for Firebolt ``EXPLAIN`` indented operator-tree text."""

    # Ordered (substring, type) pairs; first match in the lower-cased operator
    # name wins, so specific names precede the generic ones they contain.
    _OPERATOR_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("storedtable", LogicalOperatorType.SCAN),
        ("tablescan", LogicalOperatorType.SCAN),
        ("scan", LogicalOperatorType.SCAN),
        ("join", LogicalOperatorType.JOIN),
        ("aggregate", LogicalOperatorType.AGGREGATE),
        ("aggregation", LogicalOperatorType.AGGREGATE),
        ("sort", LogicalOperatorType.SORT),
        ("limit", LogicalOperatorType.LIMIT),
        ("projection", LogicalOperatorType.PROJECT),
        ("project", LogicalOperatorType.PROJECT),
        ("predicate", LogicalOperatorType.FILTER),
        ("filter", LogicalOperatorType.FILTER),
        ("unionall", LogicalOperatorType.UNION),
        ("union", LogicalOperatorType.UNION),
        ("window", LogicalOperatorType.WINDOW),
    )

    def __init__(self):
        super().__init__("firebolt")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")

        parsed = self._parse_lines(explain_output)
        if not parsed:
            raise ValueError("No operators found in EXPLAIN output")

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
            if not raw.strip():
                continue
            depth = 0
            while depth < len(raw) and raw[depth] in _CONNECTOR_CHARS:
                depth += 1
            content = _INDEX_PREFIX_RE.sub("", raw[depth:].strip())
            if not content:
                continue
            operator = content.split(maxsplit=1)[0].strip("[]():")
            if not operator:
                continue
            details = [
                (match.group(1) if match.group(1) is not None else match.group(2)).strip()
                for match in _DETAIL_RE.finditer(content)
            ]
            parsed.append({"depth": depth, "operator": operator, "details": details, "raw": content})
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
        details = node["details"]
        logical_type = self._map_operator_type(operator_str)

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN:
            table = self._extract_detail(details, ("table",))
            if table:
                kwargs["table_name"] = table
        elif logical_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = self._classify_join_type(details)
            condition = self._extract_detail(details, ("condition", "on", "keys"))
            if condition:
                kwargs["join_conditions"] = [condition]

        physical_op = self._create_physical_operator(
            operator_str,
            properties={},
            platform_metadata={"details": "; ".join(details) or None},
        )
        return self._create_logical_operator(
            operator_type=logical_type,
            children=[],
            physical_operator=physical_op,
            **kwargs,
        )

    @classmethod
    def _map_operator_type(cls, operator: str) -> LogicalOperatorType:
        normalized = operator.lower().replace(" ", "").replace("_", "")
        for keyword, logical_type in cls._OPERATOR_KEYWORDS:
            if keyword in normalized:
                return logical_type
        return LogicalOperatorType.OTHER

    @staticmethod
    def _extract_detail(details: list[str], keys: tuple[str, ...]) -> str | None:
        wanted = {key.lower() for key in keys}
        for detail in details:
            match = _KEYED_DETAIL_RE.match(detail)
            if match and match.group(1).lower() in wanted:
                return match.group(2).strip()
        return None

    @staticmethod
    def _classify_join_type(details: list[str]) -> JoinType:
        haystack = " ".join(details).lower()
        if "semi" in haystack:
            return JoinType.SEMI
        if "anti" in haystack:
            return JoinType.ANTI
        for keyword, join_type in (
            ("left", JoinType.LEFT),
            ("right", JoinType.RIGHT),
            ("full", JoinType.FULL),
            ("cross", JoinType.CROSS),
        ):
            if keyword in haystack:
                return join_type
        return JoinType.INNER
