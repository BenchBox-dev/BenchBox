"""Unit tests for TPC-DS ClickHouse dialect overrides."""

from __future__ import annotations

import re

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

TARGET_QUERY_IDS = ("47", "57", "66")
SEEDED_QUERY_IDS = (47, 57, 66)
SEEDS = (1, 2, 3)


def _bench():
    from benchbox.core.tpcds.benchmark.runner import TPCDSBenchmark

    return TPCDSBenchmark()


def _extract_v2_suffix(query: str) -> str:
    _, suffix = query.split(", v2 AS ", 1)
    return suffix


def _normalize_v2_suffix_for_comparison(query: str) -> str:
    suffix = _extract_v2_suffix(query)
    return re.sub(r"\bv1\.([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s+\1\b", r"v1.\1", suffix)


def _extract_order_limit(query: str) -> tuple[str, str]:
    match = re.search(r"ORDER BY (?P<order_by>.+) LIMIT (?P<limit>\d+)$", query)
    assert match is not None, f"Expected ORDER BY ... LIMIT ... tail in query:\n{query}"
    return match.group("order_by"), match.group("limit")


def _extract_q66_filters(query: str) -> tuple[list[str], list[str]]:
    carriers = re.findall(r"sm_carrier IN \([^)]+\)", query)
    time_windows = re.findall(r"t_time BETWEEN \d+ AND \d+ \+ 28800", query)
    return carriers, time_windows


def test_clickhouse_target_queries_are_present_and_non_empty():
    """ClickHouse get_queries() must include all targeted overrides."""
    clickhouse = _bench().get_queries(dialect="clickhouse")

    for query_id in TARGET_QUERY_IDS:
        assert query_id in clickhouse, f"Q{query_id} missing from ClickHouse query set"
        assert clickhouse[query_id].strip(), f"Q{query_id} is empty in ClickHouse query set"


def test_clickhouse_q47_q57_bulk_queries_drop_nested_avg_sum_but_keep_v2_shape():
    """Bulk ClickHouse translation must rewrite Q47/Q57 without altering the v2 tail."""
    bench = _bench()
    base = bench.get_queries()
    clickhouse = bench.get_queries(dialect="clickhouse")

    for query_id in ("47", "57"):
        assert "AVG(SUM(" in base[query_id], f"Base Q{query_id} must retain dsqgen nested aggregate shape"
        assert "AVG(SUM(" not in clickhouse[query_id], f"ClickHouse Q{query_id} must not retain nested aggregate"
        assert "AVG(sum_sales) OVER" in clickhouse[query_id], f"ClickHouse Q{query_id} must average materialized sums"
        assert _normalize_v2_suffix_for_comparison(base[query_id]) == _normalize_v2_suffix_for_comparison(
            clickhouse[query_id]
        ), f"ClickHouse Q{query_id} must preserve dsqgen-selected projection/order tail"
        assert "enable_analyzer = 0" not in clickhouse[query_id], f"ClickHouse Q{query_id} must not opt out"


def test_clickhouse_q47_q57_seeded_queries_preserve_dsqgen_tail_across_seeds():
    """Seeded ClickHouse Q47/Q57 rewrites must preserve the dsqgen-selected v2 tail."""
    bench = _bench()

    for seed in SEEDS:
        for query_id in (47, 57):
            base = bench.get_query(query_id, seed=seed)
            clickhouse = bench.get_query(query_id, seed=seed, dialect="clickhouse")

            assert "AVG(SUM(" in base, f"Base Q{query_id} seed {seed} must retain nested aggregate shape"
            assert "AVG(SUM(" not in clickhouse, f"ClickHouse Q{query_id} seed {seed} must remove nested aggregate"
            assert _normalize_v2_suffix_for_comparison(base) == _normalize_v2_suffix_for_comparison(clickhouse), (
                f"ClickHouse Q{query_id} seed {seed} must preserve dsqgen-selected v2 tail"
            )
            assert "enable_analyzer = 0" not in clickhouse, f"ClickHouse Q{query_id} seed {seed} must not opt out"


def test_clickhouse_q66_bulk_query_uses_stable_channel_sales_relation():
    """Bulk ClickHouse Q66 must aggregate from a stable intermediate relation."""
    bench = _bench()
    base = bench.get_queries()["66"]
    clickhouse = bench.get_queries(dialect="clickhouse")["66"]

    assert "SUM(jan_sales)" in base, "Base Q66 must retain the original aggregate-alias shape"
    assert "SUM(jan_sales)" not in clickhouse, "ClickHouse Q66 must not aggregate over jan_sales alias"
    assert "SUM(jan_net)" not in clickhouse, "ClickHouse Q66 must not aggregate over jan_net alias"
    assert "WITH channel_sales AS (" in clickhouse, "ClickHouse Q66 must aggregate from channel_sales"
    assert _extract_order_limit(base) == _extract_order_limit(clickhouse), "ClickHouse Q66 must preserve ORDER/LIMIT"
    assert "enable_analyzer = 0" not in clickhouse, "ClickHouse Q66 must not opt out"


