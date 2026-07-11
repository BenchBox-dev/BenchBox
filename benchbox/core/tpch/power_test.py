"""TPC-H Power Test Implementation.

This module implements the TPC-H Power Test according to the official TPC-H
specification. The Power Test measures the time to execute all 22 TPC-H queries
sequentially in a single stream to calculate the Power@Size metric.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from benchbox.core.plan_capture_phase import propagate_plan_capture_fields
from benchbox.utils.clock import elapsed_seconds, mono_time


def _parse_tpch_query_id(qid: object) -> int:
    """Parse a TPC-H query id that may carry the CLI's Q prefix ("Q1" -> 1)."""
    text = str(qid).strip()
    if text[:1] in ("Q", "q"):
        text = text[1:]
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"Invalid TPC-H query id: {qid!r} (expected 1-22, optionally Q-prefixed)") from exc


@dataclass
class TPCHPowerTestConfig:
    """Configuration for TPC-H Power Test."""

    scale_factor: float = 1.0
    seed: Optional[int] = None
    stream_id: int = 0  # TPC-H stream ID for query permutation (0-40)
    timeout: Optional[float] = None
    warm_up: bool = True
    validation: bool = True
    validation_mode: str = "exact"  # "exact", "loose", or "disabled"
    verbose: bool = False
    query_subset: Optional[list[str]] = None  # If set, run only these queries in specified order


