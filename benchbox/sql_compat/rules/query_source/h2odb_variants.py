"""H2O DB query variant rules for Phase.QUERY_SOURCE.

Q9 uses PERCENTILE_CONT … WITHIN GROUP (ORDER BY …) which is not supported
by ClickHouse or StarRocks.  Each platform requires a platform-native rewrite.
The SQL constants below are also imported by H2OBenchmark.get_queries() as
the legacy-path fallback (OFF/SHADOW modes).
"""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import (
    CompatibilityDecision,
    FailureMode,
    SelectVariantPayload,
    SupportLevel,
)
from benchbox.sql_compat.registry import REGISTRY

_B = "h2odb"
_P = Phase.QUERY_SOURCE

# ClickHouse: quantile() replaces PERCENTILE_CONT … WITHIN GROUP (ORDER BY …)
CLICKHOUSE_Q9_SQL = """
SELECT
    passenger_count,
    quantile(0.5)(fare_amount) as median_fare_amount,
    quantile(0.9)(fare_amount) as p90_fare_amount
FROM trips
GROUP BY passenger_count
ORDER BY passenger_count;
"""

# StarRocks: PERCENTILE_APPROX(expr, p) replaces ANSI WITHIN GROUP syntax
STARROCKS_Q9_SQL = """
SELECT
    passenger_count,
    PERCENTILE_APPROX(fare_amount, 0.5) as median_fare_amount,
    PERCENTILE_APPROX(fare_amount, 0.9) as p90_fare_amount
FROM trips
GROUP BY passenger_count
ORDER BY passenger_count;
"""

# MySQL/SingleStore: PERCENTILE_CONT WITHIN GROUP is supported but SQLGlot adds a
# multi-expression WITHIN GROUP ORDER BY (NULL-sort CASE) that SingleStore rejects.
# Bypass translation by providing the query verbatim.
MYSQL_Q9_SQL = """
SELECT
    passenger_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY fare_amount) as median_fare_amount,
    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY fare_amount) as p90_fare_amount
FROM trips
GROUP BY passenger_count
ORDER BY passenger_count;
"""

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.clickhouse.h2odb.q9_quantile_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=SelectVariantPayload(
            variant_key="clickhouse",
            variant_sql=CLICKHOUSE_Q9_SQL,
        ),
        reason="ClickHouse cannot parse PERCENTILE_CONT … WITHIN GROUP; replace with quantile()",
    ),
    _P,
    "clickhouse",
    benchmark=_B,
    query_id="Q9",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.starrocks.h2odb.q9_percentile_approx_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=SelectVariantPayload(
            variant_key="starrocks",
            variant_sql=STARROCKS_Q9_SQL,
        ),
        reason="StarRocks uses PERCENTILE_APPROX instead of ANSI WITHIN GROUP syntax",
    ),
    _P,
    "starrocks",
    benchmark=_B,
    query_id="Q9",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.mysql.h2odb.q9_within_group_verbatim",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=SelectVariantPayload(
            variant_key="mysql",
            variant_sql=MYSQL_Q9_SQL,
        ),
        reason=(
            "SQLGlot adds a multi-expression WITHIN GROUP ORDER BY (NULL-sort CASE) that "
            "SingleStore rejects; bypass translation with the verbatim ANSI query"
        ),
    ),
    _P,
    "mysql",
    benchmark=_B,
    query_id="Q9",
)
