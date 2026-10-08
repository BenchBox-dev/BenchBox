# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import math
import statistics
from typing import Sequence

from benchbox.core.results.metrics import percentile_ms

_QUERY_LIMITS = {"Q1": 10, "Q2": 10, "Q3": 10, "Q4": 100, "Q5": 10, "Q6": 20}
_DISTANCE_QUERY = "Q2"


def validate_search_result(query_id: str, rows: Sequence[Sequence[object]]) -> None:
    normalized_query_id = str(query_id).strip().upper()
    if normalized_query_id not in _QUERY_LIMITS:
        raise ValueError(f"Unknown vector-search query: {query_id}")

    limit = _QUERY_LIMITS[normalized_query_id]
    if len(rows) > limit:
        raise ValueError(f"{normalized_query_id} returned {len(rows)} rows; expected at most {limit}")

    seen_ids: set[object] = set()
    metrics: list[float] = []
    for index, row in enumerate(rows):
        if len(row) != 2:
            raise ValueError(f"{normalized_query_id} row {index} must contain exactly id and metric columns")
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
    if not latencies_seconds:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    latencies_ms = [v * 1000.0 for v in latencies_seconds]
    return {
        "p50": percentile_ms(latencies_ms, 0.50) / 1000.0,
        "p95": percentile_ms(latencies_ms, 0.95) / 1000.0,
        "p99": percentile_ms(latencies_ms, 0.99) / 1000.0,
    }


def queries_per_second(total_queries: int, elapsed_seconds: float) -> float:
    if elapsed_seconds <= 0:
        return 0.0
    return total_queries / elapsed_seconds


def mean_latency(latencies_seconds: list[float]) -> float:
    return statistics.mean(latencies_seconds) if latencies_seconds else 0.0
