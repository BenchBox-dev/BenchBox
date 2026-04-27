"""Implementation of the `benchbox run` command."""

from __future__ import annotations

import json
import logging
import os
import sys
import types
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import click
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from benchbox.cli.benchmark_hooks import BenchmarkHookRegistry, BenchmarkOptionError
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
from benchbox.cli.tuning_runtime import (
    build_baseline_unified_config,
    infer_runtime_tuning_mode,
    resolve_dataframe_tuning_config,
)
from benchbox.core.config import DatabaseConfig
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.core.schemas import ExecutionContext
from benchbox.platforms import is_dataframe_platform, list_available_dataframe_platforms
from benchbox.utils.cloud_storage import is_cloud_path
from benchbox.utils.compression import CompressionManager
from benchbox.utils.input_validation import MAX_QUERY_ID_LENGTH
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


class BenchmarkOptionParamType(click.ParamType):
    """Click parameter type for key=value benchmark options."""

    name = "key=value"

    def convert(self, value: str, param, ctx) -> tuple[str, str]:
        if "=" not in value:
            self.fail("Expected KEY=VALUE format", param, ctx)
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            self.fail("Benchmark option key cannot be empty", param, ctx)
        return key, raw.strip()


def _derive_execution_type(phases: list[str]) -> str:
    """Derive benchmark execution type from the requested phase list."""
    query_phases = {"power", "throughput", "maintenance"}
    selected_query_phases = set(phases) & query_phases
    if selected_query_phases:
        # Any mixed query-phase request should use combined mode so the adapter
        # can execute exactly the requested subset of query phases.
        if len(selected_query_phases) > 1:
            return "combined"
        if "power" in selected_query_phases:
            return "power"
        if "throughput" in selected_query_phases:
            return "throughput"
        if "maintenance" in selected_query_phases:
            return "maintenance"
        return "standard"
    if phases == ["load"] or ("load" in phases and not (set(phases) & query_phases)):
        return "load_only"
    if phases == ["generate"] or ("generate" in phases and not (set(phases) & ({"load"} | query_phases))):
        return "data_only"
    return "standard"


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

# ---------------------------------------------------------------------------
# Run preamble helpers - split to keep per-function McCabe complexity < 18.
# ---------------------------------------------------------------------------


def _apply_cli_adapter(s: types.SimpleNamespace) -> None:
    """Map new composite CLI params to legacy variables used downstream."""
    # Force config -> legacy flags
    force_config = s.force or ForceConfig()
    s.force_config = force_config
    s.force_regenerate = force_config.datagen
    s.force_upload = force_config.upload

    # Compression config -> legacy variables
    comp_config = s.compression or CompressionConfig()
    s.comp_config = comp_config
    s.compression_cli_set = s.compression is not None
    s.no_compression = not comp_config.enabled
    s.compression_type = comp_config.type
    s.compression_level = comp_config.level

    # Plan config -> legacy variables
    plan_cfg = s.plan_config or PlanCaptureConfig()
    s.plan_cfg = plan_cfg
    s.strict_plan_capture = plan_cfg.strict
    s.plan_sampling_rate = plan_cfg.sample_rate
    s.plan_first_n = plan_cfg.first_n
    s.plan_queries_str = ",".join(plan_cfg.queries) if plan_cfg.queries else None
    s.show_query_plans = s.capture_plans  # Show plans when capturing

    # Table format config -> legacy variables
    s.table_format_value = s.table_format.format if s.table_format else None
    s.table_format_compression = s.table_format.compression if s.table_format else "snappy"
    s.table_format_partition_cols = tuple(s.table_format.partition_cols) if s.table_format else ()

    # Validation config -> legacy variables
    val_config = s.validation or ValidationConfig()
    s.val_config = val_config
    s.validation_mode = val_config.mode if val_config.mode != "exact" or s.validation else None
    s.check_platforms = val_config.check_platforms
    s.enable_preflight_validation = val_config.preflight
    s.enable_postgen_manifest_validation = val_config.postgen
    s.enable_postload_validation = val_config.postload

    s.describe_platforms = ()
    s.plan_queries = s.plan_queries_str


def _validate_initial_flags(s: types.SimpleNamespace) -> None:
    """Validate describe_platforms, quiet+verbose, official mode."""
    if s.describe_platforms:
        _describe_platform_options(s.describe_platforms)
        s.ctx.exit(0)

    if s.quiet and s.verbose:
        console.print("[red]❌ --quiet cannot be used with -v/-vv flags[/red]")
        s.ctx.exit(2)

    if s.official:
        tpc_allowed = {1, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000}
        if s.scale not in tpc_allowed:
            console.print(f"[red]❌ Scale factor {s.scale} is not TPC-compliant[/red]")
            console.print(f"Allowed scale factors: {sorted(tpc_allowed)}")
            s.ctx.exit(1)

        if s.seed is None:
            console.print(
                "[yellow]⚠️  Warning: No --seed specified. Official TPC runs require a random seed for reproducibility.[/yellow]"
            )

        console.print("[bold blue]TPC-Compliant Official Benchmark Run[/bold blue]")
        console.print(f"Scale Factor: {s.scale} (TPC-allowed)")
        if s.seed is not None:
            console.print(f"Seed: {s.seed}")
        console.print()


def _parse_plat_bench_options(s: types.SimpleNamespace) -> None:
    """Parse --platform-option and --benchmark-option flags; set state fields."""
    s.logger, s.verbosity_settings = setup_verbose_logging(s.verbose, quiet=bool(s.quiet))
    set_quiet_output(s.verbosity_settings.quiet)
    s.ctx.obj["verbosity"] = s.verbosity_settings
    s.verbosity_payload = s.verbosity_settings.to_config()

    s.platform_key = normalize_platform_name(s.platform) if s.platform else None
    s.benchmark = normalize_benchmark_name(s.benchmark) if s.benchmark else None
    s.table_mode = (s.table_mode or "native").lower()
    s.table_mode_cli_supplied = False
    if hasattr(s.ctx, "get_parameter_source"):
        try:
            s.table_mode_cli_supplied = (
                s.ctx.get_parameter_source("table_mode") == click.core.ParameterSource.COMMANDLINE
            )
        except Exception:
            s.table_mode_cli_supplied = False

    if s.platform_option_pairs and not s.platform_key:
        console.print("[red]❌ Platform options require a --platform selection[/red]")
        s.ctx.exit(1)

    s.parsed_platform_options = {}
    if s.platform_key:
        try:
            s.parsed_platform_options = PlatformHookRegistry.parse_options(s.platform_key, s.platform_option_pairs)
        except PlatformOptionError as exc:
            console.print(f"[red]❌ {exc}[/red]")
            if s.logger:
                s.logger.error(f"Platform option error: {exc}")
            s.ctx.exit(1)

    if s.benchmark_option_pairs and not s.benchmark:
        console.print("[red]❌ Benchmark options require a --benchmark selection[/red]")
        s.ctx.exit(1)

    s.parsed_benchmark_options = {}
    if s.benchmark and s.benchmark_option_pairs:
        try:
            from benchbox.core.benchmark_loader import get_benchmark_class

            get_benchmark_class(s.benchmark)
        except ValueError:
            pass
        try:
            s.parsed_benchmark_options = BenchmarkHookRegistry.parse_options(s.benchmark, s.benchmark_option_pairs)
        except BenchmarkOptionError as exc:
            console.print(f"[red]❌ {exc}[/red]")
            if s.logger:
                s.logger.error(f"Benchmark option error: {exc}")
            s.ctx.exit(1)

    if s.logger:
        s.logger.debug("Starting BenchBox CLI run command")
        s.logger.debug(
            f"Arguments: platform={s.platform}, benchmark={s.benchmark}, scale={s.scale}, verbose={s.verbose}"
        )

    if s.table_mode == "external" and s.tuning.strip().lower() == "tuned":
        _reject_external_tuned(console, s.logger, s.ctx)


def _validate_non_interactive(s: types.SimpleNamespace) -> None:
    """Set env flag and validate required args for non-interactive mode."""
    if not s.non_interactive:
        return
    os.environ["BENCHBOX_NON_INTERACTIVE"] = "true"
    if s.logger:
        s.logger.debug("Non-interactive mode enabled via CLI flag")

    phase_list = [p.strip() for p in s.phases.split(",") if p.strip()]
    is_data_only = phase_list == ["generate"] or (
        "generate" in phase_list and not set(phase_list) & {"load", "warmup", "power", "throughput", "maintenance"}
    )

    missing_args = []
    if not s.benchmark:
        missing_args.append("--benchmark")
    if not s.platform and not is_data_only:
        missing_args.append("--platform")

    if missing_args:
        console.print("[red]❌ Error: Non-interactive mode requires all parameters[/red]")
        console.print(f"[yellow]Missing: {', '.join(missing_args)}[/yellow]")
        console.print("[dim]Use interactive mode by omitting --non-interactive flag[/dim]")
        if s.logger:
            s.logger.error(f"Non-interactive mode missing required args: {missing_args}")
        s.ctx.exit(2)


def _parse_phases_list(s: types.SimpleNamespace) -> None:
    """Parse and validate the --phases list into phases_to_run."""
    valid_phases = {"generate", "load", "warmup", "power", "throughput", "maintenance"}
    phase_list = [p.strip() for p in s.phases.split(",") if p.strip()]

    invalid_phases = set(phase_list) - valid_phases
    if invalid_phases:
        console.print(f"[red]❌ Error: Invalid phases: {', '.join(invalid_phases)}[/red]")
        console.print(f"[yellow]Valid phases: {', '.join(sorted(valid_phases))}[/yellow]")
        if s.logger:
            s.logger.error(f"Invalid phases specified: {invalid_phases}")
        s.ctx.exit(1)

    seen = set()
    phases_to_run: list[str] = []
    for p in phase_list:
        if p not in seen:
            phases_to_run.append(p)
            seen.add(p)
    s.phases_to_run = phases_to_run


