"""Azure Synapse (Dedicated SQL Pool) query plan parser.

Azure Synapse Dedicated SQL Pool answers ``EXPLAIN <query>`` with a *distributed*
query plan rendered as a single XML document (the same ``<dsql_query>`` shape
inherited from Parallel Data Warehouse / APS). The plan is a sequence of
distributed operations — data-movement steps (SHUFFLE_MOVE, BROADCAST_MOVE,
PARTITION_MOVE, TRIM_MOVE), per-node operations (ON), temp-id allocations
(RND_ID), and a final RETURN — rather than a tree of relational operators::

    <?xml version="1.0" encoding="utf-8"?>
    <dsql_query number_nodes="1" number_distributions="60">
      <sql>SELECT ...</sql>
      <dsql_operations total_cost="1.23" total_number_operations="4">
        <dsql_operation operation_type="RND_ID">
          <identifier>TEMP_ID_3</identifier>
        </dsql_operation>
        <dsql_operation operation_type="ON">
          <location permanent="false" distribution="AllComputeNodes" />
          <sql_operations>
            <sql_operation type="statement">CREATE TABLE ...</sql_operation>
          </sql_operations>
        </dsql_operation>
        <dsql_operation operation_type="SHUFFLE_MOVE">
          <operation_cost cost="1.0" output_rows="100" average_rowsize="20" />
          <location distribution="AllDistributions" />
          <source_statement>SELECT ...</source_statement>
          <destination_table>TEMP_ID_3</destination_table>
          <shuffle_columns>l_orderkey;</shuffle_columns>
        </dsql_operation>
        <dsql_operation operation_type="RETURN">
          <location distribution="AllDistributions" />
          <select>SELECT ...</select>
        </dsql_operation>
      </dsql_operations>
    </dsql_query>

Because the distributed plan is a linear pipeline, this parser models it as a
chain: the final RETURN operation is the root and each preceding operation is
nested as its single child, preserving execution order in the tree depth.

.. note::
   Synapse *Serverless* SQL Pool uses a different planner and does not emit this
   ``<dsql_query>`` format. Per the gating open question on the source TODO, this
   parser targets the Dedicated Pool EXPLAIN format that the adapter retrieves
   today; a Serverless variant is deferred pending a live fixture.
"""

from __future__ import annotations

import logging
from typing import Any
from xml.etree import ElementTree as ET

from benchbox.core.query_plans.parsers.base import QueryPlanParser
from benchbox.core.results.query_plan_models import (
    LogicalOperator,
    LogicalOperatorType,
    QueryPlanDAG,
)

logger = logging.getLogger(__name__)


class AzureSynapseQueryPlanParser(QueryPlanParser):
    """Parser for Azure Synapse Dedicated Pool ``EXPLAIN`` (dsql XML) output."""

    # Distributed operation type -> logical type. Data-movement and control
    # operations have no relational analogue, so they map to OTHER; RETURN is the
    # result-producing step and maps to PROJECT.
    _OPERATION_MAP: dict[str, LogicalOperatorType] = {
        "RETURN": LogicalOperatorType.PROJECT,
        "SHUFFLE_MOVE": LogicalOperatorType.OTHER,
        "BROADCAST_MOVE": LogicalOperatorType.OTHER,
        "PARTITION_MOVE": LogicalOperatorType.OTHER,
        "TRIM_MOVE": LogicalOperatorType.OTHER,
        "MOVE": LogicalOperatorType.OTHER,
        "COPY": LogicalOperatorType.OTHER,
        "ON": LogicalOperatorType.OTHER,
        "RND_ID": LogicalOperatorType.OTHER,
    }

    def __init__(self):
        super().__init__("azure_synapse")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")

        text = explain_output.strip()
        # The cursor sometimes prefixes a header row; trim to the XML document.
        start = text.find("<")
        if start == -1:
            raise ValueError("Azure Synapse EXPLAIN output is not XML")
        text = text[start:]

        try:
            root_el = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ValueError(f"EXPLAIN output is not valid dsql XML: {exc}") from exc

        operations_el = root_el.find("dsql_operations")
        if operations_el is None and root_el.tag == "dsql_operations":
            operations_el = root_el
        if operations_el is None:
            raise ValueError("No <dsql_operations> element in Synapse EXPLAIN XML")

        op_elements = operations_el.findall("dsql_operation")
        if not op_elements:
            raise ValueError("No <dsql_operation> elements in Synapse EXPLAIN XML")

        # Build a linear chain with the LAST operation (RETURN) at the root.
        nodes = [self._convert_operation(op) for op in op_elements]
        root = nodes[-1]
        current = root
        for node in reversed(nodes[:-1]):
            current.children.append(node)
            current = node

        estimated_cost = self._coerce_float(operations_el.get("total_cost"))
        estimated_rows = self._max_output_rows(op_elements)

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            estimated_cost=estimated_cost,
            estimated_rows=estimated_rows,
            raw_explain_output=explain_output,
        )

    def _convert_operation(self, op_el: ET.Element) -> LogicalOperator:
        op_type = (op_el.get("operation_type") or "").strip().upper()
        logical_type = self._OPERATION_MAP.get(op_type, LogicalOperatorType.OTHER)

        properties: dict[str, Any] = {}
        cost_el = op_el.find("operation_cost")
        if cost_el is not None:
            for attr in ("cost", "output_rows", "average_rowsize"):
                value = cost_el.get(attr)
                if value is not None:
                    properties[attr] = value

        location_el = op_el.find("location")
        distribution = location_el.get("distribution") if location_el is not None else None

        # Capture the SQL text carried by the operation, when present.
        sql_text = None
        for tag in ("source_statement", "select", "sql_operations"):
            child = op_el.find(tag)
            if child is not None:
                if tag == "sql_operations":
                    stmts = [
                        (s.text or "").strip()
                        for s in child.findall("sql_operation")
                        if (s.text or "").strip()
                    ]
                    sql_text = " | ".join(stmts) if stmts else None
                else:
                    sql_text = (child.text or "").strip() or None
                if sql_text:
                    break

        physical_op = self._create_physical_operator(
            op_type or "Operation",
            properties=properties,
            platform_metadata={
                "operation_type": op_type or None,
                "distribution": distribution,
                "sql": sql_text,
            },
        )

        return self._create_logical_operator(
            operator_type=logical_type,
            children=[],
            physical_operator=physical_op,
        )

    def _max_output_rows(self, op_elements: list[ET.Element]) -> int | None:
        best: int | None = None
        for op_el in op_elements:
            cost_el = op_el.find("operation_cost")
            if cost_el is None:
                continue
            rows = self._coerce_int(cost_el.get("output_rows"))
            if rows is not None and (best is None or rows > best):
                best = rows
        return best

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
