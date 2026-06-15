"""Microsoft Fabric Warehouse query plan parser.

Decision-gate note (from the source TODO's w6):
    Azure Synapse Dedicated Pool returns its plan from ``EXPLAIN`` as a
    distributed ``<dsql_query>`` *XML* document, whereas the Fabric Warehouse
    adapter retrieves its plan with ``SET SHOWPLAN_TEXT ON`` — the classic
    SQL Server hierarchical *text* showplan. The two formats are structurally
    different, so ``AzureSynapseQueryPlanParser`` cannot be reused; Fabric needs
    this dedicated parser. (Live confirmation that Fabric emits this exact text
    is deferred — no Fabric credentials in CI; see the work-unit notes.)

``SET SHOWPLAN_TEXT`` produces a single ``StmtText`` column: the first row is the
submitted statement, and subsequent rows are the physical operator tree, where
nesting is shown by the indentation of the ``|--`` connector::

    SELECT l_orderkey, SUM(l_quantity) FROM lineitem ...
      |--Compute Scalar(DEFINE:([Expr1003]=...))
           |--Stream Aggregate(GROUP BY:([l_orderkey]) DEFINE:([Expr1003]=SUM(...)))
                |--Sort(ORDER BY:([l_orderkey] ASC))
                     |--Hash Match(Inner Join, HASH:([l_orderkey])=([o_orderkey]))
                          |--Clustered Index Scan(OBJECT:([db].[dbo].[lineitem]))
                          |--Clustered Index Scan(OBJECT:([db].[dbo].[orders]))

The column position of each ``|--`` marker gives the depth; operators at the same
depth under a common ancestor are siblings (a join has two child scans).
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


class FabricWarehouseQueryPlanParser(QueryPlanParser):
    """Parser for SQL Server ``SET SHOWPLAN_TEXT`` output used by Fabric Warehouse."""

    # Ordered (substring, type). The first match in the lower-cased operator name
    # wins, so "Hash Match (Aggregate)" resolves to AGGREGATE before JOIN, and a
    # fused "...Aggregate" before the bare "match" of a hash join.
    _OPERATOR_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("aggregate", LogicalOperatorType.AGGREGATE),
        ("stream aggregate", LogicalOperatorType.AGGREGATE),
        ("hash match", LogicalOperatorType.JOIN),
        ("nested loops", LogicalOperatorType.JOIN),
        ("merge join", LogicalOperatorType.JOIN),
        ("join", LogicalOperatorType.JOIN),
        ("scan", LogicalOperatorType.SCAN),
        ("seek", LogicalOperatorType.SCAN),
        ("sort", LogicalOperatorType.SORT),
        ("top", LogicalOperatorType.LIMIT),
        ("filter", LogicalOperatorType.FILTER),
        ("compute scalar", LogicalOperatorType.PROJECT),
        ("concatenation", LogicalOperatorType.UNION),
        ("compute", LogicalOperatorType.PROJECT),
    )

    _MARKER = "|--"
    _OPERATOR_RE = re.compile(r"^(?P<name>[^(]+?)(?:\((?P<args>.*)\))?\s*$")
    _OBJECT_RE = re.compile(r"OBJECT:\(([^)]+)\)", re.IGNORECASE)

    def __init__(self):
        super().__init__("fabric_warehouse")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty SHOWPLAN_TEXT output")

        parsed = self._parse_lines(explain_output)
        if not parsed:
            raise ValueError("No plan operators found in SHOWPLAN_TEXT output")

        root = self._build_tree(parsed)
        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            raw_explain_output=explain_output,
        )

    def _parse_lines(self, explain_output: str) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for raw_line in explain_output.splitlines():
            marker_idx = raw_line.find(self._MARKER)
            if marker_idx == -1:
                # Leading statement text (no connector) — skip.
                continue
            depth = marker_idx
            body = raw_line[marker_idx + len(self._MARKER) :].strip()
            if not body:
                continue
            match = self._OPERATOR_RE.match(body)
            if match:
                name = match.group("name").strip()
                args = (match.group("args") or "").strip()
            else:
                name, args = body, ""
            nodes.append({"depth": depth, "name": name, "args": args})
        return nodes

    def _build_tree(self, parsed: list[dict[str, Any]]) -> LogicalOperator:
        stack: list[tuple[int, LogicalOperator]] = []
        root: LogicalOperator | None = None

        for node in parsed:
            logical_op = self._convert_node(node)
            while stack and stack[-1][0] >= node["depth"]:
                stack.pop()
            if not stack:
                if root is None:
                    root = logical_op
                # A second depth-0 operator would be a separate statement; nest it
                # under the existing root to keep a single DAG.
                elif logical_op is not root:
                    root.children.append(logical_op)
            else:
                stack[-1][1].children.append(logical_op)
            stack.append((node["depth"], logical_op))

        if root is None:
            raise ValueError("Could not determine root operator")
        return root

    def _convert_node(self, node: dict[str, Any]) -> LogicalOperator:
        name = node["name"]
        args = node["args"]
        logical_type = self._map_operator_type(name, args)

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN:
            table = self._extract_object(args)
            if table:
                kwargs["table_name"] = table
        elif logical_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = self._classify_join_type(args)
            condition = self._extract_join_condition(args)
            if condition:
                kwargs["join_conditions"] = [condition]
        elif logical_type == LogicalOperatorType.FILTER and args:
            kwargs["filter_expressions"] = [args]

        physical_op = self._create_physical_operator(
            name or "Operator",
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
    def _map_operator_type(cls, name: str, args: str) -> LogicalOperatorType:
        haystack = f"{name} {args}".lower()
        for keyword, logical_type in cls._OPERATOR_KEYWORDS:
            if keyword in haystack:
                return logical_type
        return LogicalOperatorType.OTHER

    @classmethod
    def _extract_object(cls, args: str) -> str | None:
        match = cls._OBJECT_RE.search(args)
        if not match:
            return None
        # OBJECT:([db].[schema].[table].[index]) -> table (or [table])
        parts = [p.strip().strip("[]") for p in match.group(1).split(".") if p.strip()]
        if not parts:
            return None
        # Drop a trailing index/alias segment when 4+ parts are present.
        table_parts = parts[:3] if len(parts) >= 4 else parts
        return ".".join(table_parts) if len(table_parts) > 1 else table_parts[-1]

    @staticmethod
    def _classify_join_type(args: str) -> JoinType:
        lowered = args.lower()
        if "left semi" in lowered or "semi join" in lowered:
            return JoinType.SEMI
        if "left anti" in lowered or "anti" in lowered:
            return JoinType.ANTI
        if "left outer" in lowered or "left join" in lowered:
            return JoinType.LEFT
        if "right outer" in lowered or "right join" in lowered:
            return JoinType.RIGHT
        if "full outer" in lowered:
            return JoinType.FULL
        return JoinType.INNER

    @staticmethod
    def _extract_join_condition(args: str) -> str | None:
        match = re.search(r"(?:HASH|MERGE|WHERE):\(([^)]+)\)\s*=\s*\(([^)]+)\)", args, re.IGNORECASE)
        if match:
            return f"{match.group(1).strip()} = {match.group(2).strip()}"
        match = re.search(r"(?:HASH|MERGE|WHERE):\(([^)]+)\)", args, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None
