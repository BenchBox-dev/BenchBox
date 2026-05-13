"""LakeSail execution-filter documentation for read_primitives skips."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

_READ_PRIMITIVES_SKIPS: dict[str, str] = {
    "approx_top_k_lineitem": "Sail rejects `APPROX_TOP_K` with `unknown function: APPROX_TOP_K`.",
    "window_moving_frame": "Sail rejects the interval RANGE window frame with an invalid argument error.",
    "json_extract_nested": "Sail lacks `JSON_VALID`; UAT reports `unknown function: JSON_VALID`.",
    "json_aggregates": "Sail parser rejects the JSON object syntax with `found :`.",
    "fulltext_simple_search": "Sail parser rejects MySQL full-text `MATCH ... AGAINST` syntax.",
    "fulltext_boolean_search": "Sail parser rejects MySQL full-text boolean search syntax.",
    "fulltext_phrase_search": "Sail parser rejects MySQL full-text phrase search syntax.",
    "approx_quantiles_array": "Sail returns a Spark Connect metadata/resource error for array approximate quantiles.",
    "optimizer_scalar_subquery_flattening": "Sail planner reports `Ambiguous reference to unqualified field __always_true`.",
    "groupby_all_simple": "Sail treats `GROUP BY ALL` as an unresolved `ALL` attribute.",
    "groupby_all_complex": "Sail treats `GROUP BY ALL` as an unresolved `ALL` attribute.",
    "orderby_all_simple": "Sail treats `ORDER BY ALL` as an unresolved sort expression.",
    "orderby_all_desc": "Sail treats `ORDER BY ALL DESC` as an unresolved sort expression.",
    "list_transform": "Sail rejects the lambda function form used by the list primitive.",
    "list_filter": "Sail rejects the lambda function form used by the list primitive.",
    "list_reduce": "Sail rejects the lambda function form used by the list primitive.",
    "asof_join_basic": "Sail parser rejects `ASOF JOIN` syntax.",
    "pivot_basic": "Sail parser rejects the PIVOT query form emitted by the catalog.",
}

for _query_id, _reason in _READ_PRIMITIVES_SKIPS.items():
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"execution_filter.lakesail.read_primitives.{_query_id}",
            action=CompatAction.SKIP_QUERY,
            support_level=SupportLevel.SKIPPED_QUERY,
            failure_mode=FailureMode.UNSUPPORTED_FEATURE,
            payload=SkipQueryPayload(
                reason=f"{_reason} Evidence: LakeSail UAT remediation sweeps on 2026-05-12/13.",
                query_id=_query_id,
            ),
            reason=_reason,
        ),
        Phase.EXECUTION_FILTER,
        "lakesail",
        benchmark="read_primitives",
        query_id=_query_id,
    )