def _parse_queries_list(s: types.SimpleNamespace) -> None:
    """Parse and validate the --queries subset list into queries_to_run."""
    s.queries_to_run = None
    if s.queries is None:
        return

    import re

    queries_to_run = [q.strip() for q in s.queries.split(",") if q.strip()]
    if not queries_to_run:
        console.print("[red]❌ Error: --queries flag provided but no valid query IDs found[/red]")
        if s.logger:
            s.logger.error("Empty queries list after parsing")
        s.ctx.exit(1)

    max_queries = 100
    if len(queries_to_run) > max_queries:
        console.print(f"[red]❌ Too many queries: {len(queries_to_run)} (max {max_queries})[/red]")
        if s.logger:
            s.logger.error(f"Query list too long: {len(queries_to_run)} exceeds limit of {max_queries}")
        s.ctx.exit(1)

    if any(len(q) > MAX_QUERY_ID_LENGTH for q in queries_to_run):
        too_long = [q for q in queries_to_run if len(q) > MAX_QUERY_ID_LENGTH]
        console.print(f"[red]❌ Query ID too long (max {MAX_QUERY_ID_LENGTH} chars): {', '.join(too_long[:3])}[/red]")
        if s.logger:
            s.logger.error(f"Query IDs exceed length limit: {too_long}")
        s.ctx.exit(1)

    query_id_pattern = re.compile(r"^[a-zA-Z0-9_.\-]+$")
    invalid_format = [q for q in queries_to_run if not query_id_pattern.match(q)]
    if invalid_format:
        console.print(
            f"[red]❌ Invalid query ID format: {', '.join(invalid_format[:5])} "
            f"(must be alphanumeric, dash, underscore, or dot)[/red]"
        )
        if s.logger:
            s.logger.error(f"Invalid query ID format: {invalid_format}")
        s.ctx.exit(1)

    incompatible_phases = {"warmup", "throughput", "maintenance"} & set(s.phases_to_run)
    query_phases = {"power", "standard"} & set(s.phases_to_run)
    if incompatible_phases and not query_phases:
        console.print(
            f"[red]❌ --queries only works with power/standard phases. "
            f"Current phases ({', '.join(sorted(s.phases_to_run))}) are incompatible.[/red]"
        )
        if s.logger:
            s.logger.error(f"--queries flag requires power or standard phase, got: {s.phases_to_run}")
        s.ctx.exit(1)
    elif incompatible_phases:
        console.print(f"[yellow]⚠️  --queries ignored for: {', '.join(sorted(incompatible_phases))}[/yellow]")
        if s.logger:
            s.logger.warning(f"--queries flag will be ignored for phases: {incompatible_phases}")

    s.queries_to_run = queries_to_run


def _derive_exec_type_and_banner(s: types.SimpleNamespace) -> None:
    """Warn about stray --iterations, compute execution type, and print banner."""
    if s.iterations is not None and "power" not in s.phases_to_run and "standard" not in s.phases_to_run:
        console.print("[yellow]⚠️  Warning: --iterations has no effect without a power or standard phase.[/yellow]")

    s.test_execution_type = _derive_execution_type(s.phases_to_run)
    if s.logger:
        s.logger.debug(f"Test execution type: {s.test_execution_type}")
    s.execution_mode = s.test_execution_type

    if not s.quiet:
        console.print(
            Panel.fit(
                Text("BenchBox Interactive Benchmark Runner", style="bold blue"),
                style="blue",
            )
        )


def _check_platforms_status(s: types.SimpleNamespace) -> None:
    """Implement the --check-platforms status check."""
    if not s.check_platforms:
        return
    console.print("\n[bold cyan]Checking Platform Status...[/bold cyan]")
    enabled_platforms = s.platform_manager.get_enabled_platforms()
    if not enabled_platforms:
        console.print("[red]❌ No platforms are enabled![/red]")
        console.print("Run [cyan]benchbox platforms setup[/cyan] to configure platforms.")
        s.ctx.exit(1)

    all_good = True
    for platform_name in enabled_platforms:
        if s.platform_manager.is_platform_available(platform_name):
            console.print(f"[green]✅ {platform_name}: Ready[/green]")
        else:
            console.print(f"[red]❌ {platform_name}: Missing dependencies[/red]")
            all_good = False

    if not all_good:
        console.print(
            "\n[red]Some platforms need attention. Run [cyan]benchbox platforms status[/cyan] for details.[/red]"
        )
        s.ctx.exit(1)
    else:
        console.print("[green]All enabled platforms are ready![/green]")


def _resolve_platform_mode(s: types.SimpleNamespace) -> None:
    """Validate platform, resolve execution mode, and check availability."""
    s.resolved_mode = None
    if not s.platform_key:
        return

    caps = PlatformRegistry.get_platform_capabilities(s.platform_key)
    if caps is None:
        is_df_platform_legacy = is_dataframe_platform(s.platform_key)
        is_df_available = is_df_platform_legacy and list_available_dataframe_platforms().get(s.platform_key, False)
        if not is_df_available and not s.dry_run:
            from benchbox.utils.dependencies import get_install_command

            console.print(f"[red]❌ Platform '{s.platform_key}' is not available (missing dependencies)[/red]")
            install_cmd = get_install_command(s.platform_key)
            console.print(f"Run [cyan]{escape(install_cmd)}[/cyan] to install dependencies.")
            s.ctx.exit(1)
        s.resolved_mode = "dataframe"
    else:
        if s.mode is not None:
            if not PlatformRegistry.supports_mode(s.platform_key, s.mode):
                supported_modes = []
                if caps.supports_sql:
                    supported_modes.append("sql")
                if caps.supports_dataframe:
                    supported_modes.append("dataframe")
                console.print(f"[red]❌ Platform '{s.platform_key}' does not support {s.mode} mode[/red]")
                console.print(f"[yellow]Supported modes: {', '.join(supported_modes)}[/yellow]")
                if s.logger:
                    s.logger.error(f"Platform {s.platform_key} does not support mode: {s.mode}")
                s.ctx.exit(1)
            s.resolved_mode = s.mode
        else:
            s.resolved_mode = caps.default_mode

        if s.resolved_mode == "sql":
            if s.platform_key == "polars":
                try:
                    import polars  # noqa: F401

                    is_available = True
                except ImportError:
                    is_available = False
            else:
                is_available = s.platform_manager.is_platform_available(s.platform_key)
        else:
            is_available = caps.supports_dataframe
            if is_available and s.platform_key in ["polars", "pandas", "modin", "cudf", "dask"]:
                df_platforms = list_available_dataframe_platforms()
                legacy_key = f"{s.platform_key}-df"
                is_available = df_platforms.get(legacy_key, df_platforms.get(s.platform_key, False))

        if not is_available and not s.dry_run:
            from benchbox.utils.dependencies import get_install_command

            console.print(f"[red]❌ Platform '{s.platform_key}' is not available (missing dependencies)[/red]")
            install_cmd = get_install_command(s.platform_key)
            console.print(f"Run [cyan]{escape(install_cmd)}[/cyan] to install dependencies.")
            s.ctx.exit(1)

    if s.logger and s.resolved_mode:
        s.logger.debug(f"Resolved execution mode for {s.platform_key}: {s.resolved_mode}")


def _check_benchmark_platform_compatibility(s: types.SimpleNamespace) -> None:
    """Reject benchmark+platform combinations that always fail before any execution begins."""
    if not s.platform_key or not s.benchmark:
        return

    caps = PlatformRegistry.get_platform_capabilities(s.platform_key)
    unsupported_benchmarks = getattr(caps, "unsupported_benchmarks", None) if caps else None
    block_reason: str | None = unsupported_benchmarks.get(s.benchmark) if unsupported_benchmarks else None

    if block_reason is None:
        return

    console.print(f"[red]❌ Benchmark '{s.benchmark}' is not compatible with platform '{s.platform_key}'[/red]")
    console.print(f"[yellow]{block_reason}[/yellow]")
    if s.logger:
        s.logger.error(f"Benchmark '{s.benchmark}' is incompatible with platform '{s.platform_key}': {block_reason}")
    s.ctx.exit(1)


def _resolve_tuning(s: types.SimpleNamespace) -> None:
    """Resolve tuning mode and load unified tuning configuration."""
    s.config = s.ctx.obj["config"]
    if s.logger:
        s.logger.debug(f"Loaded configuration from: {s.config.config_path}")
        s.logger.debug(f"Configuration validation status: {s.config.validate_config()}")

    try:
        tuning_resolution = resolve_tuning(
            tuning_arg=s.tuning,
            platform=s.platform,
            benchmark=s.benchmark,
            config_manager=s.config,
            console=console,
            logger=s.logger,
            quiet=bool(s.quiet),
            non_interactive=s.non_interactive,
        )
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]")
        if s.logger:
            s.logger.error(f"Tuning resolution failed: {e}")
        s.ctx.exit(1)

    s.tuning_resolution = tuning_resolution
    s.tuning_enabled = tuning_resolution.enabled
    s.tuning_config_file = str(tuning_resolution.config_file) if tuning_resolution.config_file else None
    s.use_auto_tuning = tuning_resolution.mode == TuningMode.AUTO

    if not s.quiet:
        display_tuning_resolution(tuning_resolution, console, verbose=bool(s.verbose))

    if s.logger:
        s.logger.debug(
            f"Tuning resolution: mode={tuning_resolution.mode.value}, "
            f"source={tuning_resolution.source.value}, enabled={s.tuning_enabled}"
        )

    _load_unified_tuning_config(s)


