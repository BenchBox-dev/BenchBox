"""TPC-DI query variant rules for Phase.QUERY_SOURCE.

AQ6 uses SUM(SUM(x)) OVER () which ClickHouse does not support; replaced with
a CROSS JOIN pre-computed grand total.  CLICKHOUSE_AQ6_SQL is a TEMPLATE -
callers must apply parameters via .format(**params) before executing.

EQ7 cross-references sibling subquery aliases which StarRocks (MySQL-compatible)
rejects; replaced by wrapping the UNION ALL in a derived table.
STARROCKS_EQ7_SQL and DORIS_EQ7_SQL are complete SQL strings with no format
placeholders.
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

_B = "tpcdi"
_P = Phase.QUERY_SOURCE

# AQ6: SUM(SUM(x)) OVER () nested window aggregate is unsupported in ClickHouse.
# Replaced with a CROSS JOIN subquery that pre-computes the grand total.
# This is a TEMPLATE - apply .format(**params) before executing.
CLICKHOUSE_AQ6_SQL = """\
SELECT
    'Industry Sector Performance Analysis' as analysis_name,
    comp.Industry,
    COUNT(DISTINCT comp.SK_CompanyID) as companies_in_sector,
    COUNT(DISTINCT s.SK_SecurityID) as securities_in_sector,
    COUNT(t.TradeID) as total_sector_trades,
    SUM(t.Quantity * t.TradePrice) as total_sector_value,
    AVG(t.TradePrice) as avg_sector_price,
    SUM(t.Quantity) as total_sector_volume,
    AVG(comp.MarketCap) as avg_market_cap,
    AVG(mh.PERatio) as avg_sector_pe_ratio,
    AVG(mh.Yield) as avg_sector_yield,
    AVG(mh.ClosePrice) as avg_closing_price,
    stddevPop(mh.ClosePrice) as price_volatility,
    COUNT(CASE WHEN comp.SPrating IN ('AAA', 'AA+', 'AA', 'AA-', 'A+', 'A', 'A-') THEN 1 END) as investment_grade_companies,
    COUNT(CASE WHEN comp.SPrating IN ('BBB+', 'BBB', 'BBB-', 'BB+', 'BB', 'BB-', 'B+', 'B', 'B-', 'CCC') THEN 1 END) as speculative_grade_companies,
    toFloat64(SUM(t.Quantity * t.TradePrice)) / toFloat64(grand_totals.grand_total_value) * 100 as sector_market_share_pct
FROM DimCompany comp
JOIN DimSecurity s ON comp.SK_CompanyID = s.SK_CompanyID
LEFT JOIN FactTrade t ON s.SK_SecurityID = t.SK_SecurityID
LEFT JOIN FactMarketHistory mh ON s.SK_SecurityID = mh.SK_SecurityID
LEFT JOIN DimDate d ON t.SK_CreateDateID = d.SK_DateID
CROSS JOIN (
    SELECT SUM(t2.Quantity * t2.TradePrice) AS grand_total_value
    FROM FactTrade t2
    JOIN DimSecurity s2 ON t2.SK_SecurityID = s2.SK_SecurityID
    JOIN DimCompany comp2 ON s2.SK_CompanyID = comp2.SK_CompanyID
    LEFT JOIN DimDate d2 ON t2.SK_CreateDateID = d2.SK_DateID
    WHERE comp2.IsCurrent = 1
      AND s2.IsCurrent = 1
      AND d2.CalendarYearID >= {start_year}
      AND d2.CalendarYearID <= {end_year}
      AND t2.Status = 'Completed'
) grand_totals
WHERE comp.IsCurrent = 1
  AND s.IsCurrent = 1
  AND (d.CalendarYearID >= {start_year} AND d.CalendarYearID <= {end_year})
  AND t.Status = 'Completed'
GROUP BY comp.Industry, grand_totals.grand_total_value
HAVING COUNT(t.TradeID) > {min_trades}
ORDER BY total_sector_value DESC, avg_sector_pe_ratio ASC
LIMIT {limit_rows};"""

# EQ7: cross-references sibling subquery aliases (quality_calculation reads
# quality_metrics columns), which MySQL-compatible engines (StarRocks) reject.
# Fix: wrap the UNION ALL in a derived table so overall_quality_score is
# computed from actual columns, not aliases.
# This is a COMPLETE SQL string - no format placeholders needed.
STARROCKS_EQ7_SQL = """\
SELECT
    'ETL Data Quality Score Calculation' AS validation_name,
    table_name,
    total_records,
    null_key_fields,
    invalid_values,
    constraint_violations,
    business_rule_violations,
    completeness_score,
    validity_score,
    consistency_score,
    (completeness_score * 0.4 + validity_score * 0.3 + consistency_score * 0.3) AS overall_quality_score,
    CASE
        WHEN (completeness_score * 0.4 + validity_score * 0.3 + consistency_score * 0.3) >= 95.0 THEN 'EXCELLENT'
        WHEN (completeness_score * 0.4 + validity_score * 0.3 + consistency_score * 0.3) >= 85.0 THEN 'GOOD'
        WHEN (completeness_score * 0.4 + validity_score * 0.3 + consistency_score * 0.3) >= 75.0 THEN 'ACCEPTABLE'
        ELSE 'POOR'
    END AS quality_rating
