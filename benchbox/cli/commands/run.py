"""Implementation of the `benchbox run` command."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import click
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from benchbox.cli.benchmarks import BenchmarkConfig, BenchmarkManager
from benchbox.cli.cloud_storage import prompt_cloud_output_location
from benchbox.cli.composite_params import (
    COMPRESSION,
    FORCE,
    PLAN_CONFIG,
    TABLE_FORMAT,
    VALIDATION,
    CompressionConfig,
    ForceConfig,
    PlanCaptureConfig,
    TableFormatConfig,
    ValidationConfig,
)
from benchbox.cli.database import DatabaseManager
from benchbox.cli.exceptions import (
    CloudStorageError,
    ErrorContext,
    ValidationError,
    ValidationRules,
    create_error_handler,
)
from benchbox.cli.help import BenchBoxCommand, advanced_option
from benchbox.cli.orchestrator import BenchmarkOrchestrator
from benchbox.cli.output import ResultExporter
from benchbox.cli.platform import get_platform_manager, normalize_platform_name
from benchbox.cli.platform_checks import check_and_setup_platform_credentials
from benchbox.cli.platform_hooks import PlatformHookRegistry, PlatformOptionError
from benchbox.cli.presentation.system import display_system_recommendations
from benchbox.cli.progress import BenchmarkProgress, should_show_progress
from benchbox.cli.shared import console, set_quiet_output, silence_output
from benchbox.cli.system import SystemProfiler
from benchbox.cli.tuning_resolver import (
    TuningMode,
    TuningSource,
    display_tuning_resolution,
    resolve_tuning,
)
from benchbox.core.config import DatabaseConfig
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.core.schemas import ExecutionContext
from benchbox.platforms import is_dataframe_platform, list_available_dataframe_platforms
from benchbox.utils.cloud_storage import is_cloud_path
from benchbox.utils.compression import CompressionManager
from benchbox.utils.output_path import normalize_output_root
from benchbox.utils.verbosity import VerbositySettings

logger = logging.getLogger(__name__)
DATA_ORGANIZATION_ENV = "BENCHBOX_DATA_ORGANIZATION_CONFIG_JSON"

# Benchmark name aliases - maps common variations to canonical names
BENCHMARK_ALIASES: dict[str, str] = {
    # TPC-H variations
    "tpc-h": "tpch",
    "tpc_h": "tpch",
    # TPC-DS variations
    "tpc-ds": "tpcds",
    "tpc_ds": "tpcds",
    # TPC-DS OBT variations
    "tpcdsobt": "tpcds_obt",
    "tpcds-obt": "tpcds_obt",
    "tpc-ds-obt": "tpcds_obt",
    "tpc-ds_obt": "tpcds_obt",
    "tpc_ds_obt": "tpcds_obt",
    # SSB (Star Schema Benchmark) variations
    "star-schema": "ssb",
    "starschema": "ssb",
    "star_schema": "ssb",
    "star-schema-benchmark": "ssb",
}


def normalize_benchmark_name(name: str) -> str:
    """Normalize benchmark name: lowercase and resolve aliases."""
    normalized = name.lower()
    return BENCHMARK_ALIASES.get(normalized, normalized)


def _reject_external_tuned(console: Any, logger: logging.Logger | None, ctx: click.Context) -> None:
    """Exit with error when --table-mode external is combined with --tuning tuned."""
    console.print("[red]❌ Error: --table-mode external is incompatible with --tuning tuned[/red]")
    console.print("[yellow]Use --table-mode native or choose a non-tuned mode[/yellow]")
    if logger:
        logger.error("Invalid flag combination: --table-mode external with --tuning tuned")
    ctx.exit(1)


def _apply_platform_optimization_overrides(
    unified_tuning: Any,
    *,
    sorted_ingestion_mode: str | None,
    sorted_ingestion_method: str | None,
    parsed_platform_options: dict[str, Any] | None = None,
) -> None:
    """Apply CLI and platform-option overrides to platform optimization settings."""
    platform_optimizations = unified_tuning.platform_optimizations
    platform_options = parsed_platform_options or {}

    if sorted_ingestion_mode:
        platform_optimizations.sorted_ingestion_mode = sorted_ingestion_mode.lower()
    if sorted_ingestion_method:
        platform_optimizations.sorted_ingestion_method = sorted_ingestion_method.lower()
    if (
        platform_optimizations.sorted_ingestion_mode == "off"
        and platform_optimizations.sorted_ingestion_method != "auto"
    ):
        raise ValueError("--sorted-ingestion-method requires --sorted-ingestion-mode auto or force")

    resolved_strategy = platform_options.get("databricks_clustering_strategy")
    if resolved_strategy:
        strategy = str(resolved_strategy).lower()
        platform_optimizations.databricks_clustering_strategy = strategy
        platform_optimizations.liquid_clustering_enabled = strategy == "liquid_clustering"

    resolved_liquid_columns = platform_options.get("liquid_clustering_columns")
    if resolved_liquid_columns:
        columns = [column.strip() for column in str(resolved_liquid_columns).split(",") if column.strip()]
        platform_optimizations.liquid_clustering_columns = columns
        if columns:
            platform_optimizations.liquid_clustering_enabled = True


def _build_data_organization_from_tuning(unified_tuning: Any) -> dict[str, Any] | None:
    """Build data organization payload from unified tuning configuration."""
    if unified_tuning is None:
        return None

    table_configs: dict[str, list[dict[str, str]]] = {}
    table_partition_configs: dict[str, list[str]] = {}
    table_cluster_configs: dict[str, list[str]] = {}

    table_tunings = getattr(unified_tuning, "table_tunings", {}) or {}
    for table_name, table_tuning in table_tunings.items():
        sorting = sorted(getattr(table_tuning, "sorting", []) or [], key=lambda c: c.order)
        partitioning = sorted(getattr(table_tuning, "partitioning", []) or [], key=lambda c: c.order)
        clustering = sorted(getattr(table_tuning, "clustering", []) or [], key=lambda c: c.order)

        if sorting:
            table_configs[table_name] = [{"name": c.name, "order": str(c.sort_order).lower()} for c in sorting]
        if partitioning:
            table_partition_configs[table_name] = [c.name for c in partitioning]
        if clustering:
            table_cluster_configs[table_name] = [c.name for c in clustering]

    if not table_configs and not table_partition_configs and not table_cluster_configs:
        return None

    platform_opts = getattr(unified_tuning, "platform_optimizations", None)
    method = "z_order"
    method_hint = str(getattr(platform_opts, "sorted_ingestion_method", "auto") or "auto").lower()
    if method_hint == "hilbert":
        method = "hilbert"
    elif method_hint == "z_order" or getattr(platform_opts, "z_ordering_enabled", False):
        method = "z_order"

    return {
        "table_configs": table_configs,
        "table_partition_configs": table_partition_configs,
        "table_cluster_configs": table_cluster_configs,
        "clustering_method": method,
    }


def _resolve_data_organization_payload(
    benchmark_name: str | None,
    presort: str | None,
    tuning_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve effective data organization payload from tuning and CLI flags."""
    if presort not in {"parquet-sorted", "delta-sorted", "iceberg-sorted"}:
        return tuning_payload

    if tuning_payload is not None:
        if presort in {"delta-sorted", "iceberg-sorted"}:
            payload = dict(tuning_payload)
            payload["output_format"] = "delta" if presort == "delta-sorted" else "iceberg"
            return payload
        return tuning_payload

    benchmark_key = (benchmark_name or "").lower()
    output_format_map = {
        "parquet-sorted": "parquet",
        "delta-sorted": "delta",
        "iceberg-sorted": "iceberg",
    }
    output_format = output_format_map[presort]
    if benchmark_key == "tpch":
        return {
            "table_configs": {"lineitem": [{"name": "l_shipdate", "order": "asc"}]},
            "output_format": output_format,
        }
    if benchmark_key == "tpcds":
        return {
            "table_configs": {"store_sales": [{"name": "ss_sold_date_sk", "order": "asc"}]},
            "output_format": output_format,
        }

    if benchmark_key:
        raise ValueError("--presort sorted modes are currently supported for tpch and tpcds benchmarks")
    return tuning_payload


def _render_post_run_charts(
    result: Any,
    console: Any,
    quiet: bool,
) -> None:
    """Render post-run summary charts to the console if applicable."""
    if quiet or not result.query_results:
        return
    try:
        from benchbox.core.visualization.post_run_summary import generate_post_run_summary

        summary = generate_post_run_summary(result)
        for chart in summary.charts:
            console.print(Text.from_ansi(chart))
    except Exception:
        logger.debug("Failed to render post-run summary charts", exc_info=True)


def _build_execution_context(
    phases_to_run: list[str],
    seed: int | None,
    compression: CompressionConfig,
    mode: str | None,
    official: bool,
    validation: ValidationConfig,
    force: ForceConfig,
    queries_to_run: list[str] | None,
    capture_plans: bool,
    strict_plan_capture: bool,
    non_interactive: bool,
    tuning: str | None,
) -> ExecutionContext:
    """Build ExecutionContext from CLI parameters for result reproducibility.

    Args:
        phases_to_run: List of phases to execute
        seed: Random seed for query generation
        compression: Compression configuration
        mode: Execution mode (sql/dataframe)
        official: TPC-compliant mode flag
        validation: Validation configuration
        force: Force flags configuration
        queries_to_run: Query subset
        capture_plans: Whether to capture query plans
        strict_plan_capture: Strict plan capture mode
        non_interactive: Non-interactive mode flag
        tuning: Tuning mode/path

    Returns:
        ExecutionContext populated from CLI parameters
    """
    return ExecutionContext(
        entry_point="cli",
        phases=phases_to_run,
        seed=seed,
        compression_enabled=compression.enabled,
        compression_type=compression.type,
        compression_level=compression.level,
        mode=mode or "sql",
        official=official,
        validation_mode=validation.mode if validation.mode != "exact" else None,
        force_datagen=force.datagen,
        force_upload=force.upload,
        query_subset=queries_to_run,
        capture_plans=capture_plans,
        strict_plan_capture=strict_plan_capture,
        non_interactive=non_interactive,
        tuning_mode=tuning if tuning and tuning != "notuning" else None,
    )


def _execute_orchestrated_run(
    orchestrator: BenchmarkOrchestrator,
    benchmark_config: BenchmarkConfig,
    system_profile: Any,
    database_config: DatabaseConfig | None,
    phases_to_run: list[str],
    *,
    quiet: bool,
    no_progress: bool,
    no_monitoring: bool,
    execution_context: ExecutionContext | None = None,
) -> Any:
    """Execute benchmark through the canonical orchestrator path."""
    progress_enabled = not no_progress and should_show_progress()
    enable_monitoring = not no_monitoring

    if progress_enabled and not quiet:
        progress = BenchmarkProgress(
            console=console,
            enable_monitoring=enable_monitoring,
        )
        with progress:
            return orchestrator.execute_benchmark(
                benchmark_config,
                system_profile,
                database_config,
                phases_to_run,
                progress=progress,
                execution_context=execution_context,
            )

    with silence_output(enabled=bool(quiet)):
        return orchestrator.execute_benchmark(
            benchmark_config,
            system_profile,
            database_config,
            phases_to_run,
            progress=None,
            execution_context=execution_context,
        )


