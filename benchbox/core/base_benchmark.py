"""Deprecated internal base class for older benchmark implementations.

New public benchmark wrappers should inherit from ``benchbox.base.BaseBenchmark``.
This module remains as an internal compatibility surface while existing core
benchmark implementations finish migrating to the public base.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import abc
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Literal, Optional, Union

from benchbox.core.benchmark_result_validation import BenchmarkResultValidationMixin
from benchbox.core.tuning import BenchmarkTunings

BENCHMARK_API_SURFACE = "deprecated"
BENCHMARK_API_DECISION = "retained-internal-compatibility-base"


class BaseBenchmark(BenchmarkResultValidationMixin, abc.ABC):
    """
    Abstract base class for all benchmarks in BenchBox.

    This class defines the common interface that all benchmark implementations
    must follow. It provides core functionality for benchmark initialization,
    metadata access, resource management, and defines abstract methods for
    benchmark-specific operations.
    """

    api_surface = BENCHMARK_API_SURFACE
    compatibility_marker = BENCHMARK_API_DECISION

    def __init__(self, scale_factor: float = 1.0, **config: Union[str, int, float, bool]) -> None:
        """
        Initialize a benchmark with the specified scale factor and configuration.

        Args:
            scale_factor: A positive number indicating the size of the benchmark
                          data. 1.0 is the standard reference size.
            **config: Additional configuration parameters specific to the
                      benchmark.

        Raises:
            ValueError: If scale_factor is not positive.
        """
        if scale_factor <= 0:
            raise ValueError("Scale factor must be positive")

        # Validate that scale factors >= 1 are whole integers
        if scale_factor >= 1 and scale_factor != int(scale_factor):
            raise ValueError(
                f"Scale factors >= 1 must be whole integers. Got: {scale_factor}. "
                f"Use values like 1, 2, 10, etc. for large scale factors. "
                f"Use values like 0.1, 0.01, 0.001, etc. for small scale factors."
            )

        self.scale_factor = scale_factor
        self.config = config
        # These should be set by subclasses
        self._name: Optional[str] = None
        self._version: Optional[str] = None
        self._description: Optional[str] = None

    @property
    def name(self) -> str:
        """Get the name of the benchmark."""
        if self._name is None:
            # Provide a default name based on the class name
            class_name = self.__class__.__name__
            if class_name.endswith("Benchmark"):
                self._name = class_name[:-9].lower()  # Remove 'Benchmark' suffix
            else:
                self._name = class_name.lower()
        return self._name

    @property
    def version(self) -> str:
        """Get the version of the benchmark."""
        if self._version is None:
            # Provide a default version
            self._version = "1.0"
        return self._version

    @property
    def description(self) -> str:
        """Get the description of the benchmark."""
        if self._description is None:
            # Provide a default description based on the benchmark name
            self._description = f"{self.name.upper()} benchmark implementation"
        return self._description

    def cleanup(self) -> None:
        """
        Clean up any resources used by the benchmark.

        This method should be called when the benchmark is no longer needed.
        It ensures that all resources are properly released.
        """
        # Default implementation does nothing

    def __enter__(self) -> "BaseBenchmark":
        """Enter context manager."""
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        """Exit context manager."""
        self.cleanup()
        # Don't suppress exceptions
        return False

    @property
    def benchmark_name(self) -> str:
        """Get the human-readable benchmark name."""
        return getattr(self, "_name", type(self).__name__)

    def _minimal_result_phases(
        self,
        phases: Optional[dict[str, dict[str, Any]]],
    ) -> None:
        """Deprecated core base keeps legacy minimal-result phase normalization."""
        return None

    @abc.abstractmethod
    def generate_data(self, tables: Optional[list[str]] = None, output_format: str = "memory") -> dict[str, Any]:
        """
        Generate the benchmark data.

        Args:
            tables: Optional list of tables to generate. If None, generates all
                    tables.
            output_format: Format for the generated data. Default is "memory"
                          for in-memory objects. Other formats may include
                          "csv", "parquet", etc.

        Returns:
            A dictionary mapping table names to their generated data.
        """

    @abc.abstractmethod
    def get_query(self, query_id: Union[int, str]) -> str:
        """
        Get the SQL text for a specific query.

        Args:
            query_id: Identifier for the query.

        Returns:
            The SQL text of the query.

        Raises:
            ValueError: If the query_id is not valid.
        """

    @abc.abstractmethod
    def get_all_queries(self) -> dict[Union[int, str], str]:
        """
        Get all available queries for this benchmark.

        Returns:
            A dictionary mapping query identifiers to their SQL text.
        """

    def get_all_query_ids(self) -> list[str]:
        """
        Get all valid query IDs for this benchmark.

        This is a convenience method that returns just the query identifiers
        without the SQL text. It derives the IDs from get_all_queries().

        Returns:
            A list of query identifiers as strings, sorted naturally.
        """
        queries = self.get_all_queries()
        return [str(qid) for qid in sorted(queries.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))]

    @abc.abstractmethod
    def execute_query(
        self,
        query_id: Union[int, str],
        connection: Any,
        params: Optional[Mapping[str, Any]] = None,
    ) -> list[tuple[Any, ...]]:
        """
        Execute a query on the given database connection.

        Args:
            query_id: Identifier for the query to execute.
            connection: Database connection to use for execution.
            params: Optional parameters to use in the query.

        Returns:
            Query results, typically as a list of tuples.

        Raises:
            ValueError: If the query_id is not valid.
        """

    def get_tunings(self) -> Optional[BenchmarkTunings]:
        """
        Get the tuning configurations for this benchmark.

        This method should be overridden by subclasses to provide benchmark-specific
        tuning configurations. The default implementation returns None, indicating
        no tuning configurations are available.

        Returns:
            BenchmarkTunings object containing tuning configurations for all tables
            in the benchmark, or None if no tunings are defined.
        """
        return None

    def validate_tunings(self, tunings: Optional[BenchmarkTunings] = None) -> dict[str, list[str]]:
        """
        Validate tuning configurations against the benchmark schema.

        This method validates that the provided tuning configurations are compatible
        with the benchmark's schema, checking for column existence, type compatibility,
        and potential conflicts.

        Args:
            tunings: Optional tuning configurations to validate. If not provided,
                    uses the result of get_tunings().

        Returns:
            Dictionary mapping table names to lists of validation error messages.
            Empty lists indicate no errors for that table.
        """
        if tunings is None:
            tunings = self.get_tunings()

        if tunings is None:
            return {}

        # Basic validation - subclasses can override for more specific validation
        return tunings.validate_all()