def _load_unified_tuning_config(s: types.SimpleNamespace) -> None:
    """Load unified tuning configuration into s.loaded_unified_config."""
    s.loaded_unified_config = None
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration

    tuning_resolution = s.tuning_resolution
    if tuning_resolution.config_file:
        try:
            s.loaded_unified_config = s.config.load_unified_tuning_config(tuning_resolution.config_file, s.platform)
            if s.logger:
                s.logger.debug(f"Loaded tuning config from: {tuning_resolution.config_file}")
        except Exception as e:
            console.print(f"[red]❌ Failed to load tuning configuration: {e}[/red]")
            if s.logger:
                s.logger.error(f"Failed to load tuning configuration: {e}", exc_info=True)
            s.ctx.exit(1)
    elif tuning_resolution.source == TuningSource.BASELINE:
        s.loaded_unified_config = build_baseline_unified_config()
        if s.logger:
            s.logger.debug("No tuning mode: all constraints disabled for baseline")
    elif tuning_resolution.source == TuningSource.FALLBACK:
        if not s.non_interactive:
            console.print("\n[bold cyan]Tuning Configuration[/bold cyan]")
            if Confirm.ask("Would you like to configure tuning options?", default=False):
                from benchbox.cli.tuning import run_tuning_wizard

                profiler = SystemProfiler()
                system_profile = profiler.get_system_profile()
                s.loaded_unified_config = run_tuning_wizard(
                    benchmark=s.benchmark,
                    platform=s.platform,
                    system_profile=system_profile,
                    interactive=True,
                )
                s.tuning_enabled, s.tuning = infer_runtime_tuning_mode(s.loaded_unified_config)
                console.print("[green]✅ Tuning configuration completed[/green]")
            else:
                s.loaded_unified_config = UnifiedTuningConfiguration()
        else:
            s.loaded_unified_config = UnifiedTuningConfiguration()
        if s.logger:
            s.logger.debug("Using basic constraints-only configuration (fallback)")
    else:
        s.loaded_unified_config = UnifiedTuningConfiguration()
        if s.logger:
            s.logger.debug(f"Using basic unified config for mode: {tuning_resolution.mode.value}")


def _resolve_data_organization(s: types.SimpleNamespace) -> None:
    """Apply platform optimizations, build data organization payload, resolve DF tuning config."""
    try:
        _apply_platform_optimization_overrides(
            s.loaded_unified_config,
            sorted_ingestion_mode=s.sorted_ingestion_mode,
            sorted_ingestion_method=s.sorted_ingestion_method,
            parsed_platform_options=s.parsed_platform_options,
        )
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        s.ctx.exit(1)

    data_organization_payload = _build_data_organization_from_tuning(s.loaded_unified_config)
    try:
        data_organization_payload = _resolve_data_organization_payload(
            s.benchmark, s.presort, data_organization_payload
        )
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        s.ctx.exit(1)
    s.data_organization_payload = data_organization_payload
    if data_organization_payload is None:
        os.environ.pop(DATA_ORGANIZATION_ENV, None)
    else:
        os.environ[DATA_ORGANIZATION_ENV] = json.dumps(data_organization_payload)

    try:
        s.df_tuning_config = resolve_dataframe_tuning_config(
            platform_name=s.platform,
            mode_name=s.resolved_mode,
            tuning_enabled_flag=s.tuning_enabled,
            use_auto_tuning_flag=s.use_auto_tuning,
            tuning_config_file_path=s.tuning_config_file,
            console=console,
            logger=s.logger,
            quiet=bool(s.quiet),
        )
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        s.ctx.exit(1)


def _resolve_compression_settings(s: types.SimpleNamespace) -> None:
    """Resolve effective compression settings (CLI/env/config precedence)."""
    if s.no_compression:
        s.compress_data = False
        if s.compression_type != "none":
            s.compression_type = "none"
        if s.logger:
            s.logger.debug("Compression disabled via --no-compression flag")
    else:
        env_no_compression = os.getenv("BENCHBOX_NO_COMPRESSION", "").lower() in ["true", "1", "yes", "on"]
        if env_no_compression:
            s.compress_data = False
            s.compression_type = "none"
            if s.logger:
                s.logger.debug("Compression disabled via BENCHBOX_NO_COMPRESSION environment variable")
        elif s.compression_cli_set:
            s.compress_data = s.comp_config.enabled
            if s.logger:
                s.logger.debug(
                    "Compression set via CLI: enabled=%s, type=%s, level=%s",
                    s.compress_data,
                    s.compression_type,
                    s.compression_level,
                )
        else:
            config_compression_enabled = s.config.get("output.compression.enabled", False)
            s.compress_data = config_compression_enabled
            s.compression_type = s.config.get("output.compression.type", "zstd")
            s.compression_level = s.config.get("output.compression.level", None)
            if s.logger:
                s.logger.debug(f"Compression enabled: type={s.compression_type}, level={s.compression_level}")

    if s.compress_data and s.compression_type != "none":
        manager = CompressionManager()
        available = manager.get_available_compressors()
        if s.compression_type not in available:
            warning = (
                f"[yellow]⚠️ Compression type '{s.compression_type}' is not available. "
                "Falling back to uncompressed output.[/yellow]"
            )
            console.print(warning)
            if s.logger:
                s.logger.warning(
                    "Compression type %s unavailable (available: %s). Falling back to no compression.",
                    s.compression_type,
                    available,
                )
            s.compress_data = False
            s.compression_type = "none"
            s.compression_level = None

    if not s.compress_data:
        s.compression_type = "none"
        s.compression_level = None


def _validate_output_dir(s: types.SimpleNamespace) -> None:
    """Validate --output directory (including cloud storage)."""
    if not s.output:
        return
    try:
        ValidationRules.validate_output_directory(s.output)
        if is_cloud_path(s.output):
            console.print(f"\n[green]✅[/green] Cloud storage output validated: {s.output}")
        else:
            console.print(f"\n[green]✅[/green] Output directory validated: {s.output}")
    except (ValidationError, CloudStorageError) as e:
        error_handler = create_error_handler(console)
        context = ErrorContext(
            operation="output_validation",
            stage="pre_execution",
            user_input={"output_path": s.output},
        )
        error_handler.handle_error(e, context)
        s.ctx.exit(1)


def _prepare_run_state(s: types.SimpleNamespace) -> None:
    """Run the full preamble: normalize CLI params, validate, resolve configs."""
    _apply_cli_adapter(s)
    _validate_initial_flags(s)
    _parse_plat_bench_options(s)
    _validate_non_interactive(s)
    _parse_phases_list(s)
    _parse_queries_list(s)
    _derive_exec_type_and_banner(s)

    s.platform_manager = get_platform_manager()
    _check_platforms_status(s)
    _resolve_platform_mode(s)
    _check_benchmark_platform_compatibility(s)
    _resolve_tuning(s)
    _resolve_data_organization(s)
    _resolve_compression_settings(s)
    _validate_output_dir(s)

    # Initialize configs - assigned in all live-run paths below; asserted non-None before use.
    s.database_config = None
    s.benchmark_config = None


# ---------------------------------------------------------------------------
# Branch helpers - one per mutually-exclusive execution path.
# ---------------------------------------------------------------------------


def _dry_run_validate_inputs(s: types.SimpleNamespace) -> None:
    """Validate inputs specific to the --dry-run path (platform/benchmark/scale)."""
    ctx = s.ctx
    logger = s.logger
    if s.test_execution_type == "data_only":
        if not s.benchmark:
            console.print("[red]❌ Dry run with --phases generate requires --benchmark parameter[/red]")
            if logger:
                logger.error("Dry run with --phases generate requires --benchmark parameter")
            ctx.exit(1)
        if s.platform:
            console.print("[yellow]⚠️️  Note: Platform parameter ignored in data-only dry run[/yellow]")
    else:
        if not (s.platform and s.benchmark):
            console.print("[red]❌ Dry run mode requires --platform and --benchmark parameters[/red]")
            console.print("[yellow]Use --phases generate if you only want to preview data generation[/yellow]")
            if logger:
                logger.error("Dry run mode requires --platform and --benchmark parameters")
            ctx.exit(1)

    if logger:
        logger.debug(f"Validating scale factor for dry run: {s.scale}")
    if s.scale >= 1 and s.scale != int(s.scale):
        console.print(f"[red]❌ Scale factors >= 1 must be whole integers. Got: {s.scale}[/red]")
        console.print("[yellow]Use values like 1, 2, 10, etc. for large scale factors[/yellow]")
        console.print("[yellow]Use values like 0.1, 0.01, 0.001, etc. for small scale factors[/yellow]")
        if logger:
            logger.error(f"Invalid scale factor for dry run: {s.scale}")
        ctx.exit(1)


def _warn_tpcds_subscale(s: types.SimpleNamespace) -> None:
    if s.benchmark == "tpcds" and s.scale < 1.0 and not s.quiet:
        console.print(
            "[yellow]⚠  TPC-DS UNOFFICIAL SUBSCALE RUN[/yellow]\n"
            f"   Scale factor: [bold]{s.scale}[/bold] (< 1.0 - not TPC-DS compliant)\n"
            "   Results are for development use only and must not be published or\n"
            "   submitted as official TPC-DS results. Official TPC metrics\n"
            "   (QphDS, power@size, throughput@size) will not be computed.\n"
            "   See _sources/tpcds-subscale-contract.md for the data contract."
        )


