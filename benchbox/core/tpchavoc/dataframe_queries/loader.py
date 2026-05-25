"""YAML loader for TPC-Havoc DataFrame variant registries."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory

VariantImpl = Callable[..., Any]

AGG_FILTER = (QueryCategory.AGGREGATE, QueryCategory.FILTER)
AGG_GROUP_FILTER = (QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.FILTER)
JOIN_AGG_FILTER = (QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER)
JOIN_AGG_GROUP_BY = (QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY)
JOIN_AGG_SORT = (QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.SORT)
JOIN_AGG_SUBQUERY = (QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.SUBQUERY)
JOIN_SUBQUERY_SORT = (QueryCategory.JOIN, QueryCategory.SUBQUERY, QueryCategory.SORT)


def load_variant_specs(
    module_file: str, namespace: dict[str, Any]
) -> tuple[list[tuple[VariantImpl, VariantImpl]], list[str]]:
    """Load variant implementation pairs and descriptions from YAML next to a module."""
    with Path(module_file).with_suffix(".yaml").open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    pairs: list[tuple[VariantImpl, VariantImpl]] = []
    descriptions: list[str] = []
    for entry in payload["variants"]:
        pairs.append((namespace[entry["expression_impl"]], namespace[entry["pandas_impl"]]))
        descriptions.append(entry["description"])
    return pairs, descriptions


def build_variants(
    query_number: int,
    impl_pairs: Sequence[tuple[VariantImpl, VariantImpl]],
    descriptions: Sequence[str],
    categories: Sequence[QueryCategory],
) -> list[DataFrameQuery]:
    """Build TPC-Havoc DataFrame variants from already-resolved impl pairs."""
    return [
        DataFrameQuery(
            query_id=f"Q{query_number}v{variant}",
            query_name=f"TPC-H Q{query_number} Variant {variant}",
            description=descriptions[variant - 1],
            categories=list(categories),
            expression_impl=expr_impl,
            pandas_impl=pandas_impl,
        )
        for variant, (expr_impl, pandas_impl) in enumerate(impl_pairs, start=1)
    ]


def build_yaml_variants(
    module_file: str,
    namespace: dict[str, Any],
    query_number: int,
    categories: Sequence[QueryCategory],
) -> list[DataFrameQuery]:
    """Build TPC-Havoc variants from the YAML file next to a query module."""
    impl_pairs, descriptions = load_variant_specs(module_file, namespace)
    return build_variants(query_number, impl_pairs, descriptions, categories)
