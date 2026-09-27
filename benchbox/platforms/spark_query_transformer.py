"""Compatibility import for the shared TPC-Havoc Spark SQL transformer."""

from benchbox.core.tpchavoc.spark_query_transformer import (
    DUAL_VARIANT_IDS,
    GROUP_BY_EMPTY_VARIANT_IDS,
    SCALAR_GROUP_BY_VARIANT_IDS,
    SparkTPCHavocQueryTransformer,
)

__all__ = [
    "SparkTPCHavocQueryTransformer",
    "SCALAR_GROUP_BY_VARIANT_IDS",
    "GROUP_BY_EMPTY_VARIANT_IDS",
    "DUAL_VARIANT_IDS",
]
