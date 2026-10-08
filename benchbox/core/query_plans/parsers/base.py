from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, TypeVar

from benchbox.core.errors import PlanParseError
from benchbox.core.results.query_plan_models import (
    JoinType,
    LogicalOperator,
    LogicalOperatorType,
    PhysicalOperator,
    QueryPlanDAG,
    validate_plan_tree,
)

logger = logging.getLogger(__name__)


_ESTIMATE_KEY_SUBSTRINGS: tuple[str, ...] = (
    "cardinality",
    "estimated",
    "cost",
    "selectivity",
)

_ESTIMATE_KEY_EXACT: frozenset[str] = frozenset(
    {
        "rows",
        "ec",
        "output_rows",
        "row_count",
        "num_rows",
        "plan_rows",
        "output_bytes",
        "output_batches",
    }
)

_METRICS_BLOCK_RE = re.compile(r",?\s*metrics=\[.*\]", re.IGNORECASE)

_COST_PAREN_RE = re.compile(
    r"\s*\(\s*cost=[\d.]+\.\.[\d.]+(?:\s+rows=\d+)?(?:\s+width=\d+)?\s*\)",
    re.IGNORECASE,
)

_INLINE_ESTIMATE_RE = re.compile(
    r"""
    (?:
        (?:estimated\s+cardinality | estimated\s+cost | estimated\s+rows)
        \s*[:=]\s*\d[\d.,]*%?
        | \bEC:\s*\d[\d.,]*%?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

T = TypeVar("T")


def _key_is_estimate(key: str) -> bool:
    normalized = str(key).strip().lower()
    if normalized in _ESTIMATE_KEY_EXACT:
        return True
    return any(token in normalized for token in _ESTIMATE_KEY_SUBSTRINGS)


def strip_estimate_keys(mapping: Mapping[str, T]) -> dict[str, T]:
    return {key: value for key, value in mapping.items() if not _key_is_estimate(key)}


def strip_estimates(text: str) -> str:
    if not text:
        return text
    cleaned = _METRICS_BLOCK_RE.sub("", text)
    sentinel = "\x00EMPTYBRACKET\x00"
    masked_original = re.sub(r"\[\s*\]", sentinel, text)
    masked = re.sub(r"\[\s*\]", sentinel, cleaned)
    cleaned = _COST_PAREN_RE.sub("", masked)
    cleaned = _INLINE_ESTIMATE_RE.sub("", cleaned)
    if cleaned != masked_original:
        cleaned = re.sub(r"\[\s*\]", "", cleaned)
        cleaned = re.sub(r"\s*,\s*(?=,|$)", "", cleaned)
        cleaned = re.sub(r",\s*$", "", cleaned)
    cleaned = cleaned.replace(sentinel, "[]")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip().strip(",").strip()


class QueryPlanParser(ABC):
    def __init__(self, platform_name: str):
        self.platform_name = platform_name
        self._operator_id_counter = 0

    def parse_explain_output(self, query_id: str, explain_output: str) -> QueryPlanDAG | None:
        self._operator_id_counter = 0

        self._current_explain_output = explain_output
        self._current_query_id = query_id

        try:
            plan = self._parse_impl(query_id, explain_output)

            if plan and plan.logical_root:
                validation_errors = validate_plan_tree(plan.logical_root)
                if validation_errors:
                    logger.warning(
                        "Plan validation warnings for %s: %s",
                        query_id,
                        "; ".join(validation_errors),
                    )

            return plan
        except PlanParseError:
            raise
        except Exception as e:
            detected_format = self._detect_explain_format(explain_output)
            recovery_hint = self._get_recovery_hint(detected_format, str(e))

            error = PlanParseError(
                query_id=query_id,
                platform=self.platform_name,
                error_message=str(e),
                explain_sample=self._get_explain_sample(),
                detected_format=detected_format,
                recovery_hint=recovery_hint,
            )
            logger.warning("Failed to parse query plan: %s", error)
            return None

    def _detect_explain_format(self, explain_output: str) -> str:
        if not explain_output:
            return "empty"

        stripped = explain_output.strip()
        if not stripped:
            return "empty"

        if stripped.startswith("{") or stripped.startswith("["):
            return "json"

        if stripped.startswith("<?xml") or stripped.startswith("<"):
            return "xml"

        if any(char in stripped for char in "┌┐└┘│─├┤┬┴┼"):
            return "text-box"

        if any(keyword in stripped.lower() for keyword in ["->", "seq scan", "index scan", "hash join", "sort"]):
            return "text-tree"

        return "unknown"

    def _get_recovery_hint(self, detected_format: str, error_message: str) -> str | None:
        hints = {
            "empty": "EXPLAIN output is empty. Check if the query executed successfully.",
            "unknown": f"Unknown EXPLAIN format for {self.platform_name}. Ensure EXPLAIN was run correctly.",
            "xml": "XML format detected. This parser may not support XML EXPLAIN output.",
        }

        if detected_format in hints:
            return hints[detected_format]

        error_lower = error_message.lower()
        if "json" in error_lower or "decode" in error_lower:
            return "JSON parsing failed. Check that the EXPLAIN output is valid JSON."
        if "no operators" in error_lower:
            return "No plan operators found. The EXPLAIN output may be truncated or in an unexpected format."

        return None

    def _get_explain_sample(self, max_length: int = 500) -> str | None:
        if not hasattr(self, "_current_explain_output") or not self._current_explain_output:
            return None
        output = self._current_explain_output
        if len(output) > max_length:
            return output[:max_length] + "..."
        return output

    @abstractmethod
    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        raise NotImplementedError

    def _generate_operator_id(self, operator_type: str) -> str:
        self._operator_id_counter += 1
        normalized = re.sub(r"[^a-z0-9]+", "_", operator_type.lower())
        return f"{normalized}_{self._operator_id_counter}"

    def _harmonize_join_type(self, native_join_type: str) -> JoinType:
        normalized = native_join_type.lower().strip()

        if "inner" in normalized:
            return JoinType.INNER
        elif "left" in normalized or "left outer" in normalized:
            return JoinType.LEFT
        elif "right" in normalized or "right outer" in normalized:
            return JoinType.RIGHT
        elif "full" in normalized or "full outer" in normalized:
            return JoinType.FULL
        elif "cross" in normalized:
            return JoinType.CROSS
        elif "semi" in normalized:
            return JoinType.SEMI
        elif "anti" in normalized:
            return JoinType.ANTI
        else:
            logger.debug("Unknown join type '%s', defaulting to INNER", native_join_type)
            return JoinType.INNER

    def _harmonize_operator_type(self, native_operator: str) -> LogicalOperatorType:
        normalized = native_operator.lower().strip()

        if any(keyword in normalized for keyword in ["scan", "seq scan", "index scan", "bitmap scan", "table scan"]):
            return LogicalOperatorType.SCAN

        if any(keyword in normalized for keyword in ["filter", "selection", "predicate"]):
            return LogicalOperatorType.FILTER

        if any(keyword in normalized for keyword in ["join", "nested loop", "hash join", "merge join"]):
            return LogicalOperatorType.JOIN

        if any(keyword in normalized for keyword in ["aggregate", "group", "hash aggregate", "group by"]):
            return LogicalOperatorType.AGGREGATE

        if any(keyword in normalized for keyword in ["sort", "order by"]):
            return LogicalOperatorType.SORT

        if any(keyword in normalized for keyword in ["limit", "top", "fetch"]):
            return LogicalOperatorType.LIMIT

        if any(keyword in normalized for keyword in ["project", "projection", "select", "compute"]):
            return LogicalOperatorType.PROJECT

        if "union" in normalized:
            return LogicalOperatorType.UNION

        if "intersect" in normalized:
            return LogicalOperatorType.INTERSECT

        if any(keyword in normalized for keyword in ["except", "minus"]):
            return LogicalOperatorType.EXCEPT

        if "window" in normalized:
            return LogicalOperatorType.WINDOW

        if any(keyword in normalized for keyword in ["cte", "with", "materialized"]):
            return LogicalOperatorType.CTE

        if "subquery" in normalized or "subplan" in normalized:
            return LogicalOperatorType.SUBQUERY

        logger.debug("Unknown operator type '%s', categorized as OTHER", native_operator)
        return LogicalOperatorType.OTHER

    def _extract_table_name(self, operator_details: dict[str, Any]) -> str | None:
        for key in ["table", "table_name", "relation", "relation_name", "object_name"]:
            if key in operator_details:
                return str(operator_details[key])
        return None

    def _extract_cost_estimates(self, operator_details: dict[str, Any]) -> tuple[float | None, int | None]:
        cost = None
        rows = None

        for key in ["cost", "total_cost", "estimated_cost", "plan_cost"]:
            if key in operator_details:
                try:
                    cost = float(operator_details[key])
                    break
                except (ValueError, TypeError):
                    pass

        for key in ["rows", "estimated_rows", "row_count", "plan_rows", "cardinality"]:
            if key in operator_details:
                try:
                    rows = int(operator_details[key])
                    break
                except (ValueError, TypeError):
                    pass

        return cost, rows

    def _create_physical_operator(
        self,
        native_operator_type: str,
        properties: dict[str, Any] | None = None,
        platform_metadata: dict[str, Any] | None = None,
    ) -> PhysicalOperator:
        return PhysicalOperator(
            operator_type=native_operator_type,
            operator_id=self._generate_operator_id(native_operator_type),
            properties=properties or {},
            platform_metadata=platform_metadata or {},
        )

    def _create_logical_operator(
        self,
        operator_type: LogicalOperatorType,
        children: list[LogicalOperator] | None = None,
        physical_operator: PhysicalOperator | None = None,
        **kwargs: Any,
    ) -> LogicalOperator:
        operator_id = self._generate_operator_id(operator_type.value)

        return LogicalOperator(
            operator_type=operator_type,
            operator_id=operator_id,
            children=children or [],
            physical_operator=physical_operator,
            **kwargs,
        )
