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


class PostgreSQLQueryPlanParser(QueryPlanParser):
    NODE_TYPE_MAP = {
        "Seq Scan": LogicalOperatorType.SCAN,
        "Index Scan": LogicalOperatorType.SCAN,
        "Index Only Scan": LogicalOperatorType.SCAN,
        "Bitmap Heap Scan": LogicalOperatorType.SCAN,
        "Bitmap Index Scan": LogicalOperatorType.SCAN,
        "Tid Scan": LogicalOperatorType.SCAN,
        "Foreign Scan": LogicalOperatorType.SCAN,
        "Custom Scan": LogicalOperatorType.SCAN,
        "Sample Scan": LogicalOperatorType.SCAN,
        "Function Scan": LogicalOperatorType.SCAN,
        "Table Function Scan": LogicalOperatorType.SCAN,
        "Values Scan": LogicalOperatorType.SCAN,
        "Named Tuplestore Scan": LogicalOperatorType.SCAN,
        "WorkTable Scan": LogicalOperatorType.SCAN,
        "Subquery Scan": LogicalOperatorType.SUBQUERY,
        "Nested Loop": LogicalOperatorType.JOIN,
        "Hash Join": LogicalOperatorType.JOIN,
        "Merge Join": LogicalOperatorType.JOIN,
        "Aggregate": LogicalOperatorType.AGGREGATE,
        "HashAggregate": LogicalOperatorType.AGGREGATE,
        "GroupAggregate": LogicalOperatorType.AGGREGATE,
        "Mixed Aggregate": LogicalOperatorType.AGGREGATE,
        "Sort": LogicalOperatorType.SORT,
        "Incremental Sort": LogicalOperatorType.SORT,
        "Limit": LogicalOperatorType.LIMIT,
        "Result": LogicalOperatorType.PROJECT,
        "ProjectSet": LogicalOperatorType.PROJECT,
        "Append": LogicalOperatorType.UNION,
        "MergeAppend": LogicalOperatorType.UNION,
        "SetOp": LogicalOperatorType.OTHER,
        "Recursive Union": LogicalOperatorType.UNION,
        "WindowAgg": LogicalOperatorType.WINDOW,
        "CTE Scan": LogicalOperatorType.CTE,
        "Materialize": LogicalOperatorType.OTHER,
        "Unique": LogicalOperatorType.OTHER,
        "Hash": LogicalOperatorType.OTHER,
        "Gather": LogicalOperatorType.OTHER,
        "Gather Merge": LogicalOperatorType.OTHER,
        "BitmapAnd": LogicalOperatorType.OTHER,
        "BitmapOr": LogicalOperatorType.OTHER,
        "LockRows": LogicalOperatorType.OTHER,
        "ModifyTable": LogicalOperatorType.OTHER,
    }

    JOIN_TYPE_MAP = {
        "Inner": JoinType.INNER,
        "Left": JoinType.LEFT,
        "Right": JoinType.RIGHT,
        "Full": JoinType.FULL,
        "Semi": JoinType.SEMI,
        "Anti": JoinType.ANTI,
    }

    def __init__(self):
        super().__init__("postgresql")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty EXPLAIN output")

        try:
            data = json.loads(explain_output)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in EXPLAIN output: {e}") from e

        if not isinstance(data, list) or len(data) == 0:
            raise ValueError("Expected array with plan data")

        plan_wrapper = data[0]
        if "Plan" not in plan_wrapper:
            raise ValueError("No 'Plan' key in EXPLAIN output")

        plan_data = plan_wrapper["Plan"]

        root = self._parse_plan_node(plan_data)

        estimated_cost = plan_data.get("Total Cost")
        estimated_rows = plan_data.get("Plan Rows")
        if estimated_rows is not None:
            estimated_rows = int(estimated_rows)

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            estimated_cost=estimated_cost,
            estimated_rows=estimated_rows,
            raw_explain_output=explain_output,
        )

    def _parse_plan_node(self, node: dict[str, Any]) -> LogicalOperator:
        node_type = node.get("Node Type", "Unknown")

        logical_type = self.NODE_TYPE_MAP.get(node_type, LogicalOperatorType.OTHER)
        if logical_type == LogicalOperatorType.OTHER and node_type not in self.NODE_TYPE_MAP:
            logger.debug("Unknown PostgreSQL node type '%s', mapping to OTHER", node_type)

        children = []
        if "Plans" in node:
            for child_node in node["Plans"]:
                children.append(self._parse_plan_node(child_node))

        kwargs = self._extract_operator_specific_info(node, node_type, logical_type)

        properties = {
            "startup_cost": node.get("Startup Cost"),
            "total_cost": node.get("Total Cost"),
            "plan_rows": node.get("Plan Rows"),
            "plan_width": node.get("Plan Width"),
            "actual_rows": node.get("Actual Rows"),
            "actual_loops": node.get("Actual Loops"),
            "actual_time": node.get("Actual Total Time"),
        }
        properties = {k: v for k, v in properties.items() if v is not None}

        physical_op = self._create_physical_operator(
            node_type,
            properties=properties,
            platform_metadata={
                "alias": node.get("Alias"),
                "schema": node.get("Schema"),
                "parallel_aware": node.get("Parallel Aware"),
                "workers_planned": node.get("Workers Planned"),
                "workers_launched": node.get("Workers Launched"),
            },
        )

        return self._create_logical_operator(
            operator_type=logical_type,
            children=children,
            physical_operator=physical_op,
            properties=properties,
            **kwargs,
        )

    def _extract_operator_specific_info(
        self, node: dict[str, Any], node_type: str, logical_type: LogicalOperatorType
    ) -> dict[str, Any]:
        _extractors = {
            LogicalOperatorType.SCAN: self._extract_scan_info,
            LogicalOperatorType.JOIN: self._extract_join_info,
            LogicalOperatorType.AGGREGATE: self._extract_aggregate_info,
            LogicalOperatorType.SORT: self._extract_sort_info,
        }

        extractor = _extractors.get(logical_type)
        kwargs = extractor(node) if extractor else {}

        filter_expr = node.get("Filter")
        if filter_expr:
            kwargs["filter_expressions"] = [filter_expr]

        output = node.get("Output")
        if output:
            kwargs["projection_expressions"] = output if isinstance(output, list) else [output]

        return kwargs

    @staticmethod
    def _extract_scan_info(node: dict[str, Any]) -> dict[str, Any]:
        table_name = node.get("Relation Name")
        return {"table_name": table_name} if table_name else {}

    def _extract_join_info(self, node: dict[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        join_type_str = node.get("Join Type", "Inner")
        kwargs["join_type"] = self.JOIN_TYPE_MAP.get(join_type_str, JoinType.INNER)

        conditions = [v for k in ("Join Filter", "Hash Cond", "Merge Cond") if (v := node.get(k))]
        if conditions:
            kwargs["join_conditions"] = conditions
        return kwargs

    @staticmethod
    def _extract_aggregate_info(node: dict[str, Any]) -> dict[str, Any]:
        group_key = node.get("Group Key")
        if group_key:
            return {"group_by_keys": group_key if isinstance(group_key, list) else [group_key]}
        return {}

    @staticmethod
    def _extract_sort_info(node: dict[str, Any]) -> dict[str, Any]:
        sort_key = node.get("Sort Key")
        if not sort_key:
            return {}
        sort_keys = []
        for key in sort_key if isinstance(sort_key, list) else [sort_key]:
            direction = "DESC" if " DESC" in key else "ASC"
            expr = (
                key.replace(" DESC", "")
                .replace(" ASC", "")
                .replace(" NULLS FIRST", "")
                .replace(" NULLS LAST", "")
                .strip()
            )
            sort_keys.append({"expr": expr, "direction": direction})
        return {"sort_keys": sort_keys}