def _export_orchestrated_result(
    *,
    orchestrator: BenchmarkOrchestrator,
    result: Any,
    benchmark: str,
    scale: float,
    platform_label: str,
    mode_label: str,
    quiet: bool,
    export_formats: list[str] | None = None,
) -> dict[str, Any]:
    """Export a canonical run result using directory-manager naming."""
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = orchestrator.directory_manager.get_result_path(
        benchmark,
        scale,
        platform_label,
        timestamp,
        result.execution_id,
        mode=mode_label,
    )

    exporter = ResultExporter()
    exporter.output_dir = orchestrator.directory_manager.results_dir
    result.output_filename = result_path.name

    formats = export_formats or ["json"]
    with silence_output(enabled=bool(quiet)):
        exported_files = exporter.export_result(result, formats)
    return exported_files


class PlatformOptionParamType(click.ParamType):
    """Click parameter type for key=value platform options."""

    name = "key=value"

    def convert(self, value: str, param, ctx) -> tuple[str, str]:
        if "=" not in value:
            self.fail("Expected KEY=VALUE format", param, ctx)
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            self.fail("Platform option key cannot be empty", param, ctx)
        return key, raw.strip()


def _describe_platform_options(platform_names: Iterable[str]) -> None:
    for name in platform_names:
        platform_key = name.lower()
        lines = PlatformHookRegistry.describe_options(platform_key)
        header = f"[bold cyan]{platform_key} platform options[/bold cyan]"
        if not lines:
            console.print(f"{header}: (no platform-specific options registered)")
            continue
        console.print(header)
        for line in lines:
            console.print(f"  • {line}")
        console.print()


from benchbox.cli.verbose_logging import setup_verbose_logging as setup_verbose_logging  # noqa: E402


