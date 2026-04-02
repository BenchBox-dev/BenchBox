"""Tests for benchbox.core.tuning.generators.doris.DorisDDLGenerator.

Focused on the generator class itself — DDL string content and TuningClauses
field values. Does not duplicate the adapter-level tests in test_doris_adapter.py.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.tuning import TableTuning
from benchbox.core.tuning.ddl_generator import ColumnDefinition
from benchbox.core.tuning.generators.doris import DorisDDLGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def gen_tpch():
    return DorisDDLGenerator(benchmark_type="tpch")


TPCH_TABLES = ["lineitem", "orders", "customer", "part", "partsupp", "supplier", "nation", "region"]


class TestGenerateTuningClausesLineitem:
    def test_sort_by_lineitem(self, gen_tpch):
        clauses = gen_tpch.generate_tuning_clauses(TableTuning(table_name="lineitem"))
        assert clauses.sort_by == "l_orderkey, l_linenumber"

    def test_distribute_by_lineitem(self, gen_tpch):
        clauses = gen_tpch.generate_tuning_clauses(TableTuning(table_name="lineitem"))
        assert clauses.distribute_by == "l_orderkey"

    def test_colocate_with_group_orders(self, gen_tpch):
        clauses = gen_tpch.generate_tuning_clauses(TableTuning(table_name="lineitem"))
        assert clauses.table_properties["colocate_with"] == "group_orders"

    def test_bloom_filter_columns_contains_orderkey(self, gen_tpch):
        clauses = gen_tpch.generate_tuning_clauses(TableTuning(table_name="lineitem"))
        assert "l_orderkey" in clauses.table_properties["bloom_filter_columns"]

    def test_additional_clauses_contains_distributed_by_hash(self, gen_tpch):
        clauses = gen_tpch.generate_tuning_clauses(TableTuning(table_name="lineitem"))
        assert len(clauses.additional_clauses) >= 1
        assert "DISTRIBUTED BY HASH" in clauses.additional_clauses[0]
        assert "BUCKETS 10" in clauses.additional_clauses[0]

    def test_post_create_statements_contains_bitmap_index(self, gen_tpch):
        clauses = gen_tpch.generate_tuning_clauses(TableTuning(table_name="lineitem"))
        assert len(clauses.post_create_statements) >= 1
        assert "USING BITMAP" in clauses.post_create_statements[0]


class TestGenerateTuningClausesNation:
    def test_nation_no_bloom_filter(self, gen_tpch):
        clauses = gen_tpch.generate_tuning_clauses(TableTuning(table_name="nation"))
        assert "bloom_filter_columns" not in clauses.table_properties

    def test_nation_no_bitmap_index(self, gen_tpch):
        clauses = gen_tpch.generate_tuning_clauses(TableTuning(table_name="nation"))
        assert clauses.post_create_statements == []


class TestScaleFactorBuckets:
    def test_scale_2_doubles_bucket_count(self):
        gen = DorisDDLGenerator(benchmark_type="tpch", scale_factor=2.0)
        clauses = gen.generate_tuning_clauses(TableTuning(table_name="lineitem"))
        assert "BUCKETS 20" in clauses.additional_clauses[0]


class TestNoneTableTuningReturnsEmpty:
    def test_none_table_tuning(self, gen_tpch):
        clauses = gen_tpch.generate_tuning_clauses(None)
        assert clauses.sort_by is None
        assert clauses.distribute_by is None


class TestAllTpchTablesHaveEntries:
    @pytest.mark.parametrize("table", TPCH_TABLES)
    def test_table_has_sort_by(self, gen_tpch, table):
        clauses = gen_tpch.generate_tuning_clauses(TableTuning(table_name=table))
        assert clauses.sort_by is not None, f"{table} missing sort_by"

    @pytest.mark.parametrize("table", TPCH_TABLES)
    def test_table_has_distribute_by(self, gen_tpch, table):
        clauses = gen_tpch.generate_tuning_clauses(TableTuning(table_name=table))
        assert clauses.distribute_by is not None, f"{table} missing distribute_by"


class TestGenerateCreateTableDdl:
    def test_lineitem_has_duplicate_key(self, gen_tpch):
        tt = TableTuning(table_name="lineitem")
        clauses = gen_tpch.generate_tuning_clauses(tt)
        cols = [ColumnDefinition("l_orderkey", "BIGINT"), ColumnDefinition("l_linenumber", "INTEGER")]
        ddl = gen_tpch.generate_create_table_ddl("lineitem", cols, clauses)
        assert "DUPLICATE KEY" in ddl
        assert "l_orderkey" in ddl
        assert "l_linenumber" in ddl

    def test_lineitem_has_distributed_by_hash(self, gen_tpch):
        tt = TableTuning(table_name="lineitem")
        clauses = gen_tpch.generate_tuning_clauses(tt)
        cols = [ColumnDefinition("l_orderkey", "BIGINT")]
        ddl = gen_tpch.generate_create_table_ddl("lineitem", cols, clauses)
        assert "DISTRIBUTED BY HASH(`l_orderkey`) BUCKETS 10" in ddl

    def test_lineitem_has_properties_block(self, gen_tpch):
        tt = TableTuning(table_name="lineitem")
        clauses = gen_tpch.generate_tuning_clauses(tt)
        cols = [ColumnDefinition("l_orderkey", "BIGINT")]
        ddl = gen_tpch.generate_create_table_ddl("lineitem", cols, clauses)
        assert "PROPERTIES" in ddl
        assert '"colocate_with" = "group_orders"' in ddl


class TestTpcdsSupport:
    def test_store_sales_distribute_by(self):
        gen = DorisDDLGenerator(benchmark_type="tpcds")
        clauses = gen.generate_tuning_clauses(TableTuning(table_name="store_sales"))
        assert clauses.distribute_by == "ss_item_sk"

    def test_store_sales_sort_by_contains_date(self):
        gen = DorisDDLGenerator(benchmark_type="tpcds")
        clauses = gen.generate_tuning_clauses(TableTuning(table_name="store_sales"))
        assert "ss_sold_date_sk" in clauses.sort_by