FROM (
    SELECT
        'DimCustomer' AS table_name,
        COUNT(*) AS total_records,
        SUM(CASE WHEN CustomerID IS NULL OR TaxID IS NULL OR Status IS NULL THEN 1 ELSE 0 END) AS null_key_fields,
        SUM(CASE WHEN Gender NOT IN ('M', 'F') OR Tier NOT IN (1,2,3) THEN 1 ELSE 0 END) AS invalid_values,
        SUM(CASE WHEN CreditRating < 300 OR CreditRating > 850 THEN 1 ELSE 0 END) AS constraint_violations,
        SUM(CASE WHEN (Tier = 1 AND NetWorth < 1000000) OR (Tier = 3 AND NetWorth > 250000) THEN 1 ELSE 0 END) AS business_rule_violations,
        (COUNT(*) - SUM(CASE WHEN CustomerID IS NULL OR TaxID IS NULL OR Status IS NULL THEN 1 ELSE 0 END)) / COUNT(*) * 100 AS completeness_score,
        (COUNT(*) - SUM(CASE WHEN Gender NOT IN ('M', 'F') OR Tier NOT IN (1,2,3) THEN 1 ELSE 0 END)) / COUNT(*) * 100 AS validity_score,
        (COUNT(*) - SUM(CASE WHEN CreditRating < 300 OR CreditRating > 850 THEN 1 ELSE 0 END)
         - SUM(CASE WHEN (Tier = 1 AND NetWorth < 1000000) OR (Tier = 3 AND NetWorth > 250000) THEN 1 ELSE 0 END)) / COUNT(*) * 100 AS consistency_score
    FROM DimCustomer
    WHERE IsCurrent = 1
    UNION ALL
    SELECT
        'DimAccount' AS table_name,
        COUNT(*) AS total_records,
        SUM(CASE WHEN AccountID IS NULL OR SK_CustomerID IS NULL OR Status IS NULL THEN 1 ELSE 0 END) AS null_key_fields,
        SUM(CASE WHEN Status NOT IN ('Active', 'Inactive', 'Closed') THEN 1 ELSE 0 END) AS invalid_values,
        SUM(CASE WHEN TaxStatus NOT IN (0, 1, 2) THEN 1 ELSE 0 END) AS constraint_violations,
        0 AS business_rule_violations,
        (COUNT(*) - SUM(CASE WHEN AccountID IS NULL OR SK_CustomerID IS NULL OR Status IS NULL THEN 1 ELSE 0 END)) / COUNT(*) * 100 AS completeness_score,
        (COUNT(*) - SUM(CASE WHEN Status NOT IN ('Active', 'Inactive', 'Closed') THEN 1 ELSE 0 END)) / COUNT(*) * 100 AS validity_score,
        (COUNT(*) - SUM(CASE WHEN TaxStatus NOT IN (0, 1, 2) THEN 1 ELSE 0 END)) / COUNT(*) * 100 AS consistency_score
    FROM DimAccount
    WHERE IsCurrent = 1
    UNION ALL
    SELECT
        'FactTrade' AS table_name,
        COUNT(*) AS total_records,
        SUM(CASE WHEN TradeID IS NULL OR SK_CustomerID IS NULL OR SK_SecurityID IS NULL THEN 1 ELSE 0 END) AS null_key_fields,
        SUM(CASE WHEN Status NOT IN ('Pending', 'Completed', 'Cancelled') OR Type NOT IN ('Buy', 'Sell') THEN 1 ELSE 0 END) AS invalid_values,
        SUM(CASE WHEN TradePrice <= 0 OR Quantity <= 0 OR Fee < 0 OR Commission < 0 THEN 1 ELSE 0 END) AS constraint_violations,
        SUM(CASE WHEN TradePrice > 10000 OR Quantity > 1000000 THEN 1 ELSE 0 END) AS business_rule_violations,
        (COUNT(*) - SUM(CASE WHEN TradeID IS NULL OR SK_CustomerID IS NULL OR SK_SecurityID IS NULL THEN 1 ELSE 0 END)) / COUNT(*) * 100 AS completeness_score,
        (COUNT(*) - SUM(CASE WHEN Status NOT IN ('Pending', 'Completed', 'Cancelled') OR Type NOT IN ('Buy', 'Sell') THEN 1 ELSE 0 END)) / COUNT(*) * 100 AS validity_score,
        (COUNT(*) - SUM(CASE WHEN TradePrice <= 0 OR Quantity <= 0 OR Fee < 0 OR Commission < 0 THEN 1 ELSE 0 END)
         - SUM(CASE WHEN TradePrice > 10000 OR Quantity > 1000000 THEN 1 ELSE 0 END)) / COUNT(*) * 100 AS consistency_score
    FROM FactTrade
) AS quality_metrics
ORDER BY (completeness_score * 0.4 + validity_score * 0.3 + consistency_score * 0.3) DESC"""

# Doris currently uses the same MySQL-compatible EQ7 rewrite as StarRocks.
# Keep a Doris-named alias so future dialect drift becomes an explicit edit.
DORIS_EQ7_SQL = STARROCKS_EQ7_SQL

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.clickhouse.tpcdi.aq6_cross_join_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="clickhouse",
            variant_sql=CLICKHOUSE_AQ6_SQL,
        ),
        reason="ClickHouse does not support nested window aggregate SUM(SUM()) OVER (); replace with CROSS JOIN grand total",
    ),
    _P,
    "clickhouse",
    benchmark=_B,
    query_id="AQ6",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.starrocks.tpcdi.eq7_derived_table_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="starrocks",
            variant_sql=STARROCKS_EQ7_SQL,
        ),
        reason="StarRocks (MySQL-compatible) rejects cross-referencing sibling subquery aliases; wrap UNION ALL in derived table",
    ),
    _P,
    "starrocks",
    benchmark=_B,
    query_id="EQ7",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.doris.tpcdi.eq7_derived_table_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="doris",
            variant_sql=DORIS_EQ7_SQL,
        ),
        reason="Doris (MySQL-compatible) rejects cross-referencing sibling subquery aliases; wrap UNION ALL in derived table",
    ),
    _P,
    "doris",
    benchmark=_B,
    query_id="EQ7",
)
