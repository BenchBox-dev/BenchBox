"""DataFusion execution-filter rules for unsupported TPC-Havoc variants.

DataFusion is the THIRD engine sampled by the TPC-Havoc cross-dialect
equivalence oracle (after DuckDB, the hard gate, and PostgreSQL, the second
engine). Unlike PostgreSQL, DataFusion's gaps are concentrated in *physical
planning* of correlated sub-queries (EXISTS / IN / scalar sub-queries in
positions its planner cannot lower), the missing ``LIST`` aggregate, and a
parser limitation on the generated empty-tuple sub-query syntax - a DIFFERENT
gap profile from PostgreSQL's HAVING/WHERE select-list-alias and
aggregate-in-window restrictions.

Every entry below is a variant DataFusion cannot *execute* (it raises a planning
or feature-not-implemented error), NOT a result divergence: the same SQL passes
the DuckDB equivalence gate, so the variant is valid and DataFusion's residual
equivalence surface is empty. These are excluded from the equivalence sample
(``DATAFUSION_TPCHAVOC_SKIPS``), never marked equivalent. Result-equivalence
exceptions, if any were ever needed, live in
``benchbox/core/tpchavoc/equivalence.py:DATAFUSION_KNOWN_DIVERGENCES`` (empty).

This skip set is a strict subset of ``LAKESAIL_TPCHAVOC_SKIPS``: Apache Sail
(LakeSail) is itself DataFusion-based, so it shares these physical-planning
limitations and adds further ones of its own - corroborating that these are
genuine engine limitations rather than translation artifacts.
"""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

DATAFUSION_TPCHAVOC_SKIPS: dict[str, str] = {
    "1_v7": "DataFusion has no `LIST` aggregate used by this variant (`Invalid function 'list'`).",
    "4_v7": "DataFusion physical planning does not support EXISTS in this variant shape.",
    "4_v10": "DataFusion physical planning does not support EXISTS in this variant shape.",
    "6_v2": "DataFusion rejects the generated empty-tuple sub-query (`Empty tuple not supported yet`).",
    "7_v1": "DataFusion physical planning does not support the scalar sub-query in this variant shape.",
    "8_v1": "DataFusion `scalar_subquery_to_join` optimizer rule fails to resolve a sub-query field for this variant.",
    "9_v1": "DataFusion physical planning does not support the scalar sub-query in this variant shape.",
    "12_v1": "DataFusion `scalar_subquery_to_join` optimizer rule reports an ambiguous `count(*)` for this variant.",
    "14_v2": "DataFusion rejects the generated empty-tuple sub-query (`Empty tuple not supported yet`).",
    "14_v8": "DataFusion physical planning does not support EXISTS in this variant shape.",
    "16_v7": "DataFusion physical planning does not support the IN sub-query in this variant shape.",
    "16_v10": "DataFusion physical planning does not support the IN sub-query in this variant shape.",
    "17_v7": "DataFusion physical planning does not support the scalar sub-query in this variant shape.",
    "17_v10": "DataFusion physical planning does not support the scalar sub-query in this variant shape.",
}

for _query_id, _reason in DATAFUSION_TPCHAVOC_SKIPS.items():
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"execution_filter.datafusion.tpchavoc.{_query_id}",
            action=CompatAction.SKIP_QUERY,
            support_level=SupportLevel.SKIPPED_QUERY,
            failure_mode=FailureMode.UNSUPPORTED_FEATURE,
            payload=SkipQueryPayload(
                reason=(
                    f"{_reason} Evidence: 2026-06-15 TPC-Havoc third-engine equivalence sweep "
                    "(`python -m benchbox.core.tpchavoc.equivalence --engine datafusion`, SF=0.1) "
                    "reported this stable variant execution failure on DataFusion."
                ),
                query_id=_query_id,
            ),
            reason=_reason,
        ),
        Phase.EXECUTION_FILTER,
        "datafusion",
        benchmark="tpchavoc",
        query_id=_query_id,
    )
