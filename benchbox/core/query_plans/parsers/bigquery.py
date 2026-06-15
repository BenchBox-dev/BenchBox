"""BigQuery query plan parser.

Unlike EXPLAIN-based engines, BigQuery exposes no ``EXPLAIN`` statement: the
query plan is only available *after* execution, from the completed
``google.cloud.bigquery.QueryJob`` via its ``job.query_plan`` job-statistics
field. ``BigQueryAdapter._capture_bq_plan`` reads that already-executed job (no
extra API call, no extra billing), serializes the per-stage statistics to JSON,
and hands the JSON to this parser.

The serialized payload is a JSON list of *stage* objects, one per
``QueryPlanEntry``::

    [
      {"id": 0, "name": "S00: Input", "status": "COMPLETE",
       "records_read": 6000000, "records_written": 6000000, "input_stages": [],
       "steps": [{"kind": "READ", "substeps": ["$1:l_orderkey", "FROM lineitem"]},
                 {"kind": "AGGREGATE", "substeps": ["GROUP BY $10 := $1"]},
                 {"kind": "WRITE", "substeps": ["$10, $20", "TO __stage00_output"]}]},
      {"id": 1, "name": "S01: Output", "input_stages": [0],
       "steps": [{"kind": "READ", ...}, {"kind": "SORT", ...}, {"kind": "WRITE", ...}]}
    ]

A stage's children are the stages named in its ``input_stages`` list; the root
is the stage no other stage reads from (typically ``Output``). Each stage's
dominant operator type is inferred from its ``steps[].kind`` values (READ →
Scan, JOIN/HASH_JOIN → Join, AGGREGATE → Aggregate, SORT → Sort, ...), falling
back to the stage ``name``.

See the BigQuery ``Job.queryPlan`` / ``ExplainQueryStage`` reference for the
field meanings.
"""

from __future__ import annotations

import json
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


class BigQueryQueryPlanParser(QueryPlanParser):
    """Parser for the JSON-serialized BigQuery ``job.query_plan`` structure."""

    # Step ``kind`` -> logical type. Ordered by structural dominance: a stage
    # that joins is a Join even though it also READs and WRITEs.
    _STEP_KIND_PRIORITY: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("join", LogicalOperatorType.JOIN),
        ("aggregate", LogicalOperatorType.AGGREGATE),
        ("analytic", LogicalOperatorType.WINDOW),
        ("sort", LogicalOperatorType.SORT),
        ("limit", LogicalOperatorType.LIMIT),
        ("filter", LogicalOperatorType.FILTER),
        ("read", LogicalOperatorType.SCAN),
        ("write", LogicalOperatorType.PROJECT),
        ("compute", LogicalOperatorType.PROJECT),
    )

    # Fallback mapping from the stage ``name`` keywords (e.g. "S01: Output").
    _NAME_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("input", LogicalOperatorType.SCAN),
        ("join", LogicalOperatorType.JOIN),
        ("aggregate", LogicalOperatorType.AGGREGATE),
        ("sort", LogicalOperatorType.SORT),
        ("limit", LogicalOperatorType.LIMIT),
        ("output", LogicalOperatorType.PROJECT),
        ("repartition", LogicalOperatorType.OTHER),
        ("coalesce", LogicalOperatorType.OTHER),
    )

    def __init__(self):
        super().__init__("bigquery")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty query plan payload")

        try:
            stages = json.loads(explain_output)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Query plan payload is not valid JSON: {exc}") from exc

        if not isinstance(stages, list) or not stages:
            raise ValueError("BigQuery query plan must be a non-empty list of stages")

        by_id: dict[Any, dict[str, Any]] = {}
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                continue
            stage_id = stage.get("id", index)
            by_id[stage_id] = stage

        if not by_id:
            raise ValueError("No stage objects found in BigQuery query plan")

        # A stage is a child of every stage that lists it in input_stages.
        referenced: set[Any] = set()
        for stage in by_id.values():
            for src in self._input_ids(stage):
                if src in by_id:
                    referenced.add(src)

        roots = [sid for sid in by_id if sid not in referenced]
        if not roots:
            roots = [max(by_id)]  # fall back to the highest-id (last) stage

        def build(stage_id: Any, visited: frozenset[Any]) -> LogicalOperator:
            stage = by_id[stage_id]
            children = [
                build(src, visited | {stage_id})
                for src in self._input_ids(stage)
                if src in by_id and src not in visited
            ]
            return self._convert_stage(stage, children)

        # Highest-id root is the conventional Output stage; keep deterministic order.
        root_id = sorted(roots, key=self._sort_key, reverse=True)[0]
        root = build(root_id, frozenset())

        estimated_rows = None
        root_stage = by_id[root_id]
        written = self._coerce_int(root_stage.get("records_written"))
        if written is not None:
            estimated_rows = written

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            estimated_rows=estimated_rows,
            raw_explain_output=explain_output,
        )

    def _convert_stage(self, stage: dict[str, Any], children: list[LogicalOperator]) -> LogicalOperator:
        name = str(stage.get("name", "")).strip()
        steps = stage.get("steps") if isinstance(stage.get("steps"), list) else []
        kinds = [str(s.get("kind", "")).strip() for s in steps if isinstance(s, dict)]
        logical_type = self._map_stage_type(name, kinds)

        substeps: list[str] = []
        for step in steps:
            if isinstance(step, dict):
                substeps.extend(str(x).strip() for x in (step.get("substeps") or []) if str(x).strip())

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN:
            table = self._extract_table(substeps)
            if table:
                kwargs["table_name"] = table

        properties: dict[str, Any] = {}
        for key in ("records_read", "records_written"):
            value = self._coerce_int(stage.get(key))
            if value is not None:
                properties[key] = value

        physical_op = self._create_physical_operator(
            name or "Stage",
            properties=properties,
            platform_metadata={
                "stage_id": stage.get("id"),
                "status": stage.get("status"),
                "step_kinds": kinds or None,
                "substeps": substeps or None,
            },
        )

        return self._create_logical_operator(
            operator_type=logical_type,
            children=children,
            physical_operator=physical_op,
            **kwargs,
        )

    @classmethod
    def _map_stage_type(cls, name: str, kinds: list[str]) -> LogicalOperatorType:
        normalized_kinds = [k.lower().replace(" ", "").replace("_", "") for k in kinds]
        for keyword, logical_type in cls._STEP_KIND_PRIORITY:
            if any(keyword in k for k in normalized_kinds):
                return logical_type
        normalized_name = name.lower()
        for keyword, logical_type in cls._NAME_KEYWORDS:
            if keyword in normalized_name:
                return logical_type
        return LogicalOperatorType.OTHER

    @staticmethod
    def _extract_table(substeps: list[str]) -> str | None:
        for sub in substeps:
            match = re.search(r"FROM\s+([\w.$-]+)", sub, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _input_ids(stage: dict[str, Any]) -> list[Any]:
        inputs = stage.get("input_stages")
        if inputs is None:
            return []
        if not isinstance(inputs, list):
            inputs = [inputs]
        return list(inputs)

    @staticmethod
    def _sort_key(stage_id: Any) -> tuple[int, str]:
        text = str(stage_id)
        return (int(text), "") if text.lstrip("-").isdigit() else (1 << 30, text)

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
