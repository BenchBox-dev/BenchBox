"""Snowflake query plan parser.

Parses the JSON emitted by ``EXPLAIN USING JSON <query>`` on Snowflake into the
harmonized :class:`QueryPlanDAG` structure.

Snowflake's ``EXPLAIN USING JSON`` returns a single JSON object::

    {
      "GlobalStats": {"partitionsTotal": 1, "partitionsAssigned": 1, "bytesAssigned": 1024},
      "Operations": [
        [
          {"id": 0, "operation": "Result", "expressions": ["O_ORDERKEY", "REVENUE"]},
          {"id": 1, "operation": "Aggregate", "parentOperators": [0], "expressions": ["SUM(...)"]},
          {"id": 2, "operation": "Join", "parentOperators": [1], "expressions": ["O_ORDERKEY = L_ORDERKEY"]},
          {"id": 3, "operation": "TableScan", "parentOperators": [2], "objects": ["TPCH.ORDERS"]},
          {"id": 4, "operation": "TableScan", "parentOperators": [2], "objects": ["TPCH.LINEITEM"]}
        ]
      ]
    }

``Operations`` is a list of plan steps; each step is a list of operator nodes.
Each node carries an integer ``id``, an ``operation`` name, a ``parentOperators``
list (the ids of the operators this node feeds into — the root ``Result`` node
has none), and optional ``objects`` (scanned tables) and ``expressions`` detail.
The tree is reconstructed from the ``parentOperators`` edges: the node with no
parent is the root, and a node's children are the operators that name it as a
parent.
"""

from __future__ import annotations

