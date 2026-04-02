"""Benchmark orchestrator using platform adapter architecture.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from benchbox.base import BaseBenchmark

from benchbox.cli.config import DirectoryManager
from benchbox.core.benchmark_loader import (
    get_benchmark_class as _core_get_benchmark_class,
)

# Import from common_types to avoid circular imports
from benchbox.core.config import BenchmarkConfig, RunConfig
from benchbox.core.constants import (
    GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS,
    GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS,
)
from benchbox.core.platform_config import get_platform_config as _core_get_platform_config
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.core.results.driver_metadata import apply_driver_metadata
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.runner.dataframe_runner import is_dataframe_execution
from benchbox.core.runner.runner import (
    LifecyclePhases,
    ValidationOptions,
    run_benchmark_lifecycle,
)
from benchbox.core.schemas import ExecutionContext
from benchbox.platforms import get_adapter, get_platform_adapter
from benchbox.utils.cloud_storage import is_databricks_path
from benchbox.utils.printing import quiet_console
from benchbox.utils.verbosity import VerbositySettings

# Module-level console handle used by orchestrator output paths.
console = quiet_console


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
        return _core_get_benchmark_class(benchmark_name)

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

        try:
            benchmark_instance = benchmark_class(parallel=cpu_cores, **kwargs)
        except TypeError:
            # Fallback for benchmarks without parallel support
            benchmark_instance = benchmark_class(**kwargs)

        data_source = getattr(benchmark_instance, "get_data_source_benchmark", lambda: None)()
        if data_source and self.custom_output_dir is None:
            shared_path = self.directory_manager.get_datagen_path(data_source.lower(), config.scale_factor)
            benchmark_instance.output_dir = shared_path

        return benchmark_instance

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
            # Preserve the exact requested phases for downstream execution logic.
            # This lets combined mode run only the phases the user asked for.
            if phases_to_run:
                options = dict(getattr(config, "options", {}) or {})
                options["requested_phases"] = list(phases_to_run)
                config.options = options

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

            # Determine output root for generation (custom cloud path or managed local path)
            # If no custom output set and platform requires cloud storage, check for default in credentials
            if not self.custom_output_dir and database_config:
                from benchbox.security.credentials import CredentialManager

                if PlatformRegistry.requires_cloud_storage(database_config.type):
                    cred_manager = CredentialManager()
                    if cred_manager.has_credentials(database_config.type):
                        creds = cred_manager.get_platform_credentials(database_config.type)
                        default_output = creds.get("default_output_location") if creds else None
                        if default_output:
                            self.custom_output_dir = default_output
                            self.console.print(
                                f"[dim]Using default output location from credentials: {default_output}[/dim]"
                            )

            if self.custom_output_dir:
                # Check if this is a cloud storage path (any provider: dbfs://, gs://, s3://, etc.)
                from benchbox.utils.cloud_storage import is_cloud_path

                if is_cloud_path(self.custom_output_dir):
                    # Get standardized local cache path for data generation/validation
                    data_source = getattr(benchmark, "get_data_source_benchmark", lambda: None)()
                    if data_source:
                        # Benchmark shares data from another benchmark - use that benchmark's path
                        local_cache_path = self.directory_manager.get_datagen_path(
                            data_source.lower(), config.scale_factor
                        )
                    else:
                        # Benchmark generates its own data - use its own path
                        local_cache_path = self.directory_manager.get_datagen_path(
                            config.name.lower(), config.scale_factor
                        )

                    # Handle Databricks dbfs:// paths with DatabricksPath (existing implementation)
                    if is_databricks_path(self.custom_output_dir):
                        from benchbox.utils.cloud_storage import DatabricksPath

                        output_root = DatabricksPath(local_cache_path, self.custom_output_dir)
                    else:
                        # Other cloud paths (gs://, s3://, etc.) - use CloudStagingPath
                        from benchbox.utils.cloud_storage import CloudStagingPath

                        output_root = CloudStagingPath(local_cache_path, self.custom_output_dir)
                        self.console.print(f"[dim]Using local cache: {local_cache_path}[/dim]")
                        self.console.print(f"[dim]Cloud target: {self.custom_output_dir}[/dim]")

                    # Pass the cloud target to adapter as staging_root for upload
                    if platform_cfg is not None:
                        platform_cfg["staging_root"] = self.custom_output_dir
                else:
                    # Local path - use directly
                    output_root = self.custom_output_dir
            else:
                # Check if benchmark shares data from another benchmark
                # If so, respect the benchmark's default path (don't override)
                data_source = getattr(benchmark, "get_data_source_benchmark", lambda: None)()
                if data_source:
                    # Benchmark shares data - use its default path (already set in __init__)
                    output_root = None
                else:
                    # Benchmark generates its own data - use CLI-managed path
                    output_root = str(self.directory_manager.get_datagen_path(config.name.lower(), config.scale_factor))

            # Use LifecyclePhases as single source of truth
            if phases_to_run:
                # Map CLI phases directly to LifecyclePhases
                phases = LifecyclePhases(
                    generate="generate" in phases_to_run,
                    load="load" in phases_to_run,
                    execute=any(p in phases_to_run for p in ["warmup", "power", "throughput", "maintenance"]),
                )
            else:
                # Default to standard lifecycle (generate + load + execute)
                phases = LifecyclePhases(generate=True, load=True, execute=True)

            # Validate phase combinations and warn about potential issues
            if phases.execute and not phases.load and database_config is not None:
                # Only warn for full benchmark runs, not read-only test types (power/throughput)
                # Power and Throughput tests are designed to query existing data without loading
                test_execution_type = getattr(config, "test_execution_type", "standard")
                readonly_tests = ["power", "throughput"]
                cloud_platforms = ["databricks", "snowflake", "bigquery", "redshift"]

                if test_execution_type not in readonly_tests and database_config.type.lower() in cloud_platforms:
                    self.console.print(
                        "[yellow]⚠️  Executing without load phase - assuming data already exists in database[/yellow]"
                    )

            # Validation options from CLI config
            opts = getattr(config, "options", {}) or {}
            validation = ValidationOptions(
                enable_preflight_validation=bool(opts.get("enable_preflight_validation")),
                enable_postgen_manifest_validation=bool(opts.get("enable_postgen_manifest_validation", False)),
                enable_postload_validation=bool(opts.get("enable_postload_validation", False)),
            )

            # Extract monitor from progress if provided
            monitor = None
            if progress is not None:
                monitor = progress.get_monitor()

            # Detect execution mode for logging purposes
            execution_mode = getattr(database_config, "execution_mode", None) if database_config else None
            if execution_mode is None and database_config is not None:
                execution_mode = PlatformRegistry.get_default_mode(database_config.type)
                if is_dataframe_execution(database_config):
                    execution_mode = "dataframe"

            # Create adapter using unified factory (handles both SQL and DataFrame)
            adapter = None
            if database_config is not None and (phases.load or phases.execute):
                if execution_mode == "dataframe":
                    self.console.print("[cyan]Using DataFrame execution mode[/cyan]")
                    df_tuning_config = opts.get("df_tuning_config")
                    adapter = get_adapter(
                        database_config.type,
                        mode="dataframe",
                        working_dir=output_root,
                        verbose=self._verbosity.verbose if self._verbosity else False,
                        very_verbose=self._verbosity.very_verbose if self._verbosity else False,
                        tuning_config=df_tuning_config,
                    )
                else:
                    adapter = get_platform_adapter(database_config.type, **(platform_cfg or {}))
                    # Set benchmark instance on adapter for database validation
                    if adapter and benchmark:
                        adapter.benchmark_instance = benchmark
                        adapter.scale_factor = config.scale_factor

            # Delegate lifecycle to core runner (handles both SQL and DataFrame adapters)
            result = run_benchmark_lifecycle(
                benchmark_config=config,
                database_config=database_config,
                system_profile=system_profile,
                platform_config=platform_cfg,
                phases=phases,
                validation_opts=validation,
                output_root=output_root,
                benchmark_instance=benchmark,
                platform_adapter=adapter,
                verbosity=self._verbosity,
                monitor=monitor,
                enable_resource_monitoring=False,
                execution_context=execution_context,
            )

            # Canonical runtime metadata enrichment for all `benchbox run` paths.
            apply_driver_metadata(result, database_config=database_config, platform_adapter=adapter)
            return result

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
            from benchbox.core.results.models import BenchmarkResults, ExecutionPhases, SetupPhase

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
                validation_details={"error": str(e)},
                data_loading_time=0.0,
                schema_creation_time=0.0,
                total_rows_loaded=0,
                data_size_mb=0.0,
                table_statistics={},
            )

    def _prepare_run_config(self, config: BenchmarkConfig, database_config) -> RunConfig:
        """Prepare benchmark run configuration using structured dataclass."""

        # Get tuning configuration if available for distinct naming
        tuning_config = None
        if config.options:
            tuning_config = config.options.get("unified_tuning_configuration")

        database_path = self.directory_manager.get_database_path(
            config.name,
            config.scale_factor,
            database_config.type,
            tuning_config=tuning_config,
        )

        options = config.options or {}
        iterations = int(
            options.get("power_iterations", GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS)
            or GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS
        )
        warmups = int(
            options.get("power_warmup_iterations", GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS)
            or GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS
        )
        fail_fast = bool(options.get("power_fail_fast", False))

        return RunConfig(
            query_subset=config.queries,
            concurrent_streams=config.concurrency,
            test_execution_type=getattr(config, "test_execution_type", "standard"),
            scale_factor=config.scale_factor,
            capture_plans=config.capture_plans,
            strict_plan_capture=config.strict_plan_capture,
            seed=int(options.get("seed")) if options.get("seed") is not None else None,
            connection={"database_path": str(database_path)},
            verbose=self._verbosity.verbose,
            verbose_level=self._verbosity.level,
            verbose_enabled=self._verbosity.verbose_enabled,
            very_verbose=self._verbosity.very_verbose,
            quiet=self._verbosity.quiet,
            iterations=max(1, iterations),
            warm_up_iterations=max(0, warmups),
            power_fail_fast=fail_fast,
        )

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
        cloud_platforms = ["snowflake", "bigquery", "databricks", "redshift"]
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
            platform: Platform name (snowflake, bigquery, databricks, redshift)

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
