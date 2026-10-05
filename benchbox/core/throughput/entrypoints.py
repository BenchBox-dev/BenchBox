from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any

from benchbox.core.schemas import MIN_THROUGHPUT_STREAMS
from benchbox.core.throughput.result import ThroughputResult, throughput_result_succeeded

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


def run_factory_throughput(
    benchmark_type: str,
    benchmark: Any,
    connection_factory: Callable[[], Any],
    *,
    scale_factor: float,
    num_streams: int,
    base_seed: int | None = None,
    stream_timeout: int | None = None,
    query_subset: list[str] | None = None,
    verbose: bool = False,
    dialect: str | None = None,
) -> ThroughputResult:
    require_stream_minimum(num_streams, "num_streams")
    options: dict[str, Any] = {"verbose": verbose}
    if base_seed is not None:
        options["base_seed"] = int(base_seed)
    if stream_timeout is not None:
        options["stream_timeout"] = int(stream_timeout)
    if query_subset:
        options["query_subset"] = [str(query_id) for query_id in query_subset]

    if benchmark_type == "tpcds":
        from benchbox.core.tpcds.throughput_test import TPCDSThroughputTest, TPCDSThroughputTestConfig

        config = TPCDSThroughputTestConfig(scale_factor=scale_factor, num_streams=num_streams, **options)
        driver = TPCDSThroughputTest(
            benchmark=benchmark,
            connection_factory=connection_factory,
            scale_factor=scale_factor,
            num_streams=num_streams,
            verbose=verbose,
            dialect=dialect,
        )
    elif benchmark_type == "tpch":
        from benchbox.core.tpch.throughput_test import TPCHThroughputTest, TPCHThroughputTestConfig

        config = TPCHThroughputTestConfig(scale_factor=scale_factor, num_streams=num_streams, **options)
        driver = TPCHThroughputTest(
            benchmark=benchmark,
            connection_factory=connection_factory,
            scale_factor=scale_factor,
            num_streams=num_streams,
            verbose=verbose,
        )
    else:
        raise ValueError(f"No supported throughput driver for benchmark type '{benchmark_type}'")

    result = driver.run(config=config)
    finalize_throughput_metrics(result, num_streams, config.query_subset)
    return result
