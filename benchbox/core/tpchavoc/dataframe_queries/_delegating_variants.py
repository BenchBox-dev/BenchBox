"""Shared helpers for TPC-Havoc DataFrame variant registration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery
from benchbox.core.tpch.dataframe_queries import get_query as get_tpch_query

VariantImpl = Callable[[DataFrameContext], Any]

_VARIANT_STRATEGIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Baseline: direct delegation to the canonical TPC-H DataFrame implementation", ()),
    ("Projection replay: explicitly project canonical result columns after execution", ("project",)),
    ("Sort replay: explicitly replay canonical result ordering after execution", ("sort",)),
    ("Projection then sort: project canonical columns before replaying ordering", ("project", "sort")),
    ("Sort then projection: replay ordering before canonical result projection", ("sort", "project")),
    ("Double projection: repeat canonical projection to exercise projection idempotence", ("project", "project")),
    ("Double sort: repeat canonical ordering to exercise sort idempotence", ("sort", "sort")),
    (
        "Projection-sort-projection: bracket ordering with canonical result projection",
        ("project", "sort", "project"),
    ),
    (
        "Sort-projection-sort: bracket projection with canonical result ordering",
        ("sort", "project", "sort"),
    ),
    (
        "Full replay: repeat projection and ordering passes after canonical execution",
        ("project", "sort", "project", "sort"),
    ),
)


def make_variant_delegate(impl: VariantImpl, *, name: str, module: str) -> VariantImpl:
    """Return a named variant callable that delegates to an equivalent body."""

    def _variant(ctx: DataFrameContext) -> Any:
        return impl(ctx)

    _variant.__name__ = name
    _variant.__qualname__ = name
    _variant.__module__ = module
    return _variant


def build_result_replay_variants(
    query_number: int,
    *,
    result_columns: Sequence[str],
    sort_columns: Sequence[str] = (),
    descending: Sequence[bool] | None = None,
) -> list[DataFrameQuery]:
    """Build safe TPC-Havoc variants that replay canonical result operations.

    Q16-Q22 use complex correlated subquery and anti-join shapes. This helper
    preserves semantic equivalence by delegating the core query to the existing
    TPC-H implementation, then varying the final result operation sequence.
    """
    base_query = get_tpch_query(f"Q{query_number}")
    sort_descending = tuple(descending or (False for _ in sort_columns))
    return [
        DataFrameQuery(
            query_id=f"Q{query_number}v{variant_id}",
            query_name=f"TPC-H Q{query_number} Variant {variant_id}",
            description=description,
            categories=base_query.categories,
            expression_impl=_wrap_expression_impl(
                base_query.expression_impl,
                result_columns=result_columns,
                sort_columns=sort_columns,
                descending=sort_descending,
                steps=steps,
                name=f"q{query_number}_v{variant_id}_expression_impl",
            ),
            pandas_impl=_wrap_pandas_impl(
                base_query.pandas_impl,
                result_columns=result_columns,
                sort_columns=sort_columns,
                descending=sort_descending,
                steps=steps,
                name=f"q{query_number}_v{variant_id}_pandas_impl",
            ),
            expected_row_count=base_query.expected_row_count,
            scale_factor_dependent=base_query.scale_factor_dependent,
            timeout_seconds=base_query.timeout_seconds,
            skip_platforms=list(base_query.skip_platforms),
        )
        for variant_id, (description, steps) in enumerate(_VARIANT_STRATEGIES, start=1)
    ]


def _wrap_expression_impl(
    impl: VariantImpl | None,
    *,
    result_columns: Sequence[str],
    sort_columns: Sequence[str],
    descending: Sequence[bool],
    steps: Sequence[str],
    name: str,
) -> VariantImpl | None:
    if impl is None:
        return None

    def _variant(ctx: DataFrameContext) -> Any:
        result = impl(ctx)
        for step in steps:
            if step == "project":
                result = result.select(*result_columns)
            elif step == "sort" and sort_columns:
                result = result.sort(list(sort_columns), descending=list(descending))
        return result

    _variant.__name__ = name
    return _variant


def _wrap_pandas_impl(
    impl: VariantImpl | None,
    *,
    result_columns: Sequence[str],
    sort_columns: Sequence[str],
    descending: Sequence[bool],
    steps: Sequence[str],
    name: str,
) -> VariantImpl | None:
    if impl is None:
        return None

    def _variant(ctx: DataFrameContext) -> Any:
        result = impl(ctx)
        for step in steps:
            if step == "project":
                result = result.loc[:, list(result_columns)]
            elif step == "sort" and sort_columns:
                result = result.sort_values(list(sort_columns), ascending=[not value for value in descending])
        return result

    _variant.__name__ = name
    return _variant
