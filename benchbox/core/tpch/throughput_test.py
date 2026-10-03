# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-H specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

import concurrent.futures
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from benchbox.core.plan_capture_phase import (
    propagate_query_execution_metadata,
)
from benchbox.core.throughput.result import ThroughputResult, ThroughputStreamResult
from benchbox.core.throughput.runner import StreamRunner
from benchbox.core.validation.query_validation import (
    clear_reference_seed_context,
    set_reference_seed_context,
)
from benchbox.utils.clock import elapsed_seconds, mono_time


@dataclass
class TPCHThroughputTestConfig:
    scale_factor: float = 1.0
    num_streams: int = 2
    base_seed: int = 42
    stream_timeout: int = 3600
    max_workers: Optional[int] = None
    verbose: bool = False
    cancel_on_timeout: bool = False
    min_success_rate: float = 0.99


TPCHThroughputStreamResult = ThroughputStreamResult


def _derive_query_seed(seed: int, stream_id: int, position: int) -> int:
    return seed + stream_id * 1000 + position


def _count_cursor_rows(cursor: Any) -> int:
    counter = getattr(cursor, "row_count", None)
    if callable(counter):
        return counter()

    rowcount = getattr(cursor, "rowcount", None)
    if isinstance(rowcount, int) and rowcount >= 0:
        return rowcount
    return len(cursor.fetchall())


@dataclass
class TPCHThroughputTestResult(ThroughputResult):
    config: TPCHThroughputTestConfig = field(kw_only=True)

    @property
    def scale_factor(self) -> float:
        return self.config.scale_factor


