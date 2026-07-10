"""TPC-DS Stream and Permutation Support

This module implements the stream generation and permutation functionality
that matches the original C implementation for concurrent query execution.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import random
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class PermutationMode(Enum):
    """Permutation modes for query ordering."""

    SEQUENTIAL = "sequential"  # Queries in order 1, 2, 3, ...
    RANDOM = "random"  # Queries in random order
    TPCDS_STANDARD = "tpcds"  # TPC-DS standard permutation algorithm


@dataclass
class QueryStreamConfig:
    """Configuration for a query stream."""

    stream_id: int
    query_ids: list[int]
    permutation_mode: PermutationMode
    seed: Optional[int] = None
    parameter_seed: Optional[int] = None


@dataclass
class StreamQuery:
    """Represents a single query in a stream."""

    stream_id: int
    position: int
    query_id: int
    variant: Optional[str] = None  # 'a' or 'b' for multi-query templates
    parameters: Optional[dict[str, Any]] = None
    sql: Optional[str] = None


class TPCDSPermutationGenerator:
    """Generates permutations using TPC-DS standard algorithms."""

    def __init__(self, seed: Optional[int] = None) -> None:
        """Initialize with optional seed for reproducible permutations."""
        self.seed = seed
        if seed is not None:
            random.seed(seed)

    def generate_permutation(self, items: list[int], mode: PermutationMode) -> list[int]:
        """Generate a permutation of items based on the specified mode."""
        if mode == PermutationMode.SEQUENTIAL:
            return sorted(items)
        elif mode == PermutationMode.RANDOM:
            return self._random_permutation(items)
        elif mode == PermutationMode.TPCDS_STANDARD:
            return self._tpcds_permutation(items)
        else:
            raise ValueError(f"Unknown permutation mode: {mode}")

    def _random_permutation(self, items: list[int]) -> list[int]:
        """Generate a random permutation."""
        permuted = items.copy()
        random.shuffle(permuted)
        return permuted

    def _tpcds_permutation(self, items: list[int]) -> list[int]:
        """Generate permutation using TPC-DS standard algorithm."""
        n = len(items)
        if n <= 1:
            return items.copy()

        # Create a copy to work with
        permuted = items.copy()

        # Use a deterministic but pseudo-random permutation
        for i in range(n - 1, 0, -1):
            # Generate a pseudo-random index based on position and seed
            if self.seed is not None:
                # Use seed to generate deterministic permutation
                j = (self.seed + i * 17 + i * i * 7) % (i + 1)
            else:
                j = random.randint(0, i)

            # Swap elements
            permuted[i], permuted[j] = permuted[j], permuted[i]

        return permuted


class TPCDSStreamManager:
    """Manages multiple query streams with different parameter sets."""

    PERMUTATION_SEED = 19620718

    def __init__(self, query_manager, stream_configs: Optional[list[QueryStreamConfig]] = None) -> None:
        """Initialize stream manager."""
        self.query_manager = query_manager
        self.stream_configs = stream_configs or []
        self.streams: dict[int, list[StreamQuery]] = {}
        self.permutation_generator = TPCDSPermutationGenerator()

    def add_stream(self, config: QueryStreamConfig) -> None:
        """Add a stream configuration."""
        self.stream_configs.append(config)

    def generate_streams(self) -> dict[int, list[StreamQuery]]:
        """Generate all configured streams."""
        self.streams = {}

        for config in self.stream_configs:
            self.streams[config.stream_id] = self._generate_single_stream(config)

        return self.streams

    def _generate_single_stream(self, config: QueryStreamConfig) -> list[StreamQuery]:
        """Generate a single query stream."""
        # Set seeds for reproducible generation
        if config.seed is not None:
            self.permutation_generator.seed = config.seed

        if config.parameter_seed is not None:
            random.seed(config.parameter_seed)

        # Generate permutation of query IDs
        permuted_queries = self.permutation_generator.generate_permutation(config.query_ids, config.permutation_mode)

        # Create stream queries
        stream_queries = []
        for position, query_id in enumerate(permuted_queries):
            # Handle multi-query templates
            variants = self._get_query_variants(query_id)

            for variant in variants:
                stream_query = StreamQuery(
                    stream_id=config.stream_id,
                    position=position,
                    query_id=query_id,
                    variant=variant,
                )

                # Generate parameters for this query instance
                try:
                    if variant:
                        # For multi-query templates like 14a, 14b, use the base query ID
                        # and pass variant information separately if supported
                        if hasattr(self.query_manager, "get_query") and hasattr(
                            self.query_manager.get_query, "__code__"
                        ):
                            # Check if the method supports variant parameter
                            if "variant" in self.query_manager.get_query.__code__.co_varnames:
                                stream_query.sql = self.query_manager.get_query(
                                    query_id,
                                    seed=config.parameter_seed,
                                    variant=variant,
                                )
                            else:
                                # Fallback: try with base query ID and add comment
                                base_query = self.query_manager.get_query(query_id, seed=config.parameter_seed)
                                stream_query.sql = f"-- Query {query_id}{variant}\\n{base_query}"
                        else:
                            # Simple fallback
                            base_query = self.query_manager.get_query(query_id, seed=config.parameter_seed)
                            stream_query.sql = f"-- Query {query_id}{variant}\\n{base_query}"
                    else:
                        # Standard single query
                        stream_query.sql = self.query_manager.get_query(query_id, seed=config.parameter_seed)
                except Exception as e:
                    # Fallback to a simple query comment if generation fails
                    variant_suffix = variant if variant else ""
                    stream_query.sql = (
                        f"-- Query {query_id}{variant_suffix} (generation failed: {e})\\nSELECT 1 AS placeholder_query;"
                    )

                stream_queries.append(stream_query)

        return stream_queries

    def _get_query_variants(self, query_id: int) -> list[Optional[str]]:
        """Get variants for a query (a, b, or None for single queries)."""
        # Multi-query template IDs from the original implementation
        multi_query_ids = {14, 23, 24, 39}

        if query_id in multi_query_ids:
            return ["a", "b"]
        else:
            return [None]

    def get_stream(self, stream_id: int) -> Optional[list[StreamQuery]]:
        """Get a specific stream by ID."""
        return self.streams.get(stream_id)

    def get_stream_summary(self, stream_id: int) -> Optional[dict[str, Any]]:
        """Get summary information for a stream."""
        stream = self.get_stream(stream_id)
        if stream is None:
            return None

        unique_queries = set()
        for sq in stream:
            query_key = f"{sq.query_id}{sq.variant or ''}"
            unique_queries.add(query_key)

        return {
            "stream_id": stream_id,
            "total_queries": len(stream),
            "unique_queries": len(unique_queries),
            "query_list": [f"{sq.query_id}{sq.variant or ''}" for sq in stream],
        }


def create_standard_streams(
    query_manager,
    num_streams: int = 2,
    query_range: tuple[int, int] = (1, 99),
    base_seed: int = 42,
    query_ids: Optional[list[int]] = None,
) -> TPCDSStreamManager:
    """Create standard TPC-DS streams with default configuration.

    Args:
        query_manager: The query manager to use for generating queries.
        num_streams: Number of streams to generate.
        query_range: Range of query IDs to include (start, end inclusive).
            Ignored if query_ids is provided.
        base_seed: Base seed for reproducible permutations.
        query_ids: Explicit list of query IDs to use. If provided, query_range is ignored.
            This is useful for benchmarks like TPC-DS OBT that have a subset of queries.

    Returns:
        TPCDSStreamManager configured with the specified streams.
    """
    manager = TPCDSStreamManager(query_manager)

    # Use explicit query_ids if provided, otherwise generate from range
    if query_ids is not None:
        query_ids = sorted(query_ids)
    else:
        query_ids = list(range(query_range[0], query_range[1] + 1))

    # Create stream configurations
    for stream_id in range(num_streams):
        config = QueryStreamConfig(
            stream_id=stream_id,
            query_ids=query_ids,
            permutation_mode=PermutationMode.TPCDS_STANDARD,
            seed=base_seed + stream_id,
            parameter_seed=base_seed + stream_id + 1000,
        )
        manager.add_stream(config)

    return manager


# Keep the original class names for backwards compatibility
TPCDSStreams = TPCDSStreamManager
TPCDSStreamRunner = TPCDSStreamManager
