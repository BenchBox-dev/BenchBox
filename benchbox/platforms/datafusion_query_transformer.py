# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


class DataFusionQueryTransformer:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.transformations_applied: list[str] = []

    def transform(self, query: str, query_id: str | None = None) -> str:
        self.transformations_applied = []

        normalized_id = self._normalize_query_id(query_id)

        if normalized_id == "11":
            query = self._rewrite_q11_having_threshold(query)
        elif normalized_id == "16":
            query = self._rewrite_q16_not_in_to_not_exists(query)
        elif normalized_id == "18":
            query = self._rewrite_q18_in_having_to_exists(query)
        elif normalized_id == "20":
            query = self._rewrite_q20_correlated_to_cte(query)

        if self.verbose and self.transformations_applied:
            logger.debug(f"Applied transformations: {', '.join(self.transformations_applied)}")

        return query

    def get_transformations_applied(self) -> list[str]:
        return self.transformations_applied

    def _normalize_query_id(self, query_id: str | None) -> str | None:
        if query_id is None:
            return None
        qid = str(query_id).strip().upper()
        if qid.startswith("Q"):
            qid = qid[1:]
        return qid

    def _rewrite_q11_having_threshold(self, query: str) -> str:
        nation_match = re.search(r"n_name\s*=\s*'([^']+)'", query)
        if not nation_match:
            return query

        fraction_match = re.search(r"sum\(ps_supplycost\s*\*\s*ps_availqty\)\s*\*\s*([\d.]+)", query, re.IGNORECASE)
        if not fraction_match:
            return query

        nation = nation_match.group(1)
        fraction = fraction_match.group(1)

        join_clause = (
            "partsupp, supplier, nation\n"
            "where\n"
            "ps_suppkey = s_suppkey\n"
            "and s_nationkey = n_nationkey\n"
            f"and n_name = '{nation}'"
        )

        rewritten = (
            f"WITH threshold AS (\n"
            f"  SELECT sum(ps_supplycost * ps_availqty) * {fraction} AS val\n"
            f"  FROM {join_clause}\n"
            f"),\n"
            f"part_values AS (\n"
            f"  SELECT ps_partkey, sum(ps_supplycost * ps_availqty) AS value\n"
            f"  FROM {join_clause}\n"
            f"  GROUP BY ps_partkey\n"
            f")\n"
            f"SELECT ps_partkey, value\n"
            f"FROM part_values, threshold\n"
            f"WHERE value > val\n"
            f"ORDER BY value DESC;"
        )

        self.transformations_applied.append("q11_having_threshold_to_cte")
        return rewritten

    def _rewrite_q16_not_in_to_not_exists(self, query: str) -> str:
        pattern = (
            r"and\s+ps_suppkey\s+not\s+in\s*\(\s*"
            r"select\s+s_suppkey\s+from\s+supplier\s+"
            r"where\s+s_comment\s+like\s+'([^']+)'\s*\)"
        )
        match = re.search(pattern, query, re.IGNORECASE | re.DOTALL)
        if not match:
            return query

        comment_pattern = match.group(1)
        replacement = (
            f"and not exists (\n"
            f"select 1\n"
            f"from\n"
            f"supplier\n"
            f"where\n"
            f"s_suppkey = ps_suppkey\n"
            f"and s_comment like '{comment_pattern}'\n"
            f")"
        )
        query = query[: match.start()] + replacement + query[match.end() :]

        self.transformations_applied.append("q16_not_in_to_not_exists")
        return query

    def _rewrite_q18_in_having_to_exists(self, query: str) -> str:
        pattern = (
            r"o_orderkey\s+in\s*\(\s*"
            r"select\s+l_orderkey\s+from\s+lineitem\s+"
            r"group\s+by\s+l_orderkey\s+having\s+"
            r"sum\(l_quantity\)\s*>\s*(\d+)\s*\)"
        )
        match = re.search(pattern, query, re.IGNORECASE | re.DOTALL)
        if not match:
            return query

        threshold = match.group(1)
        replacement = (
            f"EXISTS (\n"
            f"select 1 from (\n"
            f"select\n"
            f"l_orderkey\n"
            f"from\n"
            f"lineitem\n"
            f"group by\n"
            f"l_orderkey having\n"
            f"sum(l_quantity) > {threshold}\n"
            f") t\n"
            f"where t.l_orderkey = o_orderkey\n"
            f")"
        )
        query = query[: match.start()] + replacement + query[match.end() :]

        self.transformations_applied.append("q18_in_having_to_exists")
        return query

    def _rewrite_q20_correlated_to_cte(self, query: str) -> str:
        pname_match = re.search(r"p_name\s+like\s+'([^']+)'", query, re.IGNORECASE)
        if not pname_match:
            return query

        nation_match = re.search(r"n_name\s*=\s*'([^']+)'", query)
        if not nation_match:
            return query

        date_match = re.search(
            r"l_shipdate\s*>=\s*(?:date\s*|CAST\()'([^']+)'",
            query,
            re.IGNORECASE,
        )
        if not date_match:
            return query

        part_prefix = pname_match.group(1)
        nation = nation_match.group(1)
        start_date = date_match.group(1)

        rewritten = (
            f"WITH forest_parts AS (\n"
            f"  SELECT p_partkey FROM part WHERE p_name like '{part_prefix}'\n"
            f"),\n"
            f"shipped_qty AS (\n"
            f"  SELECT l_partkey, l_suppkey, 0.5 * sum(l_quantity) AS threshold\n"
            f"  FROM lineitem\n"
            f"  WHERE l_shipdate >= date '{start_date}'\n"
            f"    AND l_shipdate < date '{start_date}' + interval '1' year\n"
            f"  GROUP BY l_partkey, l_suppkey\n"
            f"),\n"
            f"excess_suppliers AS (\n"
            f"  SELECT DISTINCT ps_suppkey\n"
            f"  FROM partsupp\n"
            f"  JOIN forest_parts ON ps_partkey = p_partkey\n"
            f"  JOIN shipped_qty ON ps_partkey = l_partkey AND ps_suppkey = l_suppkey\n"
            f"  WHERE ps_availqty > threshold\n"
            f")\n"
            f"SELECT s_name, s_address\n"
            f"FROM supplier, nation\n"
            f"WHERE s_nationkey = n_nationkey\n"
            f"AND n_name = '{nation}'\n"
            f"AND EXISTS (SELECT 1 FROM excess_suppliers WHERE ps_suppkey = s_suppkey)\n"
            f"ORDER BY s_name;"
        )

        self.transformations_applied.append("q20_correlated_to_cte")
        return rewritten


def transform_query_for_datafusion(query: str, query_id: str | None = None, verbose: bool = False) -> str:
    transformer = DataFusionQueryTransformer(verbose=verbose)
    return transformer.transform(query, query_id=query_id)


__all__ = ["DataFusionQueryTransformer", "transform_query_for_datafusion"]
