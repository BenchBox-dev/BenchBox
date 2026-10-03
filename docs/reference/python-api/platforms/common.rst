Common platform adapter API
===========================

.. tags:: reference, python-api, sql-platform

All adapters on the platform pages implement or inherit this lifecycle.  Use
the adapter page for configuration and platform-specific operations.

.. py:class:: benchbox.platforms.base.adapter.PlatformAdapter(**config)

   Base class for platform adapters.  It stores common run configuration and
   coordinates connection, schema, loading, execution, result capture, and
   close-up.  Do not instantiate it directly.

Connection and identity
-----------------------

.. py:classmethod:: benchbox.platforms.base.adapter.PlatformAdapter.from_config(config: dict[str, Any])

   Create platform adapter instance from unified configuration.

   :param config: Unified configuration dictionary

   :returns: Platform adapter instance

.. py:property:: benchbox.platforms.base.adapter.PlatformAdapter.platform_name

   Return the name of this database platform.

   Default implementation returns the class name. Concrete adapters may
   override to provide a user-friendly display name. Lightweight adapters
   can rely on this default when no custom name is required.

.. py:property:: benchbox.platforms.base.adapter.PlatformAdapter.canonical_platform_type

   Return the canonical, machine-readable platform type key.

   Tuning-capability lookups and metadata persistence must key off a
   stable identifier (e.g. ``"clickhouse-local"``, ``"duckdb"``) -- not
   `platform_name`, which is a human-facing display string (e.g.
   ``"ClickHouse Local"``, ``"StarRocks"``) that varies by adapter and is
   never guaranteed to match the lowercase, single-word keys used by
   capability maps such as `TuningType`'s compatibility map.

   Sourced from the ``type`` key in `platform_config` when present.
   Upstream config plumbing (core/platform_config.py) strips ``type``
   from DatabaseConfig before adapter construction, so the key does NOT
   survive that path on its own -- ``get_platform_adapter`` in
   `benchbox.platforms` re-injects the resolved canonical registry name
   (`PlatformRegistry.resolve_platform_name`) into the constructor
   config, which is what this property reads on every factory-built
   adapter.

   Falls back to a normalized form of `platform_name` (lowercased,
   spaces collapsed to hyphens) when no config type is available -- e.g.
   an adapter constructed directly, bypassing the factory, as many unit
   tests do. This fallback is best-effort only: it does not guarantee a
   match against any capability map key (a parenthesized display name
   like ``"ClickHouse (Local)"`` normalizes to ``"clickhouse-(local)"``),
   it just avoids crashing on multi-word display strings.

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.create_connection(**connection_config) -> Any

   Create and return a database connection.

   :param \*\*connection_config: Connection-specific parameters

   :returns: Database connection object

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.close_connection(connection: Any) -> None

   Close database connection and cleanup resources.

   :param connection: Database connection to close

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.new_stream_connection(connection: Any, *, benchmark_type: str | None = None) -> Any

   Return a per-stream execution handle for one concurrent throughput
   (or connection-pool test) stream.

   This is the capability seam for ``throughput-independent-sessions-per-stream``:
   the throughput drivers' ``connection_factory`` closures
   (``benchbox/platforms/base/execution.py``,
   ``_execute_tpch_throughput_test`` / ``_execute_tpcds_throughput_test``)
   call this once per stream instead of unconditionally sharing one
   cursor, so the behavior is now a declared, overridable platform
   capability rather than an implicit one-size-fits-all default. The
   ``benchmark_type`` keyword (``"olap"`` for the TPC-H/TPC-DS throughput
   drivers unless the caller overrides it via run config) lets
   ``INDEPENDENT_CONNECTION`` overrides reproduce the benchmark-type
   session tuning the shared connection carries - see equivalence
   dimension 4 in ``StreamConnectionCapability``. The keyword is optional
   so pre-existing overrides and test doubles keep working unchanged.

   Dispatches on ``stream_connection_capability``:

   ``SHARED_CURSOR`` (default): returns ``_make_stream_cursor(connection)``
   a cursor of (or ``_NoCloseProxy`` over) the single shared
   ``connection`` passed in. This is the existing, unchanged fast path:
   correct for embedded engines whose client is documented thread-safe
   at cursor level against one process-local database (e.g. DuckDB -
   see docs/benchmarks/tpc-h.md). No new connections are opened, and
   closing the returned handle never closes the shared connection
   (``_NoCloseProxy.close()`` is a no-op; a real cursor's ``close()``
   only closes the cursor). ``benchmark_type`` is ignored: the shared
   connection already carries its tuning.
   ``INDEPENDENT_CONNECTION``: server-style adapters (client/server
   engines whose driver does not support true concurrent statement
   execution across cursors of one connection) MUST override this
   method to open and return a brand-new connection/session, typically
   ignoring the ``connection`` argument entirely. The base
   implementation deliberately raises ``NotImplementedError`` for this
   capability value instead of falling back to cursor sharing, so a
   subclass that declares ``INDEPENDENT_CONNECTION`` without overriding
   fails loudly rather than silently reproducing the shared-session bug
   this capability exists to fix. Overrides should apply
   ``configure_for_benchmark(stream_conn, benchmark_type or "olap")``
   (plus the ``_apply_stream_session_state`` hook for
   connection-establishment state) so the stream session measures the
   same tuning as the setup session.
   ``UNSUPPORTED``: never reaches this method - the throughput entry
   points refuse via ``require_throughput_stream_capability`` before
   any stream is submitted.

   :param connection: The adapter's shared platform connection (as created by ``create_connection``). Used as-is for ``SHARED_CURSOR``; available for reference (e.g. to read connection parameters) but not required for ``INDEPENDENT_CONNECTION`` overrides.
   :param benchmark_type: Benchmark tuning vocabulary (e.g. ``"olap"``) for per-stream session parity. Optional; overrides replay tuning only when it is supplied, so callers that pass nothing keep their previous behavior.

   :returns: either a cursor/ proxy over the shared connection, or an independent connection.
   :rtype: A connection-like object suitable for one stream

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.get_platform_info(connection: Any = None) -> dict[str, Any]

   Get platform information for results traceability.

   Default implementation returns minimal generic info. Platform adapters
   should override to provide richer details, but tests may instantiate
   lightweight adapters without implementing this method.

