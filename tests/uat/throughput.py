from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from benchbox.core.results.metrics import TPCMetricsCalculator

TPC_ALLOWED_SCALE_FACTORS = {1, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000}


def resolve_official_result_path(
    results_dir: Path,
    *,
    platform: str,
    benchmark: str,
    started_after: _dt.datetime,
    scale: float | None = None,
    emitted_path: str | None = None,
) -> Path | None:
    _ = (platform, benchmark, started_after, scale)
    if not emitted_path:
        return None
    path = Path(emitted_path).expanduser()
    if path.is_absolute() or path.exists():
        return path
    runs_dir = results_dir.parent
    if len(path.parts) >= 2 and path.parts[0] == "benchmark_runs":
        return runs_dir.parent / path
    return runs_dir / path


def validate_stream_count(
    result_json: dict[str, Any],
    *,
    requested_streams: int,
) -> tuple[bool, str]:
    queries = result_json.get("queries") or []
    streams_seen = {
        query.get("stream") for query in queries if isinstance(query, dict) and query.get("stream") is not None
    }
    executed = len(streams_seen)
    if executed != requested_streams:
        return (
            False,
            f"throughput stream count mismatch: requested {requested_streams}, executed {executed}",
        )
    return True, "ok"


def validate_stream_success(result_json: dict[str, Any]) -> tuple[bool, str]:
    queries = result_json.get("queries") or []
    stream_has_success: dict[Any, bool] = {}
    for query in queries:
        if not isinstance(query, dict):
            continue
        stream_id = query.get("stream")
        if stream_id is None:
            continue
        is_success = str(query.get("status", "")).upper() == "SUCCESS"
        stream_has_success[stream_id] = stream_has_success.get(stream_id, False) or is_success

    failed_streams = sorted(stream_id for stream_id, has_success in stream_has_success.items() if not has_success)
    if failed_streams:
        return (
            False,
            f"stream(s) {failed_streams} executed but had zero SUCCESSFUL queries",
        )
    return True, "ok"


def validate_throughput_metric(result_json: dict[str, Any]) -> tuple[bool, str]:
    tpc_metrics = (result_json.get("summary") or {}).get("tpc_metrics") or {}
    throughput_at_size = tpc_metrics.get("throughput_at_size")
    if not isinstance(throughput_at_size, (int, float)) or throughput_at_size <= 0:
        return False, f"Throughput@Size not positive (got {throughput_at_size!r})"

    queries = result_json.get("queries") or []
    total_queries = sum(1 for query in queries if isinstance(query, dict) and "stream" in query)
    scale_factor = (result_json.get("benchmark") or {}).get("scale_factor")
    duration_ms = ((result_json.get("phases") or {}).get("throughput_test") or {}).get("duration_ms")
    if not isinstance(scale_factor, (int, float)) or scale_factor <= 0:
        return False, f"Throughput@Size plausibility unavailable: invalid scale factor {scale_factor!r}"
    if not isinstance(duration_ms, (int, float)) or duration_ms <= 0:
        return False, f"Throughput@Size plausibility unavailable: invalid throughput duration {duration_ms!r}"

    stream_ids = {query.get("stream") for query in queries if isinstance(query, dict) and "stream" in query}
    expected = TPCMetricsCalculator.calculate_throughput_at_size(
        total_queries=total_queries,
        total_time_seconds=duration_ms / 1000.0,
        scale_factor=float(scale_factor),
        num_streams=len(stream_ids),
    )
    lower_bound = expected / 2.0
    upper_bound = expected * 2.0
    if not lower_bound <= throughput_at_size <= upper_bound:
        return False, (
            f"Throughput@Size outside plausibility band: got {throughput_at_size:.2f}, "
            f"expected {expected:.2f} ({lower_bound:.2f}..{upper_bound:.2f})"
        )
    return True, "ok"


def validate_throughput_result(
    result_json: dict[str, Any],
    *,
    requested_streams: int,
) -> tuple[bool, str]:
    ok, reason = validate_stream_count(result_json, requested_streams=requested_streams)
    if not ok:
        return ok, reason
    ok, reason = validate_stream_success(result_json)
    if not ok:
        return ok, reason
    return validate_throughput_metric(result_json)