def _run_dry_run(s: types.SimpleNamespace) -> None:
    """Execute the --dry-run path."""
    ctx = s.ctx
    logger = s.logger
    if logger:
        logger.debug(f"Entering dry run mode, output directory: {s.dry_run}")

    _dry_run_validate_inputs(s)

    from benchbox.cli.dryrun import DryRunExecutor

    if logger:
        logger.debug("Creating database and benchmark managers for dry run")
    db_manager = DatabaseManager()
    db_manager.set_verbosity(s.verbosity_settings)
    bench_manager = BenchmarkManager()
    bench_manager.set_verbosity(s.verbosity_settings)

    if logger:
        logger.debug(f"Validating benchmark '{s.benchmark}' exists")
    if s.benchmark not in bench_manager.benchmarks:
        console.print(f"[red]❌ Unknown benchmark: {s.benchmark}[/red]")
        console.print(f"Available benchmarks: {', '.join(bench_manager.benchmarks.keys())}")
        if logger:
            logger.error(f"Unknown benchmark: {s.benchmark}. Available: {list(bench_manager.benchmarks.keys())}")
        ctx.exit(1)

    database_config = _dry_run_build_db_config(s, db_manager)

    if logger:
        logger.debug(f"Creating benchmark configuration for: {s.benchmark}")
    benchmark_info = bench_manager.benchmarks[s.benchmark]

    try:
        bench_manager.validate_scale_factor(s.benchmark, s.scale)
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]")
        if logger:
            logger.error(f"Scale factor validation failed: {e}")
        ctx.exit(1)

    _warn_tpcds_subscale(s)

    benchmark_config = BenchmarkConfig(
        name=s.benchmark,
        display_name=benchmark_info["display_name"],
        scale_factor=s.scale,
        queries=s.queries_to_run,
        compress_data=s.compress_data,
        compression_type=s.compression_type,
        compression_level=s.compression_level,
        test_execution_type=s.test_execution_type,
        capture_plans=s.capture_plans,
        strict_plan_capture=s.strict_plan_capture,
        options={
            **s.verbosity_payload,
            "estimated_time_range": benchmark_info["estimated_time_range"],
            "tuning_enabled": s.tuning_enabled,
            "table_mode": s.table_mode,
            "unified_tuning_configuration": s.loaded_unified_config,
            **({"data_organization": s.data_organization_payload} if s.data_organization_payload is not None else {}),
            "force_regenerate": s.force_regenerate,
            "enable_preflight_validation": s.enable_preflight_validation,
            "enable_postgen_manifest_validation": s.enable_postgen_manifest_validation,
            "enable_postload_validation": s.enable_postload_validation,
            "ignore_memory_warnings": s.ignore_memory_warnings,
            **({"cache_dir": str(Path.home() / ".benchbox" / "datagen")} if s.global_cache else {}),
            **({"seed": s.seed} if s.seed is not None else {}),
            **({"power_iterations": s.iterations} if s.iterations is not None else {}),
            **({"validation_mode": s.validation_mode} if s.validation_mode is not None else {}),
            **({"table_format": s.table_format_value} if s.table_format_value is not None else {}),
            **(
                {"table_format_compression": s.table_format_compression}
                if s.table_format_compression is not None
                else {}
            ),
            **(
                {"table_format_partition_cols": list(s.table_format_partition_cols)}
                if s.table_format_partition_cols
                else {}
            ),
            **({"presort": s.presort} if s.presort is not None else {}),
            **({"benchmark_options": s.parsed_benchmark_options} if s.parsed_benchmark_options else {}),
        },
    )

    if logger:
        logger.debug(f"Benchmark config created: {benchmark_config}")
        logger.debug("Getting system profile for dry run")
    profiler = SystemProfiler()
    system_profile = profiler.get_system_profile()

    if logger:
        logger.debug(
            f"System profile: CPU cores={system_profile.cpu_cores_logical}, Memory={system_profile.memory_total_gb}GB"
        )
        logger.debug(f"Executing dry run with output directory: {s.dry_run}")
    dry_run_executor = DryRunExecutor(output_dir=s.dry_run)
    dry_run_result = dry_run_executor.execute_dry_run(benchmark_config, system_profile, database_config)

    if logger:
        logger.debug("Dry run completed")

    dry_run_executor.display_dry_run_results(dry_run_result)

    filename_prefix = f"{s.benchmark}_{'data-only' if s.execution_mode == 'data_only' else s.platform}"
    saved_files = dry_run_executor.save_dry_run_results(dry_run_result, filename_prefix)

    console.print("\n[green]✅ Dry run completed[/green]")
    if s.test_execution_type == "data_only":
        console.print(f"[dim]Data generation preview for {s.benchmark} at scale {s.scale}[/dim]")
    else:
        console.print(
            f"[dim]Configuration and queries previewed for {s.benchmark} on {s.platform} at scale {s.scale}[/dim]"
        )

    if saved_files:
        console.print("\n[dim]Output files saved to:[/dim]")
        for _file_type, file_path in saved_files.items():
            console.print(f"  [cyan]{file_path}[/cyan]")


def _dry_run_build_db_config(s: types.SimpleNamespace, db_manager: DatabaseManager) -> DatabaseConfig | None:
    """Create DatabaseConfig for dry run mode (skipped for data-only)."""
    ctx = s.ctx
    logger = s.logger
    if s.execution_mode == "data_only":
        if logger:
            logger.debug("Skipping database configuration for data-only dry run")
        return None

    if logger:
        logger.debug(f"Creating database configuration for: {s.platform}")
    assert s.platform_key is not None
    overrides = {
        **s.verbosity_payload,
        "tuning_enabled": s.tuning_enabled,
        "force_upload": bool(s.force_upload),
        "capture_plans": s.capture_plans,
        "strict_plan_capture": s.strict_plan_capture,
        "plan_sampling_rate": s.plan_sampling_rate,
        "plan_first_n": s.plan_first_n,
        "plan_queries": s.plan_queries,
        "execution_mode": s.resolved_mode,
    }
    if s.loaded_unified_config:
        overrides["unified_tuning_configuration"] = s.loaded_unified_config
    if s.df_tuning_config:
        overrides["df_tuning_config"] = s.df_tuning_config
    database_config: DatabaseConfig | None = None
    try:
        database_config = db_manager.create_config(
            s.platform_key,
            dict(s.parsed_platform_options),
            overrides,
        )
    except PlatformOptionError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        if logger:
            logger.error(f"Database configuration failed: {exc}")
        ctx.exit(1)
    except RuntimeError as exc:
        if logger:
            logger.debug(f"Driver not installed, using minimal config for dry run: {exc}")
        database_config = None
    if logger:
        logger.debug("Database configuration created for dry run")
    return database_config


def _run_direct(s: types.SimpleNamespace) -> None:
    """Execute the direct non-interactive SQL/DataFrame path."""
    ctx = s.ctx
    logger = s.logger
    if logger:
        logger.debug(f"Entering direct execution mode: platform={s.platform}, benchmark={s.benchmark}")
        logger.debug(f"Validating scale factor for direct execution: {s.scale}")
    if s.scale >= 1 and s.scale != int(s.scale):
        console.print(f"[red]❌ Scale factors >= 1 must be whole integers. Got: {s.scale}[/red]")
        console.print("[yellow]Use values like 1, 2, 10, etc. for large scale factors[/yellow]")
        console.print("[yellow]Use values like 0.1, 0.01, 0.001, etc. for small scale factors[/yellow]")
        if logger:
            logger.error(f"Invalid scale factor for direct execution: {s.scale}")
        return

    if logger:
        logger.info(f"Starting direct benchmark execution: {s.benchmark} on {s.platform} at scale {s.scale}")
        logger.debug("Creating database and benchmark managers for direct execution")
    db_manager = DatabaseManager()
    db_manager.set_verbosity(s.verbosity_settings)
    bench_manager = BenchmarkManager()
    bench_manager.set_verbosity(s.verbosity_settings)

    assert s.platform_key is not None
    overrides = {
        **s.verbosity_payload,
        "force_recreate": s.force_regenerate,
        "show_query_plans": s.show_query_plans,
        "tuning_enabled": s.tuning_enabled,
        "force_upload": bool(s.force_upload),
        "capture_plans": s.capture_plans,
        "strict_plan_capture": s.strict_plan_capture,
        "plan_sampling_rate": s.plan_sampling_rate,
        "plan_first_n": s.plan_first_n,
        "plan_queries": s.plan_queries,
        "execution_mode": s.resolved_mode,
    }
    if s.loaded_unified_config:
        overrides["unified_tuning_configuration"] = s.loaded_unified_config
    if s.df_tuning_config:
        overrides["df_tuning_config"] = s.df_tuning_config
    try:
        database_config = db_manager.create_config(
            s.platform_key,
            dict(s.parsed_platform_options),
            overrides,
        )
    except PlatformOptionError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        if logger:
            logger.error(f"Database configuration failed: {exc}")
        ctx.exit(1)

    _driver_version = database_config.driver_version_actual or database_config.driver_version_resolved
    _mode_tag = " \\[external]" if s.table_mode == "external" else ""
    if _driver_version:
        console.print(
            f"Running {s.benchmark} on {s.platform} at scale {s.scale} \\[driver {_driver_version}]{_mode_tag}"
        )
    else:
        console.print(f"Running {s.benchmark} on {s.platform} at scale {s.scale}{_mode_tag}")

    if s.benchmark not in bench_manager.benchmarks:
        console.print(f"[red]❌ Unknown benchmark: {s.benchmark}[/red]")
        console.print(f"Available benchmarks: {', '.join(bench_manager.benchmarks.keys())}")
        return

    benchmark_info = bench_manager.benchmarks[s.benchmark]

    try:
        bench_manager.validate_scale_factor(s.benchmark, s.scale)
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]")
        if logger:
            logger.error(f"Scale factor validation failed: {e}")
        ctx.exit(1)

    _warn_tpcds_subscale(s)

    benchmark_config = BenchmarkConfig(
        name=s.benchmark,
        display_name=benchmark_info["display_name"],
        scale_factor=s.scale,
        queries=s.queries_to_run,
        compress_data=s.compress_data,
        compression_type=s.compression_type,
        compression_level=s.compression_level,
        test_execution_type=s.test_execution_type,
        capture_plans=s.capture_plans,
        strict_plan_capture=s.strict_plan_capture,
        options={
            **s.verbosity_payload,
            "estimated_time_range": benchmark_info["estimated_time_range"],
            "tuning_enabled": s.tuning_enabled,
            "table_mode": s.table_mode,
            "unified_tuning_configuration": s.loaded_unified_config,
            **({"data_organization": s.data_organization_payload} if s.data_organization_payload is not None else {}),
            "force_regenerate": s.force_regenerate,
            "enable_preflight_validation": s.enable_preflight_validation,
            "enable_postgen_manifest_validation": s.enable_postgen_manifest_validation,
            "enable_postload_validation": s.enable_postload_validation,
            "seed": s.seed,
            **({"power_iterations": s.iterations} if s.iterations is not None else {}),
            "ignore_memory_warnings": s.ignore_memory_warnings,
            **({"cache_dir": str(Path.home() / ".benchbox" / "datagen")} if s.global_cache else {}),
            **({"table_format": s.table_format_value} if s.table_format_value is not None else {}),
            **(
                {"table_format_compression": s.table_format_compression}
                if s.table_format_compression is not None
                else {}
            ),
            **(
                {"table_format_partition_cols": list(s.table_format_partition_cols)}
                if s.table_format_partition_cols
                else {}
            ),
            **({"presort": s.presort} if s.presort is not None else {}),
            **({"benchmark_options": s.parsed_benchmark_options} if s.parsed_benchmark_options else {}),
        },
    )

    profiler = SystemProfiler()
    system_profile = profiler.get_system_profile()

    execution_context = _build_execution_context(
        phases_to_run=s.phases_to_run,
        seed=s.seed,
        compression=s.comp_config,
        mode=s.mode,
        official=s.official,
        validation=s.val_config,
        force=s.force_config,
        queries_to_run=s.queries_to_run,
        capture_plans=s.capture_plans,
        strict_plan_capture=s.strict_plan_capture,
        non_interactive=s.non_interactive,
        tuning=s.tuning,
    )

    orchestrator = BenchmarkOrchestrator()
    orchestrator.set_verbosity(s.verbosity_settings)

    if s.output:
        normalized_output = normalize_output_root(s.output, s.benchmark, s.scale)
        assert normalized_output is not None
        orchestrator.set_custom_output_dir(normalized_output)

    result = _execute_orchestrated_run(
        orchestrator,
        benchmark_config,
        system_profile,
        database_config,
        s.phases_to_run,
        quiet=bool(s.quiet),
        no_progress=bool(s.no_progress),
        no_monitoring=bool(s.no_monitoring),
        execution_context=execution_context,
    )

    _direct_handle_result(s, result, orchestrator, benchmark_config)


