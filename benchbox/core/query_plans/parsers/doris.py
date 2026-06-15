"""Apache Doris query plan parser.

Parses Doris ``EXPLAIN SHAPE PLAN <query>`` output into the harmonized
``QueryPlanDAG``. The Nereids planner's SHAPE PLAN is a clean indentation tree
where each level is prefixed by a run of ``-`` characters (two dashes per level)
and every node is a ``Physical*`` operator, e.g.::

    PhysicalResultSink
    --PhysicalQuickSort[MERGE_SORT]
    ----PhysicalDistribute[DistributionSpecGather]
    ------PhysicalHashAggregate[GLOBAL]
    --------PhysicalProject
    ----------PhysicalHashJoin[INNER_JOIN]
    ------------PhysicalProject
    --------------PhysicalOlapScan[lineitem]
    ------------PhysicalDistribute[DistributionSpecReplicated]
    --------------PhysicalOlapScan[orders]

``EXPLAIN SHAPE PLAN`` is used in preference to the default fragment-oriented
``EXPLAIN`` because it is structurally stable and trivially nestable; the
adapter selects it via ``DorisAdapter._explain_query_prefix()``. Operator depth
is the number of leading dash pairs; the operator name is the token before any
``[...]`` qualifier (which carries the join type or scanned table name).
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


class DorisQueryPlanParser(QueryPlanParser):
    """Parser for Apache Doris ``EXPLAIN SHAPE PLAN`` text output."""

    # Ordered (substring, type) pairs; the first substring found in the
    # lower-cased operator name wins, so more specific names precede the generic
    # ones they contain.
    _OPERATOR_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("physicalolapscan", LogicalOperatorType.SCAN),
        ("physicalfilescan", LogicalOperatorType.SCAN),
        ("physicalschemascan", LogicalOperatorType.SCAN),
        ("physicaljdbcscan", LogicalOperatorType.SCAN),
        ("physicalesscan", LogicalOperatorType.SCAN),
        ("physicalhivescan", LogicalOperatorType.SCAN),
        ("scan", LogicalOperatorType.SCAN),
        ("physicalhashjoin", LogicalOperatorType.JOIN),
        ("physicalnestedloopjoin", LogicalOperatorType.JOIN),
        ("join", LogicalOperatorType.JOIN),
        ("physicalhashaggregate", LogicalOperatorType.AGGREGATE),
        ("aggregate", LogicalOperatorType.AGGREGATE),
        ("physicalquicksort", LogicalOperatorType.SORT),
        ("physicaltopn", LogicalOperatorType.SORT),
        ("sort", LogicalOperatorType.SORT),
        ("physicallimit", LogicalOperatorType.LIMIT),
        ("limit", LogicalOperatorType.LIMIT),
        ("physicalproject", LogicalOperatorType.PROJECT),
        ("project", LogicalOperatorType.PROJECT),
        ("physicalwindow", LogicalOperatorType.WINDOW),
        ("window", LogicalOperatorType.WINDOW),
        ("physicalunion", LogicalOperatorType.UNION),
        ("union", LogicalOperatorType.UNION),
        ("physicalexcept", LogicalOperatorType.EXCEPT),
        ("physicalintersect", LogicalOperatorType.INTERSECT),
        ("physicalfilter", LogicalOperatorType.FILTER),
        ("filter", LogicalOperatorType.FILTER),
        ("physicalcte", LogicalOperatorType.CTE),
        # Distribute / exchange / sink wrappers have no dedicated logical type.
        ("physicaldistribute", LogicalOperatorType.OTHER),
        ("physicalresultsink", LogicalOperatorType.OTHER),
        ("sink", LogicalOperatorType.OTHER),
    )

    # Leading dash run encodes depth (two dashes per level); the rest is the node.
    _LINE_RE = re.compile(r"^(?P<dashes>-*)(?P<content>.*)$")

    def __init__(self):
        super().__init__("doris")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")
        if explain_output.lstrip().startswith(("Failed to get query plan", "Could not get query plan")):
            raise ValueError("EXPLAIN returned an error message, not a plan")

        parsed_nodes = self._parse_lines(explain_output)
        if not parsed_nodes:
            raise ValueError("No operators found in EXPLAIN SHAPE PLAN output")

        root = self._build_tree(parsed_nodes)
        if root is None:
            raise ValueError("Could not determine root operator")
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
            match = self._LINE_RE.match(stripped)
            content = match.group("content").strip()
            # Only treat Physical* (or any CamelCase operator) lines as nodes;
            # skip stray annotation lines that SHAPE PLAN does not emit but a
            # future/verbose mode might.
            if not content or not content[0].isalpha():
                continue
            depth = len(match.group("dashes")) // 2
            parsed.append({"depth": depth, "content": content})
        return parsed

    def _build_tree(self, parsed_nodes: list[dict[str, Any]]) -> LogicalOperator | None:
        stack: list[tuple[int, LogicalOperator]] = []
        root: LogicalOperator | None = None

        for node in parsed_nodes:
            logical_op = self._convert_to_logical_operator(node["content"])
            while stack and stack[-1][0] >= node["depth"]:
                stack.pop()
            if not stack:
                if root is None:
                    root = logical_op
                else:
                    root.children.append(logical_op)
            else:
                stack[-1][1].children.append(logical_op)
            stack.append((node["depth"], logical_op))

        return root

    def _convert_to_logical_operator(self, content: str) -> LogicalOperator:
        name_match = re.match(r"([A-Za-z][\w]*)", content)
        name = name_match.group(1) if name_match else content
        qualifier = self._extract_qualifier(content)
        logical_type = self._map_operator_type(name)

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN and qualifier:
            kwargs["table_name"] = qualifier
        elif logical_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = self._classify_join_type(qualifier)

        physical_op = self._create_physical_operator(
            name,
            properties={},
            platform_metadata={"details": qualifier or None},
        )
        return self._create_logical_operator(
            operator_type=logical_type,
            children=[],
            physical_operator=physical_op,
            **kwargs,
        )

    @staticmethod
    def _extract_qualifier(content: str) -> str | None:
        """Return the text inside the first ``[...]`` qualifier, if any."""
        match = re.search(r"\[([^\]]*)\]", content)
        return match.group(1).strip() if match else None

    @classmethod
    def _map_operator_type(cls, name: str) -> LogicalOperatorType:
        normalized = name.lower().replace(" ", "").replace("_", "")
        for keyword, logical_type in cls._OPERATOR_KEYWORDS:
            if keyword in normalized:
                return logical_type
        return LogicalOperatorType.OTHER

    def _classify_join_type(self, qualifier: str | None) -> JoinType:
        if not qualifier:
            return JoinType.INNER
        return self._harmonize_join_type(qualifier)


__all__ = ["DorisQueryPlanParser"]