class TPCHThroughputTest:
    def __init__(
        self,
        benchmark: Any,
        connection_factory: Callable[[], Any],
        scale_factor: float = 1.0,
        num_streams: int = 2,
        verbose: bool = False,
    ) -> None:
        self.benchmark = benchmark
        self.connection_factory = connection_factory
        self.config = TPCHThroughputTestConfig(scale_factor=scale_factor, num_streams=num_streams, verbose=verbose)

        self.logger = logging.getLogger(__name__)
        if verbose:
            self.logger.setLevel(logging.INFO)

        self.captured_items: list[tuple[str, str]] = []

        self._pregenerated_queries: Optional[dict[int, list[Any]]] = None

    def run(self, config: Optional[TPCHThroughputTestConfig] = None) -> TPCHThroughputTestResult:
        if config is None:
            config = self.config

        start_time = mono_time()
        start_time_str = datetime.now().isoformat()

        result = TPCHThroughputTestResult(
            config=config,
            start_time=start_time_str,
            end_time="",
            total_time=0.0,
            throughput_at_size=0.0,
            streams_executed=0,
            streams_successful=0,
            query_throughput=0.0,
        )

        try:
            if config.verbose:
                self.logger.info("Starting TPC-H Throughput Test")
                self.logger.info(f"Number of streams: {config.num_streams}")
                self.logger.info(f"Scale factor: {config.scale_factor}")

            self._pregenerated_queries = self._pregenerate_stream_queries(config)

            StreamRunner.execute(self._execute_stream, config, result, self.logger)

            result.success = StreamRunner.compute_metrics(result, config, start_time)

            if config.verbose:
                self.logger.info(f"Throughput Test completed in {result.total_time:.3f}s")
                self.logger.info(f"Successful streams: {result.streams_successful}/{config.num_streams}")
                if config.num_streams > 0:
                    success_rate = result.streams_successful / config.num_streams
                    self.logger.info(
                        f"Stream success rate: {success_rate:.2%} (threshold: {config.min_success_rate:.2%})"
                    )
                self.logger.info(f"Throughput@Size: {result.throughput_at_size:.2f}")
                self.logger.info(f"Query throughput: {result.query_throughput:.2f} queries/sec")

            return result

        except Exception as e:
            result.total_time = elapsed_seconds(start_time)
            result.end_time = datetime.now().isoformat()
            result.success = False
            result.errors.append(f"Throughput Test execution failed: {e}")

            if config.verbose:
                self.logger.error(f"Throughput Test failed: {e}")

            return result

    def _pregenerate_stream_queries(self, config: TPCHThroughputTestConfig) -> dict[int, list[Any]]:
        from benchbox.core.tpch.streams import TPCHStreams

        def _generate_one_stream(stream_id: int) -> tuple[int, list[Any]]:
            seed = config.base_seed + stream_id
            query_permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id % len(TPCHStreams.PERMUTATION_MATRIX)]
            sql_list: list[Any] = []
            for position, query_id in enumerate(query_permutation):
                stream_seed = _derive_query_seed(seed, stream_id, position)
                try:
                    sql_list.append(
                        self.benchmark.get_query(
                            query_id,
                            seed=stream_seed,
                            stream_id=stream_id,
                            scale_factor=config.scale_factor,
                        )
                    )
                except Exception as exc:
                    sql_list.append(exc)
            return stream_id, sql_list

        stream_queries: dict[int, list[Any]] = {}
        if config.num_streams <= 0:
            return stream_queries

        max_workers = max(1, config.max_workers or config.num_streams)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_generate_one_stream, sid) for sid in range(config.num_streams)]
            for future in concurrent.futures.as_completed(futures):
                stream_id, sql_list = future.result()
                stream_queries[stream_id] = sql_list

        return stream_queries

    def _resolve_query_text(
        self,
        pregenerated: Optional[list[Any]],
        position: int,
        stream_id: int,
        seed: int,
        query_id: int,
        config: TPCHThroughputTestConfig,
    ) -> str:
        if pregenerated is not None:
            pre = pregenerated[position]
            if isinstance(pre, BaseException):
                raise pre
            return pre

        stream_seed = _derive_query_seed(seed, stream_id, position)
        return self.benchmark.get_query(
            query_id,
            seed=stream_seed,
            stream_id=stream_id,
            scale_factor=config.scale_factor,
        )

    def _resolve_cancel_event(self, config: TPCHThroughputTestConfig, stream_id: int) -> Optional[threading.Event]:
        if getattr(config, "cancel_on_timeout", False) is not True:
            return None
        cancel_events = getattr(config, "_stream_cancel_events", None)
        if not isinstance(cancel_events, dict):
            return None
        cancel_event = cancel_events.get(stream_id)
        return cancel_event if isinstance(cancel_event, threading.Event) else None

    def _cooperative_cancel_requested(
        self,
        cancel_event: Optional[threading.Event],
        config: TPCHThroughputTestConfig,
        stream_id: int,
        position: int,
        total_queries: int,
    ) -> bool:
        if cancel_event is None or not cancel_event.is_set():
            return False
        if config.verbose:
            self.logger.warning(
                f"Stream {stream_id} cooperative cancel signalled; stopping after {position}/{total_queries} queries"
            )
        return True

    def _finalize_stream_outcome(
        self, stream_result: TPCHThroughputStreamResult, cancelled: bool, total_queries: int
    ) -> None:
        if cancelled:
            stream_result.success = False
            stream_result.error = (
                f"Stream cancelled cooperatively after timeout "
                f"({stream_result.queries_executed}/{total_queries} queries completed)"
            )
        else:
            stream_result.success = stream_result.queries_failed == 0

    def _execute_stream(
        self, stream_id: int, seed: int, config: TPCHThroughputTestConfig
    ) -> TPCHThroughputStreamResult:
        start_time = mono_time()

        stream_result = TPCHThroughputStreamResult(
            stream_id=stream_id,
            start_time=start_time,
            end_time=0.0,
            duration=0.0,
            queries_executed=0,
            queries_successful=0,
            queries_failed=0,
        )

        connection = None
        try:
            if config.verbose:
                self.logger.info(f"Starting stream {stream_id} with seed {seed}")

            connection = self.connection_factory()

            from benchbox.core.tpch.streams import TPCHStreams

            query_permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id % len(TPCHStreams.PERMUTATION_MATRIX)]

            if config.verbose:
                self.logger.info(f"Stream {stream_id} using TPC-H permutation: {query_permutation}")

            pregenerated = self._pregenerated_queries.get(stream_id) if self._pregenerated_queries is not None else None

            cancel_event = self._resolve_cancel_event(config, stream_id)

            from benchbox.core.tpch.benchmark import get_reference_seed

            reference_seed = get_reference_seed(config.scale_factor)

            cancelled = False
            for position, query_id in enumerate(query_permutation):
                if self._cooperative_cancel_requested(
                    cancel_event, config, stream_id, position, len(query_permutation)
                ):
                    cancelled = True
                    break

                query_start = mono_time()
                query_result = {
                    "query_id": query_id,
                    "position": position + 1,
                    "stream_id": stream_id,
                    "execution_time_seconds": 0.0,
                    "success": False,
                    "error": None,
                    "result_count": 0,
                }

                try:
                    query_text = self._resolve_query_text(pregenerated, position, stream_id, seed, query_id, config)

                    label = f"Stream_{stream_id}_Position_{position + 1}_Query_{query_id}"
                    try:
                        if hasattr(connection, "set_query_context"):
                            connection.set_query_context(query_id)

                        stream_seed = _derive_query_seed(seed, stream_id, position)
                        set_reference_seed_context(stream_seed == reference_seed)

                        cursor = connection.execute(query_text)

                        if hasattr(cursor, "platform_result"):
                            result_dict = cursor.platform_result
                            if result_dict.get("status") == "FAILED":
                                error_msg = result_dict.get(
                                    "error", result_dict.get("row_count_validation_error", "Query validation failed")
                                )
                                raise RuntimeError(error_msg)
                            propagate_query_execution_metadata(result_dict, query_result)

                        if hasattr(connection, "commit"):
                            connection.commit()
                    finally:
                        clear_reference_seed_context()
                        if hasattr(self, "captured_items"):
                            self.captured_items.append((label, query_text))

                    result_count = _count_cursor_rows(cursor)
                    execution_time = elapsed_seconds(query_start)

                    query_result.update(
                        {
                            "execution_time_seconds": execution_time,
                            "success": True,
                            "result_count": result_count,
                        }
                    )

                    stream_result.queries_successful += 1

                except Exception as e:
                    execution_time = elapsed_seconds(query_start)
                    query_result.update(
                        {
                            "execution_time_seconds": execution_time,
                            "success": False,
                            "error": str(e),
                        }
                    )

                    stream_result.queries_failed += 1

                    if config.verbose:
                        self.logger.error(f"Stream {stream_id} Query {query_id} failed: {e}")

                stream_result.query_results.append(query_result)
                stream_result.queries_executed += 1

            self._finalize_stream_outcome(stream_result, cancelled, len(query_permutation))

            if config.verbose:
                self.logger.info(
                    f"Stream {stream_id} completed: "
                    f"{stream_result.queries_successful}/{stream_result.queries_executed} successful"
                )

        except Exception as e:
            stream_result.error = str(e)
            stream_result.success = False

            if config.verbose:
                self.logger.error(f"Stream {stream_id} failed: {e}")

        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception as close_error:
                    if config.verbose:
                        self.logger.warning(f"Failed to close connection for stream {stream_id}: {close_error}")

            stream_result.end_time = mono_time()
            stream_result.duration = stream_result.end_time - stream_result.start_time

        return stream_result

    def validate_results(self, result: TPCHThroughputTestResult) -> bool:
        if not result.success:
            return False

        if result.streams_executed != result.config.num_streams:
            return False

        if result.streams_successful != result.config.num_streams:
            return False

        if result.errors or result.throughput_at_size is None or result.throughput_at_size <= 0:
            return False

        return all(stream_result.queries_executed == 22 for stream_result in result.stream_results)
