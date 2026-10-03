# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import logging

from benchbox.core.expected_results.loader import load_tpch_expected_results, load_tpch_value_digests
from benchbox.core.expected_results.models import (
    BenchmarkExpectedResults,
    ExpectedQueryResult,
    ValidationMode,
)

logger = logging.getLogger(__name__)

TPCH_RANGE_ROW_COUNT_BOUNDS: dict[str, tuple[int, int]] = {
    "11": (514, 1469),
    "18": (9, 57),
    "20": (131, 231),
}

TPCH_LOOSE_QUERY_IDS: frozenset[str] = frozenset({"16"})

PARAMETER_SENSITIVE_QUERY_IDS: frozenset[str] = frozenset(TPCH_RANGE_ROW_COUNT_BOUNDS) | TPCH_LOOSE_QUERY_IDS


def get_tpch_expected_results(scale_factor: float = 1.0) -> BenchmarkExpectedResults | None:
    if scale_factor != 1.0:
        logger.info(
            f"TPC-H expected results only available for SF=1.0. "
            f"Validation will be skipped for SF={scale_factor}. "
            f"Note: Scale-independent queries (e.g., Q1) may still validate via registry fallback."
        )
        return None

    row_counts = load_tpch_expected_results(scale_factor=1.0)
    value_digests = load_tpch_value_digests(scale_factor=1.0)

    query_results = {}

    scale_independent_queries = {
        "1": True,
    }

    for query_id, row_count in row_counts.items():
        is_scale_independent = scale_independent_queries.get(query_id, False)

        range_bounds = TPCH_RANGE_ROW_COUNT_BOUNDS.get(query_id)
        if range_bounds is not None:
            expected_row_count_min, expected_row_count_max = range_bounds
            mode_notes = (
                f"Parameter-sensitive TPC-H query; EXACT against the answer file at the "
                f"reference seed, non-reference seeds accept the SF=1.0 row-count range "
                f"{expected_row_count_min}-{expected_row_count_max}."
            )
        elif query_id in TPCH_LOOSE_QUERY_IDS:
            expected_row_count_min = None
            expected_row_count_max = None
            mode_notes = (
                "Parameter-sensitive TPC-H query; EXACT against the answer file at the "
                "reference seed, non-reference seeds use the default ±50% loose row-count tolerance."
            )
        else:
            expected_row_count_min = None
            expected_row_count_max = None
            mode_notes = "Expected result from the TPC-H answer file; output cardinality is fixed for SF=1.0."

        query_results[query_id] = ExpectedQueryResult(
            query_id=query_id,
            scale_factor=scale_factor,
            expected_row_count=row_count,
            expected_row_count_min=expected_row_count_min,
            expected_row_count_max=expected_row_count_max,
            validation_mode=ValidationMode.EXACT,
            scale_independent=is_scale_independent,
            notes=f"{mode_notes} SF={scale_factor}",
            value_digest=value_digests.get(query_id),
        )

    return BenchmarkExpectedResults(
        benchmark_name="tpch",
        scale_factor=scale_factor,
        query_results=query_results,
        metadata={
            "source": "TPC-H answer files",
            "answer_files_scale_factor": 1.0,
            "total_queries": len(query_results),
            "value_digest_queries": sum(1 for r in query_results.values() if r.value_digest is not None),
        },
    )


from benchbox.core.expected_results.registry import register_benchmark_provider

register_benchmark_provider("tpch", get_tpch_expected_results)
