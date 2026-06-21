"""ClickHouse execution-filter rules for unsupported TPC-Havoc variants.

ClickHouse is the FOURTH engine sampled by the TPC-Havoc cross-dialect
equivalence oracle (after DuckDB, the hard gate; PostgreSQL; and DataFusion).
It is the first sampled engine that translates through a NATIVE, non-Postgres
SQLGlot dialect (``normalize_dialect_for_sqlglot("clickhouse") == "clickhouse"``),
so it exercises a different code path in the dialect seam than the three
Postgres-family engines before it.

Every entry below is a variant ClickHouse cannot *execute* as translated - it
raises a planning (``NOT_IMPLEMENTED``), name-resolution, or type-system error,
NOT a result divergence. The same SQL passes the DuckDB equivalence gate, so the
variant is valid; these are simply ClickHouse engine/feature gaps. They are
excluded from the equivalence sample (``CLICKHOUSE_TPCHAVOC_SKIPS``), never marked
equivalent. Irreducible engine-semantic *result* differences (where ClickHouse
executes the variant but computes a different answer than canonical TPC-H run on
ClickHouse) live in
``benchbox/core/tpchavoc/equivalence.py:CLICKHOUSE_KNOWN_DIVERGENCES``, not here.

The dominant gap is ClickHouse's (still partial) correlated-subquery support: it
plans some correlated shapes but rejects correlated subqueries in ORDER BY, in
aggregate-function arguments, and behind a handful of plan steps. The remainder
are the missing DuckDB ``LIST`` aggregate (also skipped on Postgres/DataFusion),
ClickHouse's strict rejection of nested aggregates and of a ``SUM`` over a
``Variant`` column produced by a mixed Decimal/Float ``CASE``, a window function
in ``WHERE``, and a ``GROUP BY`` whose key is a ``CASE`` aliased to the same name
as a column it references (alias shadowing). These gaps apply to the ClickHouse
SQL engine itself, so the skips are registered for every ClickHouse deployment
mode (local/chDB, server, cloud).
"""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

CLICKHOUSE_TPCHAVOC_SKIPS: dict[str, str] = {
    "1_v7": "ClickHouse has no DuckDB `LIST` aggregate / `list_transform`/`list_zip` lambda forms this variant uses (`Syntax error` at the `->` lambda).",
    "1_v10": "ClickHouse rejects a GROUP BY whose key is a CASE aliased to the same name as a column it references (alias shadowing, Code 215 NOT_AN_AGGREGATE).",
    "3_v1": "ClickHouse does not support correlated subqueries in ORDER BY (Code 48 NOT_IMPLEMENTED).",
    "3_v9": "ClickHouse rejects a window function used in WHERE (Code 184 ILLEGAL_AGGREGATION).",
    "3_v10": "ClickHouse cannot SUM a `Variant(Decimal, Float64)` column produced by this variant's mixed-type CASE (Code 43 ILLEGAL_TYPE_OF_ARGUMENT).",
    "4_v7": "ClickHouse does not support correlated subqueries in an aggregate-function argument (Code 48 NOT_IMPLEMENTED).",
    "4_v10": "ClickHouse does not support correlated subqueries in an aggregate-function argument (Code 48 NOT_IMPLEMENTED).",
    "5_v1": "ClickHouse does not support correlated subqueries in ORDER BY (Code 48 NOT_IMPLEMENTED).",
    "5_v4": "ClickHouse rejects an aggregate over a select-list-alias aggregate (nested aggregate, Code 184 ILLEGAL_AGGREGATION).",
    "5_v10": "ClickHouse cannot SUM a `Variant(Decimal, Float64)` column produced by this variant's mixed-type CASE (Code 43 ILLEGAL_TYPE_OF_ARGUMENT).",
    "10_v1": "ClickHouse does not support correlated subqueries in ORDER BY (Code 48 NOT_IMPLEMENTED).",
    "11_v4": "ClickHouse rejects an aggregate over a select-list-alias aggregate (nested aggregate, Code 184 ILLEGAL_AGGREGATION).",
    "13_v8": "ClickHouse cannot lower this variant's correlated subquery (CommonSubplan plan step, Code 48 NOT_IMPLEMENTED).",
    "14_v8": "ClickHouse does not support correlated subqueries in an aggregate-function argument (Code 48 NOT_IMPLEMENTED).",
    "16_v1": "ClickHouse does not support correlated subqueries in ORDER BY (Code 48 NOT_IMPLEMENTED).",
    "16_v4": "ClickHouse cannot lower this variant's correlated subquery (DelayedCreatingSets plan step, Code 48 NOT_IMPLEMENTED).",
    "17_v7": "ClickHouse does not support correlated subqueries in an aggregate-function argument (Code 48 NOT_IMPLEMENTED).",
    "17_v10": "ClickHouse does not support correlated subqueries in an aggregate-function argument (Code 48 NOT_IMPLEMENTED).",
}

# The ClickHouse SQL engine is shared across deployment modes, so the same
# variant-execution gaps apply to local/chDB, self-hosted server, and Cloud.
_CLICKHOUSE_TPCHAVOC_PLATFORMS = ("clickhouse-local", "clickhouse-server", "clickhouse-cloud")

for _platform in _CLICKHOUSE_TPCHAVOC_PLATFORMS:
    for _query_id, _reason in CLICKHOUSE_TPCHAVOC_SKIPS.items():
        REGISTRY.register(
            CompatibilityDecision(
                rule_id=f"execution_filter.{_platform}.tpchavoc.{_query_id}",
                action=CompatAction.SKIP_QUERY,
                support_level=SupportLevel.SKIPPED_QUERY,
                failure_mode=FailureMode.UNSUPPORTED_FEATURE,
                payload=SkipQueryPayload(
                    reason=(
                        f"{_reason} Evidence: 2026-06-18 TPC-Havoc fourth-engine equivalence sweep "
                        "(`python -m benchbox.core.tpchavoc.equivalence --engine clickhouse`, SF=0.1) "
                        "reported this stable variant execution failure on ClickHouse."
                    ),
                    query_id=_query_id,
                ),
                reason=_reason,
            ),
            Phase.EXECUTION_FILTER,
            _platform,
            benchmark="tpchavoc",
            query_id=_query_id,
        )
