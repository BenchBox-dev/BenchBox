"""BigQuery query plan parser.

BigQuery has no ``EXPLAIN`` statement; the execution plan is only available
*after* a query runs, from the Job Statistics API as
``job.query_plan`` — a list of ``QueryPlanEntry`` (stage) objects. The
:class:`benchbox.platforms.bigquery.BigQueryAdapter` serializes that list to JSON
and hands it to this parser (see ``BigQueryAdapter._capture_bq_plan``); this
parser therefore consumes the JSON of the stage list, not EXPLAIN text.

Each stage entry (camelCase as emitted by the REST API / ``to_api_repr``)
carries::

    {
      "name": "S00: Input",
      "id": "0",
      "steps": [{"kind": "READ", "substeps": ["$1:o_orderkey", "FROM orders"]}],
      "recordsRead": "150000",
      "recordsWritten": "150000",
      "status": "COMPLETE",
      "inputStages": []
    }

Stages form a DAG via ``inputStages`` (the ids of the stages that feed into this
one — i.e. its children). The root is the terminal stage that no other stage
reads from (typically the ``Output`` stage). Operator type is derived from the
stage ``name`` (after stripping the ``Snn:`` prefix), falling back to the
``kind`` of the stage's steps.
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

_STAGE_PREFIX_RE = re.compile(r"^S\d+:\s*", re.IGNORECASE)


class BigQueryQueryPlanParser(QueryPlanParser):
    """Parser for BigQuery ``job.query_plan`` stage lists (JSON-serialized)."""

    # Ordered (substring, type) pairs matched against the lower-cased stage name
    # (and step kinds); first match wins, so specific names precede generic ones.
    _OPERATOR_KEYWORDS: tuple[tuple[str, LogicalOperatorType], ...] = (
        ("join", LogicalOperatorType.JOIN),
        ("aggregate", LogicalOperatorType.AGGREGATE),
        ("sort", LogicalOperatorType.SORT),
        ("orderby", LogicalOperatorType.SORT),
        ("limit", LogicalOperatorType.LIMIT),
        ("filter", LogicalOperatorType.FILTER),
        ("input", LogicalOperatorType.SCAN),
        ("read", LogicalOperatorType.SCAN),
        ("output", LogicalOperatorType.PROJECT),
        ("write", LogicalOperatorType.PROJECT),
        ("compute", LogicalOperatorType.PROJECT),
        ("project", LogicalOperatorType.PROJECT),
        ("union", LogicalOperatorType.UNION),
        ("analytic", LogicalOperatorType.WINDOW),
        ("window", LogicalOperatorType.WINDOW),
    )

    def __init__(self):
        super().__init__("bigquery")

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        if not explain_output or not explain_output.strip():
            raise ValueError("Empty query plan")

        try:
            payload = json.loads(explain_output)
        except json.JSONDecodeError as exc:
            raise ValueError(f"BigQuery query plan is not valid JSON: {exc}") from exc

        stages = self._extract_stages(payload)
        if not stages:
            raise ValueError("No stages found in BigQuery query plan")

        by_id = {self._stage_id(stage): stage for stage in stages}
        root_id = self._find_root_id(stages, by_id)
        root = self._build_operator(by_id[root_id], by_id, visited=set())

        return QueryPlanDAG(
            query_id=query_id,
            platform=self.platform_name,
            logical_root=root,
            raw_explain_output=explain_output,
        )

    @staticmethod
    def _extract_stages(payload: Any) -> list[dict[str, Any]]:
        """Accept either a bare stage list or a ``{"queryPlan": [...]}`` wrapper."""
        if isinstance(payload, dict):
            payload = payload.get("queryPlan") or payload.get("query_plan") or []
        if not isinstance(payload, list):
            return []
        return [stage for stage in payload if isinstance(stage, dict)]

    @staticmethod
    def _stage_id(stage: dict[str, Any]) -> str:
        return str(stage.get("id", stage.get("name", "")))

    @classmethod
    def _input_ids(cls, stage: dict[str, Any]) -> list[str]:
        inputs = stage.get("inputStages")
        if inputs is None:
            inputs = stage.get("input_stages")
        if inputs is None:
            return []
        if not isinstance(inputs, list):
            inputs = [inputs]
        return [str(item) for item in inputs]

    def _find_root_id(self, stages: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> str:
        """The root is the terminal stage no other stage reads from.

        A plan can expose more than one unreferenced stage (e.g. a trailing
        no-op/repartition stage alongside the real Output stage), so the root is
        chosen as the unreferenced stage whose subtree reaches the most stages,
        falling back to the highest stage id on a tie. This avoids rooting the
        DAG at a dangling stage and silently dropping the real result subtree.
        """
        referenced: set[str] = set()
        for stage in stages:
            referenced.update(self._input_ids(stage))
        roots = [self._stage_id(stage) for stage in stages if self._stage_id(stage) not in referenced]
        if not roots:
            # Cyclic / self-referential plan: fall back to the highest-id stage.
            return max(by_id, key=self._numeric_sort_key)
        if len(roots) == 1:
            return roots[0]
        return max(roots, key=lambda rid: (self._reachable_count(rid, by_id), self._numeric_sort_key(rid)))

    def _reachable_count(self, stage_id: str, by_id: dict[str, dict[str, Any]]) -> int:
        """Number of stages reachable from ``stage_id`` via ``inputStages``."""
        seen: set[str] = set()
        stack = [stage_id]
        while stack:
            current = stack.pop()
            if current in seen or current not in by_id:
                continue
            seen.add(current)
            stack.extend(self._input_ids(by_id[current]))
        return len(seen)

    @staticmethod
    def _numeric_sort_key(stage_id: str) -> tuple[int, str]:
        digits = re.findall(r"\d+", stage_id)
        return (int(digits[0]), stage_id) if digits else (1 << 30, stage_id)

    def _build_operator(
        self,
        stage: dict[str, Any],
        by_id: dict[str, dict[str, Any]],
        visited: set[str],
    ) -> LogicalOperator:
        stage_id = self._stage_id(stage)
        visited = visited | {stage_id}

        child_ids = [cid for cid in self._input_ids(stage) if cid in by_id and cid not in visited]
        child_ids.sort(key=self._numeric_sort_key)
        children = [self._build_operator(by_id[cid], by_id, visited) for cid in child_ids]

        name = _STAGE_PREFIX_RE.sub("", str(stage.get("name", ""))).strip()
        substeps = self._collect_substeps(stage)
        logical_type = self._map_operator_type(name, stage)

        kwargs: dict[str, Any] = {}
        if logical_type == LogicalOperatorType.SCAN:
            table = self._extract_table(substeps)
            if table:
                kwargs["table_name"] = table
        elif logical_type == LogicalOperatorType.JOIN:
            kwargs["join_type"] = self._classify_join_type(name, substeps)

        physical_op = self._create_physical_operator(
            name or "Unknown",
            properties=self._stage_metrics(stage),
            platform_metadata={
                "stage_id": stage.get("id"),
                "status": stage.get("status"),
                "substeps": substeps or None,
            },
        )

        return self._create_logical_operator(
            operator_type=logical_type,
            children=children,
            physical_operator=physical_op,
            **kwargs,
        )

    @staticmethod
    def _collect_substeps(stage: dict[str, Any]) -> list[str]:
        steps = stage.get("steps")
        substeps: list[str] = []
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                kind = str(step.get("kind", "")).strip()
                items = step.get("substeps")
                if isinstance(items, list):
                    for item in items:
                        text = str(item).strip()
                        if text:
                            substeps.append(f"{kind}: {text}" if kind else text)
                elif kind:
                    substeps.append(kind)
        return substeps

    @classmethod
    def _map_operator_type(cls, name: str, stage: dict[str, Any]) -> LogicalOperatorType:
        normalized = name.lower().replace(" ", "").replace("_", "")
        for keyword, logical_type in cls._OPERATOR_KEYWORDS:
            if keyword in normalized:
                return logical_type
        # Fall back to the kinds of the stage's steps (e.g. READ / AGGREGATE / JOIN).
        steps = stage.get("steps")
        if isinstance(steps, list):
            kinds = (
                " ".join(str(step.get("kind", "")) for step in steps if isinstance(step, dict)).lower().replace("_", "")
            )
            for keyword, logical_type in cls._OPERATOR_KEYWORDS:
                if keyword in kinds:
                    return logical_type
        return LogicalOperatorType.OTHER

    @staticmethod
    def _extract_table(substeps: list[str]) -> str | None:
        for step in substeps:
            match = re.search(r"FROM\s+([\w$.`-]+)", step, re.IGNORECASE)
            if match:
                return match.group(1).strip("`")
        return None

    @staticmethod
    def _classify_join_type(name: str, substeps: list[str]) -> JoinType:
        haystack = (name + " " + " ".join(substeps)).lower()
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

    @staticmethod
    def _stage_metrics(stage: dict[str, Any]) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for json_key, prop in (
            ("recordsRead", "records_read"),
            ("records_read", "records_read"),
            ("recordsWritten", "records_written"),
            ("records_written", "records_written"),
        ):
            value = stage.get(json_key)
            if value is not None and prop not in metrics:
                try:
                    metrics[prop] = int(value)
                except (TypeError, ValueError):
                    metrics[prop] = value
        return metrics