Schema, data, and execution
---------------------------

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.create_schema(benchmark, connection: Any) -> float

   Create database schema for the benchmark.

   :param benchmark: Benchmark instance with schema definitions
   :param connection: Database connection

   :returns: Time taken to create schema in seconds

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Load benchmark data into database using platform-specific methods.

   :param benchmark: Benchmark instance
   :param connection: Database connection
   :param data_dir: Directory containing data files

   :returns: Tuple of (table_statistics, loading_time_seconds, per_table_timings) where per_table_timings is optional dict with detailed timing per table

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Register benchmark tables as external references instead of loading native tables.

   Platforms that support external-table mode should override this method and
   return the same tuple shape as ``load_data``.

   :param benchmark: Benchmark instance
   :param connection: Database connection
   :param data_dir: Directory containing source data files or external data roots

   :returns: Tuple of (table_statistics, loading_time_seconds, per_table_timings) where per_table_timings is optional dict with detailed timing per table

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]

   Execute a single query and return detailed results.

   :param connection: Database connection
   :param query: SQL query text
   :param query_id: Query identifier
   :param benchmark_type: Type of benchmark (e.g., "tpch", "tpcds") for row count validation
   :param scale_factor: Scale factor used for the query (for row count validation)
   :param validate_row_count: Whether to validate row count against expected results
   :param stream_id: Stream identifier for multi-stream benchmarks (e.g., 0, 1, 2...) Used to select stream-specific expected results. None indicates stream 0 or single-stream execution.

   :returns: Dictionary with execution results including query_id, status ("SUCCESS", "FAILED", or "DRY_RUN"), execution_time_seconds, rows_returned, and optional row_count_validation fields.

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.run_benchmark(benchmark, **run_config) -> EnhancedBenchmarkResults

   Run complete benchmark with enhanced phase tracking.

   :param benchmark: Benchmark instance to execute
   :param \*\*run_config: Runtime configuration options

   :returns: Enhanced benchmark results with detailed phase tracking

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.run_enhanced_benchmark(benchmark, **run_config) -> EnhancedBenchmarkResults

   Run complete benchmark with enhanced phase tracking.

