"""Tests for :mod:`benchbox.core.query_catalog`.

The catalog is the shared render path behind the MCP ``get_query_details`` tool
and the query-docs generator, so these tests pin its contract across the full
benchmark registry rather than one or two examples.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.benchmark_registry import get_all_benchmarks
from benchbox.core.query_catalog import (
    REFERENCE_DIALECT,
    get_dataframe_query,
    get_dataframe_render,
    get_sql_render,
    list_query_ids,
    query_display_name,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

_ALL_BENCHMARK_IDS = sorted(get_all_benchmarks())


class TestListQueryIds:
    def test_unknown_benchmark_is_empty(self):
        assert list_query_ids("does-not-exist") == []

    @pytest.mark.parametrize("benchmark_id", _ALL_BENCHMARK_IDS)
    def test_every_registered_benchmark_has_queries(self, benchmark_id):
        ids = list_query_ids(benchmark_id)
        assert ids, f"{benchmark_id} exposed no query ids"
        assert len(ids) == len(set(ids)), f"{benchmark_id} has duplicate query ids"

    def test_order_is_stable(self):
        assert list_query_ids("tpch") == list_query_ids("tpch")

    def test_tpch_ids_are_the_22_queries(self):
        assert list_query_ids("tpch") == [str(n) for n in range(1, 23)]


class TestGetSqlRender:
    def test_unknown_benchmark_is_none(self):
        assert get_sql_render("does-not-exist", "1") is None

    def test_unknown_query_is_none(self):
        assert get_sql_render("tpch", "9999") is None

    def test_tpch_q1_translates_to_reference_dialect(self):
        render = get_sql_render("tpch", "1")
        assert render is not None
        assert render.dialect == REFERENCE_DIALECT
        assert not render.is_template
        assert "l_returnflag" in render.sql
        # netezza -> datafusion translation quotes identifiers / uppercases keywords
        assert "SELECT" in render.sql

    def test_dialect_none_reports_default_and_skips_translation(self):
        render = get_sql_render("tpch", "1", dialect=None)
        assert render is not None
        assert render.dialect == "default"

    def test_benchmark_without_translation_is_labelled_default(self):
        # datavault.get_queries() rejects a dialect kwarg and get_query absorbs
        # it into **kwargs without translating -- the label must not claim it.
        render = get_sql_render("datavault", "1")
        assert render is not None
        assert render.dialect == "default"

    def test_clickbench_q_prefixed_key(self):
        render = get_sql_render("clickbench", "Q1")
        assert render is not None
        assert "hits" in render.sql.lower()

    def test_query_id_resolves_with_or_without_q_prefix(self):
        # SSB's keys are "Q1.1"; a caller passing "1.1" must still resolve and
        # still get the dialect translation.
        with_prefix = get_sql_render("ssb", "Q1.1", dialect="snowflake")
        without_prefix = get_sql_render("ssb", "1.1", dialect="snowflake")
        assert with_prefix is not None and without_prefix is not None
        assert with_prefix.sql == without_prefix.sql
        assert without_prefix.dialect == "snowflake"

    @pytest.mark.parametrize("benchmark_id", _ALL_BENCHMARK_IDS)
    def test_first_query_of_every_benchmark_renders(self, benchmark_id):
        first = list_query_ids(benchmark_id)[0]
        render = get_sql_render(benchmark_id, first)
        assert render is not None, f"{benchmark_id}:{first} did not render"
        assert render.sql.strip()
        assert not render.is_template, f"{benchmark_id}:{first} rendered as a raw template"


class TestGetDataframeRender:
    def test_tpch_q1_expression_source(self):
        render = get_dataframe_render("tpch", "1")
        assert render is not None
        assert render.family == "expression"
        assert "def q1_expression_impl" in render.source
        assert render.query_name == "Pricing Summary Report"

    def test_pandas_family_selectable(self):
        render = get_dataframe_render("tpch", "1", family="pandas")
        assert render is not None
        assert render.family == "pandas"
        assert "pandas" in render.source.lower() or "def q1_pandas_impl" in render.source

    def test_benchmark_without_dataframe_impl_is_none(self):
        # tpcdi has SQL queries but no DataFrame registry.
        assert get_dataframe_render("tpcdi", list_query_ids("tpcdi")[0]) is None

    def test_id_normalization_matches_q_prefixed_registry(self):
        # SQL key is "6"; the DataFrame registry id is "Q6".
        assert get_dataframe_query("tpch", "6") is not None
        assert get_dataframe_query("tpch", "Q6") is not None


class TestQueryDisplayName:
    def test_tpch_uses_dataframe_query_name(self):
        assert query_display_name("tpch", "1") == "Pricing Summary Report"

    def test_missing_name_is_none(self):
        assert query_display_name("does-not-exist", "1") is None
