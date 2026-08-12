"""Vector search benchmark metrics.

Provides utility functions for computing recall@k, QPS, and latency
percentiles from benchmark results.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import math
import statistics
from typing import Sequence

from benchbox.core.results.metrics import percentile_ms

_QUERY_LIMITS = {"Q1": 10, "Q2": 10, "Q3": 10, "Q4": 100, "Q5": 10, "Q6": 20}
_DISTANCE_QUERY = "Q2"


def validate_search_result(query_id: str, rows: Sequence[Sequence[object]]) -> None:
    """Validate the engine-independent shape and ordering contract of a search result.

    This is a structural oracle for the vector-search benchmark.  It does not
    assert engine-specific nearest-neighbour IDs; it catches result-shape,
    duplicate-ID, non-finite-metric, and ordering regressions that a timing-only
    benchmark would otherwise report as successful.

    Args:
        query_id: One of Q1-Q6.
        rows: Rows returned by the query, with ``(id, metric)`` in that order.

    Raises:
        ValueError: If the result violates the query's published contract.
    """
    normalized_query_id = str(query_id).strip().upper()
    if normalized_query_id not in _QUERY_LIMITS:
        raise ValueError(f"Unknown vector-search query: {query_id}")

    limit = _QUERY_LIMITS[normalized_query_id]
    if len(rows) > limit:
        raise ValueError(f"{normalized_query_id} returned {len(rows)} rows; expected at most {limit}")

    seen_ids: set[object] = set()
    metrics: list[float] = []
    for index, row in enumerate(rows):
        if len(row) < 2:
            raise ValueError(f"{normalized_query_id} row {index} has no metric column")
        row_id = row[0]
        if row_id in seen_ids:
            raise ValueError(f"{normalized_query_id} returned duplicate id {row_id!r}")
        seen_ids.add(row_id)
        try:
            metric = float(row[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{normalized_query_id} row {index} has a non-numeric metric") from exc
        if not math.isfinite(metric):
            raise ValueError(f"{normalized_query_id} row {index} has a non-finite metric")
        metrics.append(metric)

    for previous, current in zip(metrics, metrics[1:]):
        if normalized_query_id == _DISTANCE_QUERY and previous > current:
            raise ValueError(f"{normalized_query_id} distance results are not ascending")
        if normalized_query_id != _DISTANCE_QUERY and previous < current:
            raise ValueError(f"{normalized_query_id} similarity results are not descending")


def recall_at_k(ground_truth: Sequence[int], approximate: Sequence[int], k: int) -> float:
    """Compute recall@k between an exact ground truth and an approximate result.

    recall@k = |intersection(gt[:k], approx[:k])| / k

    Args:
        ground_truth: Ordered sequence of true nearest-neighbour IDs (exact).
        approximate: Ordered sequence of approximate nearest-neighbour IDs.
        k: Number of results to consider from each sequence.

    Returns:
        Recall value in [0.0, 1.0].
    """
    if k <= 0:
        return 0.0
    gt_set = set(list(ground_truth)[:k])
    approx_set = set(list(approximate)[:k])
    if not gt_set:
        return 0.0
    return len(gt_set & approx_set) / k


def latency_percentiles(
    latencies_seconds: list[float],
) -> dict[str, float]:
    """Compute p50, p95, and p99 latency percentiles.

    Delegates to :func:`benchbox.core.results.metrics.percentile_ms` so
    that vector-search surfaces and result bundles share one
    nearest-rank definition. Values are in seconds; convert to
    milliseconds for the canonical helper, then back to seconds.

    Args:
        latencies_seconds: List of per-query latency values in seconds.

    Returns:
        Dict with keys ``p50``, ``p95``, ``p99`` (all in seconds).
        Returns zeros when the input is empty.
    """
    if not latencies_seconds:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    latencies_ms = [v * 1000.0 for v in latencies_seconds]
    return {
        "p50": percentile_ms(latencies_ms, 0.50) / 1000.0,
        "p95": percentile_ms(latencies_ms, 0.95) / 1000.0,
        "p99": percentile_ms(latencies_ms, 0.99) / 1000.0,
    }


def queries_per_second(total_queries: int, elapsed_seconds: float) -> float:
    """Compute queries per second.

    Args:
        total_queries: Number of queries executed.
        elapsed_seconds: Wall-clock seconds elapsed.

    Returns:
        QPS value, or 0.0 if ``elapsed_seconds`` is zero.
    """
    if elapsed_seconds <= 0:
        return 0.0
    return total_queries / elapsed_seconds


def mean_latency(latencies_seconds: list[float]) -> float:
    """Arithmetic mean latency.

    Args:
        latencies_seconds: Per-query latency values in seconds.

    Returns:
        Mean latency in seconds, or 0.0 for an empty list.
    """
    return statistics.mean(latencies_seconds) if latencies_seconds else 0.0