def _direct_handle_result(
    s: types.SimpleNamespace,
    result: Any,
    orchestrator: BenchmarkOrchestrator,
    benchmark_config: BenchmarkConfig,
) -> None:
    """Export results and perform post-run actions for the direct branch."""
    ctx = s.ctx
    if result.validation_status not in ["FAILED", "INTERRUPTED"]:
        if not s.quiet:
            console.print("\n[bold]Exporting results...[/bold]")

        exported_files = _export_orchestrated_result(
            orchestrator=orchestrator,
            result=result,
            benchmark=s.benchmark,
            scale=s.scale,
            platform_label=s.platform.lower(),
            mode_label=s.resolved_mode,
            quiet=bool(s.quiet),
            export_formats=["json"],
        )

        if s.quiet:
            for _format_name, filepath in exported_files.items():
                click.echo(filepath)
        else:
            console.print(f"\n[green]✅ Benchmark completed: {result.validation_status}[/green]")
            for format_name, filepath in exported_files.items():
                console.print(f"{format_name.upper()}: [dim]{filepath}[/dim]")

        _render_post_run_charts(result, console, s.quiet)

        if s.publish:
            json_bundle = exported_files.get("json")
            if json_bundle:
                from benchbox.cli.commands.publish import publish_bundle

                if not s.quiet:
                    console.print("\n[bold]Publishing result bundle...[/bold]")
                publish_bundle(
                    source_bundle=json_bundle,
                    target=s.publish_target,
                    label=s.publish_label,
                    quiet=bool(s.quiet),
                )

        from benchbox.cli.preferences import save_last_run_config

        save_last_run_config(
            database=s.platform,
            benchmark=s.benchmark,
            scale=s.scale,
            tuning_mode=s.tuning,
            phases=s.phases_to_run,
            concurrency=benchmark_config.concurrency,
            compress_data=s.compress_data,
            compression_type=s.compression_type,
            compression_level=s.compression_level,
            test_execution_type=s.test_execution_type,
            seed=s.seed,
            output=s.output,
            additional_options={"table_mode": s.table_mode},
        )
    else:
        console.print(f"\n[red]❌ Benchmark failed: {result.validation_status}[/red]")
        ctx.exit(1)


def _data_or_load_build_db_config(s: types.SimpleNamespace, db_manager: DatabaseManager) -> DatabaseConfig | None:
    """Create DatabaseConfig for load_only; return None for data_only."""
    if s.execution_mode != "load_only":
        return None

    ctx = s.ctx
    logger = s.logger
    assert s.platform_key is not None
    overrides = {
        **s.verbosity_payload,
        "force_recreate": s.force_regenerate,
        "tuning_enabled": s.tuning_enabled,
        "force_upload": bool(s.force_upload),
        "capture_plans": s.capture_plans,
        "strict_plan_capture": s.strict_plan_capture,
        "plan_sampling_rate": s.plan_sampling_rate,
        "plan_first_n": s.plan_first_n,
        "plan_queries": s.plan_queries,
        "execution_mode": s.resolved_mode,
    }
    if s.loaded_unified_config:
        overrides["unified_tuning_configuration"] = s.loaded_unified_config
    if s.df_tuning_config:
        overrides["df_tuning_config"] = s.df_tuning_config
    try:
        return db_manager.create_config(
            s.platform_key,
            dict(s.parsed_platform_options),
            overrides,
        )
    except PlatformOptionError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        if logger:
            logger.error(f"Database configuration failed: {exc}")
        ctx.exit(1)
    return None


def _data_or_load_validate_inputs(s: types.SimpleNamespace) -> None:
    """Validate platform/benchmark args for data_only / load_only branch."""
    ctx = s.ctx
    logger = s.logger
    if s.test_execution_type == "data_only":
        if s.platform:
            if not s.quiet:
                console.print("[yellow]⚠️️  Note: Platform parameter ignored in data-only mode[/yellow]")
    else:
        if not s.platform:
            console.print("[red]❌ Error: --platform parameter is required for --phases load[/red]")
            if logger:
                logger.error("Platform parameter is required for --phases load")
            ctx.exit(1)


def _run_data_or_load_only(s: types.SimpleNamespace) -> None:
    """Execute the data-only / load-only path."""
    logger = s.logger
    if logger:
        logger.debug(f"Entering {s.execution_mode} mode")

    _data_or_load_validate_inputs(s)

    if not s.benchmark:
        console.print("[red]❌ Error: --benchmark parameter is required[/red]")
        if logger:
            logger.error("Benchmark parameter is required")
        return

    db_manager = DatabaseManager()
    db_manager.set_verbosity(s.verbosity_settings)
    bench_manager = BenchmarkManager()
    bench_manager.set_verbosity(s.verbosity_settings)

    if s.benchmark not in bench_manager.benchmarks:
        console.print(f"[red]❌ Unknown benchmark: {s.benchmark}[/red]")
        console.print(f"Available benchmarks: {', '.join(bench_manager.benchmarks.keys())}")
        if logger:
            logger.error(f"Unknown benchmark: {s.benchmark}. Available: {list(bench_manager.benchmarks.keys())}")
        return

    database_config = _data_or_load_build_db_config(s, db_manager)

    benchmark_info = bench_manager.benchmarks[s.benchmark]

    try:
        bench_manager.validate_scale_factor(s.benchmark, s.scale)
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]")
        if logger:
            logger.error(f"Scale factor validation failed: {e}")
        s.ctx.exit(1)

    _warn_tpcds_subscale(s)

    benchmark_config = BenchmarkConfig(
        name=s.benchmark,
        display_name=benchmark_info["display_name"],
        scale_factor=s.scale,
        queries=s.queries_to_run,
        compress_data=s.compress_data,
        compression_type=s.compression_type,
        compression_level=s.compression_level,
        test_execution_type=s.test_execution_type,
        capture_plans=s.capture_plans,
        strict_plan_capture=s.strict_plan_capture,
        options={
            **s.verbosity_payload,
            "estimated_time_range": benchmark_info["estimated_time_range"],
            "table_mode": s.table_mode,
            "unified_tuning_configuration": s.loaded_unified_config,
            **({"data_organization": s.data_organization_payload} if s.data_organization_payload is not None else {}),
            "force_regenerate": s.force_regenerate,
            "enable_preflight_validation": s.enable_preflight_validation,
            "enable_postgen_manifest_validation": s.enable_postgen_manifest_validation,
            "enable_postload_validation": s.enable_postload_validation,
            "seed": s.seed,
            **({"power_iterations": s.iterations} if s.iterations is not None else {}),
            "ignore_memory_warnings": s.ignore_memory_warnings,
            **({"cache_dir": str(Path.home() / ".benchbox" / "datagen")} if s.global_cache else {}),
            **({"table_format": s.table_format_value} if s.table_format_value is not None else {}),
            **(
                {"table_format_compression": s.table_format_compression}
                if s.table_format_compression is not None
                else {}
            ),
            **(
                {"table_format_partition_cols": list(s.table_format_partition_cols)}
                if s.table_format_partition_cols
                else {}
            ),
            **({"presort": s.presort} if s.presort is not None else {}),
            **({"benchmark_options": s.parsed_benchmark_options} if s.parsed_benchmark_options else {}),
        },
    )

    profiler = SystemProfiler()
    system_profile = profiler.get_system_profile()

    execution_context = _build_execution_context(
        phases_to_run=s.phases_to_run,
        seed=s.seed,
        compression=s.comp_config,
        mode=s.mode,
        official=s.official,
        validation=s.val_config,
        force=s.force_config,
        queries_to_run=s.queries_to_run,
        capture_plans=s.capture_plans,
        strict_plan_capture=s.strict_plan_capture,
        non_interactive=s.non_interactive,
        tuning=s.tuning,
    )

    orchestrator = BenchmarkOrchestrator()
    orchestrator.set_verbosity(s.verbosity_settings)

    if s.output:
        normalized_output = normalize_output_root(s.output, s.benchmark, s.scale)
        assert normalized_output is not None
        orchestrator.set_custom_output_dir(normalized_output)

    if logger:
        logger.debug(
            f"Executing {'data-only' if s.execution_mode == 'data_only' else 'load-only'} mode with orchestrator"
        )

    result = _execute_orchestrated_run(
        orchestrator,
        benchmark_config,
        system_profile,
        database_config,
        s.phases_to_run,
        quiet=bool(s.quiet),
        no_progress=bool(s.no_progress),
        no_monitoring=bool(s.no_monitoring),
        execution_context=execution_context,
    )

    _data_or_load_handle_result(s, result, orchestrator, benchmark_config)


