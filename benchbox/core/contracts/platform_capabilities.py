"""Consumer-driven structural capabilities for benchmark execution.

``PlatformAdapter`` remains the public extension facade for SQL platforms.  These
protocols do not replace it and third-party adapters do not need to inherit from
them: they are narrow structural views used by individual consumers.

The split is intentional.  A review of four representative implementations found
that the same names describe different operations::

    implementation          lifecycle execution       loading       tuning       metrics          result capture
    DuckDBAdapter            SQLBenchmarkExecutor      native        adapter      legacy metadata  plan capture
    PandasDataFrameAdapter   DataFrameBenchmarkExecutor dataframe     ledger       legacy metadata  result builder
    ReadPrimitivesBenchmark  CategorizedQueryBenchmark benchmark     n/a          direct result    n/a
    DatabricksAdapter        SQLBenchmarkExecutor      native/cloud  adapter      legacy metadata  plan capture

The shared concepts are connection ownership, SQL platform orchestration,
DataFrame orchestration, table loading, statistics, tuning-ledger attachment, and
plan capture. Metrics already use the narrow ``StandardPlatformInfo`` protocol in
``benchbox.core.results.platform_info``; duplicating it here would create drift.
The direct ``run_benchmark(connection, ...)`` methods on benchmark classes are
coincidentally named: their query/category/cost semantics are not the platform
orchestration contract and must not be forced into its signature.

Only Read Primitives currently has a production consumer boundary around its
categorized direct-run operation, so only that signature is modeled here. The
general ``BaseBenchmark`` and H2O query-iteration signatures remain classified
as distinct but unmodeled until a real shared consumer exists; exporting unused
protocols for them would imply a uniformity the runtime does not have.

Rejected alternatives:

* An omnibus ``PlatformCapability`` would recreate the non-substitutable base
  class under a new name and force dataframe/cloud/specialized implementations to
  claim operations they do not provide.
* Renaming public ``run_benchmark`` methods solely for type uniformity would break
  downstream callers without improving runtime behavior.
* Nominal capability base classes would make existing third-party adapters opt in
  again.  Structural views preserve the established ``PlatformAdapter`` plus
  ``@register_platform`` extension contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class CapabilityContractError(TypeError):
    """Raised when a consumer receives an object missing its narrow capability."""


class SQLBenchmarkExecutor(Protocol):
    """Execute a benchmark through a SQL platform lifecycle."""

    def run_benchmark(self, benchmark: Any, **run_config: Any) -> Any: ...


class DataFrameBenchmarkExecutor(Protocol):
    """Execute a benchmark through the DataFrame platform lifecycle."""

    def run_benchmark(
        self,
        benchmark: Any,
        *,
        benchmark_config: Any = None,
        system_profile: Any = None,
        data_dir: Path | None = None,
        phases: Any = None,
        options: Any = None,
        monitor: Any = None,
        **run_config: Any,
    ) -> Any: ...


class ConnectionLifecycle(Protocol):
    """Open and close one platform connection."""

    def create_connection(self, **connection_config: Any) -> Any: ...

    def close_connection(self, connection: Any) -> None: ...


class ConnectionFactory(Protocol):
    """Open one platform connection when a consumer must own it."""

    def create_connection(self, **connection_config: Any) -> Any: ...


class NativeTableLoader(Protocol):
    """Create a native schema and load benchmark data into it."""

    def create_schema(self, benchmark: Any, connection: Any) -> float: ...

    def load_data(
        self,
        benchmark: Any,
        connection: Any,
        data_dir: Any,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]: ...


class ExternalTableLoader(Protocol):
    """Register benchmark data through an external-table path."""

    supports_external_tables: bool

    def create_external_tables(
        self,
        benchmark: Any,
        connection: Any,
        data_dir: Any,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]: ...


class DataFrameQueryRuntime(Protocol):
    """Create, load, and query one DataFrame execution context."""

    platform_name: str

    def create_context(self) -> Any: ...

    def load_table(
        self,
        ctx: Any,
        table_name: str,
        file_paths: list[Path],
        column_names: list[str] | None = None,
    ) -> int: ...

    def execute_query(self, ctx: Any, query: Any, query_id: str | None = None) -> dict[str, Any]: ...


class StatisticsPhaseRunner(Protocol):
    """Run the optional post-load statistics phase."""

    def run_statistics_phase(self, benchmark: Any, connection: Any, **options: Any) -> Any: ...


class TuningLedgerWriter(Protocol):
    """Attach an applied-tuning ledger to a result builder."""

    def _write_applied_tuning_ledger(self, builder: Any) -> None: ...


class PlanCaptureRuntime(Protocol):
    """Capture post-measurement query plans on a supplied connection.

    Configuration attributes are intentionally absent: the compatibility path
    historically creates/restores them dynamically with ``getattr`` defaults.
    Connection creation is a separate conditional capability.
    """

    def capture_query_plan(self, connection: Any, query: str, query_id: str) -> tuple[Any, float]: ...


class CategorizedQueryBenchmark(Protocol):
    """Specialized direct runner whose category selection is first-class."""

    def run_benchmark(
        self,
        connection: Any,
        queries: list[str] | None = None,
        iterations: int = 1,
        categories: list[str] | None = None,
    ) -> dict[str, Any]: ...
