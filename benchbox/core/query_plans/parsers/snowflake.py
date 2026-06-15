"""Snowflake query plan parser.

Parses the JSON document emitted by ``EXPLAIN USING JSON <query>`` into the
harmonized :class:`QueryPlanDAG` structure.

Snowflake's ``EXPLAIN USING JSON`` returns a single JSON value of the form::

    {
      "GlobalStats": {
        "partitionsTotal": 5,
        "partitionsAssigned": 5,
        "bytesAssigned": 123456
      },
      "Operations": [
        [
          {"id": 0, "operation": "Result", "expressions": ["L_ORDERKEY", "..."]},
          {"id": 1, "parentOperators": [0], "operation": "Aggregate", ...},
          {"id": 2, "parentOperators": [1], "operation": "InnerJoin", ...},
          {"id": 3, "parentOperators": [2], "operation": "TableScan",
           "objects": ["TPCH.LINEITEM"], ...},
          {"id": 4, "parentOperators": [2], "operation": "TableScan",
           "objects": ["TPCH.ORDERS"], ...}
        ]
      ]
    }

``Operations`` is a list of *steps* (one list of operator nodes per statement /
sub-plan). Each operator node carries an integer ``id``, an ``operation`` name,
an optional ``parentOperators`` list (the ids this node feeds into), an optional
``objects`` list (table names for scans), and an optional ``expressions`` list of
detail strings. The root operator of a step is the node with no
``parentOperators``; a node's children are the operators that name it as a
parent.

See the field reference under Snowflake's ``EXPLAIN`` documentation for the
``GlobalStats`` / ``Operations`` payload shape.
"""

from __future__ import annotations

import json
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


