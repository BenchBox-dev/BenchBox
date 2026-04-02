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
from typing import Dict

from benchbox.core.expected_results.models import BenchmarkExpectedResults, ExpectedQueryResult

logger = logging.getLogger(__name__)


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
        self._lock = threading.Lock()  # Protects cache and provider registry
        self._loading: Dict[str, Dict[float, threading.Event]] = {}  # Tracks in-progress loads
        self._logged_stream_skips: set = set()  # Track (benchmark, stream) combos we've logged about

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
        benchmark_key = benchmark_name.lower()
        sf = scale_factor or 1.0

        # Stream-aware validation: TPC benchmarks only have answer files for stream 0
        # Return None for non-stream-0 queries to trigger automatic SKIP with informative warning
        if stream_id is not None and stream_id > 0:
            if benchmark_key in ("tpch", "tpcds"):
                # Only log once per (benchmark, stream) to reduce noise
                skip_key = (benchmark_key, stream_id)
                if skip_key not in self._logged_stream_skips:
                    self._logged_stream_skips.add(skip_key)
                    logger.debug(
                        f"Stream {stream_id} requested for {benchmark_name}. "
                        f"Answer files only available for stream 0. Validation will be skipped for this stream."
                    )
                return None

        # Try to load benchmark results for the requested scale factor
        benchmark_results = self._get_benchmark_results(benchmark_key, sf)

        # If no results at requested SF and SF != 1.0, try SF=1.0 for scale-independent queries
        if benchmark_results is None and sf != 1.0:
            logger.debug(
                f"No expected results at SF={sf} for benchmark '{benchmark_name}'. "
                f"Trying SF=1.0 for scale-independent queries..."
            )
            benchmark_results_sf1 = self._get_benchmark_results(benchmark_key, 1.0)

            if benchmark_results_sf1 is not None:
                # Check if this specific query is scale-independent
                expected_result_sf1 = benchmark_results_sf1.get_expected_result(query_id)
                if expected_result_sf1 and expected_result_sf1.scale_independent:
                    logger.debug(f"Query '{query_id}' is scale-independent. Using SF=1.0 expectation at SF={sf}.")
                    return expected_result_sf1

            # No scale-independent result found - validation will skip
            logger.debug(
                f"No expected results found for benchmark '{benchmark_name}' at scale factor {sf}. "
                f"Validation will be skipped for this query."
            )
            return None

        if benchmark_results is None:
            logger.debug(
                f"No expected results found for benchmark '{benchmark_name}' at scale factor {sf}. "
                f"Validation will be skipped for this query."
            )
            return None

        # Get query-specific result
        expected_result = benchmark_results.get_expected_result(query_id)
        if expected_result is None:
            logger.debug(
                f"No expected result found for query '{query_id}' in benchmark '{benchmark_name}'. "
                f"Validation will be skipped for this query."
            )
            return None

        return expected_result

    def _get_benchmark_results(self, benchmark_key: str, scale_factor: float) -> BenchmarkExpectedResults | None:
        """Get or load benchmark results for a specific scale factor.

        Thread-safe: Uses lock to protect cache and single-flight pattern to prevent duplicate loads.

        Args:
            benchmark_key: Normalized benchmark name (lowercase)
            scale_factor: Scale factor

        Returns:
            Benchmark expected results, or None if not available
        """
        # Single-flight pattern: ensure only one thread loads a given (benchmark, SF) combination
        loading_event = None
        should_load = False

        with self._lock:
            # Check cache first
            if benchmark_key in self._cache and scale_factor in self._cache[benchmark_key]:
                return self._cache[benchmark_key][scale_factor]

            # Check if provider is registered
            if benchmark_key not in self._providers:
                logger.debug(f"No expected results provider registered for benchmark: {benchmark_key}")
                return None

            # Check if another thread is already loading this (benchmark, SF)
            if benchmark_key in self._loading and scale_factor in self._loading[benchmark_key]:
                # Another thread is loading - get event to wait for it
                loading_event = self._loading[benchmark_key][scale_factor]
                should_load = False
            else:
                # We're the first thread - create event and we'll load
                if benchmark_key not in self._loading:
                    self._loading[benchmark_key] = {}
                loading_event = threading.Event()
                self._loading[benchmark_key][scale_factor] = loading_event
                should_load = True

            # Get provider function
            provider = self._providers[benchmark_key]

        # If another thread is loading, wait for it to finish
        if not should_load:
            loading_event.wait(timeout=30.0)  # Wait up to 30 seconds for other thread
            # Now check cache again - other thread should have populated it
            with self._lock:
                if benchmark_key in self._cache and scale_factor in self._cache[benchmark_key]:
                    return self._cache[benchmark_key][scale_factor]
                # If still not in cache, other thread failed - don't retry, just return None
                logger.debug(f"Other thread failed to load {benchmark_key} SF={scale_factor}, not retrying")
                return None

        # Load results using provider (outside lock - this may be slow)
        # Use flag to distinguish recoverable vs permanent failures
        cache_failure = False
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
            cache_failure = True  # Cache to prevent repeated warnings
        except Exception as e:
            # Transient failure: might succeed on retry (don't cache)
            logger.warning(
                f"Failed to load expected results for benchmark '{benchmark_key}' "
                f"at scale factor {scale_factor}: {e}. Will not cache this failure; retry allowed."
            )
            results = None
        finally:
            # Always signal completion and cleanup loading state
            with self._lock:
                # Remove from loading dict
                if benchmark_key in self._loading and scale_factor in self._loading[benchmark_key]:
                    event = self._loading[benchmark_key][scale_factor]
                    del self._loading[benchmark_key][scale_factor]
                    if not self._loading[benchmark_key]:
                        del self._loading[benchmark_key]
                    event.set()  # Signal other threads

        # If permanent failure (FileNotFoundError), cache None to avoid repeated warnings
        if cache_failure:
            with self._lock:
                if benchmark_key not in self._cache:
                    self._cache[benchmark_key] = {}
                self._cache[benchmark_key][scale_factor] = None
            return None

        # If transient failure, return None without caching (allows retry)
        if results is None:
            return None

        # Cache the results under lock
        with self._lock:
            # Double-check cache in case another thread loaded it
            if benchmark_key in self._cache and scale_factor in self._cache[benchmark_key]:
                return self._cache[benchmark_key][scale_factor]

            if benchmark_key not in self._cache:
                self._cache[benchmark_key] = {}

            self._cache[benchmark_key][scale_factor] = results
            logger.debug(
                f"Loaded and cached expected results for benchmark '{benchmark_key}' at scale factor {scale_factor}"
            )

            return results

    def clear_cache(self) -> None:
        """Clear all cached expected results.

        Thread-safe: Uses lock to protect cache access.
        """
        with self._lock:
            self._cache.clear()
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
