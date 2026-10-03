# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-H specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from benchbox.core.plan_capture_phase import (
    propagate_query_execution_metadata,
)
from benchbox.core.validation.query_validation import (
    clear_reference_seed_context,
    set_reference_seed_context,
)
from benchbox.utils.clock import elapsed_seconds, mono_time


def _parse_tpch_query_id(qid: object) -> int:
    text = str(qid).strip()
    if text[:1] in ("Q", "q"):
        text = text[1:]
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"Invalid TPC-H query id: {qid!r} (expected 1-22, optionally Q-prefixed)") from exc


@dataclass
class TPCHPowerTestConfig:
    scale_factor: float = 1.0
    seed: Optional[int] = None
    stream_id: int = 0
    timeout: Optional[float] = None
    warm_up: bool = True
    validation: bool = True
    validation_mode: str = "exact"
    verbose: bool = False
    query_subset: Optional[list[str]] = None


@dataclass
class TPCHPowerTestResult:
    config: TPCHPowerTestConfig
    start_time: str
    end_time: str
    total_time: float
    power_at_size: float
    queries_executed: int
    queries_successful: int
    query_results: list[dict[str, Any]]
    success: bool
    errors: list[str]

    @property
    def scale_factor(self) -> float:
        return self.config.scale_factor

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_time": self.total_time,
            "power_at_size": self.power_at_size,
            "queries_executed": self.queries_executed,
            "queries_successful": self.queries_successful,
            "query_results": self.query_results,
            "success": self.success,
            "errors": self.errors,
            "config": {
                "scale_factor": self.config.scale_factor,
                "seed": self.config.seed,
                "stream_id": self.config.stream_id,
                "timeout": self.config.timeout,
                "warm_up": self.config.warm_up,
                "validation": self.config.validation,
                "validation_mode": self.config.validation_mode,
            },
        }


