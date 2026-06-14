"""Spark / Databricks query plan parser.

Parses the ``== Physical Plan ==`` section of Spark's ``EXPLAIN EXTENDED`` output
into the harmonized ``QueryPlanDAG``. ``EXPLAIN EXTENDED`` emits four sections
(Parsed / Analyzed / Optimized Logical Plan and Physical Plan); only the physical
plan is parsed, since it is the most stable across Spark versions for
fingerprinting.

The physical plan uses Spark's ``TreeNode.treeString`` drawing, where nesting is
encoded by fixed 3-character prefix groups (``+- ``/``:- `` connectors and
``:  ``/``   `` ancestor fillers) and operators may carry a ``*(n) `` whole-stage
codegen marker, e.g.::

    *(3) HashAggregate(keys=[...], functions=[...])
    +- Exchange hashpartitioning(...)
       +- *(2) BroadcastHashJoin [...], Inner, BuildRight
          :- *(2) Filter isnotnull(...)
          :  +- FileScan parquet default.lineitem[...]
          +- BroadcastExchange ...
             +- FileScan parquet default.orders[...]

Operator depth is the number of leading 3-char prefix groups; the operator name
is the first word after stripping the connector and codegen marker.
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


class SparkQueryPlanParser(QueryPlanParser):
    """Parser for Spark / Databricks ``EXPLAIN EXTENDED`` physical-plan text."""

    # Ordered (substring, type) pairs; first match in the lower-cased operator
    # name wins, so specific names precede the generic ones they contain.
    _OPERATOR_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("filescan", LogicalOperatorType.SCAN),
        ("inmemorytablescan", LogicalOperatorType.SCAN),
        ("hivetablescan", LogicalOperatorType.SCAN),
        ("batchscan", LogicalOperatorType.SCAN),
        ("rowdatasourcescan", LogicalOperatorType.SCAN),
        ("datasourcescan", LogicalOperatorType.SCAN),
        ("datasourcev2scan", LogicalOperatorType.SCAN),
        ("scan", LogicalOperatorType.SCAN),
        ("broadcasthashjoin", LogicalOperatorType.JOIN),
        ("sortmergejoin", LogicalOperatorType.JOIN),
        ("shuffledhashjoin", LogicalOperatorType.JOIN),
        ("broadcastnestedloopjoin", LogicalOperatorType.JOIN),
        ("cartesianproduct", LogicalOperatorType.JOIN),
        ("join", LogicalOperatorType.JOIN),
        ("hashaggregate", LogicalOperatorType.AGGREGATE),
        ("objecthashaggregate", LogicalOperatorType.AGGREGATE),
        ("sortaggregate", LogicalOperatorType.AGGREGATE),
        ("aggregate", LogicalOperatorType.AGGREGATE),
        ("takeorderedandproject", LogicalOperatorType.SORT),
        ("sort", LogicalOperatorType.SORT),
        ("globallimit", LogicalOperatorType.LIMIT),
        ("locallimit", LogicalOperatorType.LIMIT),
        ("collectlimit", LogicalOperatorType.LIMIT),
        ("window", LogicalOperatorType.WINDOW),
        ("union", LogicalOperatorType.UNION),
        ("filter", LogicalOperatorType.FILTER),
        ("project", LogicalOperatorType.PROJECT),
        # Exchange / shuffle / codegen wrappers have no dedicated logical type.
        ("broadcastexchange", LogicalOperatorType.OTHER),
        ("shuffleexchange", LogicalOperatorType.OTHER),
        ("exchange", LogicalOperatorType.OTHER),
    )

    _PHYSICAL_HEADER = "== Physical Plan =="
    # One nesting level: a connector ("+- "/":- ") or an ancestor filler (":  "/"   ").
    _PREFIX_RE = re.compile(r"^((?:\+- |:- |:  |   )*)(.*)$")
    # Optional whole-stage codegen marker, e.g. "*(3) " or "* ".
    _CODEGEN_RE = re.compile(r"^\*(?:\(\d+\))?\s*")

    def __init__(self):
        super().__init__("spark")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")

        physical_text = self._extract_physical_section(explain_output)
        parsed_nodes = self._parse_lines(physical_text)
        if not parsed_nodes:
            raise ValueError("No operators found in Spark physical plan")

        root = self._build_tree(parsed_nodes)
        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            raw_explain_output=explain_output,
        )

    def _extract_physical_section(self, explain_output: str) -> str:
        """Return the text after the last ``== Physical Plan ==`` header.

        Bare ``EXPLAIN`` (no EXTENDED) returns only the physical plan with no
        header, so when the header is absent the whole text is used.
        """
        idx = explain_output.rfind(self._PHYSICAL_HEADER)
        if idx == -1:
            return explain_output
        return explain_output[idx + len(self._PHYSICAL_HEADER) :]

    def _parse_lines(self, physical_text: str) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for raw_line in physical_text.splitlines():
            if not raw_line.strip():
                continue
            prefix, rest = self._PREFIX_RE.match(raw_line).groups()
            rest = rest.strip()
            # Skip AQE sub-section headers like "== Initial Plan ==".
            if rest.startswith("==") and rest.endswith("=="):
                continue
            depth = len(prefix) // 3
            node_text = self._CODEGEN_RE.sub("", rest).strip()
            name_match = re.match(r"([A-Za-z][\w]*)", node_text)
            if not name_match:
                continue
            parsed.append({"depth": depth, "name": name_match.group(1), "details": node_text})
        return parsed

    def _build_tree(self, parsed_nodes: list[dict[str, Any]]) -> LogicalOperator:
        stack: list[tuple[int, LogicalOperator]] = []
        root: LogicalOperator | None = None

        for node in parsed_nodes:
            logical_op = self._convert_to_logical_operator(node)
            while stack and stack[-1][0] >= node["depth"]:
                stack.pop()
            if not stack:
                if root is None:
                    root = logical_op
                else:
                    # A second depth-0 node (rare) becomes a child of the root so a
                    # single connected DAG is always returned.
                    root.children.append(logical_op)
            else:
                stack[-1][1].children.append(logical_op)
            stack.append((node["depth"], logical_op))

        if root is None:
            raise ValueError("Could not determine root operator")
        return root

    def _convert_to_logical_operator(self, node: dict[str, Any]) -> LogicalOperator:
        name = node["name"]
        details = node["details"]
        logical_type = self._map_operator_type(name)

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN:
            table = self._extract_table(details)
            if table:
                kwargs["table_name"] = table

        physical_op = self._create_physical_operator(
            name,
            properties={},
            platform_metadata={"details": details or None},
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
    def _extract_table(details: str) -> str | None:
        """Extract the table from a FileScan/Scan detail, e.g. 'FileScan parquet default.lineitem[...]'."""
        # FileScan <format> <db.table>[columns...]
        match = re.search(r"(?:FileScan|Scan)\s+\w+\s+([A-Za-z_][\w.]*)", details)
        if match:
            return match.group(1)
        # Fallback: a dotted identifier anywhere (e.g. "Scan hive default.orders").
        dotted = re.search(r"\b([A-Za-z_]\w*\.[A-Za-z_][\w.]*)", details)
        return dotted.group(1) if dotted else None
