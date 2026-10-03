from __future__ import annotations

import importlib
import logging
from dataclasses import replace
from typing import Any
from unittest.mock import DEFAULT

from benchbox.core.dataframe.query import QueryRegistry
from benchbox.core.results.builder import normalize_benchmark_id

logger = logging.getLogger(__name__)


def benchmark_defines_dataframe_hook(benchmark: Any | None, hook_name: str) -> bool:

    if benchmark is None:
        return False

    hook = type(benchmark).__dict__.get(hook_name)
    if callable(hook):
        return True

    instance_hook = benchmark.__dict__.get(hook_name)
    if callable(instance_hook):
        return True

    mock_children = getattr(benchmark, "_mock_children", None)
    if not isinstance(mock_children, dict):
        return False

    child = mock_children.get(hook_name)
    if child is None:
        return False

    return (
        getattr(child, "_mock_return_value", DEFAULT) is not DEFAULT
        or getattr(child, "_mock_side_effect", None) is not None
        or getattr(child, "_mock_wraps", None) is not None
    )


def benchmark_provides_dataframe_queries(benchmark: Any | None) -> bool:

    return benchmark_defines_dataframe_hook(benchmark, "get_dataframe_queries")


def build_dataframe_query_filter(query_subset: Any) -> set[str] | None:

    if not query_subset:
        return None

    normalized: set[str] = set()
    for query_id in query_subset:
        q_str = str(query_id).strip().upper()
        if q_str.startswith("Q"):
            normalized.add(q_str)
            normalized.add(q_str[1:])
        else:
            normalized.add(q_str)
            normalized.add(f"Q{q_str}")
    return normalized


def build_dataframe_query_filter_from_config(benchmark_config: Any) -> set[str] | None:

    return build_dataframe_query_filter(getattr(benchmark_config, "queries", None))


def get_dataframe_queries_for_benchmark(
    benchmark_config: Any,
    benchmark_instance: Any | None,
    stream_id: int | None = None,
) -> list[Any]:

    benchmark_id = normalize_benchmark_id(benchmark_config.name)
    if stream_id is None:
        stream_id = getattr(benchmark_config, "stream_id", 0)

    if benchmark_id == "tpch":
        return get_tpch_dataframe_queries(stream_id)
    if benchmark_id == "tpcds":
        return get_tpcds_dataframe_queries(benchmark_config, benchmark_instance, stream_id)
    if benchmark_id == "clickbench":
        return get_clickbench_dataframe_queries(benchmark_config, benchmark_instance, stream_id)

    if benchmark_provides_dataframe_queries(benchmark_instance):
        benchmark_queries = benchmark_instance.get_dataframe_queries()
        if isinstance(benchmark_queries, list):
            return benchmark_queries
        if hasattr(benchmark_queries, "get_all_queries"):
            return benchmark_queries.get_all_queries()
        logger.warning(
            "Unsupported DataFrame query container type: %s",
            type(benchmark_queries).__name__,
        )

    return registry_dataframe_queries(benchmark_id)


def registry_dataframe_queries(benchmark_id: str) -> list[Any]:

    target = f"benchbox.core.{benchmark_id}.dataframe_queries"
    try:
        module = importlib.import_module(target)
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == target or target.startswith(f"{exc.name}.")):
            return []
        raise

    registries = {id(value): value for value in vars(module).values() if isinstance(value, QueryRegistry)}
    if not registries:
        return []
    if len(registries) > 1:
        raise RuntimeError(f"Multiple DataFrame query registries found in {target}; resolution is ambiguous")
    return next(iter(registries.values())).get_all_queries()


def get_tpch_dataframe_queries(stream_id: int) -> list[Any]:

    from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES
    from benchbox.core.tpch.streams import TPCHStreams

    query_permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id % len(TPCHStreams.PERMUTATION_MATRIX)]

    queries: list[Any] = []
    for query_num in query_permutation:
        query_id = f"Q{query_num}"
        query = TPCH_DATAFRAME_QUERIES.get(query_id)
        if query:
            queries.append(query)
        else:
            logger.warning("Query %s not found in TPC-H DataFrame registry", query_id)
    return queries


