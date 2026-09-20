"""Central registry for expected query results across all benchmarks.

This module provides a centralized way to access expected query results for validation.
It supports lazy loading of benchmark-specific results and caching for performance.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from enum import Enum
from typing import Dict

from benchbox.core.expected_results.models import BenchmarkExpectedResults, ExpectedQueryResult

logger = logging.getLogger(__name__)


class LoadOutcome(str, Enum):
    """Classified outcome of an expected-results load for one (benchmark, scale factor)."""

    HIT = "hit"  # Answer data published (from cache or a fresh load)
    NO_ANSWER_SET = "no_answer_set"  # No provider, provider returned None, or query absent
    STREAM_NOT_REFERENCE_VALIDATED = "stream_not_reference_validated"  # Non-stream-0 has no answers
    PROVIDER_FAILED = "provider_failed"  # Provider raised a transient (retryable) error
    PROVIDER_TIMEOUT = "provider_timeout"  # Waiter stopped waiting while the load continued


class ExpectedResultsRegistry:
    """Central registry for expected query results.

    This registry provides a unified interface for accessing expected query results
    across all benchmarks. It supports:
    - Lazy loading of benchmark-specific results
    - Multiple scale factors per benchmark
    - Caching for performance
    - Fallback to default scale factors
    - Thread-safe operations
    """

    def __init__(self):
        """Initialize the registry with empty cache and thread safety."""
        self._cache: Dict[str, Dict[float, BenchmarkExpectedResults]] = {}
        self._providers: Dict[str, Callable] = {}
        self._lock = threading.Lock()  # Protects cache, provider registry, and load slots
        # Tracks in-progress and completed loads. Each slot holds the wait
        # event plus the published outcome; the outcome is written while
        # holding the lock BEFORE the event is signaled, so no waiter can
        # observe a signal without its corresponding published result.
        self._loading: Dict[str, Dict[float, dict]] = {}
        self._logged_stream_skips: set = set()  # Track (benchmark, stream) combos we've logged about
        # Bound on how long a waiter waits for another thread's load. A
        # timeout only bounds the caller wait (reported as PROVIDER_TIMEOUT);
        # the loader continues and publishes normally for later callers.
        self.wait_timeout_seconds = 30.0

    def register_provider(self, benchmark_name: str, provider: Callable) -> None:
        """Register a provider function for a benchmark.

        Thread-safe: Uses lock to prevent concurrent registration races.

        The provider function should accept a scale_factor parameter and return
        a BenchmarkExpectedResults object.

        Args:
            benchmark_name: Name of the benchmark (e.g., "tpch", "tpcds")
            provider: Function that loads expected results for a scale factor
        """
        benchmark_key = benchmark_name.lower()
        with self._lock:
            self._providers[benchmark_key] = provider
            logger.debug(f"Registered expected results provider for benchmark: {benchmark_name}")

    def get_expected_result(
        self,
        benchmark_name: str,
        query_id: str,
        scale_factor: float | None = None,
        stream_id: int | None = None,
    ) -> ExpectedQueryResult | None:
        """Get expected result for a specific query.

        Supports fallback to SF=1.0 for scale-independent queries when SF != 1.0.
        For multi-stream benchmarks (TPC-H, TPC-DS), only stream 0 has answer files.
        Returns None for non-stream-0 queries to trigger automatic validation SKIP.

        Args:
            benchmark_name: Name of the benchmark (e.g., "tpch", "tpcds")
            query_id: Query identifier (e.g., "1", "2a", "query14")
            scale_factor: Scale factor (defaults to 1.0 if not specified)
            stream_id: Stream identifier for multi-stream benchmarks (e.g., 0, 1, 2...)
                      None is treated as stream 0. For stream IDs > 0, returns None
                      to trigger validation SKIP with informative warning.

        Returns:
            Expected query result, or None if not found or stream_id > 0
        """
        expected_result, _ = self.get_expected_result_detailed(benchmark_name, query_id, scale_factor, stream_id)
        return expected_result

    def get_expected_result_detailed(
        self,
        benchmark_name: str,
        query_id: str,
        scale_factor: float | None = None,
        stream_id: int | None = None,
    ) -> tuple[ExpectedQueryResult | None, LoadOutcome]:
        """Get expected result plus the classified load outcome.

        Unlike get_expected_result, a None result is always accompanied by the
        reason: absent answers, non-reference stream, provider failure, or
        provider timeout. Callers must not treat PROVIDER_FAILED or
        PROVIDER_TIMEOUT as a normal validation skip.

        Args:
            benchmark_name: Name of the benchmark (e.g., "tpch", "tpcds")
            query_id: Query identifier (e.g., "1", "2a", "query14")
            scale_factor: Scale factor (defaults to 1.0 if not specified)
            stream_id: Stream identifier for multi-stream benchmarks

        Returns:
            Tuple of (expected query result or None, classified load outcome)
        """
        benchmark_key = benchmark_name.lower()
        sf = scale_factor or 1.0

        # Stream-aware validation: TPC benchmarks only have answer files for stream 0
        if stream_id is not None and stream_id > 0 and benchmark_key in ("tpch", "tpcds"):
            # Only log once per (benchmark, stream) to reduce noise
            skip_key = (benchmark_key, stream_id)
            if skip_key not in self._logged_stream_skips:
                self._logged_stream_skips.add(skip_key)
                logger.debug(
                    f"Stream {stream_id} requested for {benchmark_name}. "
                    f"Answer files only available for stream 0. Validation will be skipped for this stream."
                )
            return None, LoadOutcome.STREAM_NOT_REFERENCE_VALIDATED

        # Try to load benchmark results for the requested scale factor
        benchmark_results, outcome = self._load_benchmark_results(benchmark_key, sf)

        # A failed or timed-out load is reported as-is: falling back to
        # another scale factor would mask the failure as a normal miss.
        if outcome in (LoadOutcome.PROVIDER_FAILED, LoadOutcome.PROVIDER_TIMEOUT):
            return None, outcome

        # If no results at requested SF and SF != 1.0, try SF=1.0 for scale-independent queries
        if benchmark_results is None and sf != 1.0:
            logger.debug(
                f"No expected results at SF={sf} for benchmark '{benchmark_name}'. "
                f"Trying SF=1.0 for scale-independent queries..."
            )
            benchmark_results_sf1, outcome_sf1 = self._load_benchmark_results(benchmark_key, 1.0)

            if benchmark_results_sf1 is not None:
                # Check if this specific query is scale-independent
                expected_result_sf1 = benchmark_results_sf1.get_expected_result(query_id)
                if expected_result_sf1 and expected_result_sf1.scale_independent:
                    logger.debug(f"Query '{query_id}' is scale-independent. Using SF=1.0 expectation at SF={sf}.")
                    return expected_result_sf1, outcome_sf1

            # No scale-independent result found - validation will skip
            logger.debug(
                f"No expected results found for benchmark '{benchmark_name}' at scale factor {sf}. "
                f"Validation will be skipped for this query."
            )
            return None, LoadOutcome.NO_ANSWER_SET

        if benchmark_results is None:
            logger.debug(
                f"No expected results found for benchmark '{benchmark_name}' at scale factor {sf}. "
                f"Validation will be skipped for this query."
            )
            return None, LoadOutcome.NO_ANSWER_SET

        # Get query-specific result
        expected_result = benchmark_results.get_expected_result(query_id)
        if expected_result is None:
            logger.debug(
                f"No expected result found for query '{query_id}' in benchmark '{benchmark_name}'. "
                f"Validation will be skipped for this query."
            )
            return None, LoadOutcome.NO_ANSWER_SET

        return expected_result, LoadOutcome.HIT

    def _get_benchmark_results(self, benchmark_key: str, scale_factor: float) -> BenchmarkExpectedResults | None:
        """Get or load benchmark results for a specific scale factor.

        Thread-safe: Uses lock to protect cache and single-flight pattern to prevent duplicate loads.

        Args:
            benchmark_key: Normalized benchmark name (lowercase)
            scale_factor: Scale factor

        Returns:
            Benchmark expected results, or None if not available
        """
        results, _ = self._load_benchmark_results(benchmark_key, scale_factor)
        return results

    def _load_benchmark_results(
        self, benchmark_key: str, scale_factor: float
    ) -> tuple[BenchmarkExpectedResults | None, LoadOutcome]:
        """Load benchmark results with atomic single-flight publication.

        The loading thread publishes the result or the classified failure
        while holding the lock BEFORE signaling waiters, so every waiter
        observes the same published outcome and no waiter can interpret an
        in-progress load as a missing answer set.

        Args:
            benchmark_key: Normalized benchmark name (lowercase)
            scale_factor: Scale factor

        Returns:
            Tuple of (benchmark expected results or None, classified outcome)
        """
        # Single-flight pattern: ensure only one thread loads a given (benchmark, SF) combination
        should_load = False

        with self._lock:
            # Check cache first
            if benchmark_key in self._cache and scale_factor in self._cache[benchmark_key]:
                return self._cache[benchmark_key][scale_factor], LoadOutcome.HIT

            # Check if provider is registered
            if benchmark_key not in self._providers:
                logger.debug(f"No expected results provider registered for benchmark: {benchmark_key}")
                return None, LoadOutcome.NO_ANSWER_SET

            slot = self._loading.get(benchmark_key, {}).get(scale_factor)
            if slot is not None and slot["outcome"] is not None:
                # A previous load already published; serve it unless the cache
                # entry was cleared out from under it, in which case reload.
                if benchmark_key in self._cache and scale_factor in self._cache[benchmark_key]:
                    return self._cache[benchmark_key][scale_factor], slot["outcome"]
                del self._loading[benchmark_key][scale_factor]
                if not self._loading[benchmark_key]:
                    del self._loading[benchmark_key]
                slot = None

            if slot is None:
                # We're the first thread - create the slot and we'll load
                slot = {"event": threading.Event(), "outcome": None, "result": None}
                if benchmark_key not in self._loading:
                    self._loading[benchmark_key] = {}
                self._loading[benchmark_key][scale_factor] = slot
                should_load = True

            # Get provider function and wait event
            provider = self._providers[benchmark_key]
            event = slot["event"]

        # If another thread is loading, wait for its published outcome
        if not should_load:
            signaled = event.wait(timeout=self.wait_timeout_seconds)
            with self._lock:
                # Read the slot this caller joined, not the mutable registry
                # entry: clear_cache() or a retry may replace that entry while
                # this waiter is asleep.
                if slot["outcome"] is not None:
                    return slot["result"], slot["outcome"]
                if not signaled:
                    logger.debug(
                        f"Timed out waiting for {benchmark_key} SF={scale_factor} load; "
                        f"the load continues and later callers observe its outcome"
                    )
                    return None, LoadOutcome.PROVIDER_TIMEOUT
                # Signaled without a published outcome: fail closed rather
                # than reporting a false miss.
                logger.debug(f"Load signal without published outcome for {benchmark_key} SF={scale_factor}")
                return None, LoadOutcome.PROVIDER_FAILED

        # Load results using provider (outside lock - this may be slow).
        # Classify the failure: a missing answers directory is permanent and
        # stays a graceful skip; any other error is a provider failure.
        permanent_absence = False
        transient_error: Exception | None = None
        try:
            results = provider(scale_factor)
        except FileNotFoundError as e:
            # Permanent failure: answers directory not found (won't change during session)
            # Cache this failure to avoid noisy repeated warnings
            logger.info(
                f"Expected results not available for benchmark '{benchmark_key}' "
                f"at scale factor {scale_factor}: {e}. Validation will be skipped."
            )
            results = None
            permanent_absence = True
        except Exception as e:
            # Transient failure: might succeed on retry (don't cache)
            logger.warning(
                f"Failed to load expected results for benchmark '{benchmark_key}' "
                f"at scale factor {scale_factor}: {e}. Will not cache this failure; retry allowed."
            )
            results = None
            transient_error = e

        # Publish the result or the classified failure while holding the lock,
        # before signaling waiters.
        with self._lock:
            if permanent_absence:
                outcome = LoadOutcome.NO_ANSWER_SET
                if benchmark_key not in self._cache:
                    self._cache[benchmark_key] = {}
                self._cache[benchmark_key][scale_factor] = None
                published = None
            elif transient_error is not None:
                outcome = LoadOutcome.PROVIDER_FAILED
                published = None
            else:
                outcome = LoadOutcome.HIT
                if benchmark_key not in self._cache:
                    self._cache[benchmark_key] = {}
                self._cache[benchmark_key][scale_factor] = results
                published = results
                logger.debug(
                    f"Loaded and cached expected results for benchmark '{benchmark_key}' at scale factor {scale_factor}"
                )
            slot["result"] = published
            slot["outcome"] = outcome
            slot["event"].set()  # Signal other threads only after publication

        return published, outcome

    def clear_cache(self) -> None:
        """Clear all cached expected results.

        Completed load publications are dropped so the next request reloads
        fresh; in-progress loads keep their slots and publish normally.

        Thread-safe: Uses lock to protect cache access.
        """
        with self._lock:
            self._cache.clear()
            for benchmark_key in list(self._loading):
                for scale_factor in list(self._loading[benchmark_key]):
                    if self._loading[benchmark_key][scale_factor]["outcome"] is not None:
                        del self._loading[benchmark_key][scale_factor]
                if benchmark_key in self._loading and not self._loading[benchmark_key]:
                    del self._loading[benchmark_key]
            self._logged_stream_skips.clear()
            logger.debug("Cleared expected results cache")

    def list_available_benchmarks(self) -> list[str]:
        """List all benchmarks with registered providers.

        Thread-safe: Uses lock to protect provider registry access.

        Returns:
            List of benchmark names
        """
        with self._lock:
            return list(self._providers.keys())


# Global registry instance
_global_registry = ExpectedResultsRegistry()


def get_registry() -> ExpectedResultsRegistry:
    """Get the global expected results registry.

    Returns:
        The global registry instance
    """
    return _global_registry


def register_benchmark_provider(benchmark_name: str, provider: Callable) -> None:
    """Register a provider for a benchmark.

    This is a convenience function that registers a provider with the global registry.

    Args:
        benchmark_name: Name of the benchmark
        provider: Provider function
    """
    _global_registry.register_provider(benchmark_name, provider)
