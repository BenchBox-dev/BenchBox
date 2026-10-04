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

# Q16 retains the model's default ±50% tolerance because its full parameter
# domain is combinatorial and no defensible exhaustive RANGE bound is available.
TPCH_LOOSE_QUERY_IDS: frozenset[str] = frozenset({"16"})

# The bounded correctness gate still excludes this set from its separate
# reference-seed value oracle; the runtime row-count validator relaxes these
# queries from EXACT to the RANGE/LOOSE specifications here only under a
# non-reference seed, instead of skipping them.
PARAMETER_SENSITIVE_QUERY_IDS: frozenset[str] = frozenset(TPCH_RANGE_ROW_COUNT_BOUNDS) | TPCH_LOOSE_QUERY_IDS


def get_tpch_expected_results(scale_factor: float = 1.0) -> BenchmarkExpectedResults | None:
    """Get expected results for TPC-H queries at a given scale factor.

    This function loads expected row counts from TPC-H answer files (SF=1.0 only currently).
    For scale factors other than 1.0, returns None to trigger graceful validation skip.
    Scale-independent queries can still be validated via registry fallback to SF=1.0.

    Args:
        scale_factor: Scale factor (currently only 1.0 is supported from answer files)

    Returns:
        BenchmarkExpectedResults with all TPC-H query expectations, or None if SF != 1.0
    """
    # Only SF=1.0 is supported - return None for others to trigger graceful SKIP
    if scale_factor != 1.0:
        logger.info(
            f"TPC-H expected results only available for SF=1.0. "
            f"Validation will be skipped for SF={scale_factor}. "
            f"Note: Scale-independent queries (e.g., Q1) may still validate via registry fallback."
        )
        return None

    # Load row counts from answer files (SF=1.0)
    row_counts = load_tpch_expected_results(scale_factor=1.0)
    # Load stored reference VALUE digests (SF=1.0, pinned reference seed). Backs the
    # bounded correctness gate's value oracle; absent queries fall back to row-count
    # only. Keyed by the same query IDs as the row counts.
    value_digests = load_tpch_value_digests(scale_factor=1.0)

    # Build ExpectedQueryResult objects
    query_results = {}

    # Queries that are scale-independent (same result count regardless of scale factor)
    scale_independent_queries = {
        "1": True,  # Groups by L_RETURNFLAG, L_LINESTATUS (4 combinations)
        # Most other queries are scale-dependent
    }

    for query_id, row_count in row_counts.items():
        is_scale_independent = scale_independent_queries.get(query_id, False)

        range_bounds = TPCH_RANGE_ROW_COUNT_BOUNDS.get(query_id)
        if range_bounds is not None:
            expected_row_count_min, expected_row_count_max = range_bounds
            mode_notes = (
                f"Parameter-sensitive TPC-H query; EXACT against the answer file at the "
                f"qgen -d defaults; randomized parameters accept the SF=1.0 row-count range "
                f"{expected_row_count_min}-{expected_row_count_max}."
            )
        elif query_id in TPCH_LOOSE_QUERY_IDS:
            expected_row_count_min = None
            expected_row_count_max = None
            mode_notes = (
                "Parameter-sensitive TPC-H query; EXACT against the answer file at the "
                "qgen -d defaults; randomized parameters use the default ±50% loose row-count tolerance."
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


# Register the provider with the global registry
from benchbox.core.expected_results.registry import register_benchmark_provider

register_benchmark_provider("tpch", get_tpch_expected_results)
