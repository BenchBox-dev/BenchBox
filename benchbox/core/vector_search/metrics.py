"""Vector search benchmark metrics.

Provides utility functions for computing recall@k, QPS, and latency
percentiles from benchmark results.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import statistics
from typing import Sequence


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

    Args:
        latencies_seconds: List of per-query latency values in seconds.

    Returns:
        Dict with keys ``p50``, ``p95``, ``p99`` (all in seconds).
        Returns zeros when the input is empty.
    """
    if not latencies_seconds:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    sorted_lat = sorted(latencies_seconds)
    n = len(sorted_lat)

    def _percentile(p: float) -> float:
        idx = (p / 100.0) * (n - 1)
        low = int(idx)
        frac = idx - low
        if low + 1 < n:
            return sorted_lat[low] + frac * (sorted_lat[low + 1] - sorted_lat[low])
        return sorted_lat[low]

    return {
        "p50": _percentile(50),
        "p95": _percentile(95),
        "p99": _percentile(99),
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
