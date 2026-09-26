"""Cross-dialect TPC-Havoc query rewrite tests."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark
from benchbox.core.tpchavoc.dialect_compat import POSTGRES_ALIAS_VARIANT_IDS
from benchbox.sql_compat.rules.execution_filter.postgres_tpchavoc import POSTGRES_TPCHAVOC_SKIPS


def test_postgres_alias_variants_inline_having_and_where_references():
    benchmark = TPCHavocBenchmark(scale_factor=0.1)

    for query_id in POSTGRES_ALIAS_VARIANT_IDS:
        query = benchmark.get_query(query_id, dialect="postgres")
        tree = sqlglot.parse_one(query, read="postgres")

        assert query_id not in POSTGRES_TPCHAVOC_SKIPS
        for select in tree.find_all(exp.Select):
            aliases = {projection.alias for projection in select.expressions if isinstance(projection, exp.Alias)}
            for clause_name in ("having", "where"):
                clause = select.args.get(clause_name)
                if clause is None:
                    continue
                assert (
                    not {
                        column.name
                        for column in clause.find_all(exp.Column)
                        if not column.table and column.find_ancestor(exp.Select) is select
                    }
                    & aliases
                )


def test_postgres_alias_rules_cover_each_family_platform():
    import benchbox.sql_compat.rules.query_adapter.postgres_tpchavoc_rewrites  # noqa: F401
    from benchbox.sql_compat.context import Phase
    from benchbox.sql_compat.registry import REGISTRY

    for platform in ("pg-duckdb", "pg-mooncake", "timescaledb"):
        registered = {
            key[3]
            for key, _ in REGISTRY.all_rules()
            if key[:3] == (Phase.QUERY_ADAPTER, platform, "tpchavoc") and key[3] in POSTGRES_ALIAS_VARIANT_IDS
        }
        assert registered == POSTGRES_ALIAS_VARIANT_IDS


def test_postgres_alias_rewrite_preserves_order_by_aliases():
    query = TPCHavocBenchmark(scale_factor=0.1).get_query("3_v7", dialect="postgres")

    assert "HAVING SUM(" in query
    assert "ORDER BY revenue DESC" in query