Capability and tuning hooks
---------------------------

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.validate_platform_capabilities(benchmark_type: str) -> ValidationResult

   Validate platform-specific capabilities for the benchmark.

   :param benchmark_type: Type of benchmark (e.g., 'tpcds', 'tpch')

   :returns: ValidationResult with platform capability validation status

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.configure_for_benchmark(connection: Any, benchmark_type: str) -> None

   Apply platform-specific optimizations for the benchmark type.

   :param connection: Database connection
   :param benchmark_type: Type of benchmark (e.g., "olap", "oltp", "analytics")

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.gather_statistics(connection: Any, table_names: list[str]) -> tuple[str, int]

   Run the platform's explicit statistics build for the statistics phase.

   Returns (stats_mode, tables_analyzed). The default resolves the
   adapter's existing analyze surface: whole-database ``analyze_tables``
   when available, else per-table ``analyze_table``, else
   ``("unsupported", 0)``. Engines whose statistics are built during load
   (e.g. Redshift with auto_analyze) override this to report
   ``("auto-on-load", 0)`` instead of double-building.

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.apply_platform_optimizations(platform_config: PlatformOptimizationConfiguration, connection: Any) -> None

   Apply platform-specific optimizations.

   :param platform_config: Platform optimization configuration
   :param connection: Database connection

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.apply_constraint_configuration(primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None

   Apply constraint configurations to the database.

   :param primary_key_config: Primary key constraint configuration
   :param foreign_key_config: Foreign key constraint configuration
   :param connection: Database connection

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.get_tuning_introspector() -> Introspector | None

   Return a post-load schema introspector for this platform, or None.

   An introspector corroborates the applied-tuning ledger against the real
   database catalog, letting an ``applied_unverified`` run be upgraded to
   ``applied_verified`` -- but only when every catalog-backed tuning
   statement is corroborated (see
   ``benchbox.core.tuning.introspection``). Platforms with a structured
   catalog (DuckDB, ClickHouse) override this; the base returns None, so a
   platform without an introspector keeps the honest ledger-derived status.

Static member inventory
-----------------------

.. py:staticmethod:: benchbox.platforms.base.adapter.PlatformAdapter.add_cli_arguments(parser) -> None

   Add platform-specific CLI arguments to the argument parser.

   :param parser: argparse.ArgumentParser instance to add arguments to

.. py:property:: benchbox.platforms.base.adapter.PlatformAdapter.is_dry_run

   Return True if dry run is active via configuration or execution mode.

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.materialize_schema_only_tables(self, benchmark, connection: Any) -> dict[str, int]

   Materialize catalog objects for schema-only benchmarks.

   The ``SKIP_DATA_LOADING`` path bypasses ``load_data()``, but some
   adapters only create catalog objects there (DataFusion builds empty
   tables from the schema recorded by ``create_schema()``). Overrides
   must create empty tables without loading files; the default is a
   no-op for adapters whose ``create_schema()`` already materializes.

   :param benchmark: Benchmark instance with schema definitions
   :param connection: Database connection

   :returns: Mapping of table name to row count (zeros for empty tables)

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.upload_manifest(self, manifest_path: Path, remote_path: str) -> bool

   Upload manifest to remote storage. Override in subclasses if supported.

   :param manifest_path: Local manifest file path
   :param remote_path: Remote directory path/URI where manifest should be uploaded

   :returns: True if upload succeeded, False if unsupported or not uploaded

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.reset_statistics(self, connection: Any, table_names: list[str]) -> str

   Reset (drop/invalidate) optimizer statistics ahead of a cold-stats rebuild.

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

.. py:method:: benchbox.platforms.base.adapter.PlatformAdapter.run_statistics_phase(self, benchmark: Any, connection: Any, *, benchmark_name: str='', table_names: list[str] | None=None, reset: bool | None=None, collect_per_table_timing: bool=False) -> StatisticsGatheringPhase | None

   Run the opt-in statistics phase between load and query execution.

   Returns None (phase not run) when the benchmark has not opted in via
   the registry's ``supports_statistics_phase`` flag, so legacy
   benchmarks keep load-includes-stats semantics and their historical
   bundles stay comparable. Failures are recorded on the phase rather
   than aborting the run - queries remain meaningful on unanalyzed data.

   :param reset: Cold-stats vs warm-stats control. None (default) leaves statistics untouched and records no stats_lifecycle marker, exactly matching the PR #980 shipped behavior. True resets statistics via ``reset_statistics()`` before rebuilding (cold-stats). False explicitly records a "persist" marker (warm-stats) without changing behavior.
   :param collect_per_table_timing: When True and this adapter's statistics build falls back to a per-table ANALYZE loop (no whole-database analyze hook, and gather_statistics is not overridden with platform-specific routing), record a per-table wall-clock breakdown on the returned phase. Left None otherwise.

.. py:attribute:: benchbox.platforms.base.adapter.PlatformAdapter.driver_isolation_capability

   Declares whether this adapter can run through an isolated driver runtime; the value controls runtime-resolution support.

.. py:attribute:: benchbox.platforms.base.adapter.PlatformAdapter.stream_connection_capability

   Declares whether concurrent benchmark streams use a shared cursor or require independent connections.

.. py:attribute:: benchbox.platforms.base.adapter.PlatformAdapter.default_service_port

   Provides the default service port used when connection configuration omits one.

.. py:attribute:: benchbox.platforms.base.adapter.PlatformAdapter.supports_external_tables

   Advertises whether the adapter implements external-table creation.

.. py:attribute:: benchbox.platforms.base.adapter.PlatformAdapter.plan_capture_phase_eligible

   Advertises whether benchmark plan capture is available for this adapter.

.. py:method:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.test_connection(self, connection_config: ConnectionConfig | None=None) -> bool

   Test database connectivity.

   :param connection_config: Optional connection configuration

   :returns: True if connection successful, False otherwise

.. py:staticmethod:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.validate_platform_dependencies() -> dict[str, bool]

   Validate platform-specific dependencies are available.

   :returns: Dictionary mapping dependency names to availability status

.. py:staticmethod:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.require_dependencies(required: list[str], exit_on_missing: bool=True) -> dict[str, bool]

   Require specific dependencies, optionally exit with helpful message if missing.

   :param required: List of required dependency names
   :param exit_on_missing: Whether to exit if dependencies are missing

   :returns: Dictionary mapping dependency names to availability status

.. py:method:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.get_connection_from_pool(self) -> Any

   Get connection from pool (if supported by platform).

   :returns: Database connection from pool or new connection

.. py:method:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.get_database_path(self, **connection_config) -> str | None

   Get the database file path for file-based databases.

   Override this method in platform adapters that use file-based databases.

.. py:method:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.check_database_exists(self, **connection_config) -> bool

   Check if database already exists.

   For file-based databases, checks if file exists.
   For server-based databases, checks if database/schema exists on server.

.. py:method:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.check_server_database_exists(self, **connection_config) -> bool

   Check if database exists on server (for server-based databases).

   Override this method in platform adapters for server-based databases.

.. py:method:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.check_benchmark_tables_exist(self, **connection_config) -> bool | None

   Check whether a managed database has the current benchmark tables.

   :returns: True when the adapter can prove the required tables are present, False when the adapter can prove they are missing or unusable, and None when the adapter does not implement managed table validation.

.. py:method:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.handle_existing_database(self, **connection_config) -> None

   Handle existing database non-interactively for core/programmatic usage.

   Performs validation of database compatibility and makes automatic decisions:
   If force_recreate=True, always recreate
   If database is valid, reuse it
   If database has issues, recreate it
   If skip_database_management=True, skip create/drop management while
   allowing adapters to opt into table-readiness checks

.. py:method:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.reset_database_in_place(self, **connection_config) -> bool

   Empty a server-side database for reload without dropping it.

   Return True when the database was reset in place, so the caller skips
   ``drop_database``. The default does nothing and returns False. Override
   it where dropping objects is costly, for example where dropped tables
   keep counting against a catalog quota.

.. py:method:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.drop_database(self, **connection_config) -> None

   Drop/remove database on server (for server-based databases).

   Override this method in platform adapters for server-based databases.

.. py:attribute:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.platform_name

   Host-provided platform name (``str``), used in diagnostics and capability selection; this mixin supplies no default.

.. py:attribute:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.logger

   Holds the adapter logger used for lifecycle and diagnostic messages.

.. py:attribute:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.connection_pool

   Holds the optional reusable connection pool for adapters that support pooling.

.. py:attribute:: benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.platform_config

   Holds the platform configuration used to create the adapter.

.. py:property:: benchbox.platforms.base.dialect_translation.DialectTranslationMixin.dialect

   Return the SQL dialect for this platform (for sqlglot translation).

.. py:method:: benchbox.platforms.base.dialect_translation.DialectTranslationMixin.translate_sql(self, sql: str, source_dialect: str='standard', strict: bool | None=None, scope: str | None=None) -> str

   Translate SQL from source dialect to platform dialect using sqlglot.

   Delegates to the centralized dialect_utils pipeline, gaining dialect
   normalization, identifier quoting policy, and platform-specific
   post-fixes (DuckDB GROUP BY ALL, SQLite syntax rewrites). Handles
   multi-statement schema SQL that translate_sql_query() does not.

   :param sql: SQL query or schema block (may contain multiple statements)
   :param source_dialect: Source SQL dialect (default: standard ANSI DDL)
   :param strict: When True, raise instead of falling back to the original SQL. When omitted, the active sql_translation_context policy is used.
   :param scope: Workload scope recorded on the outcome. Defaults to ``SCHEMA_DDL_SCOPE`` since schema creation is the only production caller.

   :returns: Translated SQL string, preserving multi-statement structure.

.. py:method:: benchbox.platforms.base.dialect_translation.DialectTranslationMixin.get_tpc_base_dialect(self, benchmark_name: str) -> str

   Return the base dialect for TPC query generation (qgen/dsqgen).

   Default is 'netezza' for both TPC-DS and TPC-H for modern SQL compatibility.
   Adapters may override to select a closer match if beneficial.

   :param benchmark_name: 'tpch', 'tpcds', etc. (case-insensitive)

   :returns: Base dialect string to use when invoking qgen/dsqgen

.. py:attribute:: benchbox.platforms.base.dialect_translation.DialectTranslationMixin.logger

   Holds the adapter logger used for lifecycle and diagnostic messages.

.. py:method:: benchbox.platforms.base.tuning.TuningHooksMixin.apply_table_tunings(self, table_tuning: TableTuning, connection: Any) -> None

   Apply tuning configurations to a database table.

   This method should be implemented by platform adapters to apply
   platform-specific tuning optimizations such as partitioning,
   clustering, distribution, and sorting.

   :param table_tuning: The tuning configuration to apply
   :param connection: Database connection

   :raises NotImplementedError: If tuning is not supported by the platform
   :raises ValueError: If the tuning configuration is invalid for this platform

.. py:method:: benchbox.platforms.base.tuning.TuningHooksMixin.supports_tuning_type(self, tuning_type: TuningTypeT) -> bool

   Check if this platform adapter supports a specific tuning type.

   :param tuning_type: The type of tuning to check support for

   :returns: True if the tuning type is supported by this platform

.. py:method:: benchbox.platforms.base.tuning.TuningHooksMixin.generate_tuning_clause(self, table_tuning: TableTuning) -> str

   Generate platform-specific tuning clauses for CREATE TABLE statements.

   This method should generate the appropriate SQL clauses to be included
   in CREATE TABLE statements to apply the specified tuning configurations.

   :param table_tuning: The tuning configuration for the table

   :returns: SQL clause string to be appended to CREATE TABLE statement (empty string if no tuning clauses are needed)

   :raises ValueError: If the tuning configuration is invalid for this platform

.. py:attribute:: benchbox.platforms.base.tuning.TuningHooksMixin.platform_name

   Host-provided platform name (``str``), used in diagnostics and capability selection; this mixin supplies no default.

.. py:method:: benchbox.platforms.base.tuning_config.TuningConfigMixin.apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None

   Apply unified tuning configuration to the database.

   This method should implement platform-specific logic for applying
   the full unified tuning configuration, including:
   Schema constraints (primary keys, foreign keys, unique, check)
   Platform-specific optimizations (Z-ordering, auto-optimize, etc.)
   Table-level tunings (partitioning, clustering, distribution, sorting)

   :param unified_config: Unified tuning configuration to apply
   :param connection: Database connection

   :raises NotImplementedError: If unified tuning is not supported by the platform
   :raises ValueError: If the configuration is invalid for this platform

.. py:method:: benchbox.platforms.base.tuning_config.TuningConfigMixin.get_effective_tuning_configuration(self) -> UnifiedTuningConfiguration | None

   Get the effective tuning configuration.

   :returns: The unified tuning configuration, or None if no tuning is configured

.. py:method:: benchbox.platforms.base.tuning_config.TuningConfigMixin.validate_tuning_configuration_for_platform(self) -> list[str]

   Validate the current tuning configuration against this platform's capabilities.

   :returns: List of validation error messages (empty if no errors)

.. py:method:: benchbox.platforms.base.tuning_config.TuningConfigMixin.validate_tuning_configuration(self, unified_config: UnifiedTuningConfiguration) -> list[str]

   Validate a unified tuning configuration against platform capabilities.

   :param unified_config: The unified tuning configuration to validate

   :returns: List of validation error messages (empty if all valid)

.. py:method:: benchbox.platforms.base.tuning_config.TuningConfigMixin.save_tuning_metadata(self, connection: Any) -> bool

   Save tuning metadata to database for future validation.

   :param connection: Database connection

   :returns: True if metadata was saved successfully, False otherwise

.. py:attribute:: benchbox.platforms.base.tuning_config.TuningConfigMixin.platform_name

   Host-provided platform name (``str``), used in diagnostics and capability selection; this mixin supplies no default.

.. py:attribute:: benchbox.platforms.base.tuning_config.TuningConfigMixin.canonical_platform_type

   Host-provided canonical platform identifier (``str``), passed to tuning configuration validation; this mixin supplies no default.

.. py:attribute:: benchbox.platforms.base.tuning_config.TuningConfigMixin.logger

   Holds the adapter logger used for lifecycle and diagnostic messages.

.. py:attribute:: benchbox.platforms.base.tuning_config.TuningConfigMixin.tuning_enabled

   Host-provided flag (``bool``) that enables tuning application and metadata persistence; this mixin supplies no default.

.. py:method:: benchbox.platforms.base.sorted_ingestion.SortedIngestionMixin.get_sorted_ingestion_capability(self) -> dict[str, Any]

   Return sorted-ingestion capability metadata for the current platform.

.. py:method:: benchbox.platforms.base.sorted_ingestion.SortedIngestionMixin.resolve_sorted_ingestion_strategy(self) -> tuple[str, str]

   Resolve sorted-ingestion mode/method with capability guardrails.

.. py:method:: benchbox.platforms.base.sorted_ingestion.SortedIngestionMixin.get_sorted_ingestion_metadata(self) -> dict[str, Any]

   Return configured/resolved sorted-ingestion metadata for result reporting.

.. py:method:: benchbox.platforms.base.sorted_ingestion.SortedIngestionMixin.apply_ctas_sort(self, table_name: str, tuning_config: Any, connection: Any) -> bool

   Apply CTAS-based sorting after a table load when sorting is configured.

   This shared implementation performs table-tuning lookup, sort-column extraction,
   identifier validation, dry-run SQL capture, and execution. Platform adapters
   enable CTAS sorting by overriding _build_ctas_sort_sql(); adapters that return
   ``None`` are treated as unsupported and safely skipped.

.. py:attribute:: benchbox.platforms.base.sorted_ingestion.SortedIngestionMixin.platform_name

   Host-provided platform name (``str``), used in diagnostics and capability selection; this mixin supplies no default.

.. py:attribute:: benchbox.platforms.base.sorted_ingestion.SortedIngestionMixin.logger

   Holds the adapter logger used for lifecycle and diagnostic messages.

Additional inherited members
----------------------------

.. py:method:: benchbox.platforms.base.phase_tracking.PhaseTrackingMixin.get_table_row_count(self, connection: Any, table: str) -> int

   Get row count for a table using platform-specific API.

   Default implementation uses cursor pattern. Platforms like BigQuery
   that don't support cursor() can override to use their specific APIs.

   :param connection: Database connection
   :param table: Table name

   :returns: Row count as integer, or 0 if unable to determine

.. py:attribute:: benchbox.platforms.base.phase_tracking.PhaseTrackingMixin.logger

   Holds the adapter logger used for lifecycle and diagnostic messages.

.. py:method:: benchbox.platforms.base.result_capture.ResultCaptureMixin.get_normalized_result_metadata(self, *, connection: Any | None=None, platform_info: Mapping[str, Any] | None=None) -> dict[str, Any]

   Return normalized runtime/deployment metadata for result construction.

   Subclasses may override this optional hook to provide richer observed
   metadata. The default maps legacy ``get_platform_info()`` output into
   conservative normalized blocks.

.. py:method:: benchbox.platforms.base.result_capture.ResultCaptureMixin.display_query_plan_if_enabled(self, connection: Any, query: str, query_id: str) -> None

   Display query execution plan if show_query_plans is enabled.

   Suppressed while capture_plans is active: capture already runs EXPLAIN
   in the isolated post-measurement phase, so displaying here would issue
   EXPLAIN a second time. Centralized here (rather than at each call
   site) so new adapters cannot accidentally double-EXPLAIN.

   :param connection: Database connection
   :param query: SQL query text
   :param query_id: Query identifier

.. py:method:: benchbox.platforms.base.result_capture.ResultCaptureMixin.get_query_plan(self, connection: Any, query: str) -> str | None

   Get query execution plan for analysis.

   Override this method in platform adapters to provide platform-specific plans.

   :param connection: Database connection
   :param query: SQL query text

   :returns: Query execution plan as string, or None if not available

.. py:method:: benchbox.platforms.base.result_capture.ResultCaptureMixin.get_query_plan_parser(self)

   Get query plan parser for this platform.

   Override this method in platform adapters to provide platform-specific parser.

   :returns: QueryPlanParser instance or None if not available

.. py:method:: benchbox.platforms.base.result_capture.ResultCaptureMixin.capture_query_plan(self, connection: Any, query: str, query_id: str) -> tuple[Any, float]

   Capture structured query plan using platform-specific parser.

   Calls get_query_plan() to obtain EXPLAIN output and parses it into a QueryPlanDAG.
   Returns timing information for observability of capture overhead.

   By default (analyze_plans=False), DuckDB uses plain EXPLAIN (FORMAT JSON), which
   captures the estimated plan without re-executing the query. Set
   analyze_plans=True in the adapter config to opt into EXPLAIN (ANALYZE, FORMAT
   JSON), which re-executes every captured SELECT once to include actual
   per-operator timing and cardinality -- roughly 2x wall-clock cost for a
   --capture-plans run and perturbed cache state. The first time this method
   actually captures a plan with analyze_plans enabled for a run, it prints a
   one-time notice (see the ``_analyze_plans_notice_printed`` guard below).

   Plan fingerprints exclude timing/cardinality by design - structural comparisons
   are unaffected by this setting. See the plan fingerprint stability contract in
   ``benchbox/core/results/query_plan_models.py`` for what fingerprint equality
   does and does not guarantee.

   Capture timing (pre- vs. post-execution) — design decision:
   All adapters capture the plan AFTER the timed execution block (the
   "post-execution" plan). This is intentional and is the supported
   default:
   With ``analyze_plans=True`` (opt-in) it yields the *actual* plan that
   ran, including real per-operator timing/cardinality (EXPLAIN ANALYZE) —
   the most useful artifact for profiling, at the cost of re-execution.
   The structural fingerprint is unaffected by post- vs. pre-execution
   timing, because it excludes costs and row estimates. A plan captured
   before vs. after execution hashes to the same fingerprint as long as
   the planner's chosen shape is identical.
   A pre-execution capture mode (plan as decided before any stats change)
   would be marginally more stable for cross-run regression detection, but
   is NOT implemented: the fingerprint's stats-independence already provides
   that stability, so a separate timing mode is unnecessary. If a true
   pre-execution plan is ever required, add an opt-in
   ``capture_plan_timing: pre | post`` config (default ``post``) here rather
   than changing the default behavior.

   Multi-stream behavior (stream_id):
   Plan capture is per-query-execution. In a multi-stream (concurrent)
   run, each stream executes and captures its own plan independently, so
   the result set contains one plan record per (query_id, stream_id) — the
   plans are NOT deduplicated or averaged, preserving per-stream provenance.
   Because the fingerprint is structural, every stream running the same
   query against the same schema on the same engine version is expected to
   produce the SAME plan_fingerprint (with the engine-dependent caveat in
   query_plan_models.py that some parsers, e.g. DuckDB, fold an estimated
   cardinality into the signature — identical across streams as long as the
   cardinality estimate is stable). Only the execution stats
   (timing/per-operator cardinality) differ between streams. Consumers that
   want a single representative plan per query should deduplicate by
   ``plan_fingerprint``; a fingerprint mismatch across streams of the same
   query indicates a genuine plan-shape (or estimate) divergence worth
   investigating.

   :param connection: Database connection
   :param query: SQL query text
   :param query_id: Query identifier

   :returns: Tuple of (QueryPlanDAG | None, capture_time_ms)

.. py:method:: benchbox.platforms.base.result_capture.ResultCaptureMixin.execute_query_with_plan_capture(self, execute: Callable[..., dict[str, Any]], connection: Any, query: str, query_id: str, benchmark_type: str | None=None, scale_factor: float | None=None, validate_row_count: bool=True, stream_id: int | None=None) -> dict[str, Any]

   Run one query through the shared executor, then merge plan capture.

   Firebolt, Presto/Trino, PostgreSQL, SingleStore, and Doris each wrapped
   the shared cursor execution with the same two lines: delegate to the
   parent executor, then merge SUCCESS-guarded plan fields into the
   result. This method owns that idiom so the copies cannot drift; each
   adapter keeps its thin ``execute_query`` override (and its platform
   docstring) and forwards its own ``super().execute_query`` as
   ``execute``. Adapters with genuinely different semantics — Redshift's
   FAILED guard and display logic, pg_mooncake's transaction retry,
   QuestDB's rewriter path — keep their bespoke overrides.

   :param execute: Bound parent ``execute_query`` to delegate to.
   :param connection: Database connection.
   :param query: SQL query text.
   :param query_id: Query identifier.
   :param benchmark_type: Benchmark family for validation.
   :param scale_factor: Scale factor for validation.
   :param validate_row_count: Whether to validate row counts.
   :param stream_id: Throughput stream identifier.

   :returns: Query result dict with plan fields merged when captured.

.. py:method:: benchbox.platforms.base.result_capture.ResultCaptureMixin.validate_loaded_data(self, connection: Any, benchmark_type: str, scale_factor: float) -> ValidationResult

   Validate database state after data loading using platform-specific methods.

   :param connection: Database connection object
   :param benchmark_type: Type of benchmark (e.g., 'tpcds', 'tpch')
   :param scale_factor: Scale factor for the benchmark

   :returns: ValidationResult with database validation status

.. py:method:: benchbox.platforms.base.result_capture.ResultCaptureMixin.validate_row_counts(self, connection: Any, expected_counts: dict[str, int])

   Validate actual row counts against expected counts.

   :param connection: Database connection
   :param expected_counts: Dictionary mapping table names to expected row counts

   :returns: ValidationResult with row count comparison results

.. py:attribute:: benchbox.platforms.base.result_capture.ResultCaptureMixin.logger

   Holds the adapter logger used for lifecycle and diagnostic messages.

.. py:method:: benchbox.platforms.base.execution.TestDriversMixin.enable_dry_run(self, connection: Any=None) -> None

   Enable dry-run mode for SQL capture without execution.

.. py:method:: benchbox.platforms.base.execution.TestDriversMixin.disable_dry_run(self, connection: Any=None) -> None

   Disable dry-run mode and return to normal execution.

.. py:method:: benchbox.platforms.base.execution.TestDriversMixin.capture_sql(self, sql: str, operation_type: str='query', table_name: str | None=None) -> None

   Capture SQL statement for dry-run mode.

   :param sql: The SQL statement to capture
   :param operation_type: Type of operation (query, ddl, dml, etc.)
   :param table_name: Associated table name if applicable

.. py:method:: benchbox.platforms.base.execution.TestDriversMixin.get_captured_sql(self) -> dict[str, str]

   Return captured SQL statements as dictionary for dry-run display.

   :returns: Dictionary of query_id -> SQL statements

.. py:method:: benchbox.platforms.base.execution.TestDriversMixin.run_power_test(self, benchmark, **kwargs) -> dict[str, Any]

   Run TPC power test measuring single-stream query performance.

   The power test executes queries sequentially in a single stream to measure
   the database's ability to process complex analytical queries efficiently.
   This test focuses on query optimization and execution performance.

   :param benchmark: Benchmark instance with queries and data
   :param \*\*kwargs: Configuration options for the power test including: - query_timeout: Maximum time per query (default: platform-specific) - query_subset: List of specific queries to run (default: all) - validation: Whether to validate query results (default: True)

   :returns:     - test_type: "power" - total_execution_time: Total time for all queries in seconds - query_count: Number of queries executed - successful_queries: Number of successful query executions - failed_queries: Number of failed query executions - query_results: List of individual query execution results - geometric_mean: Geometric mean of query execution times - validation_status: Overall validation result status
   :rtype: Dictionary containing power test results with keys

.. py:method:: benchbox.platforms.base.execution.TestDriversMixin.run_throughput_test(self, benchmark, **kwargs) -> dict[str, Any]

   Run TPC throughput test measuring concurrent multi-stream performance.

   The throughput test executes multiple concurrent query streams to measure
   the database's ability to handle concurrent analytical workloads.
   This test focuses on scalability and concurrent query processing.

   :param benchmark: Benchmark instance with queries and data
   :param \*\*kwargs: Configuration options for the throughput test including: - stream_count: Number of concurrent query streams (default: platform-specific) - query_timeout: Maximum time per query (default: platform-specific) - warmup_runs: Number of warmup iterations per stream (default: 1) - measurement_runs: Number of measurement iterations (default: 1) - validation: Whether to validate query results (default: True)

   :returns:     - test_type: "throughput" - stream_count: Number of concurrent streams used - total_execution_time: Total wall-clock time in seconds - aggregate_query_time: Sum of all query execution times - queries_per_hour: Throughput metric (queries/hour) - stream_results: List of individual stream execution results - validation_status: Overall validation result status
   :rtype: Dictionary containing throughput test results with keys

.. py:method:: benchbox.platforms.base.execution.TestDriversMixin.run_maintenance_test(self, benchmark, **kwargs) -> dict[str, Any]

   Run TPC maintenance test measuring data modification performance.

   The maintenance test executes data modification operations (INSERT, UPDATE, DELETE)
   to measure the database's ability to handle data maintenance workloads while
   concurrent query streams are running.

   :param benchmark: Benchmark instance with maintenance functions and data
   :param \*\*kwargs: Configuration options for the maintenance test including: - maintenance_operations: List of operations to perform (default: all) - concurrent_streams: Number of concurrent query streams (default: 1) - batch_size: Size of maintenance operation batches (default: platform-specific) - validation: Whether to validate results (default: True)

   :returns:     - test_type: "maintenance" - operations_executed: Number of maintenance operations performed - total_execution_time: Total time for all operations in seconds - operation_results: List of individual operation execution results - concurrent_query_impact: Impact on concurrent query performance - data_integrity_status: Data consistency validation results - validation_status: Overall validation result status
   :rtype: Dictionary containing maintenance test results with keys

.. py:property:: benchbox.utils.verbosity.VerbosityMixin.logger

   Return the logger configured for the verbosity mixin consumer.

.. py:method:: benchbox.utils.verbosity.VerbosityMixin.apply_verbosity(self, settings: VerbositySettings) -> None

   Apply verbosity settings to the mixin consumer.

.. py:property:: benchbox.utils.verbosity.VerbosityMixin.verbosity_settings

   Return the current verbosity settings.

.. py:method:: benchbox.utils.verbosity.VerbosityMixin.log_verbose(self, message: str) -> None

   Log only when verbose mode is enabled.

.. py:method:: benchbox.utils.verbosity.VerbosityMixin.log_notice(self, message: str) -> None

   Log a default-visible operational notice while respecting quiet mode.

.. py:method:: benchbox.utils.verbosity.VerbosityMixin.log_very_verbose(self, message: str) -> None

   Log only when very-verbose mode is enabled.

.. py:method:: benchbox.utils.verbosity.VerbosityMixin.log_operation_start(self, operation: str, details: str='') -> None

   Logs the start of a named adapter operation, including optional details.

.. py:method:: benchbox.utils.verbosity.VerbosityMixin.log_operation_complete(self, operation: str, duration: float | None=None, details: str='') -> None

   Logs completion of a named adapter operation with optional duration and details.

.. py:method:: benchbox.utils.verbosity.VerbosityMixin.log_debug_info(self, context: str='Debug') -> None

   Log comprehensive debug information including version details.

.. py:method:: benchbox.utils.verbosity.VerbosityMixin.log_error_with_debug_info(self, error: Exception, context: str='Error') -> None

   Log an error with comprehensive debug information.

.. py:method:: benchbox.utils.verbosity.VerbosityMixin.log_version_warning(self) -> None

   Log version consistency warnings if any exist.

.. py:attribute:: benchbox.utils.verbosity.VerbosityMixin.verbose_level

   Current integer verbosity level; defaults to ``0``. ``apply_verbosity`` copies the supplied settings level.

.. py:attribute:: benchbox.utils.verbosity.VerbosityMixin.verbose_enabled

   Flag controlling verbose logging; defaults to ``False`` and is copied from the supplied settings.

.. py:attribute:: benchbox.utils.verbosity.VerbosityMixin.very_verbose

   Flag controlling detailed logging; defaults to ``False``. CLI flag normalization enables it at level 2 or higher unless quiet.

.. py:attribute:: benchbox.utils.verbosity.VerbosityMixin.quiet

   Quiet-output flag; defaults to ``False``. CLI flag normalization makes quiet take precedence over verbosity.

.. py:attribute:: benchbox.utils.verbosity.VerbosityMixin.verbose

   Legacy verbose-output flag; defaults to ``False``. ``apply_verbosity`` sets it to ``settings.verbose_enabled and not settings.quiet``.
