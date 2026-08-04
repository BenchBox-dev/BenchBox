"""Benchmark orchestrator using platform adapter architecture.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from benchbox.base import BaseBenchmark

from benchbox.cli.config import DirectoryManager
from benchbox.core.benchmark_loader import (
    get_core_benchmark_class,
    instantiate_benchmark_class,
)

# Import from common_types to avoid circular imports
from benchbox.core.config import BenchmarkConfig, RunConfig
from benchbox.core.hooks.platform_hooks import PlatformHookRegistry
from benchbox.core.platform_config import get_platform_config as _core_get_platform_config
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.run_service import execute_run, resolve_lifecycle_phases, resolve_run_config
from benchbox.core.schemas import ExecutionContext
from benchbox.platforms import get_adapter, get_platform_adapter
from benchbox.utils.cloud_storage import is_databricks_path
from benchbox.utils.printing import quiet_console
from benchbox.utils.verbosity import VerbositySettings

# Module-level console handle used by orchestrator output paths.
console = quiet_console


def resolved_deployment_mode(database_config) -> Optional[str]:
    """Return the deployment mode this run selected, or None for the default.

    Platforms that expose a deployment choice register it as a
    ``deployment_mode`` platform option, so an explicit selection arrives in
    ``database_config.options``. Returning None lets the registry fall back to
    the platform's ``default_deployment``.
    """
    if not database_config:
        return None
    options = getattr(database_config, "options", None) or {}
    mode = options.get("deployment_mode")
    return mode or None


def _build_failure_result(config: BenchmarkConfig, exc: Exception) -> BenchmarkResults:
    """Build a BenchmarkResults sentinel for a failed execute_benchmark() invocation."""
    from benchbox.core.results.models import ExecutionPhases, SetupPhase

    return BenchmarkResults(
        benchmark_name=getattr(config, "display_name", config.name.upper()),
        platform="unknown",
        scale_factor=config.scale_factor,
        execution_id=uuid.uuid4().hex[:8],
        timestamp=datetime.now(),
        duration_seconds=0.0,
        total_queries=0,
        successful_queries=0,
        failed_queries=0,
        total_execution_time=0.0,
        average_query_time=0.0,
        query_results=[],
        query_definitions={},
        execution_phases=ExecutionPhases(setup=SetupPhase()),
        validation_status="FAILED",
        validation_details={"error": str(exc)},
        data_loading_time=0.0,
        schema_creation_time=0.0,
        total_rows_loaded=0,
        data_size_mb=0.0,
        table_statistics={},
    )


class BenchmarkOrchestrator:
    """Orchestrates benchmark execution using platform adapters."""

    def __init__(self, base_dir: Optional[str] = None):
        self.console = quiet_console
        self.directory_manager = DirectoryManager(base_dir)
        self.custom_output_dir = None  # For cloud storage paths
        self._verbosity = VerbositySettings.default()

    def set_verbosity(self, settings: VerbositySettings) -> None:
        """Configure verbosity for orchestrated execution."""

        self._verbosity = settings

    # -- Private helpers (wrappable in tests) ---------------------------------
    def _get_benchmark_class(self, benchmark_name: str):
        """Resolve a benchmark class by name (via core loader)."""
        return get_core_benchmark_class(benchmark_name)

    def _get_benchmark_instance(self, config: BenchmarkConfig, system_profile):
        """Create a benchmark instance honoring parallel and compression fields.

        Attempts to pass `parallel` based on logical cores; falls back to
        constructor without `parallel` if not supported.
        """
        # Prefer using the class directly so tests can patch class resolution
        benchmark_class = self._get_benchmark_class(config.name)

        cpu_cores = 1
        if system_profile is not None:
            cpu_cores = getattr(system_profile, "cpu_cores_logical", 1)

        kwargs = {
            "scale_factor": getattr(config, "scale_factor", 1.0),
            "compress_data": getattr(config, "compress_data", False),
            "compression_type": getattr(config, "compression_type", None),
            "compression_level": getattr(config, "compression_level", None),
        }

        kwargs.update(
            {
                "verbose": self._verbosity.level,
                "quiet": self._verbosity.quiet,
            }
        )

        # Forward benchmark-specific options (--benchmark-option K=V) to constructor kwargs.
        # Also forward seed/force_regenerate from config.options when the benchmark has
        # registered specs for them, so they reach the constructor.
        opts = getattr(config, "options", {}) or {}
        benchmark_options = dict(opts.get("benchmark_options", {}))

        from benchbox.cli.benchmark_hooks import BenchmarkHookRegistry

        registered_specs = BenchmarkHookRegistry.list_option_specs(config.name)
        # Bridge seed/force_regenerate from top-level config.options into benchmark kwargs
        # when the benchmark has registered specs for them. These two keys can arrive via
        # the interactive wizard (which sets them directly on config.options rather than
        # going through --benchmark-option), so we promote them here to avoid a second
        # code path that would need to know about benchmark-option registration.
        for key in ("seed", "force_regenerate"):
            if key in registered_specs and key not in benchmark_options and key in opts:
                val = opts[key]
                if val is not None:
                    benchmark_options[key] = val

        kwargs.update(benchmark_options)

        # Resolve the final datagen root BEFORE construction so nested
        # generators capture it immediately, instead of constructing first and
        # mutating output_dir afterward.
        optional_kwargs: dict[str, Any] = {"parallel": cpu_cores}
        construction_output_dir = self._resolve_construction_output_dir(config, benchmark_class)
        if construction_output_dir is not None:
            optional_kwargs["output_dir"] = construction_output_dir

        benchmark_instance = instantiate_benchmark_class(benchmark_class, kwargs, optional_kwargs)

        # Compatibility fallback: benchmarks that declare data sharing only via
        # the get_data_source_benchmark() instance method (no
        # DATA_SOURCE_BENCHMARK class attribute) were not resolved at
        # construction, so redirect them to the shared root now. Class-attr
        # sharers were already constructed with it.
        if getattr(benchmark_class, "DATA_SOURCE_BENCHMARK", None) is None:
            data_source = getattr(benchmark_instance, "get_data_source_benchmark", lambda: None)()
            if data_source and self.custom_output_dir is None:
                shared_path = self.directory_manager.get_datagen_path(data_source.lower(), config.scale_factor)
                benchmark_instance.output_dir = shared_path

        return benchmark_instance

    def _resolve_construction_output_dir(self, config: BenchmarkConfig, benchmark_class) -> Optional[Union[str, Path]]:
        """Resolve the local datagen root before the benchmark is constructed.

        Precedence matches the post-construction resolution it replaces:
        CLI --output (custom_output_dir) wins, then the shared data-source
        root for data-sharing benchmarks, then the managed per-benchmark path.
        Returns None when the root is not knowable yet — cloud --output paths
        resolve later via _resolve_custom_output_root, which needs platform
        config; the runner's compatibility shim applies that handler
        post-construction.
        """
        if self.custom_output_dir:
            from benchbox.utils.cloud_storage import is_cloud_path

            if is_cloud_path(self.custom_output_dir):
                return None
            return self.custom_output_dir

        data_source = getattr(benchmark_class, "DATA_SOURCE_BENCHMARK", None)
        source_name = (data_source or config.name).lower()
        return self.directory_manager.get_datagen_path(source_name, config.scale_factor)

    def _get_platform_config(
        self,
        database_config,
        system_profile,
        benchmark_name: Optional[str] = None,
        scale_factor: Optional[float] = None,
        tuning_config: Optional[Any] = None,
        benchmark: Optional["BaseBenchmark"] = None,
    ) -> dict[str, Any]:
        """Build platform configuration using core helper."""
        # For benchmarks that share another benchmark's data (e.g., read_primitives → tpch),
        # use the data source name for database naming so the existing database is reused.
        if benchmark is not None:
            data_source = getattr(benchmark, "get_data_source_benchmark", lambda: None)()
            if data_source:
                benchmark_name = data_source

        return _core_get_platform_config(
            database_config,
            system_profile,
            benchmark_name=benchmark_name,
            scale_factor=scale_factor,
            tuning_config=tuning_config,
        )

    # Compatibility: explicit create method used in some tests
    def _create_benchmark_instance(self, config: BenchmarkConfig, system_profile):
        return self._get_benchmark_instance(config, system_profile)

    def set_custom_output_dir(self, output_dir: str) -> None:
        """Set custom output directory for data generation (supports cloud paths)."""
        self.custom_output_dir = output_dir

    def execute_benchmark(
        self,
        config: BenchmarkConfig,
        system_profile,
        database_config,
        phases_to_run=None,
        progress=None,
        execution_context: ExecutionContext | None = None,
    ) -> BenchmarkResults:
        """Execute benchmark by delegating lifecycle to the core runner.

        Args:
            config: Benchmark configuration
            system_profile: System profile for resource information
            database_config: Database configuration (None for data-only)
            phases_to_run: List of phases to execute (None for default)
            progress: Optional BenchmarkProgress instance for progress tracking

        Returns:
            BenchmarkResults with execution details and performance metrics
        """

        self.console.print(f"[blue]Initializing {config.name} benchmark...[/blue]")

        try:
            # Resolve benchmark instance (keeps tests patchable)
            benchmark = self._get_benchmark_instance(config, system_profile)
            self.console.print(
                f"[green]✅[/green] Loaded benchmark: [cyan]{getattr(benchmark, '_name', config.name)}[/cyan]"
            )

            # Compute platform config (dict) if a database is provided
            # Include benchmark context for config-aware adapters (Databricks, Snowflake, etc.)
            platform_cfg = (
                self._get_platform_config(
                    database_config,
                    system_profile,
                    benchmark_name=config.name,
                    scale_factor=config.scale_factor,
                    tuning_config=config.options.get("unified_tuning_configuration") if config.options else None,
                    benchmark=benchmark,
                )
                if database_config is not None
                else None
            )

            self._apply_default_cloud_output_dir(database_config)
            output_root = self._resolve_output_root(config, benchmark, platform_cfg)

            self._warn_on_execute_without_load(config, database_config, phases_to_run)

            opts = getattr(config, "options", {}) or {}
            monitor = progress.get_monitor() if progress is not None else None

            def build_adapter(*, execution_mode, output_root, phases):
                return self._build_platform_adapter(
                    database_config, execution_mode, output_root, opts, platform_cfg, benchmark, phases, config
                )

            return execute_run(
                config=config,
                benchmark_instance=benchmark,
                database_config=database_config,
                system_profile=system_profile,
                platform_config=platform_cfg,
                output_root=output_root,
                phases_to_run=phases_to_run,
                adapter_factory=build_adapter,
                verbosity=self._verbosity,
                monitor=monitor,
                execution_context=execution_context,
            )

        except Exception as e:
            # Check if this is a missing credentials error for a cloud platform
            # NOTE: This is a fallback for non-interactive flows or when credentials
            # were not checked during platform selection. Interactive flow checks
            # credentials earlier (after platform selection in run.py).
            if database_config and self._should_offer_credential_setup(database_config, e):
                # Offer interactive credential setup
                if self._offer_and_run_credential_setup(database_config.type):
                    # Credentials were successfully set up - retry the benchmark execution
                    self.console.print("[cyan]Retrying benchmark execution with new credentials...[/cyan]\n")
                    return self.execute_benchmark(
                        config=config,
                        database_config=database_config,
                        system_profile=system_profile,
                        phases_to_run=phases_to_run,
                        execution_context=execution_context,
                    )

            # Fall through to existing error handling
            self.console.print(f"[red]❌ Benchmark execution failed: {e}[/red]")
            return _build_failure_result(config, e)

    def _warn_on_execute_without_load(self, config, database_config, phases_to_run) -> None:
        """Warn when a cloud run queries without loading. Console-only, CLI-scoped."""
        if database_config is None:
            return
        phases = resolve_lifecycle_phases(phases_to_run)
        if not (phases.execute and not phases.load):
            return
        # Power and Throughput tests are designed to query existing data without loading.
        test_execution_type = getattr(config, "test_execution_type", "standard")
        readonly_tests = ["power", "throughput"]
        cloud_platforms = ["databricks", "snowflake", "bigquery", "redshift"]
        if test_execution_type not in readonly_tests and database_config.type.lower() in cloud_platforms:
            self.console.print(
                "[yellow]⚠️  Executing without load phase - assuming data already exists in database[/yellow]"
            )

    def _apply_default_cloud_output_dir(self, database_config) -> None:
        """If no custom output dir is set and this run stages remotely, pull default from credentials.

        Gated on the *deployment* rather than the platform category: platforms
        like firebolt (Core), motherduck and starburst are categorised as cloud
        but their default deployment does not stage through cloud storage, so
        pulling a cloud output location for them would redirect a local run's
        data at a remote stage it never needed.
        """
        if self.custom_output_dir or not database_config:
            return
        from benchbox.security.credentials import CredentialManager

        deployment_mode = resolved_deployment_mode(database_config)
        if not PlatformRegistry.requires_cloud_storage_for_deployment(database_config.type, deployment_mode):
            return
        cred_manager = CredentialManager()
        if not cred_manager.has_credentials(database_config.type):
            return
        creds = cred_manager.get_platform_credentials(database_config.type)
        default_output = creds.get("default_output_location") if creds else None
        if default_output:
            self.custom_output_dir = default_output
            self.console.print(f"[dim]Using default output location from credentials: {default_output}[/dim]")

    def _resolve_output_root(self, config: BenchmarkConfig, benchmark, platform_cfg):
        """Resolve the output root for data generation: custom cloud path, custom local, or managed local."""
        if self.custom_output_dir:
            return self._resolve_custom_output_root(config, benchmark, platform_cfg)

        data_source = getattr(benchmark, "get_data_source_benchmark", lambda: None)()
        if data_source:
            return None
        return str(self.directory_manager.get_datagen_path(config.name.lower(), config.scale_factor))

    def _resolve_custom_output_root(self, config: BenchmarkConfig, benchmark, platform_cfg):
        """Resolve a user-supplied custom output directory (possibly cloud) to a concrete output root."""
        from benchbox.utils.cloud_storage import is_cloud_path

        if not is_cloud_path(self.custom_output_dir):
            return self.custom_output_dir

        data_source = getattr(benchmark, "get_data_source_benchmark", lambda: None)()
        source_name = (data_source or config.name).lower()
        local_cache_path = self.directory_manager.get_datagen_path(source_name, config.scale_factor)

        if is_databricks_path(self.custom_output_dir):
            from benchbox.utils.cloud_storage import DatabricksPath

            output_root = DatabricksPath(local_cache_path, self.custom_output_dir)
        else:
            from benchbox.utils.cloud_storage import CloudStagingPath

            output_root = CloudStagingPath(local_cache_path, self.custom_output_dir)
            self.console.print(f"[dim]Using local cache: {local_cache_path}[/dim]")
            self.console.print(f"[dim]Cloud target: {self.custom_output_dir}[/dim]")

        if platform_cfg is not None:
            platform_cfg["staging_root"] = self.custom_output_dir
        return output_root

    def _build_platform_adapter(
        self, database_config, execution_mode, output_root, opts, platform_cfg, benchmark, phases, config
    ):
        """Create a SQL or DataFrame adapter for the selected database, or None if not needed."""
        if database_config is None or not (phases.load or phases.execute):
            return None
        if execution_mode == "dataframe":
            self.console.print("[cyan]Using DataFrame execution mode[/cyan]")
            # database_config.options carries both user-supplied --platform-option
            # values (e.g. target_partitions=4) AND runtime-only overrides that
            # PlatformHookRegistry.build_database_config() merges in alongside them
            # (verbose, very_verbose, tuning_enabled, force_recreate, ...; see
            # DatabaseManager.create_config). Unlike the SQL branch below (whose
            # PlatformAdapter.__init__(self, **config) accepts anything), DataFrame
            # adapters declare explicit, narrow constructor signatures (e.g.
            # DataFusionDataFrameAdapter's target_partitions/batch_size/...), and
            # the runtime-only keys would collide with the verbose=/very_verbose=
            # kwargs passed explicitly below. Restrict forwarding to option names
            # actually registered in that platform's _OPTION_SPEC_ROWS so only
            # genuine --platform-option values reach the adapter (#1062 review).
            registered_option_names = PlatformHookRegistry.list_option_specs(database_config.type)
            dataframe_options = {
                key: value for key, value in (database_config.options or {}).items() if key in registered_option_names
            }
            return get_adapter(
                database_config.type,
                mode="dataframe",
                working_dir=output_root,
                verbose=self._verbosity.verbose if self._verbosity else False,
                very_verbose=self._verbosity.very_verbose if self._verbosity else False,
                tuning_config=opts.get("df_tuning_config"),
                **dataframe_options,
            )
        adapter = get_platform_adapter(database_config.type, **(platform_cfg or {}))
        if adapter and benchmark:
            adapter.benchmark_instance = benchmark
            adapter.scale_factor = config.scale_factor
        return adapter

    def _prepare_run_config(self, config: BenchmarkConfig, database_config) -> RunConfig:
        """Prepare benchmark run configuration using structured dataclass.

        Resolution itself lives in benchbox.core.run_service. What stays here is
        the part core cannot own: DirectoryManager is CLI-layer, so the CLI
        computes the database path and hands the service data instead of a
        directory manager.
        """
        tuning_config = None
        if config.options:
            tuning_config = config.options.get("unified_tuning_configuration")

        database_path = self.directory_manager.get_database_path(
            config.name,
            config.scale_factor,
            database_config.type,
            tuning_config=tuning_config,
        )

        return resolve_run_config(config, database_path=database_path, verbosity=self._verbosity)

    def _should_offer_credential_setup(self, database_config, error: Exception) -> bool:
        """Check if error indicates missing credentials for a cloud platform.

        Args:
            database_config: Database configuration
            error: Exception that was raised

        Returns:
            True if we should offer interactive credential setup
        """
        if not database_config:
            return False

        platform = database_config.type.lower()

        # Only offer for cloud platforms that support credential setup
        cloud_platforms = ["snowflake", "bigquery", "databricks", "redshift", "singlestore"]
        if platform not in cloud_platforms:
            return False

        # Check if error message indicates missing credentials
        error_msg = str(error).lower()
        credential_keywords = [
            "configuration requires",
            "missing credentials",
            "credentials not found",
            "authentication required",
            "requires account",
            "requires username",
            "requires password",
            "no credentials",
        ]

        return any(keyword in error_msg for keyword in credential_keywords)

    def _offer_and_run_credential_setup(self, platform: str) -> bool:
        """Offer and run interactive credential setup when credentials are missing.

        Args:
            platform: Platform name (snowflake, bigquery, databricks, redshift, singlestore)

        Returns:
            True if credentials were successfully set up, False otherwise
        """
        from rich.prompt import Confirm

        from benchbox.cli.commands.setup import run_platform_credential_setup

        # Show friendly message
        self.console.print(f"\n[yellow]⚠️  {platform.capitalize()} credentials not found[/yellow]")
        self.console.print(f"\nTo use {platform.capitalize()}, you need to configure credentials.")

        # Ask if user wants to set up now
        if not Confirm.ask("\n🔧 Would you like to set up credentials now?", default=True):
            self.console.print("[yellow]Skipping credential setup[/yellow]")
            self.console.print(f"\n[dim]To set up later, run: benchbox setup --platform {platform}[/dim]")
            return False

        # Run interactive setup
        success = run_platform_credential_setup(platform, self.console, show_welcome=True)

        if success:
            self.console.print("\n[green]✅ Credentials configured! Continuing with benchmark...[/green]\n")
            return True
        else:
            self.console.print("\n[red]❌ Credential setup failed[/red]")
            return False