def test_clickhouse_q66_seeded_queries_preserve_filters_without_old_analyzer_fallback():
    """Seeded ClickHouse Q66 rewrites must preserve dsqgen filters while avoiding alias aggregation."""
    bench = _bench()

    for seed in SEEDS:
        base = bench.get_query(66, seed=seed)
        clickhouse = bench.get_query(66, seed=seed, dialect="clickhouse")
        base_carriers, base_time_windows = _extract_q66_filters(base)

        assert "SUM(jan_sales)" in base, f"Base Q66 seed {seed} must retain original aggregate-alias shape"
        assert "SUM(jan_sales)" not in clickhouse, f"ClickHouse Q66 seed {seed} must remove jan_sales alias aggregation"
        assert "SUM(jan_net)" not in clickhouse, f"ClickHouse Q66 seed {seed} must remove jan_net alias aggregation"
        assert "WITH channel_sales AS (" in clickhouse, f"ClickHouse Q66 seed {seed} must use channel_sales"
        assert _extract_order_limit(base) == _extract_order_limit(clickhouse), (
            f"ClickHouse Q66 seed {seed} must preserve ORDER/LIMIT"
        )
        for carrier_filter in base_carriers:
            assert carrier_filter in clickhouse, (
                f"ClickHouse Q66 seed {seed} must preserve carrier filter {carrier_filter}"
            )
        for time_window in base_time_windows:
            assert time_window in clickhouse, f"ClickHouse Q66 seed {seed} must preserve time window {time_window}"
        assert "enable_analyzer = 0" not in clickhouse, f"ClickHouse Q66 seed {seed} must not opt out"


def test_clickhouse_q47_rewrite_rejects_unexpected_cte_shape():
    """Monthly avg rewrite must raise ValueError when the v1 CTE shape is unexpected."""
    bench = _bench()
    malformed = "SELECT AVG(SUM(x)) OVER () FROM t"
    with pytest.raises(ValueError, match="expected leading v1 CTE"):
        bench._rewrite_clickhouse_monthly_avg_query(47, malformed)


def test_clickhouse_q47_rewrite_rejects_unexpected_aggregate_shape():
    """Monthly avg rewrite must raise ValueError when the inner structure is unexpected."""
    bench = _bench()
    malformed = "WITH v1 AS (SELECT AVG(SUM(x)) FROM t)"
    with pytest.raises(ValueError, match="monthly aggregate shape"):
        bench._rewrite_clickhouse_monthly_avg_query(47, malformed)


def test_clickhouse_q66_rewrite_rejects_missing_derived_table():
    """Q66 rewrite must raise ValueError when the derived table is absent."""
    bench = _bench()
    malformed = "SELECT SUM(jan_sales) AS jan_sales FROM t"
    with pytest.raises(ValueError, match="missing derived table"):
        bench._rewrite_clickhouse_q66(malformed)


def test_clickhouse_q66_rewrite_rejects_missing_group_by():
    """Q66 rewrite must raise ValueError when GROUP BY / ORDER BY / LIMIT is absent."""
    bench = _bench()
    malformed = (
        "SELECT w_warehouse_name, SUM(jan_sales) AS jan_sales "
        "FROM (SELECT 1 AS jan_sales UNION ALL SELECT 2 AS jan_sales) AS x"
    )
    with pytest.raises(ValueError, match="missing outer"):
        bench._rewrite_clickhouse_q66(malformed)


def test_base_tpcds_queries_retain_original_dsqgen_shapes():
    """Base TPC-DS generation must remain unchanged by the ClickHouse overrides."""
    bench = _bench()

    for seed in SEEDS:
        q47 = bench.get_query(47, seed=seed)
        q57 = bench.get_query(57, seed=seed)
        q66 = bench.get_query(66, seed=seed)

        assert "AVG(SUM(" in q47, f"Base Q47 seed {seed} must retain nested aggregate shape"
        assert "AVG(SUM(" in q57, f"Base Q57 seed {seed} must retain nested aggregate shape"
        assert "SUM(jan_sales)" in q66, f"Base Q66 seed {seed} must retain original aggregate-alias shape"
        assert "SUM(jan_net)" in q66, f"Base Q66 seed {seed} must retain original aggregate-alias shape"


def test_clickhouse_overrides_compose_cleanly_with_generic_transformer():
    """Benchmark-layer ClickHouse overrides must not break under the generic transformer pipeline."""
    from benchbox.platforms.clickhouse.query_transformer import ClickHouseQueryTransformer

    bench = _bench()
    transformer = ClickHouseQueryTransformer()

    for query_id in TARGET_QUERY_IDS:
        ch_query = bench.get_queries(dialect="clickhouse")[query_id]
        transformed = transformer.transform(ch_query)
        final = transformer.add_query_settings(transformed)

        assert "SETTINGS joined_subquery_requires_alias = 0" in final, (
            f"Q{query_id}: generic transformer must append session settings"
        )
        assert "enable_analyzer" not in final, f"Q{query_id}: pipeline must not re-introduce analyzer opt-out"
        assert "AVG(SUM(" not in final, f"Q{query_id}: pipeline must not re-introduce nested aggregate-over-window"
