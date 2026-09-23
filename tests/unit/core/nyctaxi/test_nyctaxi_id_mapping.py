"""SQL<->DataFrame query-id correspondence for NYCTaxi.

The SQL surface names its 25 queries with slugs (``trips-per-hour``,
``top-pickup-zones``, ...) while the DataFrame registry numbers them ``Q1``
.. ``Q25``. Each DataFrame query carries a human-readable title in
``_QUERY_METADATA`` that slugifies (lowercase, non-alphanumerics to hyphens)
to exactly one SQL id, and every SQL id is covered -- a documented 1:1
correspondence, not a guessed mapping. This locks that table so a future gate
can wire it without re-proving it. Gating itself is out of scope here.

Caveat for that future gate: nyctaxi's downloader always tries a network fetch
at any scale factor and falls back to synthetic data only on failure
(``benchbox/core/nyctaxi/downloader.py``), so unlike flightdata (which always
synthesizes below SF=0.1) a nyctaxi gate is not offline by default.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import re

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# DataFrame id -> SQL id, one row per query. Titles come from the registry's
# _QUERY_METADATA; each slugifies to its SQL counterpart.
EXPECTED_MAPPING = {
    "Q1": "trips-per-hour",
    "Q2": "trips-per-day",
    "Q3": "trips-per-month",
    "Q4": "trips-by-day-of-week",
    "Q5": "top-pickup-zones",
    "Q6": "top-dropoff-zones",
    "Q7": "top-routes",
    "Q8": "borough-summary",
    "Q9": "revenue-by-payment-type",
    "Q10": "fare-distribution",
    "Q11": "tip-analysis",
    "Q12": "surcharge-revenue",
    "Q13": "distance-distribution",
    "Q14": "passenger-count-analysis",
    "Q15": "trip-duration-analysis",
    "Q16": "rate-code-summary",
    "Q17": "airport-trips",
    "Q18": "vendor-comparison",
    "Q19": "hourly-zone-heatmap",
    "Q20": "weekday-weekend-comparison",
    "Q21": "rush-hour-analysis",
    "Q22": "monthly-year-over-year",
    "Q23": "single-day-summary",
    "Q24": "zone-detail",
    "Q25": "full-scan-count",
}


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def test_dataframe_titles_slugify_to_sql_ids() -> None:
    """Every registry title slugifies to a real SQL query id (no guessing)."""
    from benchbox.core.benchmark_loader import get_core_benchmark_class
    from benchbox.core.nyctaxi.dataframe_queries import NYCTAXI_DATAFRAME_QUERIES

    sql_ids = {str(q) for q in get_core_benchmark_class("nyctaxi")(scale_factor=0.01).get_queries()}
    assert len(sql_ids) == 25
    for query in NYCTAXI_DATAFRAME_QUERIES.get_all_queries():
        assert _slug(query.query_name) in sql_ids, f"{query.query_id} ({query.query_name!r}) matches no SQL query"


def test_mapping_table_is_exact_and_total() -> None:
    """The locked table covers every query on both surfaces exactly once."""
    from benchbox.core.benchmark_loader import get_core_benchmark_class
    from benchbox.core.nyctaxi.dataframe_queries import NYCTAXI_DATAFRAME_QUERIES

    sql_ids = {str(q) for q in get_core_benchmark_class("nyctaxi")(scale_factor=0.01).get_queries()}
    df_ids = {str(q) for q in NYCTAXI_DATAFRAME_QUERIES.get_query_ids()}
    assert set(EXPECTED_MAPPING) == df_ids
    assert sorted(EXPECTED_MAPPING.values()) == sorted(sql_ids)
