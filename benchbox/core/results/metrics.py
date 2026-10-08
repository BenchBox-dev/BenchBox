from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

NAMED_METRICS = ("geometric_mean", "p50", "p95", "p99", "total_time", "mean")

NON_POWER_TEST_TYPES = frozenset({"throughput", "maintenance"})
UNOFFICIAL_COMPLIANCE_CLASSES = frozenset({"unofficial_subscale", "unofficial_nonstandard"})
TPC_QUERIES_PER_STREAM = {"tpch": 22, "tpcds": 99}
_TPC_BENCHMARK_LABELS = {"tpch": "TPC-H", "tpcds": "TPC-DS"}


def percentile_ms(times_ms: Sequence[float], p: float) -> float:
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"percentile must be a fraction in [0, 1], got {p!r} (use 0.95 for p95, not 95)")

    sorted_times = sorted(times_ms)
    n = len(sorted_times)
    if n == 0:
        return 0.0
    rank = min(max(1, math.ceil(n * p)), n)
    return sorted_times[rank - 1]


def geometric_mean_ms(times_ms: Sequence[float]) -> float:
    positive = [t for t in times_ms if t > 0]
    if not positive:
        return 0.0
    return statistics.geometric_mean(positive)


def sample_stdev_ms(times_ms: Sequence[float]) -> float:
    times_list = list(times_ms)
    if len(times_list) < 2:
        return 0.0
    return statistics.stdev(times_list)


def calculate_named_metric(times_ms: Sequence[float], metric: str) -> float:
    times_list = list(times_ms)
    if not times_list:
        return 0.0

    if metric == "geometric_mean":
        return geometric_mean_ms(times_list)
    if metric == "p50":
        return percentile_ms(times_list, 0.50)
    if metric == "p95":
        return percentile_ms(times_list, 0.95)
    if metric == "p99":
        return percentile_ms(times_list, 0.99)
    if metric == "total_time":
        return sum(times_list)
    return statistics.mean(times_list)


