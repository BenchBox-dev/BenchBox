"""Base platform adapter interface.

Defines the interface for database platform adapters.
Provides database-specific optimizations with consistent API.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import math
import threading
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from benchbox.core.results.query_plan_models import DEFAULT_PLAN_MAX_DEPTH
from benchbox.core.results.schema import compute_plan_capture_stats
from benchbox.platforms.base.connection_lifecycle import ConnectionLifecycleMixin
from benchbox.platforms.base.connection_wrappers import (
    DriverIsolationCapability,
    PlatformAdapterConnection,  # noqa: F401 - re-exported for external imports
    PlatformAdapterCursor,  # noqa: F401 - re-exported for external imports
    StreamConnectionCapability,
    _make_stream_cursor,
    _NoCloseProxy,  # noqa: F401 - re-exported for external imports
    check_isolation_capability,  # noqa: F401 - re-exported for external imports
)
from benchbox.platforms.base.data_loading import SchemaHelpersMixin
from benchbox.platforms.base.dialect_translation import DialectTranslationMixin
from benchbox.platforms.base.execution import TestDriversMixin
from benchbox.platforms.base.models import (
    SetupPhase,
    StatisticsGatheringPhase,
)
from benchbox.platforms.base.phase_tracking import (
    PhaseTrackingMixin,
    _extract_table_names,  # noqa: F401 - re-exported for backward compat
    _resolve_benchmark_table_names,  # noqa: F401 - re-exported for backward compat
)
from benchbox.platforms.base.result_capture import ResultCaptureMixin
from benchbox.platforms.base.sorted_ingestion import SortedIngestionMixin
from benchbox.platforms.base.tuning import TuningHooksMixin
from benchbox.platforms.base.tuning_config import TuningConfigMixin
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.printing import quiet_console
from benchbox.utils.verbosity import VerbosityMixin, VerbositySettings

# Import result models for type hints and re-export alias
try:
    from benchbox.core.results.models import (
        BenchmarkResults,
        ExecutionPhases,  # noqa: F401 - re-exported via __init__.py
        QueryDefinition,  # noqa: F401 - re-exported via __init__.py
    )
except ImportError:
    BenchmarkResults = None
    ExecutionPhases = None
    QueryDefinition = None

# Import tuning interface classes used in abstract method signatures
try:
    from benchbox.core.tuning.interface import (
        ForeignKeyConfiguration,
        PlatformOptimizationConfiguration,
        PrimaryKeyConfiguration,
    )
except ImportError:
    PrimaryKeyConfiguration = None
    ForeignKeyConfiguration = None
    PlatformOptimizationConfiguration = None

# Import validation classes
try:
    from benchbox.core.validation import ValidationResult
except ImportError:
    # Handle case where validation module is not available
    ValidationResult = None

# Re-export alias for existing imports/tests
EnhancedBenchmarkResults = BenchmarkResults


class PlatformAdapter(
    ConnectionLifecycleMixin,
    DialectTranslationMixin,
    PhaseTrackingMixin,
    ResultCaptureMixin,
    SchemaHelpersMixin,
    SortedIngestionMixin,
    TestDriversMixin,
    TuningConfigMixin,
    TuningHooksMixin,
    VerbosityMixin,
    ABC,
):
    """Abstract base class for database platform adapters.

    This interface defines the contract that all platform adapters must implement
    to provide database-specific optimizations for benchmark execution.
    """

    # Explicit capability declaration for driver version isolation.
    # Subclasses should override this class variable to declare their capability.
    # Default is NOT_APPLICABLE - adapters that support isolation must opt in.
    driver_isolation_capability: DriverIsolationCapability = DriverIsolationCapability.NOT_APPLICABLE
    # Per-stream connection capability for concurrent throughput/pool-test streams
    # (see StreamConnectionCapability docstring). Default is SHARED_CURSOR, which
    # preserves today's behavior for every adapter that does not opt in: streams
    # share one cursor per connection, correct for embedded engines like DuckDB.
    # Server-style (client/server) adapters that need one independent connection
    # per stream must set this to INDEPENDENT_CONNECTION *and* override
    # new_stream_connection() below - declaring the capability alone is not
    # enough, since the base new_stream_connection() raises for that value to
    # fail fast instead of silently falling back to cursor sharing.
    stream_connection_capability: StreamConnectionCapability = StreamConnectionCapability.SHARED_CURSOR
    # External table mode capability declaration.
    # Subclasses that implement external table/view registration should set this to True.
    supports_external_tables: bool = False
    # Plan-capture style. When True, the generic query pipeline captures plans in
    # an isolated post-measurement phase (a single EXPLAIN pass after all timed
    # queries on the same connection) instead of inline inside each timed
    # execute_query(). This is the canonical default for EVERY EXPLAIN-based
    # engine: a standalone EXPLAIN on the measurement connection reproduces the
    # plan with no loss, so capture is fully isolatable from measurement.
    # The ONLY exceptions are engines whose plan/stats are obtainable solely as a
    # side effect of running the workload query (BigQuery-class): they set this
    # False explicitly and keep their inline/job-harvest capture path.
    plan_capture_phase_eligible: bool = True

    def __init__(self, **config):
        """Initialize the platform adapter with configuration.

        Args:
            **config: Platform-specific configuration options
        """
        self.platform_config = config
        self.connection = None
        self.connection_pool = None
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self._dialect = self.get_target_dialect()
        self.force_recreate = config.get("force_recreate", False)
        self.show_query_plans = config.get("show_query_plans", False)
        self.capture_plans = config.get("capture_plans", False)
        # When False (default), plan capture uses plain EXPLAIN (FORMAT JSON) for
        # estimated-plan-only capture with no re-execution overhead: fingerprints are
        # structure-only, so estimated plans lose nothing for structural comparison.
        # Set to True to opt into EXPLAIN (ANALYZE, FORMAT JSON), which re-executes
        # every captured SELECT once to include actual per-operator timing and
        # cardinality -- roughly 2x wall-clock for a --capture-plans run and
        # perturbed cache state. A one-time run-level notice is printed the first
        # time a plan is actually captured with this enabled (see
        # ResultCaptureMixin.capture_query_plan).
        self.analyze_plans: bool = config.get("analyze_plans", False)
        self.strict_plan_capture = config.get("strict_plan_capture", False)
        # When True, also record a literal-normalized plan fingerprint alongside
        # the default fingerprint during plan capture (see --normalize-plan-literals).
        self.normalize_plan_literals = config.get("normalize_plan_literals", False)
        self.plan_capture_timeout_seconds = int(config.get("plan_capture_timeout_seconds", 30))
        # Maximum logical-tree depth serialized when a captured plan is written to
        # the results bundle / size-checked. Nodes deeper than this become a
        # truncation marker instead of dropping the whole plan (see
        # query_plan_models.DEFAULT_PLAN_MAX_DEPTH). The structural fingerprint is
        # computed over the full in-memory tree, so it is unaffected by this cap.
        self.plan_max_depth = int(config.get("plan_max_depth", DEFAULT_PLAN_MAX_DEPTH))
        # Plan capture query selection. plan_query_filter restricts capture to an
        # explicit set of query ids; it is orthogonal to the retired per-iteration /
        # per-stream sampling machinery (plan_first_n / plan_sampling_rate), which the
        # canonical capture-once-per-query model made obsolete and which is gone.
        plan_queries_str = config.get("plan_queries")
        self.plan_query_filter: set[str] | None = (
            {q.strip() for q in plan_queries_str.split(",") if q.strip()} if plan_queries_str else None
        )
        # Guards concurrent writes to _phase_recorded_queries from throughput streams.
        self._plan_capture_lock = threading.Lock()
        # Isolated-phase plan capture (see TestDriversMixin._execute_queries_by_type).
        # When ``_plan_capture_phase_active`` is True, the inline capture chokepoint
        # (_merge_plan_capture_into_result) records each executed query into
        # ``_phase_recorded_queries`` instead of running EXPLAIN inline, so capture is
        # fully isolated from the timed run for every test type. The plans are captured
        # once, post-measurement, by the isolated phase. The buffer is written from
        # concurrent throughput streams, so writes are guarded by _plan_capture_lock.
        self._plan_capture_phase_active: bool = False
        self._phase_recorded_queries: dict[str, str] = {}
        self.tuning_enabled = config.get("tuning_enabled", False)
        # Driver runtime contract metadata (set by adapter factory / runtime resolution).
        self.driver_package = config.get("driver_package")
        self.driver_version_requested = config.get("driver_version") or config.get("driver_version_requested")
        self.driver_version_resolved = config.get("driver_version_resolved")
        self.driver_version_actual = config.get("driver_version_actual")
        self.driver_runtime_strategy = config.get("driver_runtime_strategy")
        self.driver_runtime_path = config.get("driver_runtime_path")
        self.driver_runtime_python_executable = config.get("driver_runtime_python_executable")
        self.driver_auto_install_used = bool(config.get("driver_auto_install_used", False))

        # Unified tuning configuration support
        self.unified_tuning_configuration = config.get("unified_tuning_configuration")

        # Verbose logging configuration
        self.apply_verbosity(VerbositySettings.from_mapping(config))

        # Track whether existing database was reused (vs recreated)
        self.database_was_reused = False

        # Table mode: "native" (default) or "external" (external table/view references)
        self.table_mode: str = "native"
        # External format detected during external table creation (e.g., "parquet", "delta", "tbl")
        self.external_format: str | None = None
        # Explicit --table-format from CLI; overrides platform defaults for this run only
        self.requested_table_format: str | None = None

        # Dry-run mode support
        self.dry_run = config.get("dry_run", False)
        self.dry_run_mode = False
        self.captured_sql = []
        self.query_counter = 0

        self.enable_validation = config.get("enable_validation", False)

        # Track latest throughput metrics for phase construction
        self._last_throughput_test_result = None
        self._sorted_ingestion_applied_tables: list[str] = []
        self._sorted_ingestion_total_apply_seconds: float = 0.0
        self._reset_plan_capture_stats()

    def _reset_run_scoped_state(self) -> None:
        """Reset mutable state that belongs to one benchmark execution."""
        self.database_was_reused = False
        self._last_power_test_result = None
        self._last_throughput_test_result = None
        self._sorted_ingestion_applied_tables = []
        self._sorted_ingestion_total_apply_seconds = 0.0
        self._reset_plan_capture_stats()
        if self.dry_run_mode:
            self.captured_sql = []
            self.query_counter = 0

    @staticmethod
    @abstractmethod
    def add_cli_arguments(parser) -> None:
        """Add platform-specific CLI arguments to the argument parser.

        Args:
            parser: argparse.ArgumentParser instance to add arguments to
        """

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict[str, Any]):
        """Create platform adapter instance from unified configuration.

        Args:
            config: Unified configuration dictionary

        Returns:
            Platform adapter instance
        """

    @property
    def platform_name(self) -> str:
        """Return the name of this database platform.

        Default implementation returns the class name. Concrete adapters may
        override to provide a user-friendly display name. Lightweight adapters
        can rely on this default when no custom name is required.
        """
        return self.__class__.__name__

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get platform information for results traceability.

        Default implementation returns minimal generic info. Platform adapters
        should override to provide richer details, but tests may instantiate
        lightweight adapters without implementing this method.
        """
        platform_info = {
            "platform_type": self.platform_name.lower(),
            "platform_name": self.platform_name,
            "platform_version": "unknown",
            "connection_mode": "unknown",
            "host": None,
            "port": None,
            "configuration": {},
            "client_library_version": None,
            "embedded_library_version": None,
        }
        if self.driver_package:
            platform_info["driver_package"] = self.driver_package
        if self.driver_version_requested:
            platform_info["driver_version_requested"] = self.driver_version_requested
        if self.driver_version_resolved:
            platform_info["driver_version_resolved"] = self.driver_version_resolved
        if self.driver_version_actual:
            platform_info["driver_version_actual"] = self.driver_version_actual
        if self.driver_runtime_strategy:
            platform_info["driver_runtime_strategy"] = self.driver_runtime_strategy
        return platform_info

    @abstractmethod
    def create_connection(self, **connection_config) -> Any:
        """Create and return a database connection.

        Args:
            **connection_config: Connection-specific parameters

        Returns:
            Database connection object
        """

    @abstractmethod
    def create_schema(self, benchmark, connection: Any) -> float:
        """Create database schema for the benchmark.

        Args:
            benchmark: Benchmark instance with schema definitions
            connection: Database connection

        Returns:
            Time taken to create schema in seconds
        """

    @abstractmethod
    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply platform-specific optimizations.

        Args:
            platform_config: Platform optimization configuration
            connection: Database connection
        """

    @abstractmethod
    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations to the database.

        Args:
            primary_key_config: Primary key constraint configuration
            foreign_key_config: Foreign key constraint configuration
            connection: Database connection
        """

    @abstractmethod
    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load benchmark data into database using platform-specific methods.

        Args:
            benchmark: Benchmark instance
            connection: Database connection
            data_dir: Directory containing data files

        Returns:
            Tuple of (table_statistics, loading_time_seconds, per_table_timings)
            where per_table_timings is optional dict with detailed timing per table
        """

    def create_external_tables(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Register benchmark tables as external references instead of loading native tables.

        Platforms that support external-table mode should override this method and
        return the same tuple shape as ``load_data``.

        Args:
            benchmark: Benchmark instance
            connection: Database connection
            data_dir: Directory containing source data files or external data roots

        Returns:
            Tuple of (table_statistics, loading_time_seconds, per_table_timings)
            where per_table_timings is optional dict with detailed timing per table
        """
        raise NotImplementedError(f"{self.platform_name} does not support external table mode")

    def upload_manifest(self, manifest_path: Path, remote_path: str) -> bool:
        """Upload manifest to remote storage. Override in subclasses if supported.

        Args:
            manifest_path: Local manifest file path
            remote_path: Remote directory path/URI where manifest should be uploaded

        Returns:
            True if upload succeeded, False if unsupported or not uploaded
        """
        # Default: no-op
        self.logger.debug(f"upload_manifest not implemented for {self.__class__.__name__} (remote_path={remote_path})")
        return False

    @abstractmethod
    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply platform-specific optimizations for the benchmark type.

        Args:
            connection: Database connection
            benchmark_type: Type of benchmark (e.g., "olap", "oltp", "analytics")
        """

    def gather_statistics(self, connection: Any, table_names: list[str]) -> tuple[str, int]:
        """Run the platform's explicit statistics build for the statistics phase.

        Returns (stats_mode, tables_analyzed). The default resolves the
        adapter's existing analyze surface: whole-database ``analyze_tables``
        when available, else per-table ``analyze_table``, else
        ``("unsupported", 0)``. Engines whose statistics are built during load
        (e.g. Redshift with auto_analyze) override this to report
        ``("auto-on-load", 0)`` instead of double-building.
        """
        analyze_tables = getattr(self, "analyze_tables", None)
        if callable(analyze_tables):
            analyze_tables(connection)
            return "explicit", len(table_names)
        analyze_table = getattr(self, "analyze_table", None)
        if callable(analyze_table):
            for table_name in table_names:
                analyze_table(connection, table_name)
            return "explicit", len(table_names)
        return "unsupported", 0

    def reset_statistics(self, connection: Any, table_names: list[str]) -> str:
        """Reset (drop/invalidate) optimizer statistics ahead of a cold-stats rebuild.

        Sibling of ``gather_statistics`` for the reset/persist control (opt-in
        via the statistics phase's ``reset=True``). Returns a stats_lifecycle
        marker: ``"reset"`` when statistics were actually cleared, or
        ``"unsupported"`` when this adapter has no generic drop-stats
        primitive it's safe to run generically.

        The base default is a documented no-op that always returns
        ``"unsupported"``: engines must never have this method force an
        operation that could fail or corrupt state on a platform it wasn't
        vetted for. This is a safe fallback rather than a regression - the
        statistics phase's subsequent ``gather_statistics()`` call still runs
        a full ANALYZE/rebuild that reflects current data, so a cold-stats
        study remains meaningful even without an explicit reset step.
        Platform adapters that support a real drop-stats operation should
        override this method.
        """
        self.logger.debug(
            f"reset_statistics not implemented for {self.__class__.__name__}; "
            "no generic drop-stats primitive, deferring to the gather_statistics rebuild"
        )
        return "unsupported"

    def run_statistics_phase(
        self,
        benchmark: Any,
        connection: Any,
        *,
        benchmark_name: str = "",
        table_names: list[str] | None = None,
        reset: bool | None = None,
        collect_per_table_timing: bool = False,
    ) -> StatisticsGatheringPhase | None:
        """Run the opt-in statistics phase between load and query execution.

        Returns None (phase not run) when the benchmark has not opted in via
        the registry's ``supports_statistics_phase`` flag, so legacy
        benchmarks keep load-includes-stats semantics and their historical
        bundles stay comparable. Failures are recorded on the phase rather
        than aborting the run - queries remain meaningful on unanalyzed data.

        Args:
            reset: Cold-stats vs warm-stats control. None (default) leaves
                statistics untouched and records no stats_lifecycle marker,
                exactly matching the PR #980 shipped behavior. True resets
                statistics via ``reset_statistics()`` before rebuilding
                (cold-stats). False explicitly records a "persist" marker
                (warm-stats) without changing behavior.
            collect_per_table_timing: When True and this adapter's statistics
                build falls back to a per-table ANALYZE loop (no whole-database
                analyze hook, and gather_statistics is not overridden with
                platform-specific routing), record a per-table wall-clock
                breakdown on the returned phase. Left None otherwise.
        """
        from benchbox.core.benchmark_registry import get_benchmark_metadata

        slug = (benchmark_name or "").lower()
        metadata = get_benchmark_metadata(slug) if slug else None
        if not (metadata or {}).get("supports_statistics_phase"):
            quiet_console.print(
                f"⏭️  Statistics phase requested but benchmark '{slug or 'unknown'}' has not opted in; "
                "skipping (load keeps legacy statistics semantics)"
            )
            return None

        names = table_names or _resolve_benchmark_table_names(benchmark)
        quiet_console.print("Gathering optimizer statistics...")
        start_time = mono_time()

        stats_lifecycle: str | None = None
        if reset:
            try:
                stats_lifecycle = self.reset_statistics(connection, names) or "unsupported"
            except Exception as exc:
                self.logger.warning(f"Statistics reset failed, continuing with rebuild: {exc}")
                stats_lifecycle = "unsupported"
        elif reset is False:
            # The control was explicitly exercised in persist mode (warm-stats
            # study): record the marker even though behavior matches default.
            stats_lifecycle = "persist"

        # Per-table timing is only safe to collect by looping analyze_table()
        # ourselves when gather_statistics() is the unmodified base
        # implementation - platform overrides (e.g. Redshift's auto-on-load
        # routing) must keep deciding stats_mode themselves, so we defer to
        # gather_statistics() and leave per_table_ms unset for those adapters.
        per_table_ms: dict[str, int] | None = None
        use_per_table_loop = (
            collect_per_table_timing
            and type(self).gather_statistics is PlatformAdapter.gather_statistics
            and callable(getattr(self, "analyze_table", None))
            and not callable(getattr(self, "analyze_tables", None))
        )
        try:
            if use_per_table_loop:
                per_table_ms = {}
                analyze_table = self.analyze_table  # type: ignore[attr-defined]
                for table_name in names:
                    table_start = mono_time()
                    analyze_table(connection, table_name)
                    per_table_ms[table_name] = int(elapsed_seconds(table_start) * 1000)
                stats_mode, tables_analyzed = "explicit", len(names)
            else:
                stats_mode, tables_analyzed = self.gather_statistics(connection, names)
        except Exception as exc:
            self.logger.warning(f"Statistics phase failed: {exc}")
            return StatisticsGatheringPhase(
                duration_ms=int(elapsed_seconds(start_time) * 1000),
                status="FAILED",
                stats_mode="explicit",
                tables_analyzed=0,
                error_message=str(exc),
                stats_lifecycle=stats_lifecycle,
            )
        return StatisticsGatheringPhase(
            duration_ms=int(elapsed_seconds(start_time) * 1000),
            status="COMPLETED",
            stats_mode=stats_mode,
            tables_analyzed=tables_analyzed,
            stats_lifecycle=stats_lifecycle,
            per_table_ms=(per_table_ms or None),
        )

    @abstractmethod
    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute a single query and return detailed results.

        Args:
            connection: Database connection
            query: SQL query text
            query_id: Query identifier
            benchmark_type: Type of benchmark (e.g., "tpch", "tpcds") for row count validation
            scale_factor: Scale factor used for the query (for row count validation)
            validate_row_count: Whether to validate row count against expected results
            stream_id: Stream identifier for multi-stream benchmarks (e.g., 0, 1, 2...)
                      Used to select stream-specific expected results. None indicates stream 0
                      or single-stream execution.

        Returns:
            Dictionary with execution results including query_id, status
            ("SUCCESS", "FAILED", or "DRY_RUN"), execution_time_seconds,
            rows_returned, and optional row_count_validation fields.
        """

    def close_connection(self, connection: Any) -> None:
        """Close database connection and cleanup resources.

        Args:
            connection: Database connection to close
        """
        if connection and hasattr(connection, "close"):
            connection.close()

    def new_stream_connection(self, connection: Any) -> Any:
        """Return a per-stream execution handle for one concurrent throughput
        (or connection-pool test) stream.

        This is the capability seam for ``throughput-independent-sessions-per-stream``:
        the throughput drivers' ``connection_factory`` closures
        (``benchbox/platforms/base/execution.py``,
        ``_execute_tpch_throughput_test`` / ``_execute_tpcds_throughput_test``)
        call this once per stream instead of unconditionally sharing one
        cursor, so the behavior is now a declared, overridable platform
        capability rather than an implicit one-size-fits-all default.

        Dispatches on ``stream_connection_capability``:

        - ``SHARED_CURSOR`` (default): returns ``_make_stream_cursor(connection)``
          - a cursor of (or ``_NoCloseProxy`` over) the single shared
          ``connection`` passed in. This is the existing, unchanged fast path:
          correct for embedded engines whose client is documented thread-safe
          at cursor level against one process-local database (e.g. DuckDB -
          see docs/benchmarks/tpc-h.md). No new connections are opened, and
          closing the returned handle never closes the shared connection
          (``_NoCloseProxy.close()`` is a no-op; a real cursor's ``close()``
          only closes the cursor).
        - ``INDEPENDENT_CONNECTION``: server-style adapters (client/server
          engines whose driver does not support true concurrent statement
          execution across cursors of one connection) MUST override this
          method to open and return a brand-new connection/session, typically
          ignoring the ``connection`` argument entirely. The base
          implementation deliberately raises ``NotImplementedError`` for this
          capability value instead of falling back to cursor sharing, so a
          subclass that declares ``INDEPENDENT_CONNECTION`` without overriding
          fails loudly rather than silently reproducing the shared-session bug
          this capability exists to fix.

        Args:
            connection: The adapter's shared platform connection (as created by
                ``create_connection``). Used as-is for ``SHARED_CURSOR``;
                available for reference (e.g. to read connection parameters)
                but not required for ``INDEPENDENT_CONNECTION`` overrides.

        Returns:
            A connection-like object suitable for one stream: either a cursor/
            proxy over the shared connection, or an independent connection.
        """
        if self.stream_connection_capability is StreamConnectionCapability.INDEPENDENT_CONNECTION:
            raise NotImplementedError(
                f"{self.platform_name} declares stream_connection_capability="
                "StreamConnectionCapability.INDEPENDENT_CONNECTION but does not override "
                "new_stream_connection() to open an independent per-stream connection/session."
            )
        return _make_stream_cursor(connection)

    def validate_platform_capabilities(self, benchmark_type: str) -> ValidationResult:
        """Validate platform-specific capabilities for the benchmark.

        Args:
            benchmark_type: Type of benchmark (e.g., 'tpcds', 'tpch')

        Returns:
            ValidationResult with platform capability validation status
        """
        errors = []
        warnings = []

        # Base validation - can be overridden by specific platforms
        platform_info = {
            "platform": self.platform_name,
            "benchmark_type": benchmark_type,
            "dry_run_mode": self.dry_run_mode,
        }

        # Check if platform supports the benchmark
        if benchmark_type.lower() not in ["tpcds", "tpch"]:
            warnings.append(f"Benchmark type '{benchmark_type}' may not be fully supported")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            details=platform_info,
        )

    def run_enhanced_benchmark(self, benchmark, **run_config) -> EnhancedBenchmarkResults:
        """Run complete benchmark with enhanced phase tracking."""
        start_time = mono_time()
        execution_id = str(uuid.uuid4())[:8]
        self._reset_run_scoped_state()
        plan_capture_config = {
            "capture_plans": self.capture_plans,
            "analyze_plans": self.analyze_plans,
            "strict_plan_capture": self.strict_plan_capture,
            "plan_capture_timeout_seconds": self.plan_capture_timeout_seconds,
        }
        if "capture_plans" in run_config:
            self.capture_plans = bool(run_config.get("capture_plans"))
        # analyze_plans is tri-state in RunConfig: only override the adapter's value
        # when the first-class flag was set (non-None); None leaves the adapter default.
        if run_config.get("analyze_plans") is not None:
            self.analyze_plans = bool(run_config.get("analyze_plans"))
        if "strict_plan_capture" in run_config:
            self.strict_plan_capture = bool(run_config.get("strict_plan_capture"))
        if "normalize_plan_literals" in run_config:
            self.normalize_plan_literals = bool(run_config.get("normalize_plan_literals"))
        if "plan_capture_timeout_seconds" in run_config:
            self.plan_capture_timeout_seconds = int(run_config.get("plan_capture_timeout_seconds"))

        try:
            # Step 1: Data generation phase (handled by run_benchmark_lifecycle before this call)
            data_generation_phase = self._create_enhanced_data_generation_phase(benchmark)

            quiet_console.print(f"Connecting to {self.platform_name}...")
            self.log_very_verbose(f"database_was_reused flag BEFORE connection: {self.database_was_reused}")
            self.benchmark = benchmark  # Store for handle_existing_database() to access
            connection = self.create_connection(**run_config.get("connection", {}))
            self.connection = connection
            self.log_very_verbose(f"database_was_reused flag AFTER connection: {self.database_was_reused}")

            # Step 3: Validate tuning configuration if enabled
            effective_tuning_config = self.get_effective_tuning_configuration()
            if self.tuning_enabled and effective_tuning_config:
                quiet_console.print("Validating unified tuning configuration...")
                tuning_errors = effective_tuning_config.validate_for_platform(self.platform_name)
                if tuning_errors:
                    raise ValueError(f"Invalid tuning configuration: {'; '.join(tuning_errors)}")
                quiet_console.print("✅ Unified tuning configuration validated")

            # Step 4: Schema creation and data loading
            self.log_verbose(f"Checking database_was_reused flag before schema creation: {self.database_was_reused}")
            if self.database_was_reused:
                (
                    schema_time,
                    schema_creation_phase,
                    loading_time,
                    table_stats,
                    data_loading_phase,
                    tuning_metadata_saved,
                ) = self._setup_reused_database_phases(benchmark, connection)
            else:
                (
                    schema_time,
                    schema_creation_phase,
                    loading_time,
                    table_stats,
                    data_loading_phase,
                    tuning_metadata_saved,
                ) = self._setup_fresh_database_phases(benchmark, connection, effective_tuning_config)

            quiet_console.print("Validating benchmark data...")
            validation_phase = self._create_enhanced_validation_phase(benchmark, connection, table_stats)

            tunings_applied_dict = None
            tuning_validation_status = "NOT_APPLICABLE"
            if self.tuning_enabled and effective_tuning_config:
                tunings_applied_dict = effective_tuning_config.to_dict()
                tuning_validation_status = "APPLIED" if tuning_metadata_saved else "FAILED_TO_SAVE"

            if self._check_validation_failure(validation_phase):
                return self._create_failed_benchmark_result(
                    benchmark,
                    validation_phase,
                    table_stats,
                    loading_time,
                    schema_creation_phase,
                    data_loading_phase,
                    tunings_applied_dict,
                    tuning_validation_status,
                    tuning_metadata_saved,
                )

            quiet_console.print("✅ Data validation passed")

            benchmark_type = run_config.get("benchmark_type", "olap")
            self.configure_for_benchmark(connection, benchmark_type)

            # Opt-in statistics phase: load -> statistics -> query, so
            # stats-build wall-clock is attributed to neither load nor query.
            statistics_phase = None
            if run_config.get("gather_statistics"):
                # Prefer a dedicated statistics-only slug over "benchmark_name"
                # when the caller set one. Some callers (the MCP run_benchmark
                # tool) need the registry gate to resolve correctly without also
                # setting "benchmark_name" itself, which _resolve_benchmark_slug
                # reads to route power/throughput/maintenance/combined tests to
                # TPC-specialized harnesses vs the generic handler - requesting
                # the statistics phase must not also change which harness runs.
                statistics_phase = self.run_statistics_phase(
                    benchmark,
                    connection,
                    benchmark_name=run_config.get("statistics_benchmark_name") or run_config.get("benchmark_name", ""),
                    table_names=sorted(table_stats) if table_stats else None,
                    reset=run_config.get("stats_reset"),
                    collect_per_table_timing=bool(run_config.get("stats_per_table_timing", False)),
                )

            test_execution_type = run_config.get("test_execution_type", "standard")
            quiet_console.print(f"Executing benchmark queries ({test_execution_type} mode)...")
            self._last_throughput_test_result = None
            query_results = self._execute_queries_by_type(benchmark, connection, run_config)

            # Get queries for definitions - pass canonical slug so dialect selection
            # doesn't have to infer benchmark family from object internals.
            queries = self._get_dialect_queries(
                benchmark,
                benchmark_slug=run_config.get("benchmark_name", ""),
                connection=connection,
            )
            stream_id = "standard"
            self._extract_query_definitions(benchmark, queries, stream_id)
            query_executions = self._create_standard_execution_phase(query_results, stream_id)

            # Step 7: Compile enhanced results
            total_duration = elapsed_seconds(start_time)

            setup_phase = SetupPhase(
                data_generation=data_generation_phase,
                schema_creation=schema_creation_phase,
                data_loading=data_loading_phase,
                validation=validation_phase,
                statistics_gathering=statistics_phase,
            )

            execution_phases, total_exec_time, power_test_phase, throughput_test_phase = self._build_execution_phases(
                query_results, query_executions, run_config, setup_phase
            )

            platform_info = self.get_platform_info(connection)
            normalized_metadata = self.get_normalized_result_metadata(
                connection=connection,
                platform_info=platform_info,
            )
            execution_metadata, system_profile, anonymous_machine_id = self._build_execution_metadata(run_config)

            total_rows_loaded = sum(table_stats.values()) if table_stats else 0
            data_size_mb = self._calculate_data_size(benchmark.output_dir) if hasattr(benchmark, "output_dir") else 0.0

            resource_snapshot = self._collect_resource_utilization()
            performance_summary = self._summarize_performance_characteristics(
                query_results=query_results,
                total_duration=total_duration,
                total_rows_loaded=total_rows_loaded,
            )

            power_at_size = power_test_phase.power_at_size if power_test_phase else None
            throughput_at_size = throughput_test_phase.throughput_at_size if throughput_test_phase else None

            qph_at_size = None
            if power_at_size and power_at_size > 0 and throughput_at_size and throughput_at_size > 0:
                qph_at_size = math.sqrt(power_at_size * throughput_at_size)

            eet = run_config.get("_effective_execution_type")
            execution_type = eet if eet is not None else run_config.get("test_execution_type", "standard")

            _plans_captured, _failures, _plan_errors = compute_plan_capture_stats(
                query_results,
                self.capture_plans,
                existing_errors=list(self.plan_capture_errors),
            )

            return benchmark.create_enhanced_benchmark_result(
                platform=self.platform_name,
                query_results=query_results,
                execution_metadata=execution_metadata,
                phases=execution_phases,
                resource_utilization=resource_snapshot,
                performance_characteristics=performance_summary,
                query_plans_captured=_plans_captured,
                plan_capture_failures=_failures,
                plan_capture_errors=_plan_errors,
                execution_id=execution_id,
                duration_seconds=total_duration,
                data_loading_time=loading_time,
                schema_creation_time=schema_time,
                total_rows_loaded=total_rows_loaded,
                data_size_mb=data_size_mb,
                table_statistics=table_stats or {},
                platform_info=platform_info,
                **normalized_metadata,
                tunings_applied=tunings_applied_dict,
                tuning_validation_status=tuning_validation_status,
                tuning_metadata_saved=tuning_metadata_saved,
                system_profile=system_profile,
                anonymous_machine_id=anonymous_machine_id,
                validation_status=self._determine_overall_validation_status(validation_phase),
                validation_details=validation_phase.validation_details,
                power_at_size=power_at_size,
                throughput_at_size=throughput_at_size,
                qph_at_size=qph_at_size,
                test_execution_type=execution_type,
            )

        finally:
            self.capture_plans = plan_capture_config["capture_plans"]
            self.analyze_plans = plan_capture_config["analyze_plans"]
            self.strict_plan_capture = plan_capture_config["strict_plan_capture"]
            self.plan_capture_timeout_seconds = plan_capture_config["plan_capture_timeout_seconds"]
            if hasattr(self, "connection") and self.connection:
                self.close_connection(self.connection)
                self.connection = None

    def run_benchmark(self, benchmark, **run_config) -> EnhancedBenchmarkResults:
        """Run complete benchmark with enhanced phase tracking.

        Args:
            benchmark: Benchmark instance to execute
            **run_config: Runtime configuration options

        Returns:
            Enhanced benchmark results with detailed phase tracking
        """
        return self.run_enhanced_benchmark(benchmark, **run_config)
