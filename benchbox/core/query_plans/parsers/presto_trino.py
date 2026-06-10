"""Presto / Trino query plan parser.

Parses the JSON tree emitted by ``EXPLAIN (FORMAT JSON)`` on Presto, Trino, and
compatible engines (Starburst, Amazon Athena) into the harmonized
``QueryPlanDAG`` structure.

The ``EXPLAIN (FORMAT JSON)`` payload is a single JSON value describing a tree of
plan nodes. Field naming differs slightly across the family:

- **Presto** nodes carry ``id``, ``name``, ``identifier`` (a string), ``details``
  (a string), and ``children`` (a list of child nodes).
- **Trino** nodes carry ``id``, ``name``, ``descriptor`` (an object of
  key/value detail fields), ``outputs``, ``details`` (a list of strings),
  ``estimates``, and ``children``.
- Trino's distributed plans wrap fragments in a top-level object keyed by
  fragment id; the parser unwraps that to the first/root fragment.

The parser normalizes operator ``name`` to ``LogicalOperatorType`` via
substring matching (so fused operators such as ``ScanFilterProject`` resolve to
their dominant ``Scan`` type, and version-specific names such as ``LookupJoin``
or ``InnerJoin`` resolve to ``Join``), falling back to the base harmonizer for
unknown names.
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


class PrestoTrinoQueryPlanParser(QueryPlanParser):
    """Parser for Presto / Trino ``EXPLAIN (FORMAT JSON)`` output."""

    # Ordered (substring, type) pairs. The first substring found in the
    # lower-cased operator name wins, so more specific / dominant operators are
    # listed before the generic ones they may contain (e.g. a fused
    # "ScanFilterProject" must resolve to SCAN, not FILTER or PROJECT).
    _OPERATOR_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("tablescan", LogicalOperatorType.SCAN),
        ("scan", LogicalOperatorType.SCAN),
        ("indexsource", LogicalOperatorType.SCAN),
        ("values", LogicalOperatorType.SCAN),
        ("join", LogicalOperatorType.JOIN),
        ("aggregat", LogicalOperatorType.AGGREGATE),
        ("groupid", LogicalOperatorType.AGGREGATE),
        ("distinctlimit", LogicalOperatorType.LIMIT),
        ("window", LogicalOperatorType.WINDOW),
        ("topn", LogicalOperatorType.SORT),
        ("sort", LogicalOperatorType.SORT),
        ("orderby", LogicalOperatorType.SORT),
        ("limit", LogicalOperatorType.LIMIT),
        ("output", LogicalOperatorType.PROJECT),
        ("project", LogicalOperatorType.PROJECT),
        ("filter", LogicalOperatorType.FILTER),
        ("union", LogicalOperatorType.UNION),
        ("intersect", LogicalOperatorType.INTERSECT),
        ("except", LogicalOperatorType.EXCEPT),
    )

    def __init__(self):
        super().__init__("presto_trino")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")

        try:
            payload = json.loads(explain_output)
        except json.JSONDecodeError as exc:
            raise ValueError(f"EXPLAIN output is not valid JSON: {exc}") from exc

        fragments = self._extract_fragments(payload)
        if fragments is not None:
            # Distributed output: root at the lowest-numbered fragment and splice
            # the other fragments in at their RemoteSource references.
            root_id = min(fragments, key=lambda fid: self._fragment_sort_key(fid))
            root = self._build_operator(fragments[root_id], fragments=fragments, visited={root_id})
        else:
            root_node = self._find_root_node(payload)
            if root_node is None:
                raise ValueError("No plan node found in EXPLAIN (FORMAT JSON) output")
            root = self._build_operator(root_node)

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            raw_explain_output=explain_output,
        )

    @staticmethod
    def _fragment_sort_key(fragment_id: str) -> tuple[int, str]:
        """Sort numeric fragment ids numerically; fall back to lexical for the rest."""
        text = str(fragment_id)
        return (int(text), "") if text.isdigit() else (1 << 30, text)

    def _extract_fragments(self, payload: Any) -> dict[str, dict[str, Any]] | None:
        """Return the {fragment_id: node} map for fragment-keyed Trino output, else None.

        Distributed ``EXPLAIN (FORMAT JSON)`` wraps each plan fragment in a
        top-level object keyed by fragment id (``{"0": {...}, "1": {...}}``); a
        logical (single-tree) plan is just a node with a ``name``.
        """
        if not isinstance(payload, dict) or "name" in payload:
            return None
        fragments = {str(key): value for key, value in payload.items() if isinstance(value, dict) and "name" in value}
        # Only treat as fragment-keyed when every value is a plan node.
        if fragments and len(fragments) == len(payload):
            return fragments
        return None

    def _find_root_node(self, payload: Any) -> dict[str, Any] | None:
        """Locate the root plan node for a single-tree (logical) payload."""
        if isinstance(payload, list):
            payload = payload[0] if payload else None
        if not isinstance(payload, dict):
            return None
        if "name" in payload:
            return payload
        return None

    def _build_operator(
        self,
        node: dict[str, Any],
        fragments: dict[str, dict[str, Any]] | None = None,
        visited: set[str] | None = None,
    ) -> LogicalOperator:
        """Recursively convert a JSON plan node into a LogicalOperator.

        When ``fragments`` is provided (distributed output), a RemoteSource node
        is spliced with the subtrees of the fragments it reads from, so the DAG
        is not truncated at fragment boundaries. ``visited`` guards against a
        fragment being expanded more than once on a path.
        """
        name = str(node.get("name", "")).strip()
        details = self._node_details(node)
        logical_type = self._map_operator_type(name)

        raw_children = node.get("children")
        children = [
            self._build_operator(child, fragments, visited)
            for child in (raw_children if isinstance(raw_children, list) else [])
            if isinstance(child, dict)
        ]

        if fragments:
            children.extend(self._expand_remote_sources(node, name, fragments, visited or set()))

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN:
            table = self._extract_table(node, details)
            if table:
                kwargs["table_name"] = table
        elif logical_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = self._classify_join_type(name, details, node)
            condition = self._extract_join_condition(node, details)
            if condition:
                kwargs["join_conditions"] = [condition]
        elif logical_type == LogicalOperatorType.AGGREGATE:
            keys = self._extract_descriptor_field(node, ("keys", "groupingKeys", "group_by"))
            if keys:
                kwargs["group_by_keys"] = [k.strip() for k in re.split(r"[,\s]+", keys.strip("[] ")) if k.strip()]

        physical_op = self._create_physical_operator(
            name or "Unknown",
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

    def _expand_remote_sources(
        self,
        node: dict[str, Any],
        name: str,
        fragments: dict[str, dict[str, Any]],
        visited: set[str],
    ) -> list[LogicalOperator]:
        """Splice the fragments a RemoteSource/RemoteExchange reads from as children."""
        if "remotesource" not in name.lower().replace(" ", ""):
            return []
        source_ids = self._source_fragment_ids(node)
        spliced: list[LogicalOperator] = []
        for fid in source_ids:
            if fid in visited or fid not in fragments:
                continue
            spliced.append(self._build_operator(fragments[fid], fragments, visited | {fid}))
        return spliced

    @classmethod
    def _source_fragment_ids(cls, node: dict[str, Any]) -> list[str]:
        """Parse the source fragment ids from a RemoteSource node's descriptor/details."""
        raw = cls._extract_descriptor_field(node, ("sourceFragmentIds", "sourceFragments", "sourceFragmentId"))
        if raw is None:
            details = node.get("details")
            raw = " ".join(details) if isinstance(details, list) else str(details or "")
        return re.findall(r"\d+", raw)

    @staticmethod
    def _node_details(node: dict[str, Any]) -> str:
        """Flatten Presto ``identifier``/``details`` and Trino ``descriptor``/``details``."""
        parts: list[str] = []
        identifier = node.get("identifier")
        if isinstance(identifier, str) and identifier.strip():
            parts.append(identifier.strip())
        descriptor = node.get("descriptor")
        if isinstance(descriptor, dict):
            for key, value in descriptor.items():
                text = str(value).strip()
                if text and text not in ("[]", "{}"):
                    parts.append(f"{key}={text}")
        details = node.get("details")
        if isinstance(details, str) and details.strip():
            parts.append(details.strip())
        elif isinstance(details, list):
            parts.extend(str(item).strip() for item in details if str(item).strip())
        return " ".join(parts)

    @classmethod
    def _map_operator_type(cls, name: str) -> LogicalOperatorType:
        normalized = name.lower().replace(" ", "").replace("_", "")
        for keyword, logical_type in cls._OPERATOR_KEYWORDS:
            if keyword in normalized:
                return logical_type
        if "exchange" in normalized or "remotesource" in normalized:
            return LogicalOperatorType.OTHER
        return LogicalOperatorType.OTHER

    @staticmethod
    def _extract_descriptor_field(node: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        descriptor = node.get("descriptor")
        if isinstance(descriptor, dict):
            for key in keys:
                value = descriptor.get(key)
                if value not in (None, "", "[]"):
                    return str(value)
        return None

    def _extract_table(self, node: dict[str, Any], details: str) -> str | None:
        table = self._extract_descriptor_field(node, ("table", "qualifiedName", "sourceName"))
        if table:
            return table.strip("[]")
        identifier = node.get("identifier")
        if isinstance(identifier, str):
            # Prefer an explicit "table = ..."; otherwise capture a fully
            # colon-qualified name (catalog:schema:table[:version]) without
            # truncating to the first two segments.
            match = re.search(r"table\s*=\s*([\w.:\"-]+)", identifier) or re.search(
                r"\[?([\w.-]+(?::[\w.-]+)+)\]?", identifier
            )
            if match:
                return match.group(1).strip('[]"')
        match = re.search(r"table\s*=\s*([\w.:\"-]+)", details)
        if match:
            return match.group(1).strip('[]"')
        return None

    @staticmethod
    def _classify_join_type(name: str, details: str, node: dict[str, Any]) -> JoinType:
        haystack = f"{name} {details}".lower()
        descriptor = node.get("descriptor")
        if isinstance(descriptor, dict):
            haystack += (
                " " + str(descriptor.get("type", "")).lower() + " " + str(descriptor.get("criteria", "")).lower()
            )
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

    def _extract_join_condition(self, node: dict[str, Any], details: str) -> str | None:
        criteria = self._extract_descriptor_field(node, ("criteria", "on", "condition"))
        if criteria:
            return criteria.strip("[] ")
        # Word-bounded so "on" does not match inside words like "Distribution:".
        match = re.search(r"\b(?:criteria|on|condition)\b\s*[=:]\s*\[?([^\]]+)\]?", details, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Presto join criteria live in the identifier as a parenthesized equality,
        # e.g. [("regionkey" = "regionkey_4")].
        identifier = node.get("identifier")
        if isinstance(identifier, str):
            eq = re.search(r"\(([^)]*=[^)]*)\)", identifier)
            if eq:
                return eq.group(1).strip()
        return None