class SnowflakeQueryPlanParser(QueryPlanParser):
    """Parser for Snowflake ``EXPLAIN USING JSON`` output."""

    # Ordered (substring, type) pairs. The first substring found in the
    # lower-cased operation name wins, so dominant operators are listed before
    # the generic names they may contain.
    _OPERATOR_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("tablescan", LogicalOperatorType.SCAN),
        ("joinfilter", LogicalOperatorType.SCAN),
        ("scan", LogicalOperatorType.SCAN),
        ("join", LogicalOperatorType.JOIN),
        ("aggregate", LogicalOperatorType.AGGREGATE),
        ("groupby", LogicalOperatorType.AGGREGATE),
        ("sort", LogicalOperatorType.SORT),
        ("orderby", LogicalOperatorType.SORT),
        ("limit", LogicalOperatorType.LIMIT),
        ("filter", LogicalOperatorType.FILTER),
        ("withreference", LogicalOperatorType.PROJECT),
        ("withclause", LogicalOperatorType.CTE),
        ("generator", LogicalOperatorType.PROJECT),
        ("projection", LogicalOperatorType.PROJECT),
        ("result", LogicalOperatorType.PROJECT),
        ("unionall", LogicalOperatorType.UNION),
        ("union", LogicalOperatorType.UNION),
        ("intersect", LogicalOperatorType.INTERSECT),
        ("except", LogicalOperatorType.EXCEPT),
        ("minus", LogicalOperatorType.EXCEPT),
        ("window", LogicalOperatorType.WINDOW),
    )

    def __init__(self):
        super().__init__("snowflake")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")

        try:
            payload = json.loads(explain_output)
        except json.JSONDecodeError as exc:
            raise ValueError(f"EXPLAIN output is not valid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Snowflake EXPLAIN JSON must be an object")

        operations = payload.get("Operations")
        if not isinstance(operations, list) or not operations:
            raise ValueError("No 'Operations' array found in Snowflake EXPLAIN JSON")

        # Operations is a list of steps; use the first step that contains nodes.
        nodes: list[dict[str, Any]] = []
        for step in operations:
            if isinstance(step, list) and step:
                nodes = [n for n in step if isinstance(n, dict)]
                if nodes:
                    break
        if not nodes:
            raise ValueError("No operator nodes found in Snowflake EXPLAIN JSON")

        root = self._build_tree(nodes)

        global_stats = payload.get("GlobalStats")
        estimated_rows = None
        if isinstance(global_stats, dict):
            estimated_rows = self._coerce_int(global_stats.get("partitionsAssigned"))

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            estimated_rows=estimated_rows,
            raw_explain_output=explain_output,
        )

    def _build_tree(self, nodes: list[dict[str, Any]]) -> LogicalOperator:
        """Build the operator tree from the flat node list using parentOperators."""
        by_id: dict[Any, dict[str, Any]] = {}
        for node in nodes:
            node_id = node.get("id")
            if node_id is not None:
                by_id[node_id] = node

        # children_of[parent_id] = [child node ids feeding that parent]
        children_of: dict[Any, list[Any]] = {nid: [] for nid in by_id}
        roots: list[Any] = []
        for node in nodes:
            node_id = node.get("id")
            parents = node.get("parentOperators") or []
            if not isinstance(parents, list):
                parents = [parents]
            parents = [p for p in parents if p in by_id]
            if not parents:
                roots.append(node_id)
            for parent in parents:
                children_of.setdefault(parent, []).append(node_id)

        if not roots:
            # Degenerate / cyclic input: fall back to the lowest id as root.
            roots = [min(by_id)] if by_id else []

        # Guard against cycles with a visited set on each path.
        def build(node_id: Any, visited: frozenset[Any]) -> LogicalOperator:
            node = by_id[node_id]
            children = [
                build(child_id, visited | {node_id})
                for child_id in children_of.get(node_id, [])
                if child_id in by_id and child_id not in visited
            ]
            return self._convert_node(node, children)

        root_id = roots[0]
        return build(root_id, frozenset())

    def _convert_node(self, node: dict[str, Any], children: list[LogicalOperator]) -> LogicalOperator:
        operation = str(node.get("operation", "")).strip()
        logical_type = self._map_operator_type(operation)
        expressions = self._string_list(node.get("expressions"))
        objects = self._string_list(node.get("objects"))

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN:
            table = objects[0] if objects else self._extract_table(expressions)
            if table:
                kwargs["table_name"] = table
        elif logical_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = self._classify_join_type(operation, expressions)
            condition = self._extract_join_condition(expressions)
            if condition:
                kwargs["join_conditions"] = [condition]
        elif logical_type == LogicalOperatorType.AGGREGATE:
            group_keys = self._extract_prefixed(expressions, ("groupkeys", "grouping keys", "group by"))
            if group_keys:
                kwargs["group_by_keys"] = group_keys
        elif logical_type == LogicalOperatorType.FILTER and expressions:
            kwargs["filter_expressions"] = expressions

        properties: dict[str, Any] = {}
        for key in ("partitionsAssigned", "partitionsTotal", "bytesAssigned"):
            value = node.get(key)
            if value is not None:
                properties[key] = value

        physical_op = self._create_physical_operator(
            operation or "Unknown",
            properties=properties,
            platform_metadata={
                "node_id": node.get("id"),
                "objects": objects or None,
                "expressions": expressions or None,
            },
        )

        return self._create_logical_operator(
            operator_type=logical_type,
            children=children,
            physical_operator=physical_op,
            **kwargs,
        )

    @classmethod
    def _map_operator_type(cls, operation: str) -> LogicalOperatorType:
        normalized = operation.lower().replace(" ", "").replace("_", "")
        for keyword, logical_type in cls._OPERATOR_KEYWORDS:
            if keyword in normalized:
                return logical_type
        return LogicalOperatorType.OTHER

    @staticmethod
    def _classify_join_type(operation: str, expressions: list[str]) -> JoinType:
        haystack = (operation + " " + " ".join(expressions)).lower()
        if "semi" in haystack:
            return JoinType.SEMI
        if "anti" in haystack:
            return JoinType.ANTI
        for keyword, join_type in (
            ("leftouter", JoinType.LEFT),
            ("left outer", JoinType.LEFT),
            ("rightouter", JoinType.RIGHT),
            ("right outer", JoinType.RIGHT),
            ("fullouter", JoinType.FULL),
            ("full outer", JoinType.FULL),
            ("cross", JoinType.CROSS),
        ):
            if keyword in haystack:
                return join_type
        return JoinType.INNER

    @staticmethod
    def _extract_join_condition(expressions: list[str]) -> str | None:
        for expr in expressions:
            match = re.search(r"(?:joinkey|equality\s*join\s*condition|condition)\s*[:=]\s*(.+)", expr, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_table(expressions: list[str]) -> str | None:
        for expr in expressions:
            match = re.search(r"(?:table|relation)\s*[:=]\s*([\w.$\"]+)", expr, re.IGNORECASE)
            if match:
                return match.group(1).strip('"')
        return None

    @staticmethod
    def _extract_prefixed(expressions: list[str], prefixes: tuple[str, ...]) -> list[str] | None:
        for expr in expressions:
            lowered = expr.lower()
            for prefix in prefixes:
                if lowered.startswith(prefix) or f"{prefix}:" in lowered:
                    _, _, rest = expr.partition(":")
                    body = (rest or expr).strip().strip("[]")
                    keys = [k.strip() for k in body.split(",") if k.strip()]
                    if keys:
                        return keys
        return None

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        return [text] if text else []

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