def _data_or_load_operation_status(result: Any, execution_mode: str) -> tuple[str, str]:
    """Derive operation_status / operation_name for data_only / load_only results."""
    if execution_mode == "data_only":
        return "COMPLETED", "Data generation"

    operation_name = "Data loading"
    operation_status = "NOT_RUN"
    if hasattr(result, "execution_phases") and result.execution_phases:
        if hasattr(result.execution_phases, "setup") and result.execution_phases.setup:
            if hasattr(result.execution_phases.setup, "data_loading") and result.execution_phases.setup.data_loading:
                operation_status = result.execution_phases.setup.data_loading.status
    return operation_status, operation_name


def _data_or_load_handle_result(
    s: types.SimpleNamespace,
    result: Any,
    orchestrator: BenchmarkOrchestrator,
    benchmark_config: BenchmarkConfig,
) -> None:
    """Export results and persist quick-restart config for data/load-only branch."""
    ctx = s.ctx
    if result.validation_status not in ["FAILED", "INTERRUPTED"]:
        if not s.quiet:
            console.print("\n[bold]Exporting results...[/bold]")
        platform_label = s.platform.lower() if s.platform else "unknown"
        mode_label = "data_only" if s.execution_mode == "data_only" else s.resolved_mode
        exported_files = _export_orchestrated_result(
            orchestrator=orchestrator,
            result=result,
            benchmark=s.benchmark,
            scale=s.scale,
            platform_label=platform_label,
            mode_label=mode_label,
            quiet=bool(s.quiet),
            export_formats=["json"],
        )

        operation_status, operation_name = _data_or_load_operation_status(result, s.execution_mode)

        if s.quiet:
            for _format_name, filepath in exported_files.items():
                click.echo(filepath)
        else:
            console.print(f"\n[green]✅ {operation_name} completed: {operation_status}[/green]")
            for format_name, filepath in exported_files.items():
                console.print(f"{format_name.upper()}: {filepath}")

        from benchbox.cli.preferences import save_last_run_config

        save_last_run_config(
            database=s.platform if s.platform else "none",
            benchmark=s.benchmark,
            scale=s.scale,
            tuning_mode=s.tuning,
            phases=s.phases_to_run,
            concurrency=benchmark_config.concurrency,
            compress_data=s.compress_data,
            compression_type=s.compression_type,
            compression_level=s.compression_level,
            test_execution_type=s.test_execution_type,
            seed=s.seed,
            output=s.output,
            additional_options={"table_mode": s.table_mode},
        )
    else:
        console.print(
            f"\n[red]❌ {'Data generation' if s.execution_mode == 'data_only' else 'Data loading'} failed: {result.validation_status}[/red]"
        )
        if result.validation_details:
            console.print(f"Error details: {result.validation_details}")
        ctx.exit(1)


def _run_interactive(s: types.SimpleNamespace) -> None:
    """Execute the full interactive wizard path."""
    ctx = s.ctx
    logger = s.logger
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

    from benchbox.cli.onboarding import check_and_run_first_time_setup

    is_first_run = check_and_run_first_time_setup()
    if not is_first_run:
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

    display_system_recommendations(system_profile)

    use_last_run = _interactive_try_quick_restart(s)
    if not use_last_run:
        _interactive_normal_flow(s, system_profile)

    _interactive_preflight_and_execute(s, system_profile)


def _interactive_try_quick_restart(s: types.SimpleNamespace) -> bool:
    """Offer quick-restart using saved last-run config; populate configs if accepted."""
    from benchbox.cli.preferences import format_last_run_summary, load_last_run_config

    last_run = load_last_run_config()
    if not (last_run and sys.stdin.isatty() and sys.stdout.isatty()):
        return False

    console.print("\n[bold cyan]Quick Restart[/bold cyan]")
    summary = format_last_run_summary(last_run)
    console.print(f"[dim]Last run: {summary}[/dim]")

    if not Confirm.ask("Reuse this configuration?", default=False):
        return False

    s.platform = last_run["database"]
    s.benchmark = last_run["benchmark"]
    s.scale = last_run["scale"]
    s.tuning = last_run.get("tuning_mode", "tuned")
    s.phases = last_run.get("phases", ["load", "power"])
    if not s.output:
        s.output = last_run.get("output")
    if not s.table_mode_cli_supplied:
        s.table_mode = str(last_run.get("table_mode", s.table_mode) or "native").lower()
    if s.table_mode == "external" and s.tuning.strip().lower() == "tuned":
        _reject_external_tuned(console, s.logger, s.ctx)

    console.print("[green]✓ Using saved configuration[/green]")

    if s.resolved_mode is None:
        caps = PlatformRegistry.get_platform_capabilities(s.platform)
        if caps is not None:
            s.resolved_mode = s.mode if s.mode is not None else caps.default_mode
        else:
            s.resolved_mode = "sql"
    db_manager = DatabaseManager()
    db_manager.set_verbosity(s.verbosity_settings)
    s.database_config = db_manager.create_config(
        platform=s.platform, runtime_overrides={"execution_mode": s.resolved_mode}
    )

    bench_manager = BenchmarkManager()
    bench_manager.set_verbosity(s.verbosity_settings)
    benchmark_info = bench_manager.benchmarks.get(s.benchmark, {})

    try:
        bench_manager.validate_scale_factor(s.benchmark, s.scale)
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]")
        if s.logger:
            s.logger.error(f"Scale factor validation failed: {e}")
        s.ctx.exit(1)

    _warn_tpcds_subscale(s)

    s.benchmark_config = BenchmarkConfig(
        name=s.benchmark,
        display_name=benchmark_info.get("display_name", s.benchmark.upper()),
        scale_factor=s.scale,
        queries=s.queries_to_run,
        concurrency=last_run.get("concurrency", 1),
        compress_data=last_run.get("compress_data", True),
        compression_type=last_run.get("compression_type", "zstd"),
        compression_level=last_run.get("compression_level", None),
        test_execution_type=last_run.get("test_execution_type", "power"),
        capture_plans=s.capture_plans,
        strict_plan_capture=s.strict_plan_capture,
        options={
            "estimated_time_range": benchmark_info.get("estimated_time_range", (0, 60)),
            "table_mode": s.table_mode,
            "complexity": benchmark_info.get("complexity", "medium"),
            **({"data_organization": s.data_organization_payload} if s.data_organization_payload is not None else {}),
            "force_regenerate": s.force_regenerate,
            "seed": s.seed,
            **({"power_iterations": s.iterations} if s.iterations is not None else {}),
            "ignore_memory_warnings": s.ignore_memory_warnings,
            **({"cache_dir": str(Path.home() / ".benchbox" / "datagen")} if s.global_cache else {}),
            **({"table_format": s.table_format_value} if s.table_format_value is not None else {}),
            **(
                {"table_format_compression": s.table_format_compression}
                if s.table_format_compression is not None
                else {}
            ),
            **(
                {"table_format_partition_cols": list(s.table_format_partition_cols)}
                if s.table_format_partition_cols
                else {}
            ),
            **({"presort": s.presort} if s.presort is not None else {}),
            **({"benchmark_options": s.parsed_benchmark_options} if s.parsed_benchmark_options else {}),
        },
    )
    s.benchmark_config.options.update(s.verbosity_settings.to_config())
    console.print()
    return True


def _interactive_normal_flow(s: types.SimpleNamespace, system_profile: Any) -> None:
    """Run the interactive step-by-step configuration flow when not quick-restarting."""
    console.print("\n[bold]Step 2 of 6:[/bold] [cyan]Execution Style[/cyan]")
    console.print("Choose how you want to run benchmarks...")
    db_manager = DatabaseManager()
    db_manager.set_verbosity(s.verbosity_settings)
    style_filter = db_manager.prompt_execution_style()

    console.print("\n[bold]Step 3 of 6:[/bold] [cyan]Database Selection[/cyan]")
    console.print("Selecting the best database for your benchmarks...")
    s.database_config = db_manager.select_database(style_filter=style_filter)

    _interactive_resolve_mode_for_selected_platform(s)
    _interactive_cloud_setup_if_needed(s)

    console.print("\n[bold]Step 4 of 6:[/bold] [cyan]Benchmark Configuration[/cyan]")
    console.print("Configuring benchmark parameters optimized for your system...")
    bench_manager = BenchmarkManager()
    bench_manager.set_verbosity(s.verbosity_settings)
    s.benchmark_config = bench_manager.select_benchmark()

    if sys.stdin.isatty() and sys.stdout.isatty():
        _interactive_collect_flags(s, db_manager, bench_manager)

    _interactive_tuning_step(s, system_profile)


def _interactive_resolve_mode_for_selected_platform(s: types.SimpleNamespace) -> None:
    """Resolve execution mode for the platform chosen in the interactive wizard."""
    ctx = s.ctx
    platform_type = s.database_config.type
    caps = PlatformRegistry.get_platform_capabilities(platform_type)
    if caps is not None:
        if s.mode is not None:
            if not PlatformRegistry.supports_mode(platform_type, s.mode):
                supported_modes = []
                if caps.supports_sql:
                    supported_modes.append("sql")
                if caps.supports_dataframe:
                    supported_modes.append("dataframe")
                console.print(f"[red]❌ Platform '{platform_type}' does not support {s.mode} mode[/red]")
                console.print(f"[yellow]Supported modes: {', '.join(supported_modes)}[/yellow]")
                ctx.exit(1)
            s.resolved_mode = s.mode
            s.database_config.execution_mode = s.resolved_mode
        elif hasattr(s.database_config, "execution_mode") and s.database_config.execution_mode in ("sql", "dataframe"):
            s.resolved_mode = s.database_config.execution_mode
        else:
            s.resolved_mode = caps.default_mode
            s.database_config.execution_mode = s.resolved_mode
    else:
        s.database_config.execution_mode = s.mode if s.mode is not None else "sql"