import json
import logging
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

    # Ordered (substring, type) pairs; the first substring found in the
    # lower-cased operation name wins, so more specific names precede the generic
    # ones they may contain. ``JoinFilter`` is a bloom filter pushed to the scan
    # side, so it must resolve to SCAN before the generic ``join`` rule.
    _OPERATOR_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("joinfilter", LogicalOperatorType.SCAN),
        ("tablescan", LogicalOperatorType.SCAN),
        ("scan", LogicalOperatorType.SCAN),
        ("valuesclause", LogicalOperatorType.SCAN),
        ("generator", LogicalOperatorType.SCAN),
        ("join", LogicalOperatorType.JOIN),
        ("aggregate", LogicalOperatorType.AGGREGATE),
        ("groupingsets", LogicalOperatorType.AGGREGATE),
        ("sort", LogicalOperatorType.SORT),
        ("limit", LogicalOperatorType.LIMIT),
        ("withreference", LogicalOperatorType.PROJECT),
        ("withclause", LogicalOperatorType.CTE),
        ("result", LogicalOperatorType.PROJECT),
        ("projection", LogicalOperatorType.PROJECT),
        ("project", LogicalOperatorType.PROJECT),
        ("filter", LogicalOperatorType.FILTER),
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

        nodes = self._collect_nodes(payload)
        if not nodes:
            raise ValueError("No operators found in EXPLAIN USING JSON output")

        root_node = self._find_root(nodes)
        if root_node is None:
            raise ValueError("Could not determine root operator from parentOperators links")

        root = self._build_operator(root_node, nodes, visited=set())

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            raw_explain_output=explain_output,
        )

    @staticmethod
    def _collect_nodes(payload: Any) -> dict[int, dict[str, Any]]:
        """Flatten ``Operations`` (a list of step lists) into an id -> node map."""
        if not isinstance(payload, dict):
            return {}
        operations = payload.get("Operations")
        nodes: dict[int, dict[str, Any]] = {}
        if not isinstance(operations, list):
            return nodes
        for step in operations:
            step_nodes = step if isinstance(step, list) else [step]
            for node in step_nodes:
                if isinstance(node, dict) and "id" in node:
                    try:
                        node_id = int(node["id"])
                    except (TypeError, ValueError):
                        continue
                    nodes[node_id] = node
        return nodes

    @staticmethod
    def _parent_ids(node: dict[str, Any]) -> list[int]:
        parents = node.get("parentOperators")
        if parents is None:
            return []
        if not isinstance(parents, list):
            parents = [parents]
        result: list[int] = []
        for parent in parents:
            try:
                result.append(int(parent))
            except (TypeError, ValueError):
                continue
        return result

    def _find_root(self, nodes: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
        """The root is the parentless node whose subtree reaches the most operators.

        A well-formed Snowflake plan has a single parentless ``Result`` node, but
        a multi-statement / union-style payload can expose several parentless
        nodes. Picking the one with the largest reachable subtree (lowest id on a
        tie) avoids silently dropping the main plan's operators.
        """
        roots = [node for node in nodes.values() if not self._parent_ids(node)]
        if not roots:
            return None
        if len(roots) == 1:
            return roots[0]
        return max(roots, key=lambda n: (self._reachable_count(int(n.get("id", 0)), nodes), -int(n.get("id", 0))))

    def _reachable_count(self, node_id: int, nodes: dict[int, dict[str, Any]]) -> int:
        """Number of operators reachable from ``node_id`` following child edges."""
        seen: set[int] = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(other_id for other_id, other in nodes.items() if current in self._parent_ids(other))
        return len(seen)

    def _build_operator(
        self,
        node: dict[str, Any],
        nodes: dict[int, dict[str, Any]],
        visited: set[int],
    ) -> LogicalOperator:
        node_id = int(node.get("id", -1))
        visited = visited | {node_id}

        # Children are the operators that feed into this node (name it as a parent).
        child_nodes = [
            other for other_id, other in nodes.items() if node_id in self._parent_ids(other) and other_id not in visited
        ]
        child_nodes.sort(key=lambda n: int(n.get("id", 0)))
        children = [self._build_operator(child, nodes, visited) for child in child_nodes]

        operation = str(node.get("operation", "")).strip()
        logical_type = self._map_operator_type(operation)
        details = self._node_details(node)

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN:
            table = self._extract_table(node)
            if table:
                kwargs["table_name"] = table
        elif logical_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = self._classify_join_type(operation, details)
            condition = self._join_condition(node)
            if condition:
                kwargs["join_conditions"] = [condition]

        physical_op = self._create_physical_operator(
            operation or "Unknown",
            properties={},
            platform_metadata={
                "node_id": node.get("id"),
                "details": details or None,
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
    def _node_details(node: dict[str, Any]) -> str:
        parts: list[str] = []
        expressions = node.get("expressions")
        if isinstance(expressions, list):
            parts.extend(str(item).strip() for item in expressions if str(item).strip())
        elif isinstance(expressions, str) and expressions.strip():
            parts.append(expressions.strip())
        return " ".join(parts)

    @staticmethod
    def _extract_table(node: dict[str, Any]) -> str | None:
        objects = node.get("objects")
        if isinstance(objects, list) and objects:
            return str(objects[0]).strip()
        if isinstance(objects, str) and objects.strip():
            return objects.strip()
        return None

    @staticmethod
    def _classify_join_type(operation: str, details: str) -> JoinType:
        haystack = f"{operation} {details}".lower()
        if "semi" in haystack:
            return JoinType.SEMI
        if "anti" in haystack:
            return JoinType.ANTI
        for keyword, join_type in (
            ("leftouter", JoinType.LEFT),
            ("left", JoinType.LEFT),
            ("rightouter", JoinType.RIGHT),
            ("right", JoinType.RIGHT),
            ("fullouter", JoinType.FULL),
            ("full", JoinType.FULL),
            ("cross", JoinType.CROSS),
            ("cartesian", JoinType.CROSS),
        ):
            if keyword in haystack:
                return join_type
        return JoinType.INNER

    @staticmethod
    def _join_condition(node: dict[str, Any]) -> str | None:
        expressions = node.get("expressions")
        if isinstance(expressions, list) and expressions:
            return ", ".join(str(item).strip() for item in expressions if str(item).strip()) or None
        if isinstance(expressions, str) and expressions.strip():
            return expressions.strip()
        return None