@dataclass
class TPCHPowerTestResult:
    """Result of TPC-H Power Test."""

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
        """Get scale factor from config."""
        return self.config.scale_factor

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
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
    """TPC-H Power Test implementation."""

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
        """Initialize TPC-H Power Test.

        Args:
            benchmark: TPCHBenchmark instance
            connection: Database connection object
            scale_factor: Scale factor for the benchmark
            seed: Random seed for parameter generation (None = auto-select based on validation mode)
            stream_id: TPC-H stream ID for query permutation (0-40, default: 0)
            dialect: SQL dialect
            verbose: Enable verbose logging
            timeout: Query timeout in seconds
            warm_up: Perform database warm-up
            validation: Enable result validation
            validation_mode: Validation mode ("exact", "loose", or "disabled", None = auto-select)
            query_subset: Optional list of specific query IDs to run (overrides stream permutation)
        """
        self.benchmark = benchmark
        self.connection = connection
        self.dialect = dialect

        self.logger = logging.getLogger(__name__)
        if verbose:
            self.logger.setLevel(logging.INFO)

        # Import reference seed function
        from benchbox.core.tpch.benchmark import get_reference_seed

        # Determine seed and validation mode based on user input and reference seed availability
        reference_seed = get_reference_seed(scale_factor)
        user_provided_seed = seed is not None
        actual_seed = seed  # None = use qgen defaults mode (-d flag)
        actual_validation_mode = validation_mode or "exact"

        # Seed selection and validation mode logic
        if user_provided_seed:
            # User provided a custom seed
            actual_seed = seed
            if validation and reference_seed and seed != reference_seed:
                # Custom seed conflicts with exact validation
                if validation_mode is None:
                    # Auto-switch to loose validation
                    actual_validation_mode = "loose"
                    if verbose:
                        self.logger.warning(
                            f"⚠️  Custom seed {seed} with validation enabled.\n"
                            f"   Reference seed for SF={scale_factor} is {reference_seed}.\n"
                            f"   Switching to LOOSE validation (±50% tolerance)."
                        )
                elif validation_mode == "exact":
                    # User explicitly requested exact mode with wrong seed - warn but honor request
                    if verbose:
                        self.logger.warning(
                            f"⚠️  Custom seed {seed} with EXACT validation mode.\n"
                            f"   Reference seed for SF={scale_factor} is {reference_seed}.\n"
                            f"   Validation will likely FAIL due to parameter mismatch."
                        )
        else:
            # No seed provided - use qgen defaults mode (seed=None → -d flag)
            # qgen -d produces the official TPC-H default substitution parameters
            # that match the answer files, enabling exact validation
            actual_seed = None
            if validation_mode is None:
                actual_validation_mode = "exact" if validation else "disabled"
            if verbose:
                self.logger.info("Using qgen default parameters (-d flag) for answer file parity")

        # Explicit disabled mode must turn validation off at the config layer too,
        # so downstream executors can honor the benchmark's resolved policy.
        if validation_mode == "disabled":
            validation = False

        # Answer sets are only defined for stream 0; disable validation unless explicitly requested
        if stream_id != 0 and validation and validation_mode is None:
            validation = False
            actual_validation_mode = "disabled"
            self.logger.warning(
                "⚠️  Stream 0 was validated against the answer set; "
                "streams > 0 are run for timing only (per TPC-H spec). "
                f"stream_id={stream_id} therefore runs without answer-set validation."
            )

        # If validation is disabled, override mode
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

        # Initialize captured items for dry-run SQL preview
        self.captured_items: list[tuple[str, str]] = []

    def run(self) -> TPCHPowerTestResult:
        """Execute the TPC-H Power Test.

        Returns:
            Power Test results with Power@Size metric

        Raises:
            RuntimeError: If Power Test execution fails
        """
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

        # Log and prepare
        if self.config.verbose:
            self.logger.info("Starting TPC-H Power Test")
            self.logger.info(f"Scale factor: {self.config.scale_factor}")
            self.logger.info(f"Seed: {self.config.seed}")

        # Determine query execution order
        if self.config.query_subset:
            # User specified specific queries - run in their order
            query_permutation = [_parse_tpch_query_id(qid) for qid in self.config.query_subset]
            if self.config.verbose:
                self.logger.info(f"Using user-specified query subset: {query_permutation}")
            # Warn about TPC-H compliance impact
            self.logger.warning(
                "⚠️  query_subset overrides TPC-H stream permutation - results are NOT TPC-H compliant. "
                "Official TPC-H benchmarks require running all 22 queries in the specified stream order."
            )
        else:
            # Execute all 22 TPC-H queries in proper TPC-H permutation order
            # Import the permutation matrix from streams module
            from benchbox.core.tpch.streams import TPCHStreams

            # Use stream 0 permutation for power test (TPC-H specification)
            stream_id = getattr(self.config, "stream_id", 0)
            query_permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id % len(TPCHStreams.PERMUTATION_MATRIX)]

            if self.config.verbose:
                self.logger.info(f"Using TPC-H stream {stream_id} permutation: {query_permutation}")

        # Preflight: ensure all queries can be generated for this seed/stream.
        # Propagate preflight failures as RuntimeError to surface invalid configurations early.
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

                    # Get the query with proper stream-aware parameters
                    # Use stream-specific seed as per TPC-H specification
                    # NOTE: All queries in a stream use the SAME seed (base_seed + stream_id * 1000)
                    # The position only determines query execution ORDER via permutation matrix
                    # When seed is None, use qgen defaults mode (-d flag) for all streams
                    stream_seed = None if self.config.seed is None else self.config.seed + self.config.stream_id * 1000
                    query_text = self.benchmark.get_query(
                        query_id,
                        seed=stream_seed,
                        stream_id=self.config.stream_id,
                        scale_factor=self.config.scale_factor,
                        dialect=self.dialect,
                    )

                    # Execute the actual query against the database
                    label = f"Position_{position + 1}_Query_{query_id}"
                    try:
                        # Set query context for validation
                        # NOTE: Answer files are only available for stream 0 (seed 17039360 for SF=1.0)
                        # Other streams use different seeds and will have different expected row counts
                        if hasattr(self.connection, "set_query_context"):
                            self.connection.set_query_context(query_id, stream_id=self.config.stream_id)

                        cursor = self.connection.execute(query_text)

                        # Check for validation failures from platform adapter
                        if hasattr(cursor, "platform_result"):
                            result_dict = cursor.platform_result
                            if result_dict.get("status") == "FAILED":
                                error_msg = result_dict.get(
                                    "error", result_dict.get("row_count_validation_error", "Query validation failed")
                                )
                                raise RuntimeError(error_msg)
                            # Propagate captured plan metadata (including the internal
                            # _plan_capture_key) so it reaches the result bundle and
                            # so _attach_captured_plans can match this row by its
                            # exact key rather than the ambiguous public-id fallback.
                            propagate_plan_capture_fields(result_dict, query_result)

                        if hasattr(self.connection, "commit"):
                            self.connection.commit()
                    finally:
                        # Capture labeled SQL for dry-run preview
                        self.captured_items.append((label, query_text))

                    execution_time = elapsed_seconds(query_start)

                    query_result.update(
                        {
                            "execution_time_seconds": execution_time,
                            "success": True,
                            "result_count": self._query_result_count(cursor),
                        }
                    )

                    # Gate-only value oracle: forward the full-result digest the
                    # adapter computed (behind BENCHBOX_EMIT_RESULT_DIGEST) so the
                    # bounded correctness gate can assert VALUES, not just row counts.
                    # None when emission is off; downstream forwarders drop None.
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

            # Calculate Power@Size metric (geometric mean per TPC spec)
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
            result.success = result.queries_successful == len(query_permutation)  # All queries must succeed

            if self.config.verbose:
                self.logger.info(f"Power Test completed in {total_execution_time:.3f}s")
                self.logger.info(f"Successful queries: {result.queries_successful}/{len(query_permutation)}")
                self.logger.info(f"Power@Size: {result.power_at_size:.2f}")

            return result
        except Exception as e:
            # Only capture unexpected execution errors after preflight
            result.total_time = elapsed_seconds(start_time)
            result.end_time = datetime.now().isoformat()
            result.success = False
            result.errors.append(f"Power Test execution failed: {e}")
            if self.config.verbose:
                self.logger.error(f"Power Test failed: {e}")
            return result

    @staticmethod
    def _result_digest_from_cursor(cursor: Any) -> str | None:
        """Return the gate-only full-result digest the adapter computed, if any.

        The full result set lives in the platform adapter (the wrapped cursor here
        only carries first_row + count), so the digest is computed there and
        surfaced via ``platform_result`` behind ``BENCHBOX_EMIT_RESULT_DIGEST``.
        Only stream 0 carries a stored reference digest (the reference qgen seed).
        """
        platform_result = getattr(cursor, "platform_result", None)
        if isinstance(platform_result, dict):
            digest = platform_result.get("result_digest")
            if digest is not None:
                return str(digest)
        return None

    @staticmethod
    def _query_result_count(cursor: Any) -> int:
        """Return the true result cardinality for adapter cursors when available.

        Checks platform_result["rows_returned"] first - this never
        materializes the cursor's row list, so a count-only power run never
        trips PlatformAdapterCursor's placeholder-materialization warning
        (#1137: that warning exists to catch VALUE-dependent consumers of
        fabricated placeholder rows, not this count-only path). Only calls
        cursor.fetchall() as a fallback when no reported count is available
        (raw DB-API cursors, test doubles).
        """
        platform_result = getattr(cursor, "platform_result", None)
        if isinstance(platform_result, dict):
            reported = platform_result.get("rows_returned")
            if isinstance(reported, int) and reported >= 0:
                return reported
        if hasattr(cursor, "fetchall"):
            return len(cursor.fetchall())
        return 0

    def get_all_queries(self) -> dict[str, str]:
        """Get all queries for the power test."""
        from benchbox.core.tpch.streams import TPCHStreams

        stream_id = getattr(self.config, "stream_id", 0)
        query_permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id % len(TPCHStreams.PERMUTATION_MATRIX)]

        queries = {}
        # All queries in a stream use the SAME seed (base_seed + stream_id * 1000)
        # When seed is None, use qgen defaults mode (-d flag)
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
        """Validate all TPCH queries can be generated for this stream/seed.

        Raises RuntimeError with details if any query generation fails.
        """
        failures = []
        # All queries in a stream use the SAME seed (base_seed + stream_id * 1000)
        # When seed is None, use qgen defaults mode (-d flag)
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
        """Validate Power Test results against TPC-H specification.

        Args:
            result: Power Test results to validate

        Returns:
            True if results are valid, False otherwise
        """
        if not result.success:
            return False

        if result.queries_successful != 22:
            return False

        if result.power_at_size <= 0:
            return False

        # Additional validation logic would go here
        return True