def _interactive_cloud_setup_if_needed(s: types.SimpleNamespace) -> None:
    """Perform cloud credentials + output location setup for cloud-requiring platforms."""
    ctx = s.ctx
    if not PlatformRegistry.requires_cloud_storage(s.database_config.type):
        return

    credentials_ok = check_and_setup_platform_credentials(
        platform=s.database_config.type,
        console_obj=console,
        interactive=not s.non_interactive,
    )

    if not credentials_ok:
        console.print(f"\n[red]❌ Cannot proceed without {s.database_config.type.upper()} credentials[/red]")
        console.print(f"\n[dim]To configure later: benchbox setup --platform {s.database_config.type}[/dim]")
        ctx.exit(1)

    if s.output:
        return
    default_output = None
    if PlatformRegistry.requires_cloud_storage(s.database_config.type):
        from benchbox.security.credentials import CredentialManager

        cred_manager = CredentialManager()
        if cred_manager.has_credentials(s.database_config.type):
            creds = cred_manager.get_platform_credentials(s.database_config.type)
            default_output = creds.get("default_output_location") if creds else None

    cloud_output_hint = prompt_cloud_output_location(
        platform_name=s.database_config.type,
        benchmark_name="your benchmark",
        scale_factor=s.scale or 1.0,
        non_interactive=s.non_interactive,
        default_output=default_output,
    )
    if cloud_output_hint:
        s.output = cloud_output_hint


def _interactive_prompt_phases_queries(
    s: types.SimpleNamespace, bench_manager: BenchmarkManager, prompt_phases_fn: Any, prompt_query_subset_fn: Any
) -> None:
    """Prompt for phases and optionally for the query subset in interactive mode."""
    s.phases_to_run = prompt_phases_fn(default_phases=s.phases_to_run)
    s.test_execution_type = _derive_execution_type(s.phases_to_run)
    s.execution_mode = s.test_execution_type
    s.benchmark_config.test_execution_type = s.test_execution_type

    if {"power", "standard"} & set(s.phases_to_run):
        bench_info = bench_manager.benchmarks.get(s.benchmark_config.name, {})
        num_queries = bench_info.get("num_queries", 0)
        if num_queries > 0:
            queries_selected = prompt_query_subset_fn(s.benchmark_config.name, num_queries)
            if queries_selected:
                s.benchmark_config.queries = queries_selected
                s.queries_to_run = queries_selected


def _interactive_prompt_force_and_validation(
    s: types.SimpleNamespace, prompt_force_fn: Any, prompt_validation_fn: Any
) -> None:
    """Prompt for force-regeneration and validation-mode selections if not CLI-set."""
    if s.force is None:
        force_mode_result = prompt_force_fn()
        if force_mode_result is not None:
            force_mode: str = force_mode_result
            s.force = ForceConfig(
                datagen=force_mode in ("all", "datagen"),
                upload=force_mode in ("all", "upload"),
            )

    if s.validation is None:
        validation_selection = prompt_validation_fn()
        if validation_selection is not None:
            s.validation_mode = validation_selection
            s.benchmark_config.options["validation_mode"] = s.validation_mode


def _interactive_prompt_output_and_format(
    s: types.SimpleNamespace,
    prompt_output_fn: Any,
    prompt_table_format_fn: Any,
) -> None:
    """Prompt for optional output directory and table-format selection."""
    if not s.output and not PlatformRegistry.requires_cloud_storage(s.database_config.type):
        custom_output = prompt_output_fn(default_output="benchmark_runs/")
        if custom_output:
            s.output = custom_output

    if s.table_format_value is None:
        selected_format, selected_compression = prompt_table_format_fn(s.database_config.type)
        if selected_format:
            s.table_format_value = selected_format
            if selected_compression:
                s.table_format_compression = selected_compression


def _interactive_collect_flags(
    s: types.SimpleNamespace, db_manager: DatabaseManager, bench_manager: BenchmarkManager
) -> None:
    """Collect Step 3.5 interactive prompts: phases, queries, official, seed, force, etc."""
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

    if not s.table_mode_cli_supplied:
        s.table_mode = prompt_table_mode(default_mode=s.table_mode)
        if s.table_mode == "external" and s.tuning.strip().lower() == "tuned":
            _reject_external_tuned(console, s.logger, s.ctx)
    else:
        console.print(f"[dim]Using table mode from CLI: {s.table_mode}[/dim]")

    _interactive_prompt_phases_queries(s, bench_manager, prompt_phases, prompt_query_subset)

    if not s.official:
        s.official, adjusted_scale = prompt_official_mode(s.benchmark_config.name, s.benchmark_config.scale_factor)
        if adjusted_scale is not None:
            s.benchmark_config.scale_factor = adjusted_scale

    _interactive_prompt_seed(s, prompt_seed)
    _interactive_prompt_force_and_validation(s, prompt_force_regeneration, prompt_validation_mode)

    if not s.capture_plans:
        s.capture_plans = prompt_capture_plans(s.database_config.type)
        if s.capture_plans:
            s.benchmark_config.capture_plans = True

    _interactive_prompt_output_and_format(s, prompt_output_location, prompt_table_format)

    if s.verbosity_settings.level == 0:
        verbose_level = prompt_verbose_output()
        if verbose_level > 0:
            s.verbosity_settings = VerbositySettings(
                level=verbose_level,
                verbose_enabled=verbose_level >= 1,
                very_verbose=verbose_level >= 2,
                quiet=False,
            )
            db_manager.set_verbosity(s.verbosity_settings)
            bench_manager.set_verbosity(s.verbosity_settings)

    if not s.parsed_platform_options:
        platform_opts = prompt_platform_options(s.database_config.type)
        if platform_opts:
            if s.database_config.options is None:
                s.database_config.options = {}
            s.database_config.options.update(platform_opts)


def _interactive_prompt_seed(s: types.SimpleNamespace, prompt_seed_fn: Any) -> None:
    """Prompt for seed (with official-mode treatment) and persist into config."""
    if s.seed is not None:
        return
    if s.official:
        console.print("\n[bold cyan]Seed (Required for Official Mode)[/bold cyan]")
        console.print("[dim]Official TPC runs require a seed for reproducibility.[/dim]")
        import random

        from rich.prompt import IntPrompt

        suggested_seed = random.randint(1, 999999)
        s.seed = IntPrompt.ask("Enter seed value", default=suggested_seed)
        console.print(f"[green]✓ Using seed: {s.seed}[/green]")
    else:
        s.seed = prompt_seed_fn()

    if s.seed is not None:
        s.benchmark_config.options["seed"] = s.seed


def _interactive_tuning_step(s: types.SimpleNamespace, system_profile: Any) -> None:
    """Step 5: interactive tuning configuration and final config wiring."""
    console.print("\n[bold]Step 5 of 6:[/bold] [cyan]Tuning Configuration[/cyan]")
    console.print("Configure database optimizations for best performance...")

    from benchbox.cli.tuning import run_tuning_wizard

    if sys.stdin.isatty() and sys.stdout.isatty():
        if Confirm.ask("\nWould you like to configure tuning options?", default=True):
            s.loaded_unified_config = run_tuning_wizard(
                benchmark=s.benchmark_config.name,
                platform=s.database_config.type,
                system_profile=system_profile,
                interactive=True,
            )
            s.tuning_enabled, s.tuning = infer_runtime_tuning_mode(s.loaded_unified_config)
            console.print("[green]✅ Tuning configuration completed[/green]")
            s.tuning_config_file = None
            s.use_auto_tuning = False
        else:
            s.loaded_unified_config = build_baseline_unified_config()
            console.print("[blue]Using baseline no-tuning configuration[/blue]")
            s.tuning_enabled = False
            s.tuning = "notuning"
            s.tuning_config_file = None
            s.use_auto_tuning = False
    else:
        s.loaded_unified_config = build_baseline_unified_config()
        console.print("[dim]Non-interactive mode: using baseline no-tuning configuration[/dim]")
        s.tuning_enabled = False
        s.tuning = "notuning"
        s.tuning_config_file = None
        s.use_auto_tuning = False

    if s.table_mode == "external" and s.tuning.strip().lower() == "tuned":
        _reject_external_tuned(console, s.logger, s.ctx)

    if getattr(s.database_config, "options", None) is None:
        s.database_config.options = {}
    s.database_config.options["tuning_enabled"] = s.tuning_enabled
    s.database_config.tuning_enabled = s.tuning_enabled
    s.database_config.unified_tuning_configuration = s.loaded_unified_config

    s.benchmark_config.options["unified_tuning_configuration"] = s.loaded_unified_config
    s.benchmark_config.options["tuning_enabled"] = s.tuning_enabled
    s.benchmark_config.options["seed"] = s.seed
    s.benchmark_config.options["table_mode"] = s.table_mode
    try:
        s.df_tuning_config = resolve_dataframe_tuning_config(
            platform_name=s.database_config.type,
            mode_name=s.resolved_mode,
            tuning_enabled_flag=s.tuning_enabled,
            use_auto_tuning_flag=s.use_auto_tuning,
            tuning_config_file_path=s.tuning_config_file,
            console=console,
            logger=s.logger,
            quiet=bool(s.quiet),
        )
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        s.ctx.exit(1)
    if s.df_tuning_config:
        s.benchmark_config.options["df_tuning_config"] = s.df_tuning_config
    else:
        s.benchmark_config.options.pop("df_tuning_config", None)

    if s.table_format_value is not None:
        s.benchmark_config.options["table_format"] = s.table_format_value
    if s.table_format_compression is not None:
        s.benchmark_config.options["table_format_compression"] = s.table_format_compression