def resolve_tpcds_query_manager(benchmark_instance: Any | None) -> Any | None:

    if benchmark_instance and hasattr(benchmark_instance, "query_manager"):
        return benchmark_instance.query_manager
    if (
        benchmark_instance
        and hasattr(benchmark_instance, "_impl")
        and hasattr(benchmark_instance._impl, "query_manager")
    ):
        return benchmark_instance._impl.query_manager
    return None


def get_tpcds_legacy_queries(available_query_ids: list[int], stream_id: int) -> list[Any]:

    from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES
    from benchbox.core.tpcds.streams import PermutationMode, TPCDSPermutationGenerator

    logger.warning("TPC-DS query_manager unavailable; using legacy 99-query DataFrame ordering")
    generator = TPCDSPermutationGenerator(seed=42 + stream_id)
    query_permutation = generator.generate_permutation(available_query_ids, PermutationMode.TPCDS_STANDARD)

    queries: list[Any] = []
    for query_num in query_permutation:
        query_id = f"Q{query_num}"
        query = TPCDS_DATAFRAME_QUERIES.get(query_id)
        if query:
            queries.append(query)
    return queries


def resolve_tpcds_stream_queries(stream_queries: list[Any], allow_variant_fallback: bool) -> list[Any]:

    from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

    queries: list[Any] = []
    missing_variants: list[str] = []
    for stream_query in stream_queries:
        base_query_id = f"Q{stream_query.query_id}"
        base_query = TPCDS_DATAFRAME_QUERIES.get(base_query_id)
        if base_query is None:
            logger.warning("Query %s not found in TPC-DS DataFrame registry", base_query_id)
            continue

        if stream_query.variant is None:
            queries.append(base_query)
            continue

        variant_id = f"{base_query_id}{stream_query.variant.lower()}"
        variant_query = (
            TPCDS_DATAFRAME_QUERIES.get(variant_id)
            or TPCDS_DATAFRAME_QUERIES.get(variant_id.upper())
            or TPCDS_DATAFRAME_QUERIES.get(variant_id.capitalize())
        )
        if variant_query is not None:
            queries.append(variant_query)
            continue

        missing_variants.append(variant_id)
        if allow_variant_fallback:
            queries.append(replace(base_query, query_id=variant_id))

    if missing_variants and not allow_variant_fallback:
        missing = ", ".join(sorted(set(missing_variants)))
        raise RuntimeError(
            "TPC-DS DataFrame SQL parity check failed: missing variant DataFrame implementations "
            f"for [{missing}]. Set option tpcds_dataframe_variant_fallback=true to allow "
            "non-parity fallback execution."
        )

    return queries


def get_tpcds_dataframe_queries(
    benchmark_config: Any,
    benchmark_instance: Any | None,
    stream_id: int,
) -> list[Any]:

    from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES
    from benchbox.core.tpcds.streams import create_standard_streams

    options_map = getattr(benchmark_config, "options", {}) or {}
    allow_variant_fallback = bool(options_map.get("tpcds_dataframe_variant_fallback", True))

    available_query_ids = sorted(
        int(qid[1:])
        for qid in TPCDS_DATAFRAME_QUERIES.get_query_ids()
        if qid.upper().startswith("Q") and qid[1:].isdigit()
    )

    query_manager = resolve_tpcds_query_manager(benchmark_instance)
    if query_manager is None:
        return get_tpcds_legacy_queries(available_query_ids, stream_id)

    stream_manager = create_standard_streams(
        query_manager=query_manager,
        num_streams=1,
        query_ids=available_query_ids,
        query_range=(1, 99),
        base_seed=42 + stream_id,
    )
    stream_queries = stream_manager.generate_streams().get(0, [])
    return resolve_tpcds_stream_queries(stream_queries, allow_variant_fallback)


def get_clickbench_dataframe_queries(
    benchmark_config: Any,
    benchmark_instance: Any | None,
    stream_id: int,
) -> list[Any]:

    from benchbox.core.clickbench.dataframe_queries import CLICKBENCH_DATAFRAME_QUERIES

    return CLICKBENCH_DATAFRAME_QUERIES.get_all_queries()
