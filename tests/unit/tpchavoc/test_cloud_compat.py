"""Cloud TPC-Havoc variants use executable SQL and declared skips."""

from __future__ import annotations

import duckdb
import pytest
import sqlglot

from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark
from benchbox.core.tpchavoc.cloud_compat import BIGQUERY_FILTER_IDS, rewrite_cloud_variant
from benchbox.sql_compat.rules.execution_filter.cloud_tpchavoc import CLOUD_TPCHAVOC_SKIPS

pytestmark = [pytest.mark.unit, pytest.mark.medium]


def test_bigquery_rewrites_all_filtered_aggregates_and_known_subqueries():
    benchmark = TPCHavocBenchmark(scale_factor=0.1)
    translated = TPCHBenchmark.get_queries(benchmark, dialect="bigquery")
    queries = benchmark.get_queries(dialect="bigquery")

    assert len(queries) == 220
    assert {query_id for query_id, query in translated.items() if " FILTER(" in query} == BIGQUERY_FILTER_IDS
    assert all(" FILTER(" not in query for query in queries.values())
    assert "COUNTIF(" in queries["1_v6"]
    assert "COUNT(DISTINCT IF(" in queries["16_v7"]
    for query_id in ("7_v8", "12_v8", "13_v8", "18_v4"):
        assert "FROM UNNEST([1])" in queries[query_id]
    assert "SUM(`combined`.`revenue`)" in queries["5_v4"]
    assert "SUM(`combined`.`value`)" in queries["11_v4"]
    assert "OVER (PARTITION BY `l_orderkey` ORDER BY `l_orderkey` NULLS LAST)" not in queries["3_v9"]
    assert " FILTER(" not in benchmark.get_query("1_v6", dialect="BigQuery")


def test_filtered_aggregate_rewrite_preserves_null_and_distinct_semantics():
    source = """
        SELECT SUM(x) FILTER(WHERE keep), AVG(x) FILTER(WHERE keep),
               MIN(x) FILTER(WHERE keep), COUNT(*) FILTER(WHERE keep),
               COUNT(x) FILTER(WHERE keep), COUNT(DISTINCT x) FILTER(WHERE keep)
        FROM (VALUES (1, TRUE), (1, TRUE), (NULL, TRUE), (2, FALSE), (3, NULL)) AS t(x, keep)
    """
    expected = duckdb.sql(source).fetchall()
    translated = sqlglot.transpile(source, read="duckdb", write="bigquery")[0]
    rewritten = rewrite_cloud_variant("1_v6", translated, "bigquery")
    executable = sqlglot.transpile(rewritten, read="bigquery", write="duckdb")[0]

    assert " FILTER(" not in rewritten
    assert duckdb.sql(executable).fetchall() == expected


def test_snowflake_empty_group_rewrite_is_targeted():
    benchmark = TPCHavocBenchmark(scale_factor=0.1)
    snowflake = benchmark.get_queries(dialect="snowflake")

    assert len(snowflake) == 220
    assert "GROUP BY ()" not in snowflake["6_v2"]
    assert "GROUP BY ()" not in snowflake["14_v2"]
    assert "HAVING SUM(" in snowflake["6_v2"]
    assert benchmark.get_queries(dialect="duckdb")["6_v2"].count("GROUP BY ()") == 1


def test_cloud_skips_flow_through_benchmark_runtime_mapping():
    benchmark = TPCHavocBenchmark(scale_factor=0.1)

    for platform in ("BigQuery", "Snowflake", "Databricks"):
        assert set(benchmark.get_platform_skip_queries(platform)) == set(CLOUD_TPCHAVOC_SKIPS[platform.lower()])
    assert benchmark.get_platform_skip_queries("DuckDB") == []


def test_databricks_reuses_spark_variant_rewrites():
    benchmark = TPCHavocBenchmark(scale_factor=0.1)
    queries = benchmark.get_queries(dialect="databricks")

    assert len(queries) == 220
    assert "GROUP BY ()" not in queries["6_v2"]
    assert "GROUP BY ()" not in queries["14_v2"]
    assert "FIRST(" in queries["1_v1"]
    assert "dual_col" in queries["17_v4"]


def test_registry_describes_runtime_rewrites():
    import benchbox.sql_compat.rules.query_adapter.cloud_tpchavoc_rewrites  # noqa: F401
    import benchbox.sql_compat.rules.query_adapter.spark_tpchavoc_rewrites  # noqa: F401
    from benchbox.sql_compat.context import Phase
    from benchbox.sql_compat.registry import REGISTRY

    registered = {
        platform: {key[3] for key, _ in REGISTRY.all_rules() if key[:3] == (Phase.QUERY_ADAPTER, platform, "tpchavoc")}
        for platform in ("bigquery", "snowflake", "databricks")
    }
    assert registered["bigquery"] == BIGQUERY_FILTER_IDS | {"7_v8", "12_v8", "13_v8", "18_v4", "5_v4", "11_v4", "3_v9"}
    assert registered["snowflake"] == {"6_v2", "14_v2"}
    assert len(registered["databricks"]) == 11