def _interactive_preflight_and_execute(s: types.SimpleNamespace, system_profile: Any) -> None:
    """Run pre-flight cloud check, interactive preview, execution, and export."""
    ctx = s.ctx
    assert s.database_config is not None
    assert s.benchmark_config is not None
    if PlatformRegistry.requires_cloud_storage(s.database_config.type) and not s.output:
        console.print()
        console.print("[red]❌ Error: Cloud platform requires --output parameter[/red]")
        console.print(
            f"[yellow]The {s.database_config.type.upper()} platform requires a cloud "
            f"storage location for data staging.[/yellow]"
        )

        examples = PlatformRegistry.get_cloud_path_examples(s.database_config.type)
        if examples:
            console.print("\n[bold]Example paths:[/bold]")
            for example in examples:
                console.print(f"  • {example}")

        console.print("\n[dim]Options:[/dim]")
        console.print(f"  1. Set default: benchbox setup --platform {s.database_config.type}")
        console.print(
            f"  2. Use --output flag: benchbox run --platform {s.database_config.type} "
            f"--benchmark {s.benchmark_config.name} --output <cloud-path>"
        )

        if s.logger:
            s.logger.error(f"Cloud platform {s.database_config.type} requires output parameter but none provided")

        ctx.exit(1)

    if sys.stdin.isatty() and sys.stdout.isatty() and not s.non_interactive:
        _interactive_show_preview(s)

        if not Confirm.ask("Proceed with execution?", default=True):
            console.print("[yellow]Benchmark execution cancelled.[/yellow]")
            ctx.exit(0)

    console.print("\n[bold]Step 6 of 6:[/bold] [cyan]Benchmark Execution[/cyan]")
    console.print("Executing benchmark with platform optimizations...")

    execution_context = _build_execution_context(
        phases_to_run=s.phases_to_run,
        seed=s.seed,
        compression=s.comp_config,
        mode=s.mode,
        official=s.official,
        validation=s.val_config,
        force=s.force_config,
        queries_to_run=s.queries_to_run,
        capture_plans=s.capture_plans,
        strict_plan_capture=s.strict_plan_capture,
        non_interactive=s.non_interactive,
        tuning=s.tuning,
    )

    orchestrator = BenchmarkOrchestrator()
    orchestrator.set_verbosity(s.verbosity_settings)

    if s.output:
        normalized_output = normalize_output_root(s.output, s.benchmark_config.name, s.benchmark_config.scale_factor)
        assert normalized_output is not None
        orchestrator.set_custom_output_dir(normalized_output)

    result = _execute_orchestrated_run(
        orchestrator,
        s.benchmark_config,
        system_profile,
        s.database_config,
        s.phases_to_run,
        quiet=bool(s.quiet),
        no_progress=bool(s.no_progress),
        no_monitoring=bool(s.no_monitoring),
        execution_context=execution_context,
    )

    _interactive_handle_result(s, result, orchestrator)


def _interactive_show_preview(s: types.SimpleNamespace) -> None:
    """Show the pre-execution interactive preview panel."""
    from benchbox.cli.dryrun import display_interactive_preview

    force_str = None
    if s.force:
        if s.force.datagen and s.force.upload:
            force_str = "all"
        elif s.force.datagen:
            force_str = "datagen"
        elif s.force.upload:
            force_str = "upload"

    plan_config_str = None
    if s.plan_config:
        plan_parts = []
        if s.plan_config.sample_rate is not None:
            plan_parts.append(f"sample:{s.plan_config.sample_rate}")
        if s.plan_config.first_n is not None:
            plan_parts.append(f"first:{s.plan_config.first_n}")
        if s.plan_config.queries:
            plan_parts.append(f"queries:{','.join(s.plan_config.queries)}")
        if s.plan_config.strict:
            plan_parts.append("strict:true")
        if plan_parts:
            plan_config_str = ",".join(plan_parts)

    platform_options_dict = dict(s.platform_option_pairs) if s.platform_option_pairs else None

    display_interactive_preview(
        database_config=s.database_config,
        benchmark_config=s.benchmark_config,
        phases=s.phases_to_run,
        output=s.output,
        table_mode=s.table_mode,
        tuning=s.tuning if s.tuning != "notuning" else None,
        seed=s.seed,
        force=force_str,
        official=s.official,
        capture_plans=s.capture_plans,
        validation=s.validation_mode if s.validation_mode and s.validation_mode != "exact" else None,
        verbose=s.verbosity_settings.level,
        console_obj=console,
        platform_options=platform_options_dict,
        plan_config=plan_config_str,
        presort=s.presort,
        sorted_ingestion_mode=s.sorted_ingestion_mode,
        sorted_ingestion_method=s.sorted_ingestion_method,
        global_cache=s.global_cache,
        benchmark_options=dict(s.benchmark_option_pairs) if s.benchmark_option_pairs else None,
    )


def _interactive_handle_result(s: types.SimpleNamespace, result: Any, orchestrator: BenchmarkOrchestrator) -> None:
    """Export results, render charts, publish, and save last-run config (interactive branch)."""
    ctx = s.ctx
    if result.validation_status not in ["FAILED", "INTERRUPTED"]:
        console.print("\n[bold]Step 5:[/bold] Export Results")
        export_formats = s.config.get("output.formats", ["json"])
        exported_files = _export_orchestrated_result(
            orchestrator=orchestrator,
            result=result,
            benchmark=s.benchmark_config.name,
            scale=s.benchmark_config.scale_factor,
            platform_label=s.database_config.type.lower(),
            mode_label=s.resolved_mode,
            quiet=bool(s.quiet),
            export_formats=export_formats,
        )

        if s.quiet:
            for _format_name, filepath in exported_files.items():
                click.echo(filepath)
        else:
            console.print(f"\n[green]✅ Benchmark completed with status: {result.validation_status}[/green]")
            console.print(f"Result ID: [cyan]{result.execution_id}[/cyan]")
            for format_name, filepath in exported_files.items():
                console.print(f"{format_name.upper()}: [dim]{filepath}[/dim]")

        _render_post_run_charts(result, console, s.quiet)

        if s.publish:
            json_bundle = exported_files.get("json")
            if json_bundle:
                from benchbox.cli.commands.publish import publish_bundle

                if not s.quiet:
                    console.print("\n[bold]Publishing result bundle...[/bold]")
                publish_bundle(
                    source_bundle=json_bundle,
                    target=s.publish_target,
                    label=s.publish_label,
                    quiet=bool(s.quiet),
                )

        from benchbox.cli.preferences import save_last_run_config

        save_last_run_config(
            database=s.database_config.type,
            benchmark=s.benchmark_config.name,
            scale=s.benchmark_config.scale_factor,
            tuning_mode=s.tuning,
            phases=s.phases_to_run,
            concurrency=s.benchmark_config.concurrency,
            compress_data=s.benchmark_config.compress_data,
            compression_type=s.benchmark_config.compression_type,
            compression_level=s.benchmark_config.compression_level,
            test_execution_type=s.benchmark_config.test_execution_type,
            seed=s.seed,
            output=s.output,
            additional_options={"table_mode": s.table_mode},
        )
    else:
        console.print(f"\n[red]❌ Benchmark failed with status: {result.validation_status}[/red]")
        ctx.exit(1)


@click.command("run", cls=BenchBoxCommand)
# === Core Options (Tier 1 - Always visible) ===
@click.option(
    "--platform",
    type=str,
    help="Platform with optional deployment mode (platform:mode). Examples: duckdb, clickhouse:server, firebolt:core",
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
        "DuckDB uses EXPLAIN (ANALYZE, FORMAT JSON) by default - actual per-operator timing and "
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
@click.option(
    "--benchmark-option",
    "benchmark_option_pairs",
    type=BenchmarkOptionParamType(),
    multiple=True,
    hidden=True,
    help=(
        "Benchmark option in KEY=VALUE form (repeatable). "
        "Benchmark-specific parameters (e.g. taxi_types=yellow,green for nyctaxi, "
        "skew_preset=heavy for tpch_skew). "
        "Use --help-topic benchmarks to see available options per benchmark."
    ),
)
@advanced_option(
    "--mode",
    type=click.Choice(["sql", "dataframe"], case_sensitive=False),
    default=None,
    help="Execution mode: sql or dataframe",
)
@advanced_option("--seed", type=int, help="RNG seed for query parameter generation")
@advanced_option(
    "--iterations",
    type=click.IntRange(min=1),
    default=None,
    help="Number of power test measurement iterations (default: 3). Power phase only.",
)
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
    benchmark_option_pairs: tuple[tuple[str, str], ...],
    mode: str | None,
    seed: int | None,
    iterations: int | None,
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
    Deployment Targets:
      benchbox run --platform clickhouse:local --benchmark tpch    # ClickHouse local mode via chDB
      benchbox run --platform clickhouse:server --benchmark tpch   # ClickHouse server
      benchbox run --platform clickhouse-cloud --benchmark tpch    # ClickHouse Cloud
      benchbox run --platform firebolt:core --benchmark tpch       # Firebolt Core (Docker)
      benchbox run --platform firebolt:cloud --benchmark tpch      # Firebolt Cloud

    Use --help-topic examples for more, --help-topic all for advanced options.
    """
    s = types.SimpleNamespace(
        ctx=ctx,
        platform=platform,
        benchmark=benchmark,
        scale=scale,
        output=output,
        phases=phases,
        queries=queries,
        tuning=tuning,
        table_mode=table_mode,
        sorted_ingestion_mode=sorted_ingestion_mode,
        sorted_ingestion_method=sorted_ingestion_method,
        dry_run=dry_run,
        force=force,
        verbose=verbose,
        quiet=quiet,
        non_interactive=non_interactive,
        official=official,
        capture_plans=capture_plans,
        plan_config=plan_config,
        compression=compression,
        table_format=table_format,
        presort=presort,
        validation=validation,
        platform_option_pairs=platform_option_pairs,
        benchmark_option_pairs=benchmark_option_pairs,
        mode=mode,
        seed=seed,
        iterations=iterations,
        no_monitoring=no_monitoring,
        no_progress=no_progress,
        ignore_memory_warnings=ignore_memory_warnings,
        global_cache=global_cache,
        publish=publish,
        publish_target=publish_target,
        publish_label=publish_label,
    )
    _prepare_run_state(s)

    if s.dry_run:
        _run_dry_run(s)
        return

    if s.test_execution_type not in {"data_only", "load_only"} and s.platform and s.benchmark:
        _run_direct(s)
        return

    if s.test_execution_type in {"data_only", "load_only"}:
        _run_data_or_load_only(s)
        return

    _run_interactive(s)


__all__ = ["run", "BenchmarkOptionParamType", "PlatformOptionParamType", "setup_verbose_logging"]
