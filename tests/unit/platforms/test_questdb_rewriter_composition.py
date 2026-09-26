"""Unit tests for the QuestDB rewriter entrypoint composition.

Pins that rewrite() applies all four fixup stages end to end: comma-JOIN
expansion, INTERVAL arithmetic to dateadd(), SUBSTRING FROM/FOR, and CTE
column-list removal. Individual stages are covered in test_questdb_rewriter;
these tests pin the composed behavior on single queries needing multiple
or zero fixups.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.platforms.questdb_rewriter import rewrite

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestRewriteComposition:
    def test_plain_select_passes_through_unchanged(self) -> None:
        sql = "SELECT l_orderkey FROM lineitem WHERE l_quantity > 10"
        assert rewrite(sql) == sql

    def test_interval_arithmetic_becomes_dateadd(self) -> None:
        sql = "SELECT CAST('1998-12-01' AS DATE) - INTERVAL '90' DAY"
        result = rewrite(sql)
        assert "dateadd" in result.lower()
        assert "INTERVAL" not in result.upper()

    def test_substring_from_for_becomes_comma_form(self) -> None:
        sql = "SELECT SUBSTRING(c_phone FROM 1 FOR 2) FROM customer"
        result = rewrite(sql)
        assert "substring(c_phone, 1, 2)" in result.lower()
        assert "FROM 1 FOR 2" not in result

    def test_cte_column_list_removed(self) -> None:
        sql = (
            "WITH revenue0 (supplier_no, total_revenue) AS (SELECT s_suppkey, 1.0 FROM partsupp) SELECT * FROM revenue0"
        )
        result = rewrite(sql)
        assert "(supplier_no, total_revenue)" not in result
        assert "revenue0 AS" in result

    def test_comma_join_expanded_to_explicit_join(self) -> None:
        sql = "SELECT l.l_orderkey FROM lineitem l, orders o WHERE l.l_orderkey = o.o_orderkey AND l.l_quantity > 5"
        result = rewrite(sql)
        assert "JOIN" in result.upper()
        assert "l.l_orderkey = o.o_orderkey" in result
        assert "l.l_quantity > 5" in result

    def test_multi_stage_query_applies_all_fixups(self) -> None:
        sql = (
            "WITH rev (sno, total) AS (SELECT s_suppkey, 1.0 FROM partsupp) "
            "SELECT SUBSTRING(c_phone FROM 1 FOR 2) FROM customer c, orders o "
            "WHERE c.c_custkey = o.o_custkey"
        )
        result = rewrite(sql)
        assert "(sno, total)" not in result
        assert "substring(c_phone, 1, 2)" in result.lower()
        assert "JOIN" in result.upper()

    def test_interval_fixup_composes_with_join_expansion(self) -> None:
        # The comma-JOIN stage runs sqlglot first, which normalizes
        # INTERVAL '90' DAY to INTERVAL '90 DAY'. The interval stage must
        # still eliminate it in the same rewrite() pass.
        sql = (
            "SELECT l.l_orderkey FROM lineitem l, orders o "
            "WHERE l.l_orderkey = o.o_orderkey AND o.o_orderdate > "
            "CAST('1998-12-01' AS DATE) - INTERVAL '90' DAY"
        )
        result = rewrite(sql)
        assert "JOIN" in result.upper()
        assert "INTERVAL" not in result.upper()
        assert "dateadd('d', -90," in result

    def test_composed_rewrite_is_idempotent(self) -> None:
        sql = (
            "SELECT l.l_orderkey FROM lineitem l, orders o "
            "WHERE l.l_orderkey = o.o_orderkey AND o.o_orderdate > "
            "CAST('1998-12-01' AS DATE) - INTERVAL '90' DAY"
        )
        assert rewrite(rewrite(sql)) == rewrite(sql)
