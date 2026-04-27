"""CoffeeShop query variant rules for Phase.QUERY_SOURCE.

SA4 and TM1 use SQL constructs that ClickHouse does not support natively.
The SQL constants below are TEMPLATES - callers must apply default parameters
via .format(**params) before executing.  The same constants are imported by
CoffeeShopBenchmark.get_queries() as the legacy-path fallback (OFF/SHADOW modes).
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

_B = "coffeeshop"
_P = Phase.QUERY_SOURCE

# SA4: SUM(SUM(x)) OVER () is a nested window aggregate unsupported in ClickHouse.
# Replaced with a CROSS JOIN subquery that pre-computes the grand total.
CLICKHOUSE_SA4_SQL = """\
SELECT
    dl.region,
    COUNT(DISTINCT ol.order_id) AS orders,
    SUM(ol.total_price) AS revenue,
    toFloat64(SUM(ol.total_price)) / toFloat64(totals.grand_total) AS revenue_share
FROM order_lines ol
JOIN dim_locations dl ON ol.location_record_id = dl.record_id
CROSS JOIN (
    SELECT SUM(total_price) AS grand_total
    FROM order_lines
    WHERE order_date BETWEEN toDate('{start_date}') AND toDate('{end_date}')
) totals
WHERE ol.order_date BETWEEN toDate('{start_date}') AND toDate('{end_date}')
GROUP BY dl.region, totals.grand_total
ORDER BY revenue DESC;"""

# TM1: EXTRACT(HOUR FROM TIME column) fails on ClickHouse - toHour() requires DateTime.
CLICKHOUSE_TM1_SQL = """\
SELECT
    CASE
        WHEN toHour(toDateTime(ol.order_time)) BETWEEN 5 AND 10 THEN 'Morning'
        WHEN toHour(toDateTime(ol.order_time)) BETWEEN 11 AND 14 THEN 'Midday'
        WHEN toHour(toDateTime(ol.order_time)) BETWEEN 15 AND 17 THEN 'Afternoon'
        ELSE 'Evening'
    END AS day_part,
    COUNT(DISTINCT ol.order_id) AS orders,
    SUM(ol.total_price) AS revenue,
    AVG(ol.total_price) AS avg_line_value
FROM order_lines ol
JOIN dim_locations dl ON ol.location_record_id = dl.record_id
WHERE dl.region = '{region}'
  AND ol.order_date BETWEEN toDate('{start_date}') AND toDate('{end_date}')
GROUP BY day_part
ORDER BY day_part;"""

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.clickhouse.coffeeshop.sa4_cross_join_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="clickhouse",
            variant_sql=CLICKHOUSE_SA4_SQL,
        ),
        reason="ClickHouse does not support nested window aggregate SUM(SUM()) OVER (); replace with CROSS JOIN subquery",
    ),
    _P,
    "clickhouse",
    benchmark=_B,
    query_id="SA4",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.clickhouse.coffeeshop.tm1_todatetime_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="clickhouse",
            variant_sql=CLICKHOUSE_TM1_SQL,
        ),
        reason="ClickHouse toHour() requires DateTime; EXTRACT(HOUR FROM TIME) fails on TIME columns",
    ),
    _P,
    "clickhouse",
    benchmark=_B,
    query_id="TM1",
)
