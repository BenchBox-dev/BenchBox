"""Query transformation utilities for Spark SQL TPC-Havoc compatibility.

Spark's analyzer rejects two SQL shapes used by TPC-Havoc variants:

- Correlated scalar subqueries in the SELECT list of an aggregated query
  (``SCALAR_SUBQUERY_IS_IN_GROUP_BY_OR_AGGREGATE_FUNCTION``). The scalar is
  correlated on the GROUP BY keys, so it is constant per group; wrapping it in
  ``first()`` preserves semantics while satisfying the analyzer.
- Empty grouping (``GROUP BY ()``), which the Spark parser rejects outright.
  Dropping the empty grouping keeps the single-group aggregate semantics
  (``HAVING`` without ``GROUP BY`` is valid on both Spark and DuckDB).
- The ``(SELECT 1) AS dual`` leg of the Q17 UNION ALL variant, which has no
  explicit column alias. Adding one hardens the variant across Spark versions
  and Spark-Connect engines.

Import discipline: the Spark adapter imports ``SparkTPCHavocQueryTransformer``
lazily inside ``execute_query``. Tests should patch this source-module name
(``benchbox.platforms.spark_query_transformer.SparkTPCHavocQueryTransformer``)
before calling ``execute_query``; there is no stable module-level binding on
``benchbox.platforms.spark`` to patch.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

# Variant IDs using a correlated scalar subquery in the SELECT list of a
# GROUP BY query. Verified against Spark 4.2
# (``SCALAR_SUBQUERY_IS_IN_GROUP_BY_OR_AGGREGATE_FUNCTION``).
SCALAR_GROUP_BY_VARIANT_IDS: frozenset[str] = frozenset(
    {
        "1_v1",
        "3_v1",
        "7_v1",
        "8_v1",
        "9_v1",
        "10_v1",
        "12_v1",
        "16_v1",
    }
)

# Variant IDs using empty grouping (``GROUP BY ()``), which the Spark parser
# rejects with ``PARSE_SYNTAX_ERROR``.
GROUP_BY_EMPTY_VARIANT_IDS: frozenset[str] = frozenset({"6_v2", "14_v2"})

# Variant IDs using the ``(SELECT 1) AS dual`` UNION ALL leg.
DUAL_VARIANT_IDS: frozenset[str] = frozenset({"17_v4"})


class SparkTPCHavocQueryTransformer:
    """Transform TPC-Havoc variant SQL for Spark compatibility.

    Uses variant-ID-based dispatch to apply targeted rewrites for the specific
    TPC-Havoc variants Spark rejects. Follows the same pattern as
    DataFusionQueryTransformer. All other queries pass through unchanged.
    """

    def __init__(self, verbose: bool = False):
        """Initialize query transformer.

        Args:
            verbose: Enable verbose logging of transformations
        """
        self.verbose = verbose
        self.transformations_applied: list[str] = []

    def transform(self, query: str, query_id: str | None = None) -> str:
        """Apply Spark-specific transformations to a TPC-Havoc variant query.

        Args:
            query: Original SQL query
            query_id: Optional variant identifier (e.g., "1_v1", "Q17_V4")

        Returns:
            Transformed SQL query compatible with Spark
        """
        self.transformations_applied = []

        normalized_id = self.normalize_query_id(query_id)

        if normalized_id in SCALAR_GROUP_BY_VARIANT_IDS:
            query = self._rewrite_scalar_group_by(query)
        elif normalized_id in GROUP_BY_EMPTY_VARIANT_IDS:
            query = self._rewrite_group_by_empty(query)
        elif normalized_id in DUAL_VARIANT_IDS:
            query = self._rewrite_dual(query)

        if self.verbose and self.transformations_applied:
            logger.debug(f"Applied transformations: {', '.join(self.transformations_applied)}")

        return query

    def get_transformations_applied(self) -> list[str]:
        """Return list of transformations applied to last query.

        Returns:
            List of transformation names
        """
        return self.transformations_applied

    @classmethod
    def known_variant_ids(cls) -> frozenset[str]:
        """All TPC-Havoc variant IDs this transformer rewrites."""
        return SCALAR_GROUP_BY_VARIANT_IDS | GROUP_BY_EMPTY_VARIANT_IDS | DUAL_VARIANT_IDS

    def normalize_query_id(self, query_id: str | None) -> str | None:
        """Normalize a TPC-Havoc variant ID to "<query>_v<variant>" form.

        Args:
            query_id: Raw variant ID (e.g., "Q1_V1", "1-v1", "1_v1", "Q01_V1")

        Returns:
            Normalized ID (e.g., "1_v1") or None
        """
        if query_id is None:
            return None
        qid = str(query_id).strip().lower()
        if qid.startswith("q"):
            qid = qid[1:]
        qid = qid.replace("-", "_")
        if "_v" in qid:
            q_num, _, v_num = qid.partition("_v")
            qid = f"{q_num.lstrip('0') or '0'}_v{v_num}"
        return qid

    # Backward-compatible alias.
    _normalize_query_id = normalize_query_id

    def _rewrite_scalar_group_by(self, query: str) -> str:
        """Wrap bare SELECT-list scalar subqueries in ``first()``.

        Spark requires a correlated scalar subquery in an aggregated query to
        appear in GROUP BY or inside an aggregate function. Each rewritten
        scalar is correlated on the GROUP BY keys, hence constant per group,
        so ``first()`` preserves semantics.
        """
        tree = sqlglot.parse_one(query, read="duckdb")
        applied = False
        for select in tree.find_all(exp.Select):
            if not select.args.get("group"):
                continue
            new_projections = []
            select_changed = False
            for projection in select.expressions:
                new_projection = self._wrap_bare_scalars(projection)
                new_projections.append(new_projection)
                select_changed |= new_projection is not projection
            if select_changed:
                select.set("expressions", new_projections)
                applied = True
        if not applied:
            return query
        self.transformations_applied.append("scalar_group_by_first")
        return tree.sql(dialect="duckdb")

    def _wrap_bare_scalars(self, node):  # type: ignore[no-untyped-def]
        """Wrap scalar-subquery nodes not already inside an aggregate.

        Stops at subquery, aggregate, membership-test, and nested-SELECT
        boundaries so inner-query shapes are never rewritten.
        """
        from sqlglot import exp

        if isinstance(node, exp.Subquery):
            return exp.First(this=node)
        if isinstance(node, (exp.AggFunc, exp.Exists, exp.In, exp.Any, exp.All, exp.Window)):
            return node
        if isinstance(node, exp.Select):
            return node
        args: dict = {}
        changed = False
        for key, value in node.args.items():
            if isinstance(value, exp.Expr):
                new_value = self._wrap_bare_scalars(value)
                args[key] = new_value
                changed |= new_value is not value
            elif isinstance(value, list):
                new_list = [self._wrap_bare_scalars(item) if isinstance(item, exp.Expr) else item for item in value]
                args[key] = new_list
                changed |= any(new is not old for new, old in zip(new_list, value))
            else:
                args[key] = value
        if not changed:
            return node
        new_node = node.__class__(**args)
        new_node.comments = node.comments
        return new_node

    def _rewrite_group_by_empty(self, query: str) -> str:
        """Drop empty grouping (``GROUP BY ()``) Spark cannot parse.

        With no GROUP BY the aggregate still computes a single group, so the
        accompanying ``HAVING`` keeps its semantics on Spark and DuckDB.
        """
        tree = sqlglot.parse_one(query, read="duckdb")
        applied = False
        for select in tree.find_all(exp.Select):
            group = select.args.get("group")
            if group and len(group.expressions) == 1:
                only = group.expressions[0]
                if isinstance(only, exp.Tuple) and not only.expressions:
                    select.set("group", None)
                    applied = True
        if not applied:
            return query
        self.transformations_applied.append("group_by_empty_drop")
        return tree.sql(dialect="duckdb")

    def _rewrite_dual(self, query: str) -> str:
        """Give the ``(SELECT 1) AS dual`` leg an explicit column alias."""
        tree = sqlglot.parse_one(query, read="duckdb")
        applied = False
        for subquery in tree.find_all(exp.Subquery):
            inner = subquery.this
            if not isinstance(inner, exp.Select) or len(inner.expressions) != 1:
                continue
            only = inner.expressions[0]
            if isinstance(only, exp.Alias):
                continue
            if isinstance(only, exp.Literal) and only.this == "1" and not only.args.get("is_string"):
                only.replace(exp.alias_(only.copy(), "dual_col"))
                applied = True
        if not applied:
            return query
        self.transformations_applied.append("dual_column_alias")
        return tree.sql(dialect="duckdb")


__all__ = [
    "SparkTPCHavocQueryTransformer",
    "SCALAR_GROUP_BY_VARIANT_IDS",
    "GROUP_BY_EMPTY_VARIANT_IDS",
    "DUAL_VARIANT_IDS",
]
