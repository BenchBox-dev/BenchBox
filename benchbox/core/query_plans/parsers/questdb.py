"""QuestDB query plan parser.

Parses QuestDB ``EXPLAIN <query>`` output into the harmonized ``QueryPlanDAG``.
QuestDB returns the plan as a single ``QUERY PLAN`` text column (one row per
line); ``QuestDBAdapter.get_query_plan()`` joins those rows with newlines. The
result is an indentation-based tree, e.g.::

    Sort light lo: 10
      keys: [symbol]
        GroupBy vectorized: true workers: 1
          keys: [symbol]
          values: [sum(price)]
            Async JIT Filter workers: 1
              filter: 100<price
                PageFrame
                    Row forward scan
                    Frame forward scan on: trades

Two kinds of line appear: operator nodes (start with an upper-case letter, e.g.
``Sort``, ``GroupBy``, ``Async JIT Filter``, ``PageFrame``, ``Frame forward scan
on: ...``) and property lines (start lower-case, e.g. ``keys:``, ``values:``,
``filter:``). Property lines attach to the nearest enclosing operator; only
operator lines nest the tree. Because QuestDB's indentation step is not uniform
(properties and child operators can share an indent), nesting is derived from
relative indentation rather than a fixed unit.
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


class QuestDBQueryPlanParser(QueryPlanParser):
    """Parser for QuestDB ``EXPLAIN`` indented text output."""

    # Ordered (substring, type) pairs; the first substring found in the
    # lower-cased, space-stripped operator line wins (QuestDB appends inline
    # parameters to the operator name, e.g. "Sort light lo: 10"). More specific
    # names precede the generic ones they contain.
    _OPERATOR_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("frameforwardscan", LogicalOperatorType.SCAN),
        ("framebackwardscan", LogicalOperatorType.SCAN),
        ("intervalforwardscan", LogicalOperatorType.SCAN),
        ("intervalbackwardscan", LogicalOperatorType.SCAN),
        ("rowforwardscan", LogicalOperatorType.SCAN),
        ("rowbackwardscan", LogicalOperatorType.SCAN),
        ("dataframe", LogicalOperatorType.SCAN),
        ("pageframe", LogicalOperatorType.SCAN),
        ("indexscan", LogicalOperatorType.SCAN),
        ("scan", LogicalOperatorType.SCAN),
        ("hashjoin", LogicalOperatorType.JOIN),
        ("asofjoin", LogicalOperatorType.JOIN),
        ("splicejoin", LogicalOperatorType.JOIN),
        ("nestedloopjoin", LogicalOperatorType.JOIN),
        ("crossjoin", LogicalOperatorType.JOIN),
        ("join", LogicalOperatorType.JOIN),
        ("groupby", LogicalOperatorType.AGGREGATE),
        ("sampleby", LogicalOperatorType.AGGREGATE),
        ("count", LogicalOperatorType.AGGREGATE),
        ("filter", LogicalOperatorType.FILTER),
        ("topk", LogicalOperatorType.SORT),
        ("sort", LogicalOperatorType.SORT),
        ("orderby", LogicalOperatorType.SORT),
        ("limit", LogicalOperatorType.LIMIT),
        ("union", LogicalOperatorType.UNION),
        ("except", LogicalOperatorType.EXCEPT),
        ("intersect", LogicalOperatorType.INTERSECT),
        ("window", LogicalOperatorType.WINDOW),
        ("distinct", LogicalOperatorType.OTHER),
        ("virtualrecord", LogicalOperatorType.PROJECT),
        ("selectedrecord", LogicalOperatorType.PROJECT),
        ("select", LogicalOperatorType.PROJECT),
    )

    def __init__(self):
        super().__init__("questdb")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")
        if explain_output.lstrip().startswith(("Failed to get query plan", "Could not get query plan")):
            raise ValueError("EXPLAIN returned an error message, not a plan")

        parsed_lines = self._parse_lines(explain_output)
        if not parsed_lines:
            raise ValueError("No operators found in EXPLAIN output")

        raw_root = self._build_raw_tree(parsed_lines)
        if raw_root is None:
            raise ValueError("Could not determine root operator")

        root = self._convert_raw(raw_root)
        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            raw_explain_output=explain_output,
        )

    def _parse_lines(self, explain_output: str) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for raw_line in explain_output.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            # Skip a leading "QUERY PLAN" column header if present.
            if stripped == "QUERY PLAN":
                continue
            indent = len(raw_line) - len(raw_line.lstrip())
            # Operator lines start with an upper-case letter; property lines
            # (keys:/values:/filter:/condition:) start lower-case.
            is_operator = stripped[0].isupper()
            parsed.append({"indent": indent, "content": stripped, "is_operator": is_operator})
        return parsed

    def _build_raw_tree(self, parsed_lines: list[dict[str, Any]]) -> dict[str, Any] | None:
        root: dict[str, Any] | None = None
        # Stack of operator nodes on the current root-to-leaf path, keyed by indent.
        stack: list[dict[str, Any]] = []

        for line in parsed_lines:
            indent = line["indent"]
            if line["is_operator"]:
                node = {"content": line["content"], "indent": indent, "details": [], "children": []}
                while stack and stack[-1]["indent"] >= indent:
                    stack.pop()
                if not stack:
                    if root is None:
                        root = node
                    else:
                        root["children"].append(node)
                else:
                    stack[-1]["children"].append(node)
                stack.append(node)
            else:
                parent = next((op for op in reversed(stack) if op["indent"] < indent), None)
                if parent is None and stack:
                    parent = stack[-1]
                if parent is not None:
                    parent["details"].append(line["content"])
        return root

    def _convert_raw(self, raw: dict[str, Any]) -> LogicalOperator:
        content = raw["content"]
        logical_type = self._map_operator_type(content)
        children = [self._convert_raw(child) for child in raw["children"]]

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN:
            table = self._extract_table(content)
            if table:
                kwargs["table_name"] = table

        physical_op = self._create_physical_operator(
            content.split()[0] if content.split() else content,
            properties={},
            platform_metadata={"details": "; ".join(raw["details"]) or None},
        )
        return self._create_logical_operator(
            operator_type=logical_type,
            children=children,
            physical_operator=physical_op,
            **kwargs,
        )

    @classmethod
    def _map_operator_type(cls, content: str) -> LogicalOperatorType:
        compact = content.lower().replace(" ", "").replace("_", "")
        for keyword, logical_type in cls._OPERATOR_KEYWORDS:
            if keyword in compact:
                return logical_type
        return LogicalOperatorType.OTHER

    @staticmethod
    def _extract_table(content: str) -> str | None:
        """Extract the table from a frame-scan line, e.g. 'Frame forward scan on: trades'."""
        match = re.search(r"\bon:\s*([A-Za-z_][\w.]*)", content)
        return match.group(1) if match else None


__all__ = ["QuestDBQueryPlanParser"]
