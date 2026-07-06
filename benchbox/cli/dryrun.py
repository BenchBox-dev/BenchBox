"""Dry run display functionality for BenchBox CLI.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

# Import DryRunExecutor from core module
from benchbox.core.dryrun import DryRunExecutor as CoreDryRunExecutor
from benchbox.core.schemas import BenchmarkConfig, DatabaseConfig, DryRunResult
from benchbox.utils.printing import quiet_console

if TYPE_CHECKING:  # pragma: no cover - typing only
    from rich.console import Console

# Module-level console handle used by display helpers.
# Cast to Console for type checking since QuietConsoleProxy forwards all calls to Console.
console: Any = quiet_console


def generate_cli_command(
    platform: str,
    benchmark: str,
    scale: float,
    phases: list[str] | None = None,
    queries: list[str] | None = None,
    tuning: str | None = None,
    seed: int | None = None,
    iterations: int | None = None,
    output: str | None = None,
    table_mode: str | None = None,
    table_format: str | None = None,
    compression: str | None = None,
    mode: str | None = None,
    force: str | None = None,
    official: bool = False,
    capture_plans: bool = False,
    analyze_plans: bool | None = None,
    show_plans: bool = False,
    strict_translation: bool = False,
    normalize_plan_literals: bool = False,
    stats_reset: bool | None = None,
    stats_per_table_timing: bool = False,
    validation: str | None = None,
    verbose: int = 0,
    platform_options: dict[str, str] | None = None,
    plan_config: str | None = None,
    presort: str | None = None,
    sorted_ingestion_mode: str | None = None,
    sorted_ingestion_method: str | None = None,
    global_cache: bool = False,
    publish: bool = False,
    publish_target: str | None = None,
    publish_label: str | None = None,
    benchmark_options: dict[str, str] | None = None,
    funding: str | None = None,
    result_source: str | None = None,
) -> str:
    """Generate equivalent CLI command from interactive wizard configuration.

    Args:
        platform: Platform name (duckdb, snowflake, etc.)
        benchmark: Benchmark name (tpch, tpcds, etc.)
        scale: Scale factor
        phases: List of phases to run
        queries: Query subset (e.g., ["Q1", "Q6"])
        tuning: Tuning mode (tuned, notuning, auto, or YAML path)
        seed: RNG seed for reproducibility
        output: Output directory
        table_mode: Table mode (native, external)
        table_format: Table format (parquet, vortex, delta, iceberg, or format:compression)
        compression: Compression config (zstd:9, gzip:6, etc.), None when not explicitly set
        mode: Execution mode (sql, dataframe)
        force: Force mode (all, datagen, upload)
        official: TPC-compliant mode
        capture_plans: Capture query execution plans
        strict_translation: Fail when SQL dialect translation falls back
        normalize_plan_literals: Also record a literal-normalized plan fingerprint
        stats_reset: Cold-stats vs warm-stats control for the statistics phase
        stats_per_table_timing: Record a per-table statistics-build timing breakdown
        validation: Validation mode (exact, loose, range, disabled, full)
        verbose: Verbosity level (0=off, 1=-v, 2=-vv)
        platform_options: Platform-specific key=value options
        plan_config: Plan capture config string
        presort: Pre-sort mode (parquet-sorted, delta-sorted, iceberg-sorted)
        sorted_ingestion_mode: Cloud sorted-ingestion strategy (off, auto, force)
        sorted_ingestion_method: Cloud sorted-ingestion method override
        global_cache: Use global DataFrame cache
        publish: Publish the exported result bundle after a successful run
        publish_target: Destination for --publish (local dir or cloud URI)
        publish_label: Trust label for --publish
        funding: Funding-source disclosure recorded in the bundle's provenance block
        result_source: Advisory producer hint recorded in the bundle's provenance block

    Returns:
        Complete CLI command string
    """
    parts = ["benchbox run"]
    parts.append(f"--platform {platform}")
    parts.append(f"--benchmark {benchmark}")

    if scale != 0.01:
        parts.append(f"--scale {scale}")

    # List-value flags: (value, flag, skip_value) - joined with comma
    _LIST_PARAMS = [
        (phases, "--phases", ["power"]),
        (queries, "--queries", None),
    ]
    for value, flag, skip in _LIST_PARAMS:
        if value and value != skip:
            parts.append(f"{flag} {','.join(value)}")

    # Simple value flags: (value, flag, skip_value)
    _VALUE_PARAMS = [
        (tuning, "--tuning", "notuning"),
        (seed, "--seed", None),
        (iterations, "--iterations", None),
        (output, "--output", None),
        (table_mode, "--table-mode", "native"),
        (table_format, "--table-format", None),
        (compression, "--compression", None),
        (mode, "--mode", None),
        (force, "--force", None),
        (validation, "--validation", None),
        (plan_config, "--plan-config", None),
        (presort, "--presort", None),
        (sorted_ingestion_mode, "--sorted-ingestion-mode", "off"),
        (sorted_ingestion_method, "--sorted-ingestion-method", None),
        (funding, "--funding", None),
        (result_source, "--result-source", None),
    ]
    for value, flag, skip in _VALUE_PARAMS:
        if value is not None and value != skip:
            parts.append(f"{flag} {value}")

    # Repeated key=value flags
    if platform_options:
        for key, val in sorted(platform_options.items()):
            parts.append(f"--platform-option {key}={val}")

    if benchmark_options:
        for key, val in sorted(benchmark_options.items()):
            parts.append(f"--benchmark-option {key}={val}")

    # Boolean flags: (value, flag)
    _BOOL_PARAMS = [
        (official, "--official"),
        (capture_plans, "--capture-plans"),
        (show_plans, "--show-plans"),
        (strict_translation, "--strict-translation"),
        (normalize_plan_literals, "--normalize-plan-literals"),
        (stats_per_table_timing, "--stats-per-table-timing"),
        (global_cache, "--global-cache"),
        (publish, "--publish"),
    ]
    for flag_value, flag in _BOOL_PARAMS:
        if flag_value:
            parts.append(flag)

    # analyze_plans is a tri-state --analyze-plans/--no-analyze-plans flag: only
    # emit it when explicitly set (None = not passed, adapter default applies).
    if analyze_plans is not None:
        parts.append("--analyze-plans" if analyze_plans else "--no-analyze-plans")

    # stats_reset is a tri-state --stats-reset/--no-stats-reset flag: only emit
    # it when explicitly set (None = not passed, PR #980 default applies).
    if stats_reset is not None:
        parts.append("--stats-reset" if stats_reset else "--no-stats-reset")

    # Publish target/label only meaningful when --publish is set
    if publish:
        if publish_target and publish_target != "benchmark_runs/published":
            parts.append(f"--publish-target {publish_target}")
        if publish_label and publish_label != "maintainer-run":
            parts.append(f"--publish-label {publish_label}")

    # Verbose flags (-v, -vv)
    if verbose > 0:
        parts.append("-" + "v" * min(verbose, 2))

    return " \\\n    ".join(parts)


def _format_compression_str(
    compress_data: bool,
    compression_type: str | None,
    compression_level: int | None,
    default_type: str | None = None,
) -> str | None:
    """Format compression type and level into a display string."""
    if not compress_data:
        return None
    comp_str = compression_type or default_type
    if comp_str is None:
        return None
    if compression_level:
        comp_str += f":{compression_level}"
    return comp_str


def _resolve_cli_table_format(options: dict[str, Any]) -> str | None:
    """Resolve table format with optional compression suffix for CLI display."""
    table_format = options.get("table_format")
    if not table_format:
        return None
    fmt_compression = options.get("table_format_compression")
    if fmt_compression and fmt_compression != "snappy":
        table_format = f"{table_format}:{fmt_compression}"
    return table_format


def display_interactive_preview(
    database_config: DatabaseConfig,
    benchmark_config: BenchmarkConfig,
    phases: list[str],
    output: str | None = None,
    table_mode: str = "native",
    tuning: str | None = None,
    seed: int | None = None,
    force: str | None = None,
    official: bool = False,
    capture_plans: bool = False,
    analyze_plans: bool | None = None,
    strict_translation: bool = False,
    validation: str | None = None,
    verbose: int = 0,
    console_obj: Console | None = None,
    platform_options: dict[str, str] | None = None,
    plan_config: str | None = None,
    presort: str | None = None,
    sorted_ingestion_mode: str | None = None,
    sorted_ingestion_method: str | None = None,
    global_cache: bool = False,
    benchmark_options: dict[str, str] | None = None,
) -> None:
    """Display a preview summary for interactive wizard users.

    Shows configuration summary, resource estimates, and equivalent CLI command
    before proceeding with benchmark execution.

    Args:
        database_config: Database configuration from wizard
        benchmark_config: Benchmark configuration from wizard
        phases: Phases to execute
        output: Output directory (if specified)
        table_mode: Table mode (native or external)
        tuning: Tuning mode
        seed: RNG seed
        force: Force mode (all, datagen, upload)
        official: TPC-compliant mode
        capture_plans: Capture query execution plans
        strict_translation: Fail when SQL dialect translation falls back
        validation: Validation mode
        verbose: Verbosity level (0=off, 1=-v, 2=-vv)
        console_obj: Rich console for output
        platform_options: Platform-specific key=value options
        plan_config: Plan capture config string
        presort: Pre-sort mode
        sorted_ingestion_mode: Cloud sorted-ingestion strategy
        sorted_ingestion_method: Cloud sorted-ingestion method override
        global_cache: Use global DataFrame cache
    """
    display_console = console_obj or console

    display_console.print()
    display_console.print(
        Panel.fit(
            Text("Configuration Preview", style="bold cyan"),
            style="cyan",
        )
    )

    # Configuration summary table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Setting", style="cyan", min_width=18)
    table.add_column("Value", style="white")

    # Platform info
    platform_display = database_config.type.upper()
    if hasattr(database_config, "execution_mode") and database_config.execution_mode:
        platform_display += f" ({database_config.execution_mode} mode)"
    table.add_row("Platform:", platform_display)

    # Benchmark info
    table.add_row("Benchmark:", f"{benchmark_config.display_name} at scale {benchmark_config.scale_factor}")

    # Phases
    table.add_row("Phases:", ", ".join(phases))

    # Queries
    if benchmark_config.queries:
        table.add_row("Queries:", f"{len(benchmark_config.queries)} selected")
    else:
        num_queries = getattr(benchmark_config, "options", {}).get("num_queries", "all")
        table.add_row("Queries:", str(num_queries) if num_queries != "all" else "All")

    # Data-driven optional rows to reduce per-field branching
    options = getattr(benchmark_config, "options", {})
    table_fmt = options.get("table_format")
    optional_rows: list[tuple[str, str | None]] = [
        ("Tuning:", tuning),
        ("Seed:", str(seed) if seed is not None else None),
        ("Output:", output),
        ("Table Mode:", table_mode),
        (
            "Compression:",
            _format_compression_str(
                benchmark_config.compress_data,
                benchmark_config.compression_type,
                benchmark_config.compression_level,
                default_type="zstd",
            ),
        ),
        (
            "Table Format:",
            f"{table_fmt.capitalize()} ({options.get('table_format_compression', 'snappy')})" if table_fmt else None,
        ),
        ("Pre-sort:", presort),
        (
            "Sorted Ingestion:",
            sorted_ingestion_mode if sorted_ingestion_mode and sorted_ingestion_mode != "off" else None,
        ),
        ("Ingestion Method:", sorted_ingestion_method),
        ("Plan Config:", plan_config),
        ("Strict Translation:", "Enabled" if strict_translation else None),
        ("Global Cache:", "Enabled" if global_cache else None),
    ]
    for label, value in optional_rows:
        if value is not None:
            table.add_row(label, value)

    if platform_options:
        for key, val in sorted(platform_options.items()):
            table.add_row(f"Platform ({key}):", val)

    time_range = options.get("estimated_time_range")
    if time_range:
        table.add_row("Est. Time:", f"{time_range[0]}-{time_range[1]} minutes")

    display_console.print(table)

    # Generate and show CLI command
    display_console.print()
    display_console.print("[bold]Equivalent CLI command:[/bold]")

    table_format = _resolve_cli_table_format(options)
    compression_str = _format_compression_str(
        benchmark_config.compress_data,
        benchmark_config.compression_type,
        benchmark_config.compression_level,
    )

    cli_cmd = generate_cli_command(
        platform=database_config.type,
        benchmark=benchmark_config.name,
        scale=benchmark_config.scale_factor,
        phases=phases if phases != ["power"] else None,
        queries=benchmark_config.queries,
        tuning=tuning,
        seed=seed,
        output=output,
        table_mode=table_mode,
        table_format=table_format,
        compression=compression_str,
        mode=getattr(database_config, "execution_mode", None),
        force=force,
        official=official,
        capture_plans=capture_plans,
        analyze_plans=analyze_plans,
        strict_translation=strict_translation,
        validation=validation,
        verbose=verbose,
        platform_options=platform_options,
        plan_config=plan_config,
        presort=presort,
        sorted_ingestion_mode=sorted_ingestion_mode,
        sorted_ingestion_method=sorted_ingestion_method,
        global_cache=global_cache,
        benchmark_options=benchmark_options,
    )

    display_console.print(f"[dim]{cli_cmd}[/dim]")
    display_console.print()


class DryRunDisplay:
    """Handles display of dry run results."""

    def __init__(self, console: Console | None = None):
        self.console = console or quiet_console

    def display_dry_run_results(self, result: DryRunResult):
        """Display dry run results to console."""
        self.console.print(
            Panel.fit(
                Text("DRY RUN MODE - No queries will be executed", style="bold yellow"),
                style="yellow",
            )
        )

        self._display_configuration_summary(result)

        self._display_query_preview(result.queries, result)

        # Display schema based on execution mode
        if result.execution_mode == "dataframe" and getattr(result, "dataframe_schema", None):
            self._display_schema_preview(result.dataframe_schema, syntax_lang="python", title="DataFrame Schema")
        elif result.schema_sql:
            self._display_schema_preview(result.schema_sql, syntax_lang="sql", title="Database Schema")

        if result.tuning_config:
            self._display_tuning_config(result.tuning_config)

        # Display DDL preview with tuning clauses
        if result.ddl_preview:
            self._display_ddl_preview(result.ddl_preview)

        # Display post-load statements
        if result.post_load_statements:
            self._display_post_load_statements(result.post_load_statements)

        if result.estimated_resources:
            self._display_resource_estimates(result.estimated_resources)

        if result.warnings:
            self._display_warnings(result.warnings)

    def _display_configuration_summary(self, result: DryRunResult):
        self.console.print("\n[bold]Configuration Summary[/bold]")

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("Category", style="cyan")
        table.add_column("Setting", style="white")
        table.add_column("Value", style="yellow")

        benchmark_config = result.benchmark_config
        table.add_row("Benchmark", "Name", str(benchmark_config.get("name", "N/A")))
        table.add_row("", "Scale Factor", str(benchmark_config.get("scale_factor", "N/A")))
        table.add_row("", "Concurrency", str(benchmark_config.get("concurrency", 1)))

        database_config = result.database_config
        table.add_row("Database", "Type", str(database_config.get("type", "N/A")))
        table.add_row("", "Name", str(database_config.get("name", "N/A")))
        table.add_row("", "Execution Mode", result.execution_mode.upper())

        system_config = result.system_profile
        table.add_row("System", "CPU Cores", str(system_config.get("cpu_cores_logical", "N/A")))
        table.add_row("", "Memory (GB)", str(system_config.get("memory_total_gb", "N/A")))
        table.add_row("", "Platform", str(system_config.get("os_name", "N/A")))

        if result.query_preview:
            test_execution_type = result.query_preview.get("test_execution_type", "standard")
            execution_context = result.query_preview.get("execution_context", "Sequential execution")
        else:
            test_execution_type = "standard"
            execution_context = "Sequential execution"
        table.add_row(
            "Test Execution",
            "Type",
            self._format_test_execution_type(test_execution_type),
        )
        table.add_row("", "Context", execution_context)

        # Data layout: table mode, table format, compression
        options = benchmark_config.get("options", {})
        table_mode = str(options.get("table_mode", "native") or "native").lower()
        table_format = options.get("table_format") or benchmark_config.get("table_format")
        compress_data = benchmark_config.get("compress_data", False)
        compression_type = benchmark_config.get("compression_type")
        compression_level = benchmark_config.get("compression_level")

        has_data_layout = table_mode != "native" or table_format or compress_data
        if has_data_layout:
            category = "Data Layout"
            if table_mode != "native":
                table.add_row(category, "Table Mode", table_mode.capitalize())
                category = ""
            if table_format:
                table.add_row(category, "Table Format", table_format.capitalize())
                category = ""
            if compress_data and compression_type:
                comp_display = compression_type
                if compression_level is not None:
                    comp_display += f":{compression_level}"
                table.add_row(category, "Compression", comp_display)
                category = ""

        # Tuning
        tuning_config = result.tuning_config
        if tuning_config:
            tuning_type = tuning_config.get("tuning_type", "tuned")
            table.add_row("Tuning", "Mode", tuning_type.capitalize())
        else:
            table.add_row("Tuning", "Mode", "Disabled (baseline)")

        constraint_config = result.constraint_config or {}
        table.add_row(
            "Constraints",
            "Primary Keys",
            str(constraint_config.get("enable_primary_keys", "N/A")),
        )
        table.add_row(
            "",
            "Foreign Keys",
            str(constraint_config.get("enable_foreign_keys", "N/A")),
        )

        self.console.print(table)

    def _display_query_preview(self, queries: dict[str, str], result: DryRunResult | None = None):
        if not queries:
            self.console.print("\n[yellow]No queries available for preview[/yellow]")
            return

        test_execution_type = "standard"
        execution_context = "Sequential execution"
        execution_mode = "sql"
        if result and result.query_preview:
            test_execution_type = result.query_preview.get("test_execution_type", "standard")
            execution_context = result.query_preview.get("execution_context", "Sequential execution")
        if result:
            execution_mode = getattr(result, "execution_mode", "sql")

        # Separate maintenance operations from regular queries
        maintenance_ops = {k: v for k, v in queries.items() if k in ("RF1", "RF2")}
        regular_queries = {k: v for k, v in queries.items() if k not in ("RF1", "RF2") and not k.startswith("_")}

        # Determine syntax highlighting language based on execution mode
        syntax_lang = "python" if execution_mode == "dataframe" else "sql"

        preview_title = self._get_preview_title(test_execution_type, len(regular_queries))
        if execution_mode == "dataframe":
            preview_title = "DataFrame Query Preview"
        self.console.print(f"\n[bold]{preview_title}[/bold] ([dim]{execution_context}[/dim])")

        # Filter out error entries for DataFrame mode (use regular_queries now)
        display_queries = list(regular_queries.items())

        for _i, (query_id, query_content) in enumerate(display_queries[:3]):
            display_title = self._format_query_display_title(query_id, test_execution_type)
            if execution_mode == "dataframe":
                display_title = f"DataFrame Query {query_id}"
            self.console.print(f"\n[cyan]{display_title}:[/cyan]")

            display_content = query_content
            if len(query_content) > 500:
                display_content = query_content[:500] + "\n... [truncated]"

            syntax = Syntax(display_content, syntax_lang, theme="monokai", line_numbers=False)
            panel_title = self._format_panel_title(query_id, test_execution_type)
            if execution_mode == "dataframe":
                panel_title = f"Query {query_id} (Python)"
            self.console.print(Panel(syntax, title=panel_title, border_style="blue"))

        if len(display_queries) > 3:
            remaining = len(display_queries) - 3
            remaining_type = "operations" if test_execution_type == "maintenance" else "queries"
            self.console.print(f"\n[dim]... and {remaining} more {remaining_type}[/dim]")

        # Display maintenance operations in separate section
        if maintenance_ops:
            self._display_maintenance_operations(maintenance_ops)

    def _display_schema_preview(self, schema_content: str, syntax_lang: str = "sql", title: str = "Database Schema"):
        self.console.print("\n[bold]Schema Preview[/bold]")

        display_content = schema_content
        if len(schema_content) > 1000:
            display_content = schema_content[:1000] + "\n... [truncated]"

        syntax = Syntax(display_content, syntax_lang, theme="monokai", line_numbers=False)
        self.console.print(Panel(syntax, title=title, border_style="green"))

    def _display_tuning_config(self, tuning_config: dict[str, Any]):
        self.console.print("\n[bold]Tuning Configuration[/bold]")

        if not tuning_config:
            self.console.print("[dim]No tuning configuration available[/dim]")
            return

        if tuning_config.get("constraints"):
            self._display_constraints_table(tuning_config["constraints"])

        if tuning_config.get("table_tunings"):
            self._display_table_tunings(tuning_config["table_tunings"])

        platform_opts = tuning_config.get("platform_optimizations")
        if platform_opts and any(platform_opts.values()):
            self._display_platform_optimizations(platform_opts)

        df_tuning = tuning_config.get("dataframe_tuning")
        if df_tuning:
            self._display_dataframe_tuning(df_tuning)

        if not tuning_config.get("table_tunings") and not tuning_config.get("constraints") and not df_tuning:
            self.console.print("[dim]No detailed tuning configuration available[/dim]")

    def _display_constraints_table(self, constraints: dict[str, Any]) -> None:
        """Display constraints configuration table."""
        constraints_table = Table(show_header=True, header_style="bold blue")
        constraints_table.add_column("Constraint Type", style="cyan")
        constraints_table.add_column("Enabled", style="white")
        constraints_table.add_column("Configuration", style="yellow")

        if constraints.get("primary_keys"):
            pk_config = constraints["primary_keys"]
            config_str = f"Uniqueness: {pk_config.get('enforce_uniqueness', 'N/A')}, Nullable: {pk_config.get('nullable', 'N/A')}"
            constraints_table.add_row("Primary Keys", str(pk_config.get("enabled", False)), config_str)

        if constraints.get("foreign_keys"):
            fk_config = constraints["foreign_keys"]
            config_str = f"Referential Integrity: {fk_config.get('enforce_referential_integrity', 'N/A')}"
            constraints_table.add_row("Foreign Keys", str(fk_config.get("enabled", False)), config_str)

        self.console.print(constraints_table)

    def _display_table_tunings(self, table_tunings: dict[str, Any]) -> None:
        """Display table organization tunings."""
        self.console.print("\n[bold]Table Organization Tunings[/bold]")

        tuning_table = Table(show_header=True, header_style="bold blue")
        tuning_table.add_column("Table", style="cyan")
        tuning_table.add_column("Tuning Type", style="white")
        tuning_table.add_column("Columns", style="yellow")

        for table_name, table_config in table_tunings.items():
            first_row = True
            for tuning_type in ["partitioning", "sorting", "clustering", "distribution"]:
                columns = table_config.get(tuning_type)
                if columns:
                    column_names = [f"{col['name']} ({col['type']})" for col in columns]
                    column_str = ", ".join(column_names)
                    tuning_table.add_row(table_name if first_row else "", tuning_type.title(), column_str)
                    first_row = False

        self.console.print(tuning_table)

    def _display_platform_optimizations(self, platform_opts: dict[str, Any]) -> None:
        """Display platform optimization settings."""
        self.console.print("\n[bold]Platform Optimizations[/bold]")

        platform_table = Table(show_header=True, header_style="bold blue")
        platform_table.add_column("Optimization", style="cyan")
        platform_table.add_column("Enabled", style="white")

        for opt_name, opt_value in platform_opts.items():
            if opt_value:
                platform_table.add_row(opt_name.replace("_", " ").title(), str(opt_value))

        if platform_table.row_count > 0:
            self.console.print(platform_table)

    def _display_dataframe_tuning(self, df_tuning: dict[str, Any]) -> None:
        """Display DataFrame tuning configuration."""
        self.console.print("\n[bold]DataFrame Tuning Configuration[/bold]")

        df_table = Table(show_header=True, header_style="bold blue")
        df_table.add_column("Category", style="cyan")
        df_table.add_column("Setting", style="white")
        df_table.add_column("Value", style="yellow")

        for section_key, category_name in [
            ("parallelism", "Parallelism"),
            ("memory", "Memory"),
            ("execution", "Execution"),
        ]:
            section = df_tuning.get(section_key)
            if section:
                self._add_df_tuning_section(df_table, category_name, section)

        if df_tuning.get("write"):
            self._add_df_write_layout(df_table, df_tuning["write"])

        if df_table.row_count > 0:
            self.console.print(df_table)

    def _add_df_tuning_section(self, df_table: Table, category_name: str, section: dict[str, Any]) -> None:
        """Add a runtime tuning section to the DataFrame table."""
        first_row = True
        for key, value in section.items():
            category = category_name if first_row else ""
            df_table.add_row(category, key.replace("_", " ").title(), str(value))
            first_row = False

    def _add_df_write_layout(self, df_table: Table, write: dict[str, Any]) -> None:
        """Add write layout settings to the DataFrame table."""
        first_row = True

        if write.get("sort_by"):
            sort_cols = [f"{col['name']} ({col['order']})" for col in write["sort_by"]]
            df_table.add_row("Write Layout", "Sort By", ", ".join(sort_cols))
            first_row = False

        if write.get("partition_by"):
            part_cols = [f"{col['name']} ({col['strategy']})" for col in write["partition_by"]]
            df_table.add_row("Write Layout" if first_row else "", "Partition By", ", ".join(part_cols))
            first_row = False

        if write.get("row_group_size"):
            df_table.add_row("Write Layout" if first_row else "", "Row Group Size", f"{write['row_group_size']:,}")
            first_row = False

        if write.get("repartition_count"):
            df_table.add_row("Write Layout" if first_row else "", "Repartition Count", str(write["repartition_count"]))
            first_row = False

        if write.get("compression"):
            comp_str = write["compression"]
            if write.get("compression_level"):
                comp_str += f":{write['compression_level']}"
            df_table.add_row("Write Layout" if first_row else "", "Compression", comp_str)
            first_row = False

        if write.get("dictionary_columns"):
            df_table.add_row(
                "Write Layout" if first_row else "", "Dictionary Columns", ", ".join(write["dictionary_columns"])
            )

    def _display_ddl_preview(self, ddl_preview: dict[str, dict[str, Any]]):
        """Display DDL preview with tuning clauses per table."""
        if not ddl_preview:
            return

        self.console.print("\n[bold]DDL Preview (Tuning Clauses)[/bold]")

        for table_name, table_info in ddl_preview.items():
            self.console.print(f"\n[cyan]Table: {table_name}[/cyan]")

            # Display tuning summary
            tuning_summary = table_info.get("tuning_summary", {})
            if tuning_summary:
                summary_parts = []
                if tuning_summary.get("sort_by"):
                    summary_parts.append(f"Sort: {tuning_summary['sort_by']}")
                if tuning_summary.get("partition_by"):
                    summary_parts.append(f"Partition: {tuning_summary['partition_by']}")
                if tuning_summary.get("cluster_by"):
                    summary_parts.append(f"Cluster: {tuning_summary['cluster_by']}")
                if tuning_summary.get("distribution_style"):
                    summary_parts.append(f"Dist: {tuning_summary['distribution_style']}")
                if tuning_summary.get("distribution_key"):
                    summary_parts.append(f"DistKey: {tuning_summary['distribution_key']}")

                self.console.print(f"  [dim]Tuning: {' | '.join(summary_parts)}[/dim]")

            # Display DDL clauses with syntax highlighting
            ddl_clauses = table_info.get("ddl_clauses")
            if ddl_clauses:
                syntax = Syntax(ddl_clauses, "sql", theme="monokai", line_numbers=False)
                self.console.print(Panel(syntax, border_style="green", padding=(0, 1)))

    def _display_post_load_statements(self, post_load_statements: dict[str, list[str]]):
        """Display post-load statements (VACUUM, ANALYZE, OPTIMIZE, etc.)."""
        if not post_load_statements:
            return

        self.console.print("\n[bold]Post-Load Operations[/bold]")

        all_statements = []
        for table_name, statements in post_load_statements.items():
            for stmt in statements:
                all_statements.append(f"-- {table_name}")
                all_statements.append(stmt)
                all_statements.append("")

        if all_statements:
            sql_content = "\n".join(all_statements)
            syntax = Syntax(sql_content, "sql", theme="monokai", line_numbers=False)
            self.console.print(Panel(syntax, title="Post-Load SQL", border_style="yellow"))

    def _display_maintenance_operations(self, operations: dict[str, str]):
        """Display TPC-H maintenance operation SQL."""
        display_ops = {k: v for k, v in operations.items() if not k.startswith("_")}
        if not display_ops:
            return

        self.console.print("\n[bold magenta]TPC-H Maintenance Operations (RF1/RF2)[/bold magenta]")
        self.console.print("[dim]These INSERT/DELETE operations execute during the maintenance phase[/dim]")

        for op_id, sql in display_ops.items():
            # Truncate very long SQL for display (keep full in output files)
            display_sql = sql
            if len(sql) > 2000:
                display_sql = sql[:2000] + "\n\n-- [truncated for display, see output files for full SQL]"

            syntax = Syntax(display_sql, "sql", theme="monokai", line_numbers=False)
            self.console.print(Panel(syntax, title=f"Refresh Function {op_id}", border_style="magenta"))

    def _display_resource_estimates(self, estimates: dict[str, Any]):
        self.console.print("\n[bold]Resource Estimates[/bold]")

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("Resource", style="cyan")
        table.add_column("Estimated", style="yellow")
        table.add_column("Available", style="green")

        data_size = estimates.get("estimated_data_size_mb", 0)
        table.add_row("Data Size", f"{data_size:.1f} MB", "N/A")

        memory_usage = estimates.get("estimated_memory_usage_mb", 0)
        memory_available = estimates.get("memory_gb_available", 0) * 1024
        table.add_row("Memory Usage", f"{memory_usage:.0f} MB", f"{memory_available:.0f} MB")

        runtime = estimates.get("estimated_runtime_minutes", 0)
        table.add_row("Runtime", f"{runtime:.1f} minutes", "N/A")

        cpu_cores = estimates.get("cpu_cores_available", 1)
        table.add_row("CPU Cores", "All available", f"{cpu_cores}")

        self.console.print(table)

        if memory_usage > memory_available * 0.9:
            self.console.print("[yellow]⚠️ Warning: Estimated memory usage is close to available memory[/yellow]")

    def _display_warnings(self, warnings: list[str]):
        if not warnings:
            return

        self.console.print(f"\n[bold yellow]Warnings ({len(warnings)})[/bold yellow]")
        for warning in warnings:
            self.console.print(f"[yellow]⚠️[/yellow] {warning}")

    def _get_execution_context(self, benchmark_config: BenchmarkConfig, query_count: int) -> str:
        test_execution_type = getattr(benchmark_config, "test_execution_type", "standard")
        benchmark_name = getattr(benchmark_config, "name", "").lower()

        if test_execution_type == "power":
            if benchmark_name == "tpcds":
                return "TPC-DS PowerTest stream permutation (99 queries in randomized order)"
            elif benchmark_name == "tpch":
                return "TPC-H PowerTest stream 0 permutation (22 queries in a specific, randomized order)"
            else:
                return "Power test execution (stream permutation)"
        elif test_execution_type == "throughput":
            if benchmark_name == "tpcds":
                return f"TPC-DS ThroughputTest (4 concurrent streams, {query_count} queries total)"
            else:
                return "Throughput test execution (concurrent streams)"
        elif test_execution_type == "maintenance":
            if benchmark_name == "tpcds":
                return "TPC-DS MaintenanceTest (data operations: INSERT/UPDATE/DELETE)"
            else:
                return "Maintenance test execution (data operations)"
        else:
            return f"Standard sequential execution ({query_count} queries)"

    def _format_test_execution_type(self, test_execution_type: str) -> str:
        type_formats = {
            "standard": "Standard (Sequential)",
            "power": "PowerTest (Stream Permutation)",
            "throughput": "ThroughputTest (Concurrent Streams)",
            "maintenance": "MaintenanceTest (Data Operations)",
            "combined": "Combined Test (All Phases)",
            "load_only": "Load Only (Data Generation)",
            "data_only": "Data Only (No Database)",
        }
        return type_formats.get(test_execution_type, f"{test_execution_type.title()} Test")

    def _get_preview_title(self, test_execution_type: str, query_count: int) -> str:
        if test_execution_type == "power":
            return "PowerTest Stream Execution Preview"
        elif test_execution_type == "throughput":
            return "ThroughputTest Concurrent Stream Preview"
        elif test_execution_type == "maintenance":
            return "MaintenanceTest Operations Preview"
        else:
            return "Query Preview"

    def _format_query_display_title(self, query_id: str, test_execution_type: str) -> str:
        query_id_str = str(query_id)
        if test_execution_type == "maintenance":
            return f"Operation {query_id_str}"
        elif "Stream_" in query_id_str:
            return query_id_str.replace("_", " ")
        elif "Position_" in query_id_str:
            return query_id_str.replace("_", " ").replace("Position", "Stream Position")
        else:
            return f"Query {query_id_str}"

    def _format_panel_title(self, query_id: str, test_execution_type: str) -> str:
        query_id_str = str(query_id)
        if test_execution_type == "maintenance":
            return f"Maintenance Operation: {query_id_str}"
        elif "Stream_" in query_id_str:
            parts = query_id_str.split("_")
            if len(parts) >= 6:
                stream = parts[1]
                position = parts[3]
                query_num = parts[5]
                return f"Stream {stream} Position {position}: Query {query_num}"
        elif "Position_" in query_id_str:
            parts = query_id_str.split("_")
            if len(parts) >= 4:
                position = parts[1]
                query_num = parts[3]
                return f"Stream Position {position}: Query {query_num}"

        return f"Query {query_id_str}"


class DryRunExecutor(CoreDryRunExecutor):
    """Extended DryRunExecutor with CLI-specific display functionality."""

    def __init__(self, output_dir=None):
        super().__init__(output_dir)
        self.console = quiet_console
        self.display = DryRunDisplay(self.console)

    def display_dry_run_results(self, result: DryRunResult):
        """Display dry run results using the display component."""
        self.display.display_dry_run_results(result)

    def _format_test_execution_type(self, test_execution_type: str) -> str:
        """Format test execution type for display."""
        type_formats = {
            "standard": "Standard (Sequential)",
            "power": "PowerTest (Stream Permutation)",
            "throughput": "ThroughputTest (Concurrent Streams)",
            "maintenance": "MaintenanceTest (Data Operations)",
            "combined": "Combined Test (All Phases)",
            "load_only": "Load Only (Data Generation)",
            "data_only": "Data Only (No Database)",
        }
        return type_formats.get(test_execution_type, f"{test_execution_type.title()} Test")

    def _get_preview_title(self, test_execution_type: str, query_count: int) -> str:
        """Get the preview title for different test types."""
        if test_execution_type == "power":
            return "PowerTest Stream Execution Preview"
        elif test_execution_type == "throughput":
            return "ThroughputTest Concurrent Stream Preview"
        elif test_execution_type == "maintenance":
            return "MaintenanceTest Operations Preview"
        else:
            return "Query Preview"

    def _format_query_display_title(self, query_id: str, test_execution_type: str) -> str:
        """Format query display title based on test type and query ID."""
        query_id_str = str(query_id)
        if test_execution_type == "maintenance":
            return f"Operation {query_id_str}"
        elif "Stream_" in query_id_str:
            return query_id_str.replace("_", " ")
        elif "Position_" in query_id_str:
            return query_id_str.replace("_", " ").replace("Position", "Stream Position")
        else:
            return f"Query {query_id_str}"

    def _format_panel_title(self, query_id: str, test_execution_type: str) -> str:
        """Format panel title for query display."""
        query_id_str = str(query_id)
        if test_execution_type == "maintenance":
            return f"Maintenance Operation: {query_id_str}"
        elif "Stream_" in query_id_str:
            parts = query_id_str.split("_")
            if len(parts) >= 6:
                stream = parts[1]
                position = parts[3]
                query_num = parts[5]
                return f"Stream {stream} Position {position}: Query {query_num}"
        elif "Position_" in query_id_str:
            parts = query_id_str.split("_")
            if len(parts) >= 4:
                position = parts[1]
                query_num = parts[3]
                return f"Stream Position {position}: Query {query_num}"

        return f"Query {query_id_str}"