class TPCHPowerTest:
    def __init__(
        self,
        benchmark: Any,
        connection: Any,
        scale_factor: float = 1.0,
        seed: Optional[int] = None,
        stream_id: int = 0,
        dialect: str = "standard",
        verbose: bool = False,
        timeout: Optional[float] = None,
        warm_up: bool = True,
        validation: bool = True,
        validation_mode: Optional[str] = None,
        query_subset: Optional[list[str]] = None,
    ) -> None:
        self.benchmark = benchmark
        self.connection = connection
        self.dialect = dialect

        self.logger = logging.getLogger(__name__)
        if verbose:
            self.logger.setLevel(logging.INFO)

        from benchbox.core.tpch.benchmark import get_reference_seed

        reference_seed = get_reference_seed(scale_factor)
        self.reference_seed = reference_seed
        user_provided_seed = seed is not None
        actual_seed = seed
        actual_validation_mode = validation_mode or "exact"

        if user_provided_seed:
            actual_seed = seed
            if validation and reference_seed and seed != reference_seed:
                if validation_mode is None:
                    actual_validation_mode = "loose"
                    if verbose:
                        self.logger.warning(
                            f"⚠️  Custom seed {seed} with validation enabled.\n"
                            f"   Reference seed for SF={scale_factor} is {reference_seed}.\n"
                            f"   Switching to LOOSE validation (±50% tolerance)."
                        )
                elif validation_mode == "exact":
                    if verbose:
                        self.logger.warning(
                            f"⚠️  Custom seed {seed} with EXACT validation mode.\n"
                            f"   Reference seed for SF={scale_factor} is {reference_seed}.\n"
                            f"   Validation will likely FAIL due to parameter mismatch."
                        )
        else:
            actual_seed = None
            if validation_mode is None:
                actual_validation_mode = "exact" if validation else "disabled"
            if verbose:
                self.logger.info("Using qgen default parameters (-d flag) for answer file parity")

        if validation_mode == "disabled":
            validation = False

        if stream_id != 0 and validation and validation_mode is None:
            validation = False
            actual_validation_mode = "disabled"
            self.logger.warning(
                "⚠️  Stream 0 was validated against the answer set; "
                "streams > 0 are run for timing only (per TPC-H spec). "
                f"stream_id={stream_id} therefore runs without answer-set validation."
            )

        if not validation:
            actual_validation_mode = "disabled"

        self.config = TPCHPowerTestConfig(
            scale_factor=scale_factor,
            seed=actual_seed,
            stream_id=stream_id,
            timeout=timeout,
            warm_up=warm_up,
            validation=validation,
            validation_mode=actual_validation_mode,
            verbose=verbose,
            query_subset=query_subset,
        )

        self.captured_items: list[tuple[str, str]] = []

    def run(self) -> TPCHPowerTestResult:
        start_time = mono_time()
        start_time_str = datetime.now().isoformat()

        result = TPCHPowerTestResult(
            config=self.config,
            start_time=start_time_str,
            end_time="",
            total_time=0.0,
            power_at_size=0.0,
            queries_executed=0,
            queries_successful=0,
            query_results=[],
            success=True,
            errors=[],
        )

        if self.config.verbose:
            self.logger.info("Starting TPC-H Power Test")
            self.logger.info(f"Scale factor: {self.config.scale_factor}")
            self.logger.info(f"Seed: {self.config.seed}")

        if self.config.query_subset:
            query_permutation = [_parse_tpch_query_id(qid) for qid in self.config.query_subset]
            if self.config.verbose:
                self.logger.info(f"Using user-specified query subset: {query_permutation}")
            self.logger.warning(
                "⚠️  query_subset overrides TPC-H stream permutation - results are NOT TPC-H compliant. "
                "Official TPC-H benchmarks require running all 22 queries in the specified stream order."
            )
        else:
            from benchbox.core.tpch.streams import TPCHStreams

            stream_id = getattr(self.config, "stream_id", 0)
            query_permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id % len(TPCHStreams.PERMUTATION_MATRIX)]

            if self.config.verbose:
                self.logger.info(f"Using TPC-H stream {stream_id} permutation: {query_permutation}")

        self._preflight_validate_generation(query_permutation)

        try:
            for position, query_id in enumerate(query_permutation):
                query_start = mono_time()
                query_result = {
                    "query_id": query_id,
                    "position": position + 1,
                    "stream_id": self.config.stream_id,
                    "execution_time_seconds": 0.0,
                    "success": False,
                    "error": None,
                    "result_count": 0,
                }

                try:
                    if self.config.verbose:
                        self.logger.info(
                            f"Executing Query {query_id} (position {position + 1}/{len(query_permutation)})"
                        )

                    stream_seed = None if self.config.seed is None else self.config.seed + self.config.stream_id * 1000
                    query_text = self.benchmark.get_query(
                        query_id,
                        seed=stream_seed,
                        stream_id=self.config.stream_id,
                        scale_factor=self.config.scale_factor,
                        dialect=self.dialect,
                    )

                    label = f"Position_{position + 1}_Query_{query_id}"
                    try:
                        if hasattr(self.connection, "set_query_context"):
                            self.connection.set_query_context(query_id, stream_id=self.config.stream_id)

                        set_reference_seed_context(stream_seed is None or stream_seed == self.reference_seed)

                        cursor = self.connection.execute(query_text)

                        if hasattr(cursor, "platform_result"):
                            result_dict = cursor.platform_result
                            if result_dict.get("status") == "FAILED":
                                error_msg = result_dict.get(
                                    "error", result_dict.get("row_count_validation_error", "Query validation failed")
                                )
                                raise RuntimeError(error_msg)
                            propagate_query_execution_metadata(result_dict, query_result)

                        result_count = self._query_result_count(cursor)

                        if hasattr(self.connection, "commit"):
                            self.connection.commit()
                    finally:
                        clear_reference_seed_context()
                        self.captured_items.append((label, query_text))

                    execution_time = elapsed_seconds(query_start)

                    query_result.update(
                        {
                            "execution_time_seconds": execution_time,
                            "success": True,
                            "result_count": result_count,
                        }
                    )

                    query_result["result_digest"] = self._result_digest_from_cursor(cursor)

                    result.queries_successful += 1

                    if self.config.verbose:
                        self.logger.info(f"Query {query_id} completed in {execution_time:.3f}s")

                except Exception as e:
                    execution_time = elapsed_seconds(query_start)
                    query_result.update(
                        {
                            "execution_time_seconds": execution_time,
                            "success": False,
                            "error": str(e),
                        }
                    )

                    result.errors.append(f"Query {query_id} failed: {e}")

                    if self.config.verbose:
                        self.logger.error(f"Query {query_id} failed: {e}")

                result.query_results.append(query_result)
                result.queries_executed += 1

            total_execution_time = elapsed_seconds(start_time)
            exec_times = [
                qr["execution_time_seconds"]
                for qr in result.query_results
                if qr.get("success", True) and qr.get("execution_time_seconds", 0) > 0
            ]
            if exec_times:
                from benchbox.core.results.metrics import TPCMetricsCalculator

                result.power_at_size = TPCMetricsCalculator.calculate_power_at_size(
                    exec_times,
                    self.config.scale_factor,
                )

            result.total_time = total_execution_time
            result.end_time = datetime.now().isoformat()
            result.success = result.queries_successful == len(query_permutation)

            if self.config.verbose:
                self.logger.info(f"Power Test completed in {total_execution_time:.3f}s")
                self.logger.info(f"Successful queries: {result.queries_successful}/{len(query_permutation)}")
                self.logger.info(f"Power@Size: {result.power_at_size:.2f}")

            return result
        except Exception as e:
            result.total_time = elapsed_seconds(start_time)
            result.end_time = datetime.now().isoformat()
            result.success = False
            result.errors.append(f"Power Test execution failed: {e}")
            if self.config.verbose:
                self.logger.error(f"Power Test failed: {e}")
            return result

    @staticmethod
    def _result_digest_from_cursor(cursor: Any) -> str | None:
        platform_result = getattr(cursor, "platform_result", None)
        if isinstance(platform_result, dict):
            digest = platform_result.get("result_digest")
            if digest is not None:
                return str(digest)
        return None

    @staticmethod
    def _query_result_count(cursor: Any) -> int:
        platform_result = getattr(cursor, "platform_result", None)
        if isinstance(platform_result, dict):
            reported = platform_result.get("rows_returned")
            if isinstance(reported, int) and reported >= 0:
                return reported
        if hasattr(cursor, "fetchall"):
            return len(cursor.fetchall())
        return 0

    def get_all_queries(self) -> dict[str, str]:
        from benchbox.core.tpch.streams import TPCHStreams

        stream_id = getattr(self.config, "stream_id", 0)
        query_permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id % len(TPCHStreams.PERMUTATION_MATRIX)]

        queries = {}
        stream_seed = None if self.config.seed is None else self.config.seed + self.config.stream_id * 1000
        for position, query_id in enumerate(query_permutation):
            try:
                query_text = self.benchmark.get_query(
                    query_id,
                    seed=stream_seed,
                    stream_id=self.config.stream_id,
                    scale_factor=self.config.scale_factor,
                    dialect=self.dialect,
                )
                queries[f"Position_{position + 1}_Query_{query_id}"] = query_text
            except Exception as e:
                self.logger.error(f"Failed to get query {query_id}: {e}")
        return queries

    def _preflight_validate_generation(self, query_permutation: list[int]) -> None:
        failures = []
        stream_seed = None if self.config.seed is None else self.config.seed + self.config.stream_id * 1000
        for position, query_id in enumerate(query_permutation):
            try:
                _ = self.benchmark.get_query(
                    query_id,
                    seed=stream_seed,
                    stream_id=self.config.stream_id,
                    scale_factor=self.config.scale_factor,
                    dialect=self.dialect,
                )
            except Exception as e:
                failures.append(f"{query_id}: {e}")
        if failures:
            msg = f"TPC-H PowerTest preflight failed for {len(failures)} queries. Examples: {', '.join(failures[:3])}"
            raise RuntimeError(msg)

    def validate_results(self, result: TPCHPowerTestResult) -> bool:
        if not result.success:
            return False

        if result.queries_successful != 22:
            return False

        if result.power_at_size <= 0:
            return False

        return True