class TPCMetricsCalculator:
    @staticmethod
    def calculate_power_at_size(
        query_times_seconds: Sequence[float],
        scale_factor: float,
    ) -> float:
        if not query_times_seconds:
            return 0.0

        valid_times = [t for t in query_times_seconds if t > 0]
        if not valid_times:
            return 0.0

        geometric_mean = statistics.geometric_mean(valid_times)
        if geometric_mean <= 0:
            return 0.0

        return (scale_factor * 3600) / geometric_mean

    @staticmethod
    def calculate_throughput_at_size(
        total_queries: int,
        total_time_seconds: float,
        scale_factor: float,
        num_streams: int = 1,
    ) -> float:
        if total_time_seconds <= 0 or num_streams <= 0:
            return 0.0

        return (total_queries * scale_factor * 3600) / total_time_seconds

    @staticmethod
    def calculate_geometric_mean(times: Sequence[float]) -> float:
        return geometric_mean_ms(times)

    @staticmethod
    def resolve_scale_factor(
        power_data: dict,
        throughput_data: dict,
        scale_factor: float | None = None,
    ) -> float:
        if scale_factor is not None:
            return scale_factor
        sf_power = power_data.get("environment", {}).get("scale_factor") or power_data.get("benchmark", {}).get(
            "scale_factor"
        )
        sf_throughput = throughput_data.get("environment", {}).get("scale_factor") or throughput_data.get(
            "benchmark", {}
        ).get("scale_factor")
        if sf_power and sf_throughput:
            if sf_power != sf_throughput:
                raise ValueError(f"Scale factor mismatch: power={sf_power}, throughput={sf_throughput}")
            return sf_power
        raise ValueError("Could not auto-detect scale factor. Please specify --scale-factor")

    @staticmethod
    def metrics_refusal_reason(data: dict, label: str) -> str | None:
        summary = data.get("summary", {})
        tpc_metrics = summary.get("tpc_metrics") or {}
        if tpc_metrics.get("suppressed"):
            return f"{label} results have suppressed TPC metrics ({tpc_metrics.get('reason', 'suppressed')})"
        compliance_class = (data.get("benchmark") or {}).get("compliance_class")
        if compliance_class in UNOFFICIAL_COMPLIANCE_CLASSES:
            return f"{label} results are {compliance_class} and carry no official TPC metrics"
        failed = (summary.get("queries") or {}).get("failed") or 0
        if failed:
            return f"{label} results contain {failed} failed queries"
        throughput_phase = (data.get("phases") or {}).get("throughput_test") or {}
        if throughput_phase.get("status") == "FAILED":
            return f"{label} results have a failed throughput phase"
        return None

    @staticmethod
    def derive_tpc_metrics(
        power_data: dict,
        throughput_data: dict,
        scale_factor: float,
    ) -> tuple[float | None, float | None, float | None, float | None]:
        for label, data in (("Power", power_data), ("Throughput", throughput_data)):
            reason = TPCMetricsCalculator.metrics_refusal_reason(data, label)
            if reason:
                raise ValueError(reason)

        power_metrics = power_data.get("summary", {}).get("tpc_metrics", {})
        throughput_metrics = throughput_data.get("summary", {}).get("tpc_metrics", {})
        power_at_size = power_metrics.get("power_at_size")
        throughput_at_size = throughput_metrics.get("throughput_at_size")

        power_times = TPCMetricsCalculator._final_power_iteration_times(power_data)
        power_time = sum(power_times) if power_times else None
        if power_at_size is None and power_times:
            power_at_size = TPCMetricsCalculator.calculate_power_at_size(power_times, scale_factor)

        phase = (throughput_data.get("phases") or {}).get("throughput_test") or {}
        duration_ms = phase.get("duration_ms")
        throughput_time = duration_ms / 1000.0 if duration_ms else None
        if throughput_at_size is None and throughput_time and phase.get("status") == "COMPLETED":
            num_streams = len(phase.get("stream_results") or []) or throughput_data.get("run", {}).get("streams") or 1
            per_stream = TPC_QUERIES_PER_STREAM.get(throughput_data.get("benchmark", {}).get("id"))
            if per_stream:
                throughput_at_size = TPCMetricsCalculator.calculate_throughput_at_size(
                    per_stream * num_streams,
                    throughput_time,
                    scale_factor,
                    num_streams,
                )
        return power_at_size, throughput_at_size, power_time, throughput_time

    @staticmethod
    def _final_power_iteration_times(power_data: dict) -> list[float]:
        rows = [
            q
            for q in power_data.get("queries", [])
            if q.get("run_type") == "measurement"
            and q.get("status") == "SUCCESS"
            and q.get("test_type") not in NON_POWER_TEST_TYPES
            and q.get("ms")
        ]
        if not rows:
            return []
        final_iteration = max(q.get("iter") or 0 for q in rows)
        return [q["ms"] / 1000.0 for q in rows if (q.get("iter") or 0) == final_iteration]

    @staticmethod
    def compute_qphh_result(
        power_data: dict,
        throughput_data: dict,
        scale_factor: float | None = None,
    ) -> dict:
        sf = TPCMetricsCalculator.resolve_scale_factor(power_data, throughput_data, scale_factor)
        power_at_size, throughput_at_size, power_time, throughput_time = TPCMetricsCalculator.derive_tpc_metrics(
            power_data, throughput_data, sf
        )
        if power_at_size is None or throughput_at_size is None:
            raise ValueError("Could not derive Power@Size or Throughput@Size from result data")
        throughput_phase = (throughput_data.get("phases") or {}).get("throughput_test") or {}
        num_streams = (
            len(throughput_phase.get("stream_results") or [])
            or throughput_data.get("run", {}).get("streams")
            or throughput_data.get("environment", {}).get("num_streams", 1)
        )
        benchmark = throughput_data.get("benchmark", {})
        return {
            "benchmark": benchmark.get("name") or _TPC_BENCHMARK_LABELS.get(benchmark.get("id"), "TPC"),
            "scale_factor": sf,
            "num_streams": num_streams,
            "power_test_time": power_time,
            "throughput_test_time": throughput_time,
            "power_at_size": power_at_size,
            "throughput_at_size": throughput_at_size,
        }


class TimingStatsCalculator:
    @staticmethod
    def calculate(times_ms: Sequence[float]) -> dict[str, float]:
        if not times_ms:
            return {}

        times_list = list(times_ms)

        return {
            "total_ms": sum(times_list),
            "avg_ms": statistics.mean(times_list),
            "min_ms": min(times_list),
            "max_ms": max(times_list),
            "geometric_mean_ms": geometric_mean_ms(times_list),
            "stdev_ms": sample_stdev_ms(times_list),
            "p50_ms": percentile_ms(times_list, 0.50),
            "p90_ms": percentile_ms(times_list, 0.90),
            "p95_ms": percentile_ms(times_list, 0.95),
            "p99_ms": percentile_ms(times_list, 0.99),
        }

    @staticmethod
    def calculate_seconds(times_seconds: Sequence[float]) -> dict[str, float]:
        if not times_seconds:
            return {}

        times_ms = [t * 1000 for t in times_seconds]
        stats_ms = TimingStatsCalculator.calculate(times_ms)

        return {key.replace("_ms", "_s"): value / 1000 for key, value in stats_ms.items()}