@click.command("run", cls=BenchBoxCommand)
# === Core Options (Tier 1 - Always visible) ===
@click.option(
    "--platform",
    type=str,
    help="Platform with optional deployment mode (platform:mode). Examples: duckdb, clickhouse:cloud, firebolt:core",
)
@click.option("--benchmark", type=str, help="Benchmark (tpch, tpcds, ssb, clickbench)")
@click.option("--scale", type=float, default=0.01, help="Scale factor", show_default=True)
@click.option(
    "--output",
    type=str,
    help="Output directory (required for cloud platforms). Supports: s3://, gs://, abfss://, dbfs:/Volumes/",
)
# === Common Options (Tier 2 - Always visible) ===
@click.option(
    "--phases",
    type=str,
    default="power",
    help="Phases: generate,load,warmup,power,throughput,maintenance",
)
@click.option(
    "--queries",
    type=str,
    help="Query subset (e.g., 'Q1,Q6,Q17'). Only for power/standard phases.",
)
@click.option(
    "--tuning",
    type=str,
    default="notuning",
    help="Tuning: tuned, notuning, auto, or YAML path",
)
@click.option(
    "--table-mode",
    type=click.Choice(["native", "external"], case_sensitive=False),
    default="native",
    help="Table mode: native materialized tables or external table/view references",
)
@advanced_option(
    "--sorted-ingestion-mode",
    type=click.Choice(["off", "auto", "force"], case_sensitive=False),
    default=None,
    help="Cloud sorted-ingestion strategy mode: off, auto, force",
)
@advanced_option(
    "--sorted-ingestion-method",
    type=click.Choice(["auto", "ctas", "z_order", "hilbert", "liquid_clustering", "vacuum_sort"], case_sensitive=False),
    default=None,
    help="Cloud sorted-ingestion method override",
)
@click.option(
    "--dry-run",
    type=str,
    metavar="OUTPUT_DIR",
    help="Preview configuration without execution",
)
@click.option(
    "--force",
    type=FORCE,
    default=None,
    is_flag=False,
    flag_value="all",
    help="Force regeneration: all, datagen, upload, or datagen,upload",
)
@click.option("-v", "--verbose", count=True, help="Verbose output (-vv for debug)")
@click.option("-q", "--quiet", is_flag=True, help="Suppress output")
@click.option("--non-interactive", is_flag=True, help="Non-interactive mode (CI/CD)")
@click.option(
    "--official",
    is_flag=True,
    help="TPC-compliant mode: validates scale factors, requires seed for reproducibility",
)
# === Advanced Options (Tier 3 - Hidden, shown with --help-all) ===
# Plan Capture
@advanced_option(
    "--capture-plans",
    is_flag=True,
    help=(
        "Capture query execution plans. Supported: DuckDB, PostgreSQL, DataFusion. "
        "DuckDB uses EXPLAIN (ANALYZE, FORMAT JSON) by default — actual per-operator timing and "
        "cardinality included, at ~2x query cost per captured plan. "
        "Set analyze_plans=false via --platform-option to capture estimated plans only."
    ),
)
@advanced_option(
    "--plan-config",
    type=PLAN_CONFIG,
    default=None,
    help="Plan capture config: sample:0.1,first:5,queries:1,6,strict:true",
)
# Compression
@advanced_option(
    "--compression",
    type=COMPRESSION,
    default=None,
    help="Compression: zstd, zstd:9, gzip:6, none",
)
# Format Conversion
@advanced_option(
    "--table-format",
    type=TABLE_FORMAT,
    default=None,
    help="Table format: parquet, vortex, delta:snappy, iceberg:zstd,partition:year,month",
)
@advanced_option(
    "--presort",
    type=click.Choice(["parquet-sorted", "delta-sorted", "iceberg-sorted"], case_sensitive=False),
    default=None,
    help="Pre-sort data into open table formats (parquet-sorted, delta-sorted, iceberg-sorted).",
)
# Validation
@advanced_option(
    "--validation",
    type=VALIDATION,
    default=None,
    help="Validation: exact, loose, range, disabled, full",
)
# Platform-specific
@click.option(
    "--platform-option",
    "platform_option_pairs",
    type=PlatformOptionParamType(),
    multiple=True,
    hidden=True,
    help=(
        "Platform option in KEY=VALUE form (repeatable). "
        "Well-known keys available on all platforms: "
        "driver_version (pin Python driver package version, e.g. '1.2.0'), "
        "driver_auto_install (auto-install driver via uv if missing, true/false). "
        "Athena Spark only: engine_version (Spark engine version, "
        "e.g. 'PySpark engine version 3'). "
        "Platform-specific keys are also accepted (e.g. warehouse=MY_WH for Snowflake). "
        "Run --help-topic examples for the full driver versioning workflow."
    ),
)
@advanced_option(
    "--mode",
    type=click.Choice(["sql", "dataframe"], case_sensitive=False),
    default=None,
    help="Execution mode: sql or dataframe",
)
@advanced_option("--seed", type=int, help="RNG seed for query parameter generation")
# Output Control
@advanced_option("--no-monitoring", is_flag=True, help="Disable metrics collection")
@advanced_option("--no-progress", is_flag=True, help="Disable progress bars")
@advanced_option("--ignore-memory-warnings", is_flag=True, help="Proceed despite insufficient memory warnings")
@advanced_option(
    "--global-cache",
    is_flag=True,
    help="Use ~/.benchbox/datagen/ as DataFrame cache (shared across projects). Default: project-local benchmark_runs/.",
)
@click.option(
    "--publish",
    is_flag=True,
    help="Publish the exported result bundle after a successful run (uses benchbox publish defaults).",
)
@click.option(
    "--publish-target",
    default="benchmark_runs/published",
    show_default=True,
    help="Destination for --publish: local directory or cloud URI (s3://, gs://, abfss://).",
)
@click.option(
    "--publish-label",
    default="maintainer-run",
    show_default=True,
    help="Trust label for --publish (maintainer-run, community-submission, ci, local).",
)
@click.pass_context
def run(
    ctx: click.Context,
    platform: str | None,
    benchmark: str | None,
    scale: float,
    output: str | None,
    phases: str,
    queries: str | None,
    tuning: str,
    table_mode: str,
    sorted_ingestion_mode: str | None,
    sorted_ingestion_method: str | None,
    dry_run: str | None,
    force: ForceConfig | None,
    verbose: int,
    quiet: bool,
    non_interactive: bool,
    official: bool,
    capture_plans: bool,
    plan_config: PlanCaptureConfig | None,
    compression: CompressionConfig | None,
    table_format: TableFormatConfig | None,
    presort: str | None,
    validation: ValidationConfig | None,
    platform_option_pairs: tuple[tuple[str, str], ...],
    mode: str | None,
    seed: int | None,
    no_monitoring: bool,
    no_progress: bool,
    ignore_memory_warnings: bool,
    global_cache: bool,
    publish: bool,
    publish_target: str,
    publish_label: str,
) -> None:
    """Run benchmarks.

    \b
    Examples:
      benchbox run --platform duckdb --benchmark tpch
      benchbox run --platform duckdb --benchmark tpch --queries Q1,Q6,Q17
      benchbox run --dry-run ./preview --platform snowflake --benchmark tpch
      benchbox run --official --platform snowflake --benchmark tpch --scale 100 --seed 42

    \b
    Deployment Modes (use colon separator):
      benchbox run --platform clickhouse:local --benchmark tpch    # chDB embedded
      benchbox run --platform clickhouse:cloud --benchmark tpch    # ClickHouse Cloud
      benchbox run --platform firebolt:core --benchmark tpch       # Firebolt Core (Docker)
      benchbox run --platform firebolt:cloud --benchmark tpch      # Firebolt Cloud

    Use --help-topic examples for more, --help-topic all for advanced options.
    """
    # === Adapter: Map new composite params to legacy variable names ===
    # This preserves compatibility with the rest of the function body

    # Force config -> legacy flags
    force_config = force or ForceConfig()
    force_regenerate = force_config.datagen
    force_upload = force_config.upload

    # Compression config -> legacy variables
    comp_config = compression or CompressionConfig()
    compression_cli_set = compression is not None
    no_compression = not comp_config.enabled
    compression_type = comp_config.type
    compression_level = comp_config.level

    # Plan config -> legacy variables
    plan_cfg = plan_config or PlanCaptureConfig()
    strict_plan_capture = plan_cfg.strict
    plan_sampling_rate = plan_cfg.sample_rate
    plan_first_n = plan_cfg.first_n
    plan_queries_str = ",".join(plan_cfg.queries) if plan_cfg.queries else None
    show_query_plans = capture_plans  # Show plans when capturing

    # Table format config -> legacy variables
    table_format_value = table_format.format if table_format else None
    table_format_compression = table_format.compression if table_format else "snappy"
    table_format_partition_cols = tuple(table_format.partition_cols) if table_format else ()

    # Validation config -> legacy variables
    val_config = validation or ValidationConfig()
    validation_mode = val_config.mode if val_config.mode != "exact" or validation else None
    check_platforms = val_config.check_platforms
    enable_preflight_validation = val_config.preflight
    enable_postgen_manifest_validation = val_config.postgen
    enable_postload_validation = val_config.postload

    # Removed options (no longer supported)
    describe_platforms: tuple[str, ...] = ()  # Moved to separate command

    # Assign plan_queries to match original variable name used in body
    plan_queries = plan_queries_str

    if describe_platforms:
        _describe_platform_options(describe_platforms)
        ctx.exit(0)

    if quiet and verbose:
        console.print("[red]❌ --quiet cannot be used with -v/-vv flags[/red]")
        ctx.exit(2)

    # === TPC Official Mode Validation ===
    if official:
        TPC_ALLOWED_SCALE_FACTORS = {1, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000}

        # Validate scale factor
        if scale not in TPC_ALLOWED_SCALE_FACTORS:
            console.print(f"[red]❌ Scale factor {scale} is not TPC-compliant[/red]")
            console.print(f"Allowed scale factors: {sorted(TPC_ALLOWED_SCALE_FACTORS)}")
            ctx.exit(1)

        # Warn if no seed for reproducibility
        if seed is None:
            console.print(
                "[yellow]⚠️  Warning: No --seed specified. Official TPC runs require a random seed for reproducibility.[/yellow]"
            )

        # Show compliance banner
        console.print("[bold blue]TPC-Compliant Official Benchmark Run[/bold blue]")
        console.print(f"Scale Factor: {scale} (TPC-allowed)")
        if seed is not None:
            console.print(f"Seed: {seed}")
        console.print()

    # Configure quiet/verbose behavior and persist settings for downstream components
    logger, verbosity_settings = setup_verbose_logging(verbose, quiet=bool(quiet))
    set_quiet_output(verbosity_settings.quiet)
    ctx.obj["verbosity"] = verbosity_settings
    verbosity_payload = verbosity_settings.to_config()

    platform_key = normalize_platform_name(platform) if platform else None
    benchmark = normalize_benchmark_name(benchmark) if benchmark else None
    table_mode = (table_mode or "native").lower()
    table_mode_cli_supplied = False
    if hasattr(ctx, "get_parameter_source"):
        try:
            table_mode_cli_supplied = ctx.get_parameter_source("table_mode") == click.core.ParameterSource.COMMANDLINE
        except Exception:
            table_mode_cli_supplied = False
    if platform_option_pairs and not platform_key:
        console.print("[red]❌ Platform options require a --platform selection[/red]")
        ctx.exit(1)

    parsed_platform_options: dict[str, Any] = {}
    if platform_key:
        try:
            parsed_platform_options = PlatformHookRegistry.parse_options(platform_key, platform_option_pairs)
        except PlatformOptionError as exc:
            console.print(f"[red]❌ {exc}[/red]")
            if logger:
                logger.error(f"Platform option error: {exc}")
            ctx.exit(1)

    if logger:
        logger.debug("Starting BenchBox CLI run command")
        logger.debug(f"Arguments: platform={platform}, benchmark={benchmark}, scale={scale}, verbose={verbose}")

    if table_mode == "external" and tuning.strip().lower() == "tuned":
        _reject_external_tuned(console, logger, ctx)

    # Set non-interactive environment variable if flag is provided
    if non_interactive:
        os.environ["BENCHBOX_NON_INTERACTIVE"] = "true"
        if logger:
            logger.debug("Non-interactive mode enabled via CLI flag")

        # Validate required arguments are provided in non-interactive mode
        # Parse phases first to determine required args
        phase_list = [p.strip() for p in phases.split(",") if p.strip()]
        is_data_only = phase_list == ["generate"] or (
            "generate" in phase_list and not set(phase_list) & {"load", "warmup", "power", "throughput", "maintenance"}
        )

        # Check for missing required arguments
        missing_args = []
        if not benchmark:
            missing_args.append("--benchmark")
        if not platform and not is_data_only:
            # Platform not required for data-only mode
            missing_args.append("--platform")

        if missing_args:
            console.print("[red]❌ Error: Non-interactive mode requires all parameters[/red]")
            console.print(f"[yellow]Missing: {', '.join(missing_args)}[/yellow]")
            console.print("[dim]Use interactive mode by omitting --non-interactive flag[/dim]")
            if logger:
                logger.error(f"Non-interactive mode missing required args: {missing_args}")
            ctx.exit(2)

    # Parse and validate phases
    valid_phases = {"generate", "load", "warmup", "power", "throughput", "maintenance"}
    phase_list = [p.strip() for p in phases.split(",") if p.strip()]

    # Validate all phases are valid
    invalid_phases = set(phase_list) - valid_phases
    if invalid_phases:
        console.print(f"[red]❌ Error: Invalid phases: {', '.join(invalid_phases)}[/red]")
        console.print(f"[yellow]Valid phases: {', '.join(sorted(valid_phases))}[/yellow]")
        if logger:
            logger.error(f"Invalid phases specified: {invalid_phases}")
        ctx.exit(1)

    # Remove duplicates while preserving order
    seen = set()
    phases_to_run = []
    for p in phase_list:
        if p not in seen:
            phases_to_run.append(p)
            seen.add(p)

    # Parse and validate queries list
    queries_to_run = None
    if queries is not None:
        import re

        # Split on commas and strip whitespace, preserving user-specified order
        queries_to_run = [q.strip() for q in queries.split(",") if q.strip()]

        if not queries_to_run:
            console.print("[red]❌ Error: --queries flag provided but no valid query IDs found[/red]")
            if logger:
                logger.error("Empty queries list after parsing")
            ctx.exit(1)

        # Length limits (DoS protection)
        max_queries = 100
        max_query_id_len = 20
        if len(queries_to_run) > max_queries:
            console.print(f"[red]❌ Too many queries: {len(queries_to_run)} (max {max_queries})[/red]")
            if logger:
                logger.error(f"Query list too long: {len(queries_to_run)} exceeds limit of {max_queries}")
            ctx.exit(1)

        if any(len(q) > max_query_id_len for q in queries_to_run):
            too_long = [q for q in queries_to_run if len(q) > max_query_id_len]
            console.print(f"[red]❌ Query ID too long (max {max_query_id_len} chars): {', '.join(too_long[:3])}[/red]")
            if logger:
                logger.error(f"Query IDs exceed length limit: {too_long}")
            ctx.exit(1)

        # Character validation (alphanumeric only)
        query_id_pattern = re.compile(r"^[a-zA-Z0-9_.\-]+$")
        invalid_format = [q for q in queries_to_run if not query_id_pattern.match(q)]
        if invalid_format:
            console.print(
                f"[red]❌ Invalid query ID format: {', '.join(invalid_format[:5])} "
                f"(must be alphanumeric, dash, underscore, or dot)[/red]"
            )
            if logger:
                logger.error(f"Invalid query ID format: {invalid_format}")
            ctx.exit(1)

        # Check phase compatibility
        incompatible_phases = {"warmup", "throughput", "maintenance"} & set(phases_to_run)
        query_phases = {"power", "standard"} & set(phases_to_run)

        if incompatible_phases and not query_phases:
            # ONLY incompatible phases - error
            console.print(
                f"[red]❌ --queries only works with power/standard phases. "
                f"Current phases ({', '.join(sorted(phases_to_run))}) are incompatible.[/red]"
            )
            if logger:
                logger.error(f"--queries flag requires power or standard phase, got: {phases_to_run}")
            ctx.exit(1)
        elif incompatible_phases:
            # Mixed compatible and incompatible - warn
            console.print(f"[yellow]⚠️  --queries ignored for: {', '.join(sorted(incompatible_phases))}[/yellow]")
            if logger:
                logger.warning(f"--queries flag will be ignored for phases: {incompatible_phases}")

    # Determine test execution type based on phases
    query_phases = {"power", "throughput", "maintenance"}
    selected_query_phases = set(phases_to_run) & query_phases
    if selected_query_phases:
        # Any mixed query-phase request should use combined mode so the adapter
        # can execute exactly the requested subset of query phases.
        if len(selected_query_phases) > 1:
            test_execution_type = "combined"
        elif "power" in selected_query_phases:
            test_execution_type = "power"
        elif "throughput" in selected_query_phases:
            test_execution_type = "throughput"
        elif "maintenance" in selected_query_phases:
            test_execution_type = "maintenance"
        else:
            test_execution_type = "standard"
    elif phases_to_run == ["load"] or ("load" in phases_to_run and not set(phases_to_run) & query_phases):
        test_execution_type = "load_only"
    elif phases_to_run == ["generate"] or (
        "generate" in phases_to_run and not set(phases_to_run) & {"load"} | query_phases
    ):
        test_execution_type = "data_only"
    else:
        test_execution_type = "standard"

    if logger:
        logger.debug(f"Test execution type: {test_execution_type}")

    # Set execution_mode for compatibility (simplified logic)
    execution_mode = test_execution_type

    if not quiet:
        console.print(
            Panel.fit(
                Text("BenchBox Interactive Benchmark Runner", style="bold blue"),
                style="blue",
            )
        )

    # Platform validation
    platform_manager = get_platform_manager()

    # Check platforms if requested
    if check_platforms:
        console.print("\n[bold cyan]Checking Platform Status...[/bold cyan]")
        enabled_platforms = platform_manager.get_enabled_platforms()

        if not enabled_platforms:
            console.print("[red]❌ No platforms are enabled![/red]")
            console.print("Run [cyan]benchbox platforms setup[/cyan] to configure platforms.")
            ctx.exit(1)

        all_good = True
        for platform_name in enabled_platforms:
            if platform_manager.is_platform_available(platform_name):
                console.print(f"[green]✅ {platform_name}: Ready[/green]")
            else:
                console.print(f"[red]❌ {platform_name}: Missing dependencies[/red]")
                all_good = False

        if not all_good:
            console.print(
                "\n[red]Some platforms need attention. Run [cyan]benchbox platforms status[/cyan] for details.[/red]"
            )
            ctx.exit(1)
        else:
            console.print("[green]All enabled platforms are ready![/green]")

    # Validate platform and mode if specified
    # Uses new capability-based platform registry
    resolved_mode = None
    if platform_key:
        # Get platform capabilities
        caps = PlatformRegistry.get_platform_capabilities(platform_key)

        if caps is None:
            # Platform not in registry - check legacy DataFrame platforms
            is_df_platform_legacy = is_dataframe_platform(platform_key)
            is_df_available = is_df_platform_legacy and list_available_dataframe_platforms().get(platform_key, False)

            if not is_df_available and not dry_run:
                from benchbox.utils.dependencies import get_install_command

                console.print(f"[red]❌ Platform '{platform_key}' is not available (missing dependencies)[/red]")
                install_cmd = get_install_command(platform_key)
                console.print(f"Run [cyan]{escape(install_cmd)}[/cyan] to install dependencies.")
                ctx.exit(1)
            # Legacy DataFrame platform handling
            resolved_mode = "dataframe"
        else:
            # Validate mode against platform capabilities
            if mode is not None:
                if not PlatformRegistry.supports_mode(platform_key, mode):
                    supported_modes = []
                    if caps.supports_sql:
                        supported_modes.append("sql")
                    if caps.supports_dataframe:
                        supported_modes.append("dataframe")
                    console.print(f"[red]❌ Platform '{platform_key}' does not support {mode} mode[/red]")
                    console.print(f"[yellow]Supported modes: {', '.join(supported_modes)}[/yellow]")
                    if logger:
                        logger.error(f"Platform {platform_key} does not support mode: {mode}")
                    ctx.exit(1)
                resolved_mode = mode
            else:
                # Use platform default mode
                resolved_mode = caps.default_mode

            # Check platform availability for the resolved mode
            if resolved_mode == "sql":
                # For polars SQL mode, check if polars library is available directly
                if platform_key == "polars":
                    try:
                        import polars  # noqa: F401

                        is_available = True
                    except ImportError:
                        is_available = False
                else:
                    is_available = platform_manager.is_platform_available(platform_key)
            else:
                # DataFrame mode - check DataFrame adapter availability
                is_available = caps.supports_dataframe
                # For DataFrame-capable platforms, also check library availability
                if is_available and platform_key in ["polars", "pandas", "modin", "cudf", "dask"]:
                    df_platforms = list_available_dataframe_platforms()
                    # Check legacy key first, then new key
                    legacy_key = f"{platform_key}-df"
                    is_available = df_platforms.get(legacy_key, df_platforms.get(platform_key, False))

            if not is_available and not dry_run:
                from benchbox.utils.dependencies import get_install_command

                console.print(f"[red]❌ Platform '{platform_key}' is not available (missing dependencies)[/red]")
                install_cmd = get_install_command(platform_key)
                console.print(f"Run [cyan]{escape(install_cmd)}[/cyan] to install dependencies.")
                ctx.exit(1)

        if logger and resolved_mode:
            logger.debug(f"Resolved execution mode for {platform_key}: {resolved_mode}")

    config = ctx.obj["config"]
    if logger:
        logger.debug(f"Loaded configuration from: {config.config_path}")
        logger.debug(f"Configuration validation status: {config.validate_config()}")

    # Parse tuning mode using the transparent tuning resolver
    # This provides clear feedback about what tuning configuration is being used
    try:
        tuning_resolution = resolve_tuning(
            tuning_arg=tuning,
            platform=platform,
            benchmark=benchmark,
            config_manager=config,
            console=console,
            logger=logger,
            quiet=bool(quiet),
            non_interactive=non_interactive,
        )
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]")
        if logger:
            logger.error(f"Tuning resolution failed: {e}")
        ctx.exit(1)

    # Extract tuning state from resolution for compatibility
    tuning_enabled = tuning_resolution.enabled
    tuning_config_file = str(tuning_resolution.config_file) if tuning_resolution.config_file else None
    use_auto_tuning = tuning_resolution.mode == TuningMode.AUTO

    # Display tuning resolution information (always show in non-quiet mode)
    if not quiet:
        display_tuning_resolution(tuning_resolution, console, verbose=bool(verbose))

    if logger:
        logger.debug(
            f"Tuning resolution: mode={tuning_resolution.mode.value}, "
            f"source={tuning_resolution.source.value}, enabled={tuning_enabled}"
        )

    # Load unified tuning configuration based on resolution
    loaded_unified_config = None
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration

    if tuning_resolution.config_file:
        # Load from resolved file path
        try:
            loaded_unified_config = config.load_unified_tuning_config(tuning_resolution.config_file, platform)
            if logger:
                logger.debug(f"Loaded tuning config from: {tuning_resolution.config_file}")
        except Exception as e:
            console.print(f"[red]❌ Failed to load tuning configuration: {e}[/red]")
            if logger:
                logger.error(f"Failed to load tuning configuration: {e}", exc_info=True)
            ctx.exit(1)

    elif tuning_resolution.source == TuningSource.BASELINE:
        # No tuning: disable all constraints for true baseline
        loaded_unified_config = UnifiedTuningConfiguration()
        loaded_unified_config.primary_keys.enabled = False
        loaded_unified_config.foreign_keys.enabled = False
        if logger:
            logger.debug("No tuning mode: all constraints disabled for baseline")

    elif tuning_resolution.source == TuningSource.FALLBACK:
        # Fallback to basic constraints OR launch tuning wizard
        if not non_interactive:
            console.print("\n[bold cyan]Tuning Configuration[/bold cyan]")

            if Confirm.ask("Would you like to configure tuning options?", default=False):
                # Launch tuning wizard
                from benchbox.cli.tuning import run_tuning_wizard

                profiler = SystemProfiler()
                system_profile = profiler.get_system_profile()

                loaded_unified_config = run_tuning_wizard(
                    benchmark=benchmark,
                    platform=platform,
                    system_profile=system_profile,
                    interactive=True,
                )
                console.print("[green]✅ Tuning configuration completed[/green]")
            else:
                loaded_unified_config = UnifiedTuningConfiguration()
        else:
            loaded_unified_config = UnifiedTuningConfiguration()

        if logger:
            logger.debug("Using basic constraints-only configuration (fallback)")

    else:
        # Smart defaults or other modes - use basic config as baseline
        loaded_unified_config = UnifiedTuningConfiguration()
        if logger:
            logger.debug(f"Using basic unified config for mode: {tuning_resolution.mode.value}")

    try:
        _apply_platform_optimization_overrides(
            loaded_unified_config,
            sorted_ingestion_mode=sorted_ingestion_mode,
            sorted_ingestion_method=sorted_ingestion_method,
            parsed_platform_options=parsed_platform_options,
        )
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        ctx.exit(1)

    data_organization_payload = _build_data_organization_from_tuning(loaded_unified_config)
    try:
        data_organization_payload = _resolve_data_organization_payload(benchmark, presort, data_organization_payload)
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        ctx.exit(1)
    if data_organization_payload is None:
        os.environ.pop(DATA_ORGANIZATION_ENV, None)
    else:
        os.environ[DATA_ORGANIZATION_ENV] = json.dumps(data_organization_payload)

    # Apply DataFrame tuning configuration (for DataFrame platforms)
    # Uses the unified --tuning parameter
    df_tuning_config = None
    if resolved_mode == "dataframe" and tuning_enabled:
        from benchbox.core.dataframe.tuning import (
            get_smart_defaults,
            load_dataframe_tuning,
            validate_dataframe_tuning,
        )

        if use_auto_tuning:
            # 'auto' mode: Use smart defaults based on system profile
            df_tuning_config = get_smart_defaults(platform)
            if not quiet:
                console.print("[green]✅ Using auto-detected DataFrame tuning configuration[/green]")
            if logger:
                logger.debug(f"Using smart defaults for DataFrame tuning: {df_tuning_config.get_summary()}")
        elif tuning_config_file:
            # Load DataFrame tuning from file
            try:
                df_tuning_config = load_dataframe_tuning(tuning_config_file)
                if not quiet:
                    console.print(f"[green]✅ Loaded DataFrame tuning configuration from {tuning_config_file}[/green]")
                if logger:
                    logger.debug(f"Loaded DataFrame tuning config from: {tuning_config_file}")

                # Validate the configuration
                issues = validate_dataframe_tuning(df_tuning_config, platform)
                for issue in issues:
                    if issue.level.value == "error":
                        console.print(f"[red]❌ DataFrame tuning error: {issue}[/red]")
                        ctx.exit(1)
                    elif issue.level.value == "warning":
                        console.print(f"[yellow]⚠️ DataFrame tuning warning: {issue}[/yellow]")
            except Exception as e:
                console.print(f"[red]❌ Failed to load DataFrame tuning configuration: {e}[/red]")
                if logger:
                    logger.error(f"Failed to load DataFrame tuning configuration: {e}", exc_info=True)
                ctx.exit(1)
        else:
            # 'tuned' mode without config file: use smart defaults
            df_tuning_config = get_smart_defaults(platform)
            if not quiet:
                console.print("[green]✅ Using optimized DataFrame tuning configuration[/green]")
            if logger:
                logger.debug(f"Using smart defaults for 'tuned' mode: {df_tuning_config.get_summary()}")

    # Process compression settings
    if no_compression:
        # Explicit opt-out of compression
        compress_data = False
        if compression_type != "none":
            compression_type = "none"  # Override compression type when opting out
        if logger:
            logger.debug("Compression disabled via --no-compression flag")
    else:
        # Check for environment variable override
        env_no_compression = os.getenv("BENCHBOX_NO_COMPRESSION", "").lower() in [
            "true",
            "1",
            "yes",
            "on",
        ]
        if env_no_compression:
            compress_data = False
            compression_type = "none"
            if logger:
                logger.debug("Compression disabled via BENCHBOX_NO_COMPRESSION environment variable")
        elif compression_cli_set:
            # Explicit CLI compression always takes precedence over config defaults.
            compress_data = comp_config.enabled
            if logger:
                logger.debug(
                    "Compression set via CLI: enabled=%s, type=%s, level=%s",
                    compress_data,
                    compression_type,
                    compression_level,
                )
        else:
            # Use configuration defaults or CLI arguments
            config_compression_enabled = config.get("output.compression.enabled", False)
            compress_data = config_compression_enabled

            # Use configuration defaults when CLI compression is not explicitly set.
            compression_type = config.get("output.compression.type", "zstd")
            compression_level = config.get("output.compression.level", None)

            if logger:
                logger.debug(f"Compression enabled: type={compression_type}, level={compression_level}")

    if compress_data and compression_type != "none":
        manager = CompressionManager()
        available = manager.get_available_compressors()
        if compression_type not in available:
            warning = (
                f"[yellow]⚠️ Compression type '{compression_type}' is not available. "
                "Falling back to uncompressed output.[/yellow]"
            )
            console.print(warning)
            if logger:
                logger.warning(
                    "Compression type %s unavailable (available: %s). Falling back to no compression.",
                    compression_type,
                    available,
                )
            compress_data = False
            compression_type = "none"
            compression_level = None

    if not compress_data:
        compression_type = "none"
        compression_level = None

    # Validate output directory (including cloud storage)
    if output:
        try:
            ValidationRules.validate_output_directory(output)
            if is_cloud_path(output):
                console.print(f"\n[green]✅[/green] Cloud storage output validated: {output}")
            else:
                console.print(f"\n[green]✅[/green] Output directory validated: {output}")
        except (ValidationError, CloudStorageError) as e:
            error_handler = create_error_handler(console)
            context = ErrorContext(
                operation="output_validation",
                stage="pre_execution",
                user_input={"output_path": output},
            )
            error_handler.handle_error(e, context)
            ctx.exit(1)

    # Initialize configs — assigned in all live-run paths below; asserted non-None before use.
    database_config: DatabaseConfig | None = None
    benchmark_config: BenchmarkConfig | None = None

    # Handle dry run mode
    if dry_run:
        if logger:
            logger.debug(f"Entering dry run mode, output directory: {dry_run}")

        # For generate-only (data-only) mode, only benchmark is required
        if test_execution_type == "data_only":
            if not benchmark:
                console.print("[red]❌ Dry run with --phases generate requires --benchmark parameter[/red]")
                if logger:
                    logger.error("Dry run with --phases generate requires --benchmark parameter")
                ctx.exit(1)
            if platform:
                console.print("[yellow]⚠️️  Note: Platform parameter ignored in data-only dry run[/yellow]")
        else:
            # For other modes, both platform and benchmark are required
            if not (platform and benchmark):
                console.print("[red]❌ Dry run mode requires --platform and --benchmark parameters[/red]")
                console.print("[yellow]Use --phases generate if you only want to preview data generation[/yellow]")
                if logger:
                    logger.error("Dry run mode requires --platform and --benchmark parameters")
                ctx.exit(1)

        # Execute dry run instead of actual benchmark
        from benchbox.cli.dryrun import DryRunExecutor

        # Validate scale factor for dry run
        if logger:
            logger.debug(f"Validating scale factor for dry run: {scale}")
        if scale >= 1 and scale != int(scale):
            console.print(f"[red]❌ Scale factors >= 1 must be whole integers. Got: {scale}[/red]")
            console.print("[yellow]Use values like 1, 2, 10, etc. for large scale factors[/yellow]")
            console.print("[yellow]Use values like 0.1, 0.01, 0.001, etc. for small scale factors[/yellow]")
            if logger:
                logger.error(f"Invalid scale factor for dry run: {scale}")
            ctx.exit(1)

        # Create configurations for dry run
        if logger:
            logger.debug("Creating database and benchmark managers for dry run")
        db_manager = DatabaseManager()
        db_manager.set_verbosity(verbosity_settings)
        bench_manager = BenchmarkManager()
        bench_manager.set_verbosity(verbosity_settings)

        # Validate benchmark exists
        if logger:
            logger.debug(f"Validating benchmark '{benchmark}' exists")
        if benchmark not in bench_manager.benchmarks:
            console.print(f"[red]❌ Unknown benchmark: {benchmark}[/red]")
            console.print(f"Available benchmarks: {', '.join(bench_manager.benchmarks.keys())}")
            if logger:
                logger.error(f"Unknown benchmark: {benchmark}. Available: {list(bench_manager.benchmarks.keys())}")
            ctx.exit(1)

        # Create database config (skip for data-only mode)
        if execution_mode == "data_only":
            database_config = None
            if logger:
                logger.debug("Skipping database configuration for data-only dry run")
        else:
            if logger:
                logger.debug(f"Creating database configuration for: {platform}")
            # Type checker doesn't understand that platform_key is non-None here due to validation above
            assert platform_key is not None
            overrides = {
                **verbosity_payload,
                "tuning_enabled": tuning_enabled,
                "force_upload": bool(force_upload),
                "capture_plans": capture_plans,
                "strict_plan_capture": strict_plan_capture,
                "plan_sampling_rate": plan_sampling_rate,
                "plan_first_n": plan_first_n,
                "plan_queries": plan_queries,
                "execution_mode": resolved_mode,
            }
            if loaded_unified_config:
                overrides["unified_tuning_configuration"] = loaded_unified_config
            if df_tuning_config:
                overrides["df_tuning_config"] = df_tuning_config
            try:
                database_config = db_manager.create_config(
                    platform_key,
                    dict(parsed_platform_options),
                    overrides,
                )
            except PlatformOptionError as exc:
                console.print(f"[red]❌ {exc}[/red]")
                if logger:
                    logger.error(f"Database configuration failed: {exc}")
                ctx.exit(1)
            except RuntimeError as exc:
                # Driver not installed - acceptable for dry run, use minimal config
                if logger:
                    logger.debug(f"Driver not installed, using minimal config for dry run: {exc}")
                database_config = None
            if logger:
                logger.debug("Database configuration created for dry run")

        # Create benchmark config
        if logger:
            logger.debug(f"Creating benchmark configuration for: {benchmark}")
        benchmark_info = bench_manager.benchmarks[benchmark]

        # Validate scale factor against benchmark requirements (e.g., TPC-DS requires SF >= 1.0)
        try:
            bench_manager.validate_scale_factor(benchmark, scale)
        except ValueError as e:
            console.print(f"[red]❌ {e}[/red]")
            if logger:
                logger.error(f"Scale factor validation failed: {e}")
            ctx.exit(1)

        benchmark_config = BenchmarkConfig(
            name=benchmark,
            display_name=benchmark_info["display_name"],
            scale_factor=scale,
            queries=queries_to_run,
            compress_data=compress_data,
            compression_type=compression_type,
            compression_level=compression_level,
            test_execution_type=test_execution_type,  # Required for runner mode detection
            capture_plans=capture_plans,
            strict_plan_capture=strict_plan_capture,
            options={
                **verbosity_payload,
                "estimated_time_range": benchmark_info["estimated_time_range"],
                "tuning_enabled": tuning_enabled,
                "table_mode": table_mode,
                "unified_tuning_configuration": loaded_unified_config,
                **({"data_organization": data_organization_payload} if data_organization_payload is not None else {}),
                "force_regenerate": force_regenerate,
                "enable_preflight_validation": enable_preflight_validation,
                "enable_postgen_manifest_validation": enable_postgen_manifest_validation,
                "enable_postload_validation": enable_postload_validation,
                "ignore_memory_warnings": ignore_memory_warnings,
                **({"cache_dir": str(Path.home() / ".benchbox" / "datagen")} if global_cache else {}),
                **({"seed": seed} if seed is not None else {}),
                **({"validation_mode": validation_mode} if validation_mode is not None else {}),
                **({"table_format": table_format_value} if table_format_value is not None else {}),
                **(
                    {"table_format_compression": table_format_compression}
                    if table_format_compression is not None
                    else {}
                ),
                **(
                    {"table_format_partition_cols": list(table_format_partition_cols)}
                    if table_format_partition_cols
                    else {}
                ),
                **({"presort": presort} if presort is not None else {}),
            },
        )

        if logger:
            logger.debug(f"Benchmark config created: {benchmark_config}")

        # Get system profile
        if logger:
            logger.debug("Getting system profile for dry run")
        profiler = SystemProfiler()
        system_profile = profiler.get_system_profile()

        if logger:
            logger.debug(
                f"System profile: CPU cores={system_profile.cpu_cores_logical}, Memory={system_profile.memory_total_gb}GB"
            )

        # Execute dry run
        if logger:
            logger.debug(f"Executing dry run with output directory: {dry_run}")
        dry_run_executor = DryRunExecutor(output_dir=dry_run)
        dry_run_result = dry_run_executor.execute_dry_run(benchmark_config, system_profile, database_config)

        if logger:
            logger.debug("Dry run completed")

        # Display results
        dry_run_executor.display_dry_run_results(dry_run_result)

        # Save results to files
        filename_prefix = f"{benchmark}_{'data-only' if execution_mode == 'data_only' else platform}"
        saved_files = dry_run_executor.save_dry_run_results(dry_run_result, filename_prefix)

        console.print("\n[green]✅ Dry run completed[/green]")
        if test_execution_type == "data_only":
            console.print(f"[dim]Data generation preview for {benchmark} at scale {scale}[/dim]")
        else:
            console.print(
                f"[dim]Configuration and queries previewed for {benchmark} on {platform} at scale {scale}[/dim]"
            )

        # Print paths of saved files
        if saved_files:
            console.print("\n[dim]Output files saved to:[/dim]")
            for file_type, file_path in saved_files.items():
                console.print(f"  [cyan]{file_path}[/cyan]")

        return

    # Handle direct non-interactive SQL/DataFrame execution arguments
    if test_execution_type not in {"data_only", "load_only"} and platform and benchmark:
        if logger:
            logger.debug(f"Entering direct execution mode: platform={platform}, benchmark={benchmark}")

        # Validate scale factor: if >= 1, must be whole integer
        if logger:
            logger.debug(f"Validating scale factor for direct execution: {scale}")
        if scale >= 1 and scale != int(scale):
            console.print(f"[red]❌ Scale factors >= 1 must be whole integers. Got: {scale}[/red]")
            console.print("[yellow]Use values like 1, 2, 10, etc. for large scale factors[/yellow]")
            console.print("[yellow]Use values like 0.1, 0.01, 0.001, etc. for small scale factors[/yellow]")
            if logger:
                logger.error(f"Invalid scale factor for direct execution: {scale}")
            return

        if logger:
            logger.info(f"Starting direct benchmark execution: {benchmark} on {platform} at scale {scale}")

        # Create configuration objects for direct execution
        if logger:
            logger.debug("Creating database and benchmark managers for direct execution")
        db_manager = DatabaseManager()
        db_manager.set_verbosity(verbosity_settings)
        bench_manager = BenchmarkManager()
        bench_manager.set_verbosity(verbosity_settings)

        # Create database config
        # Type checker doesn't understand that platform_key is non-None here due to validation above
        assert platform_key is not None
        overrides = {
            **verbosity_payload,
            "force_recreate": force_regenerate,
            "show_query_plans": show_query_plans,
            "tuning_enabled": tuning_enabled,
            "force_upload": bool(force_upload),
            "capture_plans": capture_plans,
            "strict_plan_capture": strict_plan_capture,
            "plan_sampling_rate": plan_sampling_rate,
            "plan_first_n": plan_first_n,
            "plan_queries": plan_queries,
            "execution_mode": resolved_mode,
        }
        if loaded_unified_config:
            overrides["unified_tuning_configuration"] = loaded_unified_config
        if df_tuning_config:
            overrides["df_tuning_config"] = df_tuning_config
        try:
            database_config = db_manager.create_config(
                platform_key,
                dict(parsed_platform_options),
                overrides,
            )
        except PlatformOptionError as exc:
            console.print(f"[red]❌ {exc}[/red]")
            if logger:
                logger.error(f"Database configuration failed: {exc}")
            ctx.exit(1)

        # Emit the run announcement now that driver version is resolved
        _driver_version = database_config.driver_version_actual or database_config.driver_version_resolved
        _mode_tag = " \\[external]" if table_mode == "external" else ""
        if _driver_version:
            console.print(f"Running {benchmark} on {platform} at scale {scale} \\[driver {_driver_version}]{_mode_tag}")
        else:
            console.print(f"Running {benchmark} on {platform} at scale {scale}{_mode_tag}")

        # Validate benchmark exists
        if benchmark not in bench_manager.benchmarks:
            console.print(f"[red]❌ Unknown benchmark: {benchmark}[/red]")
            console.print(f"Available benchmarks: {', '.join(bench_manager.benchmarks.keys())}")
            return

        benchmark_info = bench_manager.benchmarks[benchmark]

        # Validate scale factor against benchmark requirements (e.g., TPC-DS requires SF >= 1.0)
        try:
            bench_manager.validate_scale_factor(benchmark, scale)
        except ValueError as e:
            console.print(f"[red]❌ {e}[/red]")
            if logger:
                logger.error(f"Scale factor validation failed: {e}")
            ctx.exit(1)

        # Create benchmark config
        benchmark_config = BenchmarkConfig(
            name=benchmark,
            display_name=benchmark_info["display_name"],
            scale_factor=scale,
            queries=queries_to_run,
            compress_data=compress_data,
            compression_type=compression_type,
            compression_level=compression_level,
            test_execution_type=test_execution_type,
            capture_plans=capture_plans,
            strict_plan_capture=strict_plan_capture,
            options={
                **verbosity_payload,
                "estimated_time_range": benchmark_info["estimated_time_range"],
                "tuning_enabled": tuning_enabled,
                "table_mode": table_mode,
                "unified_tuning_configuration": loaded_unified_config,
                **({"data_organization": data_organization_payload} if data_organization_payload is not None else {}),
                "force_regenerate": force_regenerate,
                "enable_preflight_validation": enable_preflight_validation,
                "enable_postgen_manifest_validation": enable_postgen_manifest_validation,
                "enable_postload_validation": enable_postload_validation,
                "seed": seed,
                "ignore_memory_warnings": ignore_memory_warnings,
                **({"cache_dir": str(Path.home() / ".benchbox" / "datagen")} if global_cache else {}),
                **({"table_format": table_format_value} if table_format_value is not None else {}),
                **(
                    {"table_format_compression": table_format_compression}
                    if table_format_compression is not None
                    else {}
                ),
                **(
                    {"table_format_partition_cols": list(table_format_partition_cols)}
                    if table_format_partition_cols
                    else {}
                ),
                **({"presort": presort} if presort is not None else {}),
            },
        )

        # Get system profile for execution
        profiler = SystemProfiler()
        system_profile = profiler.get_system_profile()

        # Build execution context for reproducibility
        execution_context = _build_execution_context(
            phases_to_run=phases_to_run,
            seed=seed,
            compression=comp_config,
            mode=mode,
            official=official,
            validation=val_config,
            force=force_config,
            queries_to_run=queries_to_run,
            capture_plans=capture_plans,
            strict_plan_capture=strict_plan_capture,
            non_interactive=non_interactive,
            tuning=tuning,
        )

        # Execute benchmark using orchestrator
        orchestrator = BenchmarkOrchestrator()
        orchestrator.set_verbosity(verbosity_settings)

        # Set custom output directory if provided (supports cloud paths)
        if output:
            normalized_output = normalize_output_root(output, benchmark, scale)
            # Type checker doesn't understand normalize_output_root returns str when input is truthy
            assert normalized_output is not None
            orchestrator.set_custom_output_dir(normalized_output)

        result = _execute_orchestrated_run(
            orchestrator,
            benchmark_config,
            system_profile,
            database_config,
            phases_to_run,
            quiet=bool(quiet),
            no_progress=bool(no_progress),
            no_monitoring=bool(no_monitoring),
            execution_context=execution_context,
        )

        # Export results if successful
        if result.validation_status not in ["FAILED", "INTERRUPTED"]:
            if not quiet:
                console.print("\n[bold]Exporting results...[/bold]")

            exported_files = _export_orchestrated_result(
                orchestrator=orchestrator,
                result=result,
                benchmark=benchmark,
                scale=scale,
                platform_label=platform.lower(),
                mode_label=resolved_mode,
                quiet=bool(quiet),
                export_formats=["json"],
            )

            if quiet:
                for format_name, filepath in exported_files.items():
                    click.echo(filepath)
            else:
                console.print(f"\n[green]✅ Benchmark completed: {result.validation_status}[/green]")
                for format_name, filepath in exported_files.items():
                    console.print(f"{format_name.upper()}: [dim]{filepath}[/dim]")

            _render_post_run_charts(result, console, quiet)

            # Optional post-run publish
            if publish:
                json_bundle = exported_files.get("json")
                if json_bundle:
                    from benchbox.cli.commands.publish import publish_bundle

                    if not quiet:
                        console.print("\n[bold]Publishing result bundle...[/bold]")
                    publish_bundle(
                        source_bundle=json_bundle,
                        target=publish_target,
                        label=publish_label,
                        quiet=bool(quiet),
                    )

            # Save configuration for quick restart
            from benchbox.cli.preferences import save_last_run_config

            save_last_run_config(
                database=platform,
                benchmark=benchmark,
                scale=scale,
                tuning_mode=tuning,
                phases=phases_to_run,
                concurrency=benchmark_config.concurrency,
                compress_data=compress_data,
                compression_type=compression_type,
                compression_level=compression_level,
                test_execution_type=test_execution_type,
                seed=seed,
                output=output,
                additional_options={"table_mode": table_mode},
            )
        else:
            console.print(f"\n[red]❌ Benchmark failed: {result.validation_status}[/red]")
            ctx.exit(1)

        return

    # Handle data-only and load-only modes
    if test_execution_type in ["data_only", "load_only"]:
        if logger:
            logger.debug(f"Entering {execution_mode} mode")

        # Initialize database_config (set to None for data_only, created below for load_only)
        database_config: DatabaseConfig | None = None

        # For data-only mode, platform is not required
        if test_execution_type == "data_only":
            if platform:
                if not quiet:
                    console.print("[yellow]⚠️️  Note: Platform parameter ignored in data-only mode[/yellow]")
            # database_config stays None for data_only mode
        else:
            # For load-only mode, platform is required
            if not platform:
                console.print("[red]❌ Error: --platform parameter is required for --phases load[/red]")
                if logger:
                    logger.error("Platform parameter is required for --phases load")
                ctx.exit(1)

        # Benchmark is always required
        if not benchmark:
            console.print("[red]❌ Error: --benchmark parameter is required[/red]")
            if logger:
                logger.error("Benchmark parameter is required")
            return

        # Create managers
        db_manager = DatabaseManager()
        db_manager.set_verbosity(verbosity_settings)
        bench_manager = BenchmarkManager()
        bench_manager.set_verbosity(verbosity_settings)

        # Validate benchmark exists
        if benchmark not in bench_manager.benchmarks:
            console.print(f"[red]❌ Unknown benchmark: {benchmark}[/red]")
            console.print(f"Available benchmarks: {', '.join(bench_manager.benchmarks.keys())}")
            if logger:
                logger.error(f"Unknown benchmark: {benchmark}. Available: {list(bench_manager.benchmarks.keys())}")
            return

        # Create database config for load-only mode
        if execution_mode == "load_only":
            # Type checker doesn't understand that platform_key is non-None here due to validation above
            assert platform_key is not None
            overrides = {
                **verbosity_payload,
                "force_recreate": force_regenerate,
                "tuning_enabled": tuning_enabled,
                "force_upload": bool(force_upload),
                "capture_plans": capture_plans,
                "strict_plan_capture": strict_plan_capture,
                "plan_sampling_rate": plan_sampling_rate,
                "plan_first_n": plan_first_n,
                "plan_queries": plan_queries,
                "execution_mode": resolved_mode,
            }
            if loaded_unified_config:
                overrides["unified_tuning_configuration"] = loaded_unified_config
            if df_tuning_config:
                overrides["df_tuning_config"] = df_tuning_config
            try:
                database_config = db_manager.create_config(
                    platform_key,
                    dict(parsed_platform_options),
                    overrides,
                )
            except PlatformOptionError as exc:
                console.print(f"[red]❌ {exc}[/red]")
                if logger:
                    logger.error(f"Database configuration failed: {exc}")
                ctx.exit(1)

        # Create benchmark config
        benchmark_info = bench_manager.benchmarks[benchmark]

        # Validate scale factor against benchmark requirements (e.g., TPC-DS requires SF >= 1.0)
        try:
            bench_manager.validate_scale_factor(benchmark, scale)
        except ValueError as e:
            console.print(f"[red]❌ {e}[/red]")
            if logger:
                logger.error(f"Scale factor validation failed: {e}")
            ctx.exit(1)

        benchmark_config = BenchmarkConfig(
            name=benchmark,
            display_name=benchmark_info["display_name"],
            scale_factor=scale,
            queries=queries_to_run,
            compress_data=compress_data,
            compression_type=compression_type,
            compression_level=compression_level,
            test_execution_type=test_execution_type,  # Required for runner to enter load_only/data_only mode
            capture_plans=capture_plans,
            strict_plan_capture=strict_plan_capture,
            options={
                **verbosity_payload,
                "estimated_time_range": benchmark_info["estimated_time_range"],
                "table_mode": table_mode,
                "unified_tuning_configuration": loaded_unified_config,
                **({"data_organization": data_organization_payload} if data_organization_payload is not None else {}),
                "force_regenerate": force_regenerate,
                "enable_preflight_validation": enable_preflight_validation,
                "enable_postgen_manifest_validation": enable_postgen_manifest_validation,
                "enable_postload_validation": enable_postload_validation,
                "seed": seed,
                "ignore_memory_warnings": ignore_memory_warnings,
                **({"cache_dir": str(Path.home() / ".benchbox" / "datagen")} if global_cache else {}),
                **({"table_format": table_format_value} if table_format_value is not None else {}),
                **(
                    {"table_format_compression": table_format_compression}
                    if table_format_compression is not None
                    else {}
                ),
                **(
                    {"table_format_partition_cols": list(table_format_partition_cols)}
                    if table_format_partition_cols
                    else {}
                ),
                **({"presort": presort} if presort is not None else {}),
            },
        )

        # Get system profile
        profiler = SystemProfiler()
        system_profile = profiler.get_system_profile()

        # Build execution context for reproducibility
        execution_context = _build_execution_context(
            phases_to_run=phases_to_run,
            seed=seed,
            compression=comp_config,
            mode=mode,
            official=official,
            validation=val_config,
            force=force_config,
            queries_to_run=queries_to_run,
            capture_plans=capture_plans,
            strict_plan_capture=strict_plan_capture,
            non_interactive=non_interactive,
            tuning=tuning,
        )

        # Execute using orchestrator
        orchestrator = BenchmarkOrchestrator()
        orchestrator.set_verbosity(verbosity_settings)

        # Set custom output directory if provided
        if output:
            normalized_output = normalize_output_root(output, benchmark, scale)
            # Type checker doesn't understand normalize_output_root returns str when input is truthy
            assert normalized_output is not None
            orchestrator.set_custom_output_dir(normalized_output)

        if logger:
            logger.debug(
                f"Executing {'data-only' if execution_mode == 'data_only' else 'load-only'} mode with orchestrator"
            )

        result = _execute_orchestrated_run(
            orchestrator,
            benchmark_config,
            system_profile,
            database_config,
            phases_to_run,
            quiet=bool(quiet),
            no_progress=bool(no_progress),
            no_monitoring=bool(no_monitoring),
            execution_context=execution_context,
        )

        # Export results if successful
        if result.validation_status not in ["FAILED", "INTERRUPTED"]:
            if not quiet:
                console.print("\n[bold]Exporting results...[/bold]")
            platform_label = platform.lower() if platform else "unknown"
            mode_label = "data_only" if execution_mode == "data_only" else resolved_mode
            exported_files = _export_orchestrated_result(
                orchestrator=orchestrator,
                result=result,
                benchmark=benchmark,
                scale=scale,
                platform_label=platform_label,
                mode_label=mode_label,
                quiet=bool(quiet),
                export_formats=["json"],
            )

            # Determine actual status from execution phases, not validation status
            if execution_mode == "data_only":
                operation_status = "COMPLETED"  # Data generation always completes if no error
                operation_name = "Data generation"
            else:
                # For load-only mode, check data loading phase status
                operation_name = "Data loading"
                if hasattr(result, "execution_phases") and result.execution_phases:
                    if hasattr(result.execution_phases, "setup") and result.execution_phases.setup:
                        if (
                            hasattr(result.execution_phases.setup, "data_loading")
                            and result.execution_phases.setup.data_loading
                        ):
                            operation_status = result.execution_phases.setup.data_loading.status
                        else:
                            operation_status = "NOT_RUN"
                    else:
                        operation_status = "NOT_RUN"
                else:
                    operation_status = "NOT_RUN"

            if quiet:
                for format_name, filepath in exported_files.items():
                    click.echo(filepath)
            else:
                console.print(f"\n[green]✅ {operation_name} completed: {operation_status}[/green]")
                for format_name, filepath in exported_files.items():
                    console.print(f"{format_name.upper()}: {filepath}")

            # Save configuration for quick restart
            from benchbox.cli.preferences import save_last_run_config

            save_last_run_config(
                database=platform if platform else "none",
                benchmark=benchmark,
                scale=scale,
                tuning_mode=tuning,
                phases=phases_to_run,
                concurrency=benchmark_config.concurrency,
                compress_data=compress_data,
                compression_type=compression_type,
                compression_level=compression_level,
                test_execution_type=test_execution_type,
                seed=seed,
                output=output,
                additional_options={"table_mode": table_mode},
            )
        else:
            console.print(
                f"\n[red]❌ {'Data generation' if execution_mode == 'data_only' else 'Data loading'} failed: {result.validation_status}[/red]"
            )
            if result.validation_details:
                console.print(f"Error details: {result.validation_details}")
            ctx.exit(1)

        return

    # Interactive mode with guidance
    # Require TTY for interactive mode
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        console.print("[red]❌ Error: Interactive mode requires a terminal (TTY)[/red]")
        console.print(
            "[yellow]Please provide --platform and --benchmark parameters for non-interactive execution[/yellow]"
        )
        console.print("[dim]Or use --non-interactive flag with all required parameters[/dim]")
        if logger:
            logger.error("Interactive mode attempted in non-TTY environment")
        ctx.exit(2)

    if logger:
        logger.debug("Entering interactive mode")

    # Check for first-time user and offer onboarding
    from benchbox.cli.onboarding import check_and_run_first_time_setup

    is_first_run = check_and_run_first_time_setup()

    if not is_first_run:
        # Regular interactive setup for returning users
        console.print("\n[bold blue]BenchBox Interactive Setup[/bold blue]")
        console.print("We'll guide you through selecting the optimal configuration for your system.\n")

    console.print("[bold]Step 1 of 6:[/bold] [cyan]System Analysis[/cyan]")
    console.print("Analyzing your system resources to provide smart recommendations...")
    if logger:
        logger.debug("Starting system profiling for interactive mode")
    profiler = SystemProfiler()
    system_profile = profiler.get_system_profile()
    profiler.display_profile(system_profile)

    if logger:
        logger.debug(f"Interactive mode system profile: {system_profile}")

    # Provide intelligent system guidance
    display_system_recommendations(system_profile)

    # Check for last run configuration
    from benchbox.cli.preferences import format_last_run_summary, load_last_run_config

    last_run = load_last_run_config()
    use_last_run = False

    # Only offer quick restart in interactive TTY mode
    if last_run and sys.stdin.isatty() and sys.stdout.isatty():
        console.print("\n[bold cyan]Quick Restart[/bold cyan]")
        summary = format_last_run_summary(last_run)
        console.print(f"[dim]Last run: {summary}[/dim]")

        use_last_run = Confirm.ask("Reuse this configuration?", default=False)

        if use_last_run:
            # Use last run configuration
            platform = last_run["database"]
            benchmark = last_run["benchmark"]
            scale = last_run["scale"]
            tuning = last_run.get("tuning_mode", "tuned")
            phases = last_run.get("phases", ["load", "power"])
            # Restore output location (critical for cloud platforms)
            if not output:
                output = last_run.get("output")
            # Preserve explicit CLI --table-mode over saved quick-restart preference.
            if not table_mode_cli_supplied:
                table_mode = str(last_run.get("table_mode", table_mode) or "native").lower()
            if table_mode == "external" and tuning.strip().lower() == "tuned":
                _reject_external_tuned(console, logger, ctx)

            console.print("[green]✓ Using saved configuration[/green]")

            # Create configs from saved data
            # Note: DatabaseManager and BenchmarkManager are already imported at module level

            # Database config - resolve mode if not already set
            if resolved_mode is None:
                caps = PlatformRegistry.get_platform_capabilities(platform)
                if caps is not None:
                    resolved_mode = mode if mode is not None else caps.default_mode
                else:
                    resolved_mode = "sql"  # Default fallback
            db_manager = DatabaseManager()
            db_manager.set_verbosity(verbosity_settings)
            database_config = db_manager.create_config(
                platform=platform, runtime_overrides={"execution_mode": resolved_mode}
            )

            # Benchmark config - reconstruct from saved data and benchmark metadata
            bench_manager = BenchmarkManager()
            bench_manager.set_verbosity(verbosity_settings)
            benchmark_info = bench_manager.benchmarks.get(benchmark, {})

            # Validate scale factor against benchmark requirements (e.g., TPC-DS requires SF >= 1.0)
            try:
                bench_manager.validate_scale_factor(benchmark, scale)
            except ValueError as e:
                console.print(f"[red]❌ {e}[/red]")
                if logger:
                    logger.error(f"Scale factor validation failed: {e}")
                ctx.exit(1)

            benchmark_config = BenchmarkConfig(
                name=benchmark,
                display_name=benchmark_info.get("display_name", benchmark.upper()),
                scale_factor=scale,
                queries=queries_to_run,
                concurrency=last_run.get("concurrency", 1),
                compress_data=last_run.get("compress_data", True),
                compression_type=last_run.get("compression_type", "zstd"),
                compression_level=last_run.get("compression_level", None),
                test_execution_type=last_run.get("test_execution_type", "power"),
                capture_plans=capture_plans,
                strict_plan_capture=strict_plan_capture,
                options={
                    "estimated_time_range": benchmark_info.get("estimated_time_range", (0, 60)),
                    "table_mode": table_mode,
                    "complexity": benchmark_info.get("complexity", "medium"),
                    **(
                        {"data_organization": data_organization_payload}
                        if data_organization_payload is not None
                        else {}
                    ),
                    "force_regenerate": force_regenerate,
                    "seed": seed,
                    "ignore_memory_warnings": ignore_memory_warnings,
                    **({"cache_dir": str(Path.home() / ".benchbox" / "datagen")} if global_cache else {}),
                    **({"table_format": table_format_value} if table_format_value is not None else {}),
                    **(
                        {"table_format_compression": table_format_compression}
                        if table_format_compression is not None
                        else {}
                    ),
                    **(
                        {"table_format_partition_cols": list(table_format_partition_cols)}
                        if table_format_partition_cols
                        else {}
                    ),
                    **({"presort": presort} if presort is not None else {}),
                },
            )

            # Add verbosity settings
            benchmark_config.options.update(verbosity_settings.to_config())

            console.print()

    if not use_last_run:
        # Normal interactive flow

        # Step 2: Execution Style Selection (new step to filter platforms)
        console.print("\n[bold]Step 2 of 6:[/bold] [cyan]Execution Style[/cyan]")
        console.print("Choose how you want to run benchmarks...")
        db_manager = DatabaseManager()
        db_manager.set_verbosity(verbosity_settings)
        style_filter = db_manager.prompt_execution_style()

        # Step 3: Database Selection (was Step 2)
        console.print("\n[bold]Step 3 of 6:[/bold] [cyan]Database Selection[/cyan]")
        console.print("Selecting the best database for your benchmarks...")
        database_config = db_manager.select_database(style_filter=style_filter)

        # Resolve execution mode for the selected platform
        # Priority: CLI --mode > style_filter selection > platform default
        platform_type = database_config.type
        caps = PlatformRegistry.get_platform_capabilities(platform_type)
        if caps is not None:
            if mode is not None:
                # CLI --mode flag takes highest priority
                if not PlatformRegistry.supports_mode(platform_type, mode):
                    supported_modes = []
                    if caps.supports_sql:
                        supported_modes.append("sql")
                    if caps.supports_dataframe:
                        supported_modes.append("dataframe")
                    console.print(f"[red]❌ Platform '{platform_type}' does not support {mode} mode[/red]")
                    console.print(f"[yellow]Supported modes: {', '.join(supported_modes)}[/yellow]")
                    ctx.exit(1)
                resolved_mode = mode
                database_config.execution_mode = resolved_mode
            elif hasattr(database_config, "execution_mode") and database_config.execution_mode in ("sql", "dataframe"):
                # Style filter already set execution_mode - respect it
                resolved_mode = database_config.execution_mode
            else:
                # Fall back to platform default
                resolved_mode = caps.default_mode
                database_config.execution_mode = resolved_mode
        else:
            # Platform not in capabilities registry - use sql as default
            database_config.execution_mode = mode if mode is not None else "sql"

        # Immediately check platform requirements after selection
        if PlatformRegistry.requires_cloud_storage(database_config.type):
            # Check 1: Platform credentials (for cloud platforms)
            credentials_ok = check_and_setup_platform_credentials(
                platform=database_config.type,
                console_obj=console,
                interactive=not non_interactive,
            )

            if not credentials_ok:
                console.print(f"\n[red]❌ Cannot proceed without {database_config.type.upper()} credentials[/red]")
                console.print(f"\n[dim]To configure later: benchbox setup --platform {database_config.type}[/dim]")
                ctx.exit(1)

            # Check 2: Cloud output location (prompt early, before benchmark selection)
            if not output:
                # Load default from credentials FIRST
                default_output = None
                if PlatformRegistry.requires_cloud_storage(database_config.type):
                    from benchbox.security.credentials import CredentialManager

                    cred_manager = CredentialManager()
                    if cred_manager.has_credentials(database_config.type):
                        creds = cred_manager.get_platform_credentials(database_config.type)
                        default_output = creds.get("default_output_location") if creds else None

                # Then prompt with the default
                cloud_output_hint = prompt_cloud_output_location(
                    platform_name=database_config.type,
                    benchmark_name="your benchmark",  # Generic - don't have specific benchmark yet
                    scale_factor=scale or 1.0,  # Use CLI arg or default
                    non_interactive=non_interactive,
                    default_output=default_output,  # PASS THE DEFAULT
                )
                if cloud_output_hint:
                    output = cloud_output_hint

        console.print("\n[bold]Step 4 of 6:[/bold] [cyan]Benchmark Configuration[/cyan]")
        console.print("Configuring benchmark parameters optimized for your system...")
        bench_manager = BenchmarkManager()
        bench_manager.set_verbosity(verbosity_settings)
        benchmark_config = bench_manager.select_benchmark()

        # Step 3.5: Phase, Query, Official Mode, Seed, and Force Selection (interactive-only)
        if sys.stdin.isatty() and sys.stdout.isatty():
            from benchbox.cli.benchmarks import (
                prompt_capture_plans,
                prompt_force_regeneration,
                prompt_official_mode,
                prompt_output_location,
                prompt_phases,
                prompt_platform_options,
                prompt_query_subset,
                prompt_seed,
                prompt_table_format,
                prompt_table_mode,
                prompt_validation_mode,
                prompt_verbose_output,
            )

            # Table mode selection (unless explicitly provided on CLI)
            if not table_mode_cli_supplied:
                table_mode = prompt_table_mode(default_mode=table_mode)
                if table_mode == "external" and tuning.strip().lower() == "tuned":
                    _reject_external_tuned(console, logger, ctx)
            else:
                console.print(f"[dim]Using table mode from CLI: {table_mode}[/dim]")

            # Phase selection
            phases_to_run = prompt_phases(default_phases=phases_to_run)

            # Query subset selection (only if running query phases)
            if {"power", "standard"} & set(phases_to_run):
                bench_info = bench_manager.benchmarks.get(benchmark_config.name, {})
                num_queries = bench_info.get("num_queries", 0)
                if num_queries > 0:
                    queries_selected = prompt_query_subset(benchmark_config.name, num_queries)
                    if queries_selected:
                        benchmark_config.queries = queries_selected
                        queries_to_run = queries_selected

            # Official TPC mode (only for TPC benchmarks)
            if not official:  # Only prompt if not already set via CLI
                official, adjusted_scale = prompt_official_mode(benchmark_config.name, benchmark_config.scale_factor)
                if adjusted_scale is not None:
                    benchmark_config.scale_factor = adjusted_scale

            # Seed selection for reproducibility
            # In official mode, seed is required - prompt with different message
            if seed is None:
                if official:
                    console.print("\n[bold cyan]Seed (Required for Official Mode)[/bold cyan]")
                    console.print("[dim]Official TPC runs require a seed for reproducibility.[/dim]")
                    import random

                    from rich.prompt import IntPrompt

                    suggested_seed = random.randint(1, 999999)
                    seed = IntPrompt.ask("Enter seed value", default=suggested_seed)
                    console.print(f"[green]✓ Using seed: {seed}[/green]")
                else:
                    seed = prompt_seed()

                if seed is not None:
                    benchmark_config.options["seed"] = seed

            # Force regeneration option (only if not already set via CLI)
            if force is None:
                force_mode_result = prompt_force_regeneration()
                if force_mode_result is not None:
                    # Type narrowing: force_mode_result is now str
                    force_mode: str = force_mode_result
                    # Create ForceConfig to match CLI behavior
                    force = ForceConfig(
                        datagen=force_mode in ("all", "datagen"),
                        upload=force_mode in ("all", "upload"),
                    )

            # Validation mode selection (only if not already set via CLI)
            if validation is None:
                validation_selection = prompt_validation_mode()
                if validation_selection is not None:
                    validation_mode = validation_selection
                    benchmark_config.options["validation_mode"] = validation_mode

            # Capture plans option (only if not already set via CLI and platform supports it)
            if not capture_plans:
                capture_plans = prompt_capture_plans(database_config.type)
                if capture_plans:
                    benchmark_config.capture_plans = True

            # Output location for local platforms (cloud platforms already prompted above)
            if not output and not PlatformRegistry.requires_cloud_storage(database_config.type):
                custom_output = prompt_output_location(default_output="benchmark_runs/")
                if custom_output:
                    output = custom_output

            # Table format selection (only if not already set via CLI)
            if table_format_value is None:
                selected_format, selected_compression = prompt_table_format(database_config.type)
                if selected_format:
                    table_format_value = selected_format
                    if selected_compression:
                        table_format_compression = selected_compression

            # Verbose output selection (only if not already set via CLI)
            if verbosity_settings.level == 0:
                verbose_level = prompt_verbose_output()
                if verbose_level > 0:
                    verbosity_settings = VerbositySettings(
                        level=verbose_level,
                        verbose_enabled=verbose_level >= 1,
                        very_verbose=verbose_level >= 2,
                        quiet=False,
                    )
                    # Update managers with new verbosity
                    db_manager.set_verbosity(verbosity_settings)
                    bench_manager.set_verbosity(verbosity_settings)

            # Platform options (only if not already set via CLI)
            if not parsed_platform_options:
                platform_opts = prompt_platform_options(database_config.type)
                if platform_opts:
                    # Merge into database config options
                    if database_config.options is None:
                        database_config.options = {}
                    database_config.options.update(platform_opts)

        console.print("\n[bold]Step 5 of 6:[/bold] [cyan]Tuning Configuration[/cyan]")
        console.print("Configure database optimizations for best performance...")

        from benchbox.cli.tuning import run_tuning_wizard

        # Only prompt for tuning in TTY mode, otherwise use defaults
        if sys.stdin.isatty() and sys.stdout.isatty():
            if Confirm.ask("\nWould you like to configure tuning options?", default=True):
                loaded_unified_config = run_tuning_wizard(
                    benchmark=benchmark_config.name,
                    platform=database_config.type,
                    system_profile=system_profile,
                    interactive=True,
                )
                console.print("[green]✅ Tuning configuration completed[/green]")
            else:
                # User declined, use basic constraints-only configuration
                loaded_unified_config = UnifiedTuningConfiguration()
                console.print("[blue]Using basic constraints-only configuration[/blue]")
        else:
            # Non-TTY mode: use basic configuration
            loaded_unified_config = UnifiedTuningConfiguration()
            console.print("[dim]Non-interactive mode: using basic constraints-only configuration[/dim]")

        # Add tuning config to benchmark options
        benchmark_config.options["unified_tuning_configuration"] = loaded_unified_config
        benchmark_config.options["tuning_enabled"] = True
        # Update tuning variable so the CLI preview command includes --tuning
        tuning = "tuned"
        benchmark_config.options["seed"] = seed
        benchmark_config.options["table_mode"] = table_mode
        if df_tuning_config:
            benchmark_config.options["df_tuning_config"] = df_tuning_config

        # Propagate table format settings from interactive prompt
        if table_format_value is not None:
            benchmark_config.options["table_format"] = table_format_value
        if table_format_compression is not None:
            benchmark_config.options["table_format_compression"] = table_format_compression

    # Pre-flight validation: Ensure cloud platforms have output location
    # Note: In interactive mode, this should not be reached since prompt handles it
    # This is a safety check for edge cases and non-interactive mode
    assert database_config is not None  # Set by platform/benchmark selection above
    assert benchmark_config is not None  # Set by platform/benchmark selection above
    if PlatformRegistry.requires_cloud_storage(database_config.type) and not output:
        console.print()
        console.print("[red]❌ Error: Cloud platform requires --output parameter[/red]")
        console.print(
            f"[yellow]The {database_config.type.upper()} platform requires a cloud "
            f"storage location for data staging.[/yellow]"
        )

        examples = PlatformRegistry.get_cloud_path_examples(database_config.type)
        if examples:
            console.print("\n[bold]Example paths:[/bold]")
            for example in examples:
                console.print(f"  • {example}")

        console.print("\n[dim]Options:[/dim]")
        console.print(f"  1. Set default: benchbox setup --platform {database_config.type}")
        console.print(
            f"  2. Use --output flag: benchbox run --platform {database_config.type} "
            f"--benchmark {benchmark_config.name} --output <cloud-path>"
        )

        if logger:
            logger.error(f"Cloud platform {database_config.type} requires output parameter but none provided")

        ctx.exit(1)

    # Interactive preview before execution (only in TTY mode)
    if sys.stdin.isatty() and sys.stdout.isatty() and not non_interactive:
        from benchbox.cli.dryrun import display_interactive_preview

        # Determine force mode string from ForceConfig
        force_str = None
        if force:
            if force.datagen and force.upload:
                force_str = "all"
            elif force.datagen:
                force_str = "datagen"
            elif force.upload:
                force_str = "upload"

        # Build plan_config string for CLI preview
        plan_config_str = None
        if plan_config:
            plan_parts = []
            if plan_config.sample_rate is not None:
                plan_parts.append(f"sample:{plan_config.sample_rate}")
            if plan_config.first_n is not None:
                plan_parts.append(f"first:{plan_config.first_n}")
            if plan_config.queries:
                plan_parts.append(f"queries:{','.join(plan_config.queries)}")
            if plan_config.strict:
                plan_parts.append("strict:true")
            if plan_parts:
                plan_config_str = ",".join(plan_parts)

        # Build platform_options dict for CLI preview
        platform_options_dict = dict(platform_option_pairs) if platform_option_pairs else None

        display_interactive_preview(
            database_config=database_config,
            benchmark_config=benchmark_config,
            phases=phases_to_run,
            output=output,
            table_mode=table_mode,
            tuning=tuning if tuning != "notuning" else None,
            seed=seed,
            force=force_str,
            official=official,
            capture_plans=capture_plans,
            validation=validation_mode if validation_mode and validation_mode != "exact" else None,
            verbose=verbosity_settings.level,
            console_obj=console,
            platform_options=platform_options_dict,
            plan_config=plan_config_str,
            presort=presort,
            sorted_ingestion_mode=sorted_ingestion_mode,
            sorted_ingestion_method=sorted_ingestion_method,
            global_cache=global_cache,
        )

        if not Confirm.ask("Proceed with execution?", default=True):
            console.print("[yellow]Benchmark execution cancelled.[/yellow]")
            ctx.exit(0)

    console.print("\n[bold]Step 6 of 6:[/bold] [cyan]Benchmark Execution[/cyan]")
    console.print("Executing benchmark with platform optimizations...")

    # Build execution context for reproducibility
    execution_context = _build_execution_context(
        phases_to_run=phases_to_run,
        seed=seed,
        compression=comp_config,
        mode=mode,
        official=official,
        validation=val_config,
        force=force_config,
        queries_to_run=queries_to_run,
        capture_plans=capture_plans,
        strict_plan_capture=strict_plan_capture,
        non_interactive=non_interactive,
        tuning=tuning,
    )

    # Use orchestrator for better execution
    orchestrator = BenchmarkOrchestrator()
    orchestrator.set_verbosity(verbosity_settings)

    # Set custom output directory if provided (supports cloud paths)
    if output:
        normalized_output = normalize_output_root(output, benchmark_config.name, benchmark_config.scale_factor)
        # Type checker doesn't understand normalize_output_root returns str when input is truthy
        assert normalized_output is not None
        orchestrator.set_custom_output_dir(normalized_output)

    result = _execute_orchestrated_run(
        orchestrator,
        benchmark_config,
        system_profile,
        database_config,
        phases_to_run,
        quiet=bool(quiet),
        no_progress=bool(no_progress),
        no_monitoring=bool(no_monitoring),
        execution_context=execution_context,
    )

    # Export results
    if result.validation_status not in ["FAILED", "INTERRUPTED"]:
        console.print("\n[bold]Step 5:[/bold] Export Results")
        export_formats = config.get("output.formats", ["json"])
        exported_files = _export_orchestrated_result(
            orchestrator=orchestrator,
            result=result,
            benchmark=benchmark_config.name,
            scale=benchmark_config.scale_factor,
            platform_label=database_config.type.lower(),
            mode_label=resolved_mode,
            quiet=bool(quiet),
            export_formats=export_formats,
        )

        # Show what was exported
        if quiet:
            for format_name, filepath in exported_files.items():
                click.echo(filepath)
        else:
            console.print(f"\n[green]✅ Benchmark completed with status: {result.validation_status}[/green]")
            console.print(f"Result ID: [cyan]{result.execution_id}[/cyan]")

            for format_name, filepath in exported_files.items():
                console.print(f"{format_name.upper()}: [dim]{filepath}[/dim]")

        _render_post_run_charts(result, console, quiet)

        # Optional post-run publish
        if publish:
            json_bundle = exported_files.get("json")
            if json_bundle:
                from benchbox.cli.commands.publish import publish_bundle

                if not quiet:
                    console.print("\n[bold]Publishing result bundle...[/bold]")
                publish_bundle(
                    source_bundle=json_bundle,
                    target=publish_target,
                    label=publish_label,
                    quiet=bool(quiet),
                )

        # Save configuration for quick restart
        from benchbox.cli.preferences import save_last_run_config

        save_last_run_config(
            database=database_config.type,
            benchmark=benchmark_config.name,
            scale=benchmark_config.scale_factor,
            tuning_mode=tuning,
            phases=phases_to_run,
            concurrency=benchmark_config.concurrency,
            compress_data=benchmark_config.compress_data,
            compression_type=benchmark_config.compression_type,
            compression_level=benchmark_config.compression_level,
            test_execution_type=benchmark_config.test_execution_type,
            seed=seed,
            output=output,
            additional_options={"table_mode": table_mode},
        )
    else:
        console.print(f"\n[red]❌ Benchmark failed with status: {result.validation_status}[/red]")
        ctx.exit(1)


__all__ = ["run", "PlatformOptionParamType", "setup_verbose_logging"]
