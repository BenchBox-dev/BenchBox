from __future__ import annotations

import logging
import re
from typing import Any
from xml.etree import ElementTree as ET

from benchbox.core.query_plans.parsers.base import QueryPlanParser
from benchbox.core.results.query_plan_models import (
    JoinType,
    LogicalOperator,
    LogicalOperatorType,
    QueryPlanDAG,
)

logger = logging.getLogger(__name__)


class AzureSynapseQueryPlanParser(QueryPlanParser):
    _OPERATION_TYPE_MAP: dict[str, LogicalOperatorType] = {
        "RETURN": LogicalOperatorType.PROJECT,
        "SHUFFLE_MOVE": LogicalOperatorType.OTHER,
        "BROADCAST_MOVE": LogicalOperatorType.OTHER,
        "PARTITION_MOVE": LogicalOperatorType.OTHER,
        "TRIM_MOVE": LogicalOperatorType.OTHER,
        "MASTER_MERGE": LogicalOperatorType.OTHER,
        "MOVE": LogicalOperatorType.OTHER,
        "COPY": LogicalOperatorType.OTHER,
        "RND_ID": LogicalOperatorType.OTHER,
        "ON": LogicalOperatorType.OTHER,
        "META_DATA_CREATE": LogicalOperatorType.OTHER,
    }

    def __init__(self):
        super().__init__("azure_synapse")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")

        try:
            root_el = ET.fromstring(explain_output.strip())
        except ET.ParseError as exc:
            raise ValueError(f"EXPLAIN output is not valid XML: {exc}") from exc

        operations = root_el.findall(".//dsql_operations/dsql_operation")
        if not operations:
            raise ValueError("No dsql_operation elements found in EXPLAIN XML")

        child: LogicalOperator | None = None
        for op in operations:
            child = self._build_operator(op, child)
            if (op.get("operation_type") or "").strip().upper() == "RETURN":
                break

        assert child is not None
        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=child,
            raw_explain_output=explain_output,
        )

    def _build_operator(self, op: ET.Element, downstream_child: LogicalOperator | None) -> LogicalOperator:
        operation_type = (op.get("operation_type") or "").strip()
        sql_text = self._embedded_sql(op)
        logical_type = self._map_operation(operation_type, sql_text)

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.JOIN and sql_text:
            kwargs["join_type"] = self._classify_join_type(sql_text)

        properties: dict[str, Any] = {}
        cost_el = op.find("operation_cost")
        if cost_el is not None:
            output_rows = cost_el.get("output_rows")
            if output_rows is not None:
                try:
                    properties["output_rows"] = int(output_rows)
                except (TypeError, ValueError):
                    pass

        physical_op = self._create_physical_operator(
            operation_type or "Unknown",
            properties=properties,
            platform_metadata={
                "operation_type": operation_type or None,
                "sql": sql_text or None,
            },
        )

        return self._create_logical_operator(
            operator_type=logical_type,
            children=[downstream_child] if downstream_child is not None else [],
            physical_operator=physical_op,
            **kwargs,
        )

    @staticmethod
    def _embedded_sql(op: ET.Element) -> str:
        for tag in ("source_statement", "sql_operation", "statement"):
            el = op.find(tag)
            if el is not None and el.text and el.text.strip():
                return el.text.strip()
        return ""

    @classmethod
    def _map_operation(cls, operation_type: str, sql_text: str) -> LogicalOperatorType:
        base = cls._OPERATION_TYPE_MAP.get(operation_type.upper(), LogicalOperatorType.OTHER)
        if sql_text and base in (LogicalOperatorType.OTHER,):
            refined = cls._classify_sql(sql_text)
            if refined is not None:
                return refined
        return base

    @staticmethod
    def _classify_sql(sql_text: str) -> LogicalOperatorType | None:
        lowered = sql_text.lower()
        if re.search(r"\bjoin\b", lowered):
            return LogicalOperatorType.JOIN
        if re.search(r"\bgroup\s+by\b", lowered):
            return LogicalOperatorType.AGGREGATE
        if re.search(r"\border\s+by\b", lowered):
            return LogicalOperatorType.SORT
        return None

    _JOIN_QUALIFIER_RE = re.compile(r"\b(left|right|full|cross)\b(?:\s+outer)?\s+join\b", re.IGNORECASE)

    @classmethod
    def _classify_join_type(cls, sql_text: str) -> JoinType:
        match = cls._JOIN_QUALIFIER_RE.search(sql_text)
        if not match:
            return JoinType.INNER
        return {
            "left": JoinType.LEFT,
            "right": JoinType.RIGHT,
            "full": JoinType.FULL,
            "cross": JoinType.CROSS,
        }[match.group(1).lower()]
