from __future__ import annotations

import warnings
from typing import Any

from benchbox.core.schemas import MIN_THROUGHPUT_STREAMS
from benchbox.core.throughput.result import throughput_result_succeeded

SUPPORTED_THROUGHPUT_DRIVERS = {
    "tpch": "the TPC-H throughput driver that `benchbox run` uses (TPCHThroughputTest)",
    "tpcds": "the dsqgen-based TPC-DS throughput driver that `benchbox run` uses (TPCDSThroughputTest)",
}


def require_stream_minimum(count: int, source: str) -> int:
    if count < MIN_THROUGHPUT_STREAMS:
        raise ValueError(
            f"Throughput requires at least {MIN_THROUGHPUT_STREAMS} concurrent streams (TPC minimum); "
            f"got {count} from '{source}'."
        )
    return count


def finalize_throughput_metrics(result: Any, num_streams: int, query_subset: list[str] | None) -> None:
    result.success = throughput_result_succeeded(result, num_streams)
    if not result.success:
        result.throughput_at_size = None
        result.query_throughput = 0.0
    elif query_subset:
        result.throughput_at_size = None


def warn_legacy_throughput_api(api: str, benchmark_type: str | None = None, *, stacklevel: int = 3) -> None:
    driver = SUPPORTED_THROUGHPUT_DRIVERS.get(benchmark_type or "", "the supported throughput drivers")
    warnings.warn(
        f"{api} is deprecated. It now runs {driver} instead of its former private stream runner. "
        "Use `benchbox run --phases throughput` (or PlatformAdapter.run_benchmark with the throughput phase) "
        "for supported runs.",
        DeprecationWarning,
        stacklevel=stacklevel,
    )


def require_adapter(api: str, adapter: Any) -> Any:
    if adapter is None:
        raise TypeError(
            f"{api} needs adapter=<platform adapter> so the platform's stream capability gate and per-stream "
            "sessions apply; without it every stream would share the caller's connection. "
            "Pass adapter=, or run `benchbox run --phases throughput`."
        )
    return adapter
