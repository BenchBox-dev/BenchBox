# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License. See LICENSE file in the project root for details.

import pytest

from benchbox.platforms.datafusion_query_transformer import (
    DataFusionQueryTransformer,
    transform_query_for_datafusion,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


Q11_SQL = """\
select
ps_partkey,
sum(ps_supplycost * ps_availqty) as value
from
partsupp,
supplier,
nation
where
ps_suppkey = s_suppkey
and s_nationkey = n_nationkey
and n_name = 'GERMANY'
group by
ps_partkey having
sum(ps_supplycost * ps_availqty) > (
select
sum(ps_supplycost * ps_availqty) * 0.0001000000
from
partsupp,
supplier,
nation
where
ps_suppkey = s_suppkey
and s_nationkey = n_nationkey
and n_name = 'GERMANY'
)
order by
value desc;"""

Q16_SQL = """\
select
p_brand,
p_type,
p_size,
count(distinct ps_suppkey) as supplier_cnt
from
partsupp,
part
where
p_partkey = ps_partkey
and p_brand <> 'Brand#45'
and p_type not like 'MEDIUM POLISHED%'
and p_size in (49, 14, 23, 45, 19, 3, 36, 9)
and ps_suppkey not in (
select
s_suppkey
from
supplier
where
s_comment like '%Customer%Complaints%'
)
group by
p_brand,
p_type,
p_size
order by
supplier_cnt desc,
p_brand,
p_type,
p_size;"""

Q18_SQL = """\
select
c_name,
c_custkey,
o_orderkey,
o_orderdate,
o_totalprice,
sum(l_quantity)
from
customer,
orders,
lineitem
where
o_orderkey in (
select
l_orderkey
from
lineitem
group by
l_orderkey having
sum(l_quantity) > 300
)
and c_custkey = o_custkey
and o_orderkey = l_orderkey
group by
c_name,
c_custkey,
o_orderkey,
o_orderdate,
o_totalprice
order by
o_totalprice desc,
o_orderdate
LIMIT 100;"""

Q20_SQL = """\
select
s_name,
s_address
from
supplier,
nation
where
s_suppkey in (
select
ps_suppkey
from
partsupp
where
ps_partkey in (
select
p_partkey
from
part
where
p_name like 'forest%'
)
and ps_availqty > (
select
0.5 * sum(l_quantity)
from
lineitem
where
l_partkey = ps_partkey
and l_suppkey = ps_suppkey
and l_shipdate >= date '1994-01-01'
and l_shipdate < date '1994-01-01' + interval '1' year
)
)
and s_nationkey = n_nationkey
and n_name = 'CANADA'
order by
s_name;"""


class TestDataFusionQueryTransformer:
    def setup_method(self):
        self.transformer = DataFusionQueryTransformer()

    def test_q11_rewrite_applied(self):
        result = self.transformer.transform(Q11_SQL, query_id="11")
        assert "WITH threshold AS" in result
        assert "part_values AS" in result
        assert "WHERE value > val" in result
        assert "HAVING" not in result

    def test_q11_preserves_nation_parameter(self):
        result = self.transformer.transform(Q11_SQL, query_id="11")
        assert "n_name = 'GERMANY'" in result

    def test_q11_preserves_fraction_parameter(self):
        result = self.transformer.transform(Q11_SQL, query_id="11")
        assert "0.0001000000" in result

    def test_q11_tracks_transformation(self):
        self.transformer.transform(Q11_SQL, query_id="11")
        assert self.transformer.get_transformations_applied() == ["q11_having_threshold_to_cte"]

    def test_q11_order_by_preserved(self):
        result = self.transformer.transform(Q11_SQL, query_id="11")
        assert "ORDER BY value DESC" in result

    def test_q16_rewrite_applied(self):
        result = self.transformer.transform(Q16_SQL, query_id="16")
        assert "not exists" in result.lower()
        assert "s_suppkey = ps_suppkey" in result

    def test_q16_preserves_comment_pattern(self):
        result = self.transformer.transform(Q16_SQL, query_id="16")
        assert "%Customer%Complaints%" in result

    def test_q16_preserves_surrounding_query(self):
        result = self.transformer.transform(Q16_SQL, query_id="16")
        assert "count(distinct ps_suppkey)" in result
        assert "p_brand" in result
        assert "supplier_cnt desc" in result

    def test_q16_removes_not_in(self):
        result = self.transformer.transform(Q16_SQL, query_id="16")
        assert "not in" not in result.lower()

    def test_q16_tracks_transformation(self):
        self.transformer.transform(Q16_SQL, query_id="16")
        assert self.transformer.get_transformations_applied() == ["q16_not_in_to_not_exists"]

    def test_q18_rewrite_applied(self):
        result = self.transformer.transform(Q18_SQL, query_id="18")
        assert "EXISTS" in result
        assert "t.l_orderkey = o_orderkey" in result

    def test_q18_preserves_threshold(self):
        result = self.transformer.transform(Q18_SQL, query_id="18")
        assert "sum(l_quantity) > 300" in result

    def test_q18_preserves_outer_query(self):
        result = self.transformer.transform(Q18_SQL, query_id="18")
        assert "c_name" in result
        assert "o_totalprice desc" in result
        assert "LIMIT 100" in result

    def test_q18_removes_in_pattern(self):
        result = self.transformer.transform(Q18_SQL, query_id="18")
        assert "o_orderkey in" not in result.lower()

    def test_q18_tracks_transformation(self):
        self.transformer.transform(Q18_SQL, query_id="18")
        assert self.transformer.get_transformations_applied() == ["q18_in_having_to_exists"]

    def test_q20_rewrite_applied(self):
        result = self.transformer.transform(Q20_SQL, query_id="20")
        assert "WITH forest_parts AS" in result
        assert "shipped_qty AS" in result
        assert "excess_suppliers AS" in result

    def test_q20_preserves_part_prefix(self):
        result = self.transformer.transform(Q20_SQL, query_id="20")
        assert "forest%" in result

    def test_q20_preserves_nation(self):
        result = self.transformer.transform(Q20_SQL, query_id="20")
        assert "n_name = 'CANADA'" in result

    def test_q20_preserves_date(self):
        result = self.transformer.transform(Q20_SQL, query_id="20")
        assert "1994-01-01" in result

    def test_q20_uses_explicit_joins(self):
        result = self.transformer.transform(Q20_SQL, query_id="20")
        assert "JOIN forest_parts ON" in result
        assert "JOIN shipped_qty ON" in result

    def test_q20_order_by_preserved(self):
        result = self.transformer.transform(Q20_SQL, query_id="20")
        assert "ORDER BY s_name" in result

    def test_q20_handles_cast_date_syntax(self):
        cast_sql = Q20_SQL.replace("date '1994-01-01'", "CAST('1994-01-01' AS DATE)")
        result = self.transformer.transform(cast_sql, query_id="20")
        assert "WITH forest_parts AS" in result
        assert "1994-01-01" in result
        assert self.transformer.get_transformations_applied() == ["q20_correlated_to_cte"]

    def test_q20_tracks_transformation(self):
        self.transformer.transform(Q20_SQL, query_id="20")
        assert self.transformer.get_transformations_applied() == ["q20_correlated_to_cte"]


class TestPassthrough:
    def setup_method(self):
        self.transformer = DataFusionQueryTransformer()

    @pytest.mark.parametrize("query_id", [str(i) for i in range(1, 23) if i not in (11, 16, 18, 20)])
    def test_unaffected_queries_unchanged(self, query_id):
        sample_sql = f"SELECT * FROM lineitem WHERE l_orderkey = {query_id};"
        result = self.transformer.transform(sample_sql, query_id=query_id)
        assert result == sample_sql
        assert self.transformer.get_transformations_applied() == []

    def test_no_query_id_passthrough(self):
        sql = "SELECT count(*) FROM orders;"
        result = self.transformer.transform(sql)
        assert result == sql
        assert self.transformer.get_transformations_applied() == []

    def test_none_query_id_passthrough(self):
        sql = "SELECT count(*) FROM orders;"
        result = self.transformer.transform(sql, query_id=None)
        assert result == sql


class TestQueryIdNormalization:
    def setup_method(self):
        self.transformer = DataFusionQueryTransformer()

    def test_bare_number(self):
        assert self.transformer._normalize_query_id("11") == "11"

    def test_uppercase_prefix(self):
        assert self.transformer._normalize_query_id("Q11") == "11"

    def test_lowercase_prefix(self):
        assert self.transformer._normalize_query_id("q11") == "11"

    def test_with_whitespace(self):
        assert self.transformer._normalize_query_id(" Q11 ") == "11"

    def test_none_returns_none(self):
        assert self.transformer._normalize_query_id(None) is None

    def test_integer_input(self):
        assert self.transformer._normalize_query_id(11) == "11"


class TestTransformationsTracking:
    def setup_method(self):
        self.transformer = DataFusionQueryTransformer()

    def test_reset_between_calls(self):
        self.transformer.transform(Q11_SQL, query_id="11")
        assert len(self.transformer.get_transformations_applied()) == 1

        self.transformer.transform("SELECT 1;", query_id="1")
        assert self.transformer.get_transformations_applied() == []

    def test_empty_for_passthrough(self):
        self.transformer.transform("SELECT 1;", query_id="5")
        assert self.transformer.get_transformations_applied() == []

    def test_no_match_q11_returns_unchanged(self):
        result = self.transformer.transform("SELECT 1;", query_id="11")
        assert result == "SELECT 1;"
        assert self.transformer.get_transformations_applied() == []

    def test_no_match_q16_returns_unchanged(self):
        result = self.transformer.transform("SELECT 1;", query_id="16")
        assert result == "SELECT 1;"
        assert self.transformer.get_transformations_applied() == []

    def test_no_match_q18_returns_unchanged(self):
        result = self.transformer.transform("SELECT 1;", query_id="18")
        assert result == "SELECT 1;"
        assert self.transformer.get_transformations_applied() == []

    def test_no_match_q20_returns_unchanged(self):
        result = self.transformer.transform("SELECT 1;", query_id="20")
        assert result == "SELECT 1;"
        assert self.transformer.get_transformations_applied() == []


class TestConvenienceFunction:
    def test_convenience_function_applies_rewrite(self):
        result = transform_query_for_datafusion(Q11_SQL, query_id="11")
        assert "WITH threshold AS" in result

    def test_convenience_function_passthrough(self):
        sql = "SELECT 1;"
        result = transform_query_for_datafusion(sql, query_id="5")
        assert result == sql

    def test_convenience_function_no_query_id(self):
        sql = "SELECT 1;"
        result = transform_query_for_datafusion(sql)
        assert result == sql
