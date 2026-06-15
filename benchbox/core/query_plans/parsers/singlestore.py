"""SingleStore (MemSQL) query plan parser.

Parses SingleStore ``EXPLAIN <query>`` output into the harmonized
``QueryPlanDAG``. SingleStore returns the plan as text rows that form a tree
with two structural conventions:

- The main pipeline is a vertical chain at the base level: each line is the
  *input* (child) of the line above it, e.g. ``Project`` consumes ``Gather``
  consumes ``HashGroupBy`` ... down to the leaf scan.
- A ``|---`` connector marks an additional branch input (typically a join's
  build side); deeper branches stack the connector (``|   |---``).

Example::

    Project [l_orderkey, revenue]
    Gather partitions:all
    Project [l_orderkey, revenue]
    TopSort limit:[10] [revenue DESC]
    HashGroupBy [SUM(l_extendedprice) AS revenue] groups:[l_orderkey]
    HashJoin [INNER] ON lineitem.l_orderkey = orders.o_orderkey
    |---ColumnStoreScan db.orders, KEY (o_orderkey) table_type:reference
    ColumnStoreScan db.lineitem, KEY (l_orderkey) table_type:sharded

There the ``HashJoin`` has two children: the ``|---`` build branch (orders) and
the next base-level line (lineitem), which continues the chain as the probe
input. Depth is the number of leading 4-character connector groups (``|---`` or
``|   ``); base-level lines are depth 0.
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


class SingleStoreQueryPlanParser(QueryPlanParser):
    """Parser for SingleStore ``EXPLAIN`` connector-tree text output."""

    # Ordered (substring, type) pairs; the first substring found in the
    # lower-cased, space-stripped operator name wins. "TopSort" must precede the
    # bare "top" (LIMIT) so a sort is not misread as a limit.
    _OPERATOR_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("orderedcolumnstorescan", LogicalOperatorType.SCAN),
        ("columnstorescan", LogicalOperatorType.SCAN),
        ("indexrangescan", LogicalOperatorType.SCAN),
        ("indexseek", LogicalOperatorType.SCAN),
        ("tablescan", LogicalOperatorType.SCAN),
        ("nestedloopjoin", LogicalOperatorType.JOIN),
        ("hashjoin", LogicalOperatorType.JOIN),
        ("mergejoin", LogicalOperatorType.JOIN),
        ("join", LogicalOperatorType.JOIN),
        ("hashgroupby", LogicalOperatorType.AGGREGATE),
        ("streaminggroupby", LogicalOperatorType.AGGREGATE),
        ("groupby", LogicalOperatorType.AGGREGATE),
        ("aggregate", LogicalOperatorType.AGGREGATE),
        ("topsort", LogicalOperatorType.SORT),
        ("sort", LogicalOperatorType.SORT),
        ("top", LogicalOperatorType.LIMIT),
        ("limit", LogicalOperatorType.LIMIT),
        ("filter", LogicalOperatorType.FILTER),
        ("project", LogicalOperatorType.PROJECT),
        ("window", LogicalOperatorType.WINDOW),
        ("union", LogicalOperatorType.UNION),
        # Distributed data-movement operators have no dedicated logical type.
        ("gathermerge", LogicalOperatorType.OTHER),
        ("gather", LogicalOperatorType.OTHER),
        ("repartition", LogicalOperatorType.OTHER),
        ("broadcast", LogicalOperatorType.OTHER),
        ("shuffle", LogicalOperatorType.OTHER),
    )

    # One nesting level: a "|---" branch connector or a "|   " ancestor filler.
    _PREFIX_RE = re.compile(r"^((?:\|---|\|   |\|--|    )*)(.*)$")

    def __init__(self):
        super().__init__("singlestore")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")
        if explain_output.lstrip().startswith(("Failed to get query plan", "Could not get query plan")):
            raise ValueError("EXPLAIN returned an error message, not a plan")

        parsed_nodes = self._parse_lines(explain_output)
        if not parsed_nodes:
            raise ValueError("No operators found in EXPLAIN output")

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
            if not raw_line.strip():
                continue
            # Drop the MySQL-client column border ("| ... |") if present so the
            # parser works on both raw-connector and tabular renderings.
            line = raw_line.strip()
            if line.startswith("|") and line.endswith("|") and ("---" not in line):
                line = line[1:-1]
            elif line.startswith("+") and set(line) <= {"+", "-"}:
                continue  # table-border separator row
            if line.strip() in ("EXPLAIN", "QUERY PLAN"):
                continue
            prefix, rest = self._PREFIX_RE.match(line).groups()
            rest = rest.strip()
            if not rest or not rest[0].isalpha():
                continue
            depth = len(prefix) // 4
            parsed.append({"depth": depth, "content": rest})
        return parsed

    def _build_tree(self, parsed_nodes: list[dict[str, Any]]) -> LogicalOperator | None:
        root: LogicalOperator | None = None
        # The most recent operator seen at each depth. A base-level (depth 0) chain
        # links each node to the previous depth-0 node; a deeper branch links to
        # the most recent node one level shallower.
        last_at_depth: dict[int, LogicalOperator] = {}

        for node in parsed_nodes:
            depth = node["depth"]
            logical_op = self._convert_to_logical_operator(node["content"])

            parent = last_at_depth.get(depth - 1) if depth > 0 else last_at_depth.get(0)
            if parent is None:
                if root is None:
                    root = logical_op
                else:
                    root.children.append(logical_op)
            else:
                parent.children.append(logical_op)

            last_at_depth[depth] = logical_op
            # Moving back to a shallower/equal depth invalidates deeper entries so
            # a later branch cannot attach under a stale child.
            for deeper in [d for d in last_at_depth if d > depth]:
                del last_at_depth[deeper]

        return root

    def _convert_to_logical_operator(self, content: str) -> LogicalOperator:
        name_match = re.match(r"([A-Za-z][\w]*)", content)
        name = name_match.group(1) if name_match else content
        logical_type = self._map_operator_type(name)

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN:
            table = self._extract_table(content)
            if table:
                kwargs["table_name"] = table
        elif logical_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = self._classify_join_type(content)

        physical_op = self._create_physical_operator(
            name,
            properties={},
            platform_metadata={"details": content},
        )
        return self._create_logical_operator(
            operator_type=logical_type,
            children=[],
            physical_operator=physical_op,
            **kwargs,
        )

    @classmethod
    def _map_operator_type(cls, name: str) -> LogicalOperatorType:
        normalized = name.lower().replace(" ", "").replace("_", "")
        for keyword, logical_type in cls._OPERATOR_KEYWORDS:
            if keyword in normalized:
                return logical_type
        return LogicalOperatorType.OTHER

    @staticmethod
    def _extract_table(content: str) -> str | None:
        """Extract the table from a scan line, e.g. 'ColumnStoreScan db.orders, KEY (...)'."""
        # The scanned relation follows the operator name: "<Scan> <db.table>[, ...]".
        match = re.match(r"[A-Za-z][\w]*\s+([A-Za-z_][\w.]*)", content)
        return match.group(1) if match else None

    def _classify_join_type(self, content: str) -> JoinType:
        match = re.search(r"\[([^\]]*)\]", content)
        if match:
            return self._harmonize_join_type(match.group(1))
        return JoinType.INNER


__all__ = ["SingleStoreQueryPlanParser"]
