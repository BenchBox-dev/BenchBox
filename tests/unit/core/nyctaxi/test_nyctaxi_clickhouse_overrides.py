"""Unit tests for NYC Taxi ClickHouse dialect overrides.

Verifies that the three queries using EXTRACT(DOW/EPOCH/HOUR …) are replaced
with native ClickHouse functions when dialect='clickhouse' is requested.
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

OVERRIDDEN_QUERIES = ["trips-by-day-of-week", "weekday-weekend-comparison", "rush-hour-analysis"]


def _bench():
    from benchbox.core.nyctaxi.benchmark import NYCTaxiBenchmark

    return NYCTaxiBenchmark()


# ---------------------------------------------------------------------------
# trips-by-day-of-week
# ---------------------------------------------------------------------------


def test_trips_by_dow_clickhouse_uses_todayofweek():
    q = _bench().get_queries(dialect="clickhouse")["trips-by-day-of-week"]
    assert "toDayOfWeek(" in q, f"Expected toDayOfWeek(), got:\n{q}"
    assert "EXTRACT" not in q.upper(), f"Must not use EXTRACT for ClickHouse, got:\n{q}"


def test_trips_by_dow_clickhouse_applies_modulo_7():
    q = _bench().get_queries(dialect="clickhouse")["trips-by-day-of-week"]
    assert "% 7" in q, f"Must apply % 7 to map ClickHouse DOW to SQL standard, got:\n{q}"


def test_trips_by_dow_base_retains_extract():
    q = _bench().get_queries()["trips-by-day-of-week"]
    assert "EXTRACT" in q.upper(), f"Base query must use EXTRACT(DOW …), got:\n{q}"


# ---------------------------------------------------------------------------
# weekday-weekend-comparison
# ---------------------------------------------------------------------------


def test_weekday_weekend_clickhouse_uses_todayofweek_and_tohour():
    q = _bench().get_queries(dialect="clickhouse")["weekday-weekend-comparison"]
    assert "toDayOfWeek(" in q, f"Expected toDayOfWeek(), got:\n{q}"
    assert "toHour(" in q, f"Expected toHour(), got:\n{q}"
    assert "EXTRACT" not in q.upper(), f"Must not use EXTRACT for ClickHouse, got:\n{q}"


def test_weekday_weekend_clickhouse_preserves_day_type_column():
    q = _bench().get_queries(dialect="clickhouse")["weekday-weekend-comparison"]
    assert "day_type" in q, f"Must preserve day_type column alias, got:\n{q}"
    assert "'weekend'" in q and "'weekday'" in q, f"Must categorize weekend/weekday, got:\n{q}"


# ---------------------------------------------------------------------------
# rush-hour-analysis
# ---------------------------------------------------------------------------


def test_rush_hour_clickhouse_uses_tohour_and_datediff():
    q = _bench().get_queries(dialect="clickhouse")["rush-hour-analysis"]
    assert "toHour(" in q, f"Expected toHour(), got:\n{q}"
    assert "dateDiff(" in q, f"Expected dateDiff('second', ...) for duration, got:\n{q}"
    assert "EXTRACT" not in q.upper(), f"Must not use EXTRACT for ClickHouse, got:\n{q}"


def test_rush_hour_clickhouse_preserves_period_categories():
    q = _bench().get_queries(dialect="clickhouse")["rush-hour-analysis"]
    assert "morning_rush" in q, f"Must categorize morning_rush, got:\n{q}"
    assert "evening_rush" in q, f"Must categorize evening_rush, got:\n{q}"
    assert "avg_duration_min" in q, f"Must compute avg_duration_min column, got:\n{q}"


# ---------------------------------------------------------------------------
# Other queries unaffected
# ---------------------------------------------------------------------------


def test_non_overridden_queries_present_in_clickhouse_dialect():
    bench = _bench()
    base = bench.get_queries()
    clickhouse = bench.get_queries(dialect="clickhouse")

    for qid in base:
        if qid not in OVERRIDDEN_QUERIES:
            assert qid in clickhouse, f"{qid} missing from ClickHouse queries"
            assert clickhouse[qid].strip(), f"{qid} is empty in ClickHouse queries"
