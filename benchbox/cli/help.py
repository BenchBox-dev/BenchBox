"""Custom help formatting for BenchBox CLI.

This module provides a tiered help system that shows only common options by default,
with advanced options revealed via --help-topic all.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import re
from typing import Any

import click

# Valid help topics
HELP_TOPICS = ("all", "examples", "benchmarks")


# Command categories for grouped help display
# Order matters - categories are displayed in this order
COMMAND_CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "core": (
        "Core",
        ["run", "run-official", "datagen"],
    ),
    "results": (
        "Results & Analysis",
        ["results", "report", "aggregate", "export"],
    ),
    "comparison": (
        "Comparison",
        ["compare", "compare-dataframes", "compare-plans"],
    ),
    "visualization": (
        "Visualization",
        ["visualize"],
    ),
    "plans": (
        "Query Plans",
        ["show-plan", "plan-history"],
    ),
    "configuration": (
        "Configuration",
        ["setup", "platforms", "tuning", "validate"],
    ),
    "utilities": (
        "Utilities",
        ["shell", "profile", "check-deps", "convert", "calculate-qphh", "benchmarks"],
    ),
}


# Examples registry - commands can register their examples here
COMMAND_EXAMPLES: dict[str, dict[str, list[str]]] = {
    "run": {
        # === Basic Usage ===
        "Basic Usage": [
            "benchbox run --platform duckdb --benchmark tpch",
            "benchbox run --platform sqlite --benchmark ssb --scale 1",
            "benchbox run --platform duckdb --benchmark tpcds --scale 10",
        ],
        "Driver & Version Management": [
            "# BenchBox uses whatever driver version is installed in the current environment.",
            "# When invoked via 'uv run', uv syncs your env to uv.lock first - a version you",
            "# installed manually (e.g. uv pip install duckdb==1.5.0) may be silently reverted.",
            "# Use driver_auto_install to reliably switch versions without touching the lock file:",
            "benchbox run --platform duckdb --benchmark tpch \\",
            "  --platform-option driver_version=1.5.0 \\",
            "  --platform-option driver_auto_install=true",
            "# Or override inline without modifying the lock file:",
            'uv run --with "duckdb==1.5.0" benchbox run --platform duckdb --benchmark tpch',
            "# Pin driver for any platform (not just DuckDB):",
            "benchbox run --platform snowflake --benchmark tpch \\",
            "  --platform-option driver_version=3.12.0 \\",
            "  --platform-option driver_auto_install=true \\",
            "  --output s3://my-bucket/results/",
            "# Verify which version actually ran: check result JSON field execution.driver_version_actual",
            "# or watch the 'Running ... [driver X.Y.Z]' line in CLI output.",
        ],
        # === Platform-Specific Examples ===
        "Snowflake": [
            "benchbox run --platform snowflake --benchmark tpch --output s3://bucket/benchbox/",
            "benchbox run --platform snowflake --benchmark tpcds --scale 100 \\",
            "  --platform-option warehouse=BENCHBOX_XL --output s3://my-bucket/results/",
            "benchbox run --platform snowflake --benchmark tpch --tuning tuned \\",
            "  --output s3://bucket/benchbox/  # Uses clustering, result caching",
            "benchbox run --platform snowflake --benchmark tpch --table-mode external \\",
            "  --platform-option staging_root=s3://bucket/benchbox/  # External tables over staged Parquet",
        ],
        "Databricks": [
            "benchbox run --platform databricks --benchmark tpch \\",
            "  --output dbfs:/Volumes/catalog/schema/benchbox/",
            "benchbox run --platform databricks --benchmark tpcds --scale 100 \\",
            "  --output abfss://container@storage.dfs.core.windows.net/benchbox/",
            "benchbox run --platform databricks --benchmark tpch --tuning tuned \\",
            "  --output dbfs:/Volumes/main/default/benchbox/  # Uses Photon, Delta optimization",
        ],
        "BigQuery": [
            "benchbox run --platform bigquery --benchmark tpch --output gs://bucket/benchbox/",
            "benchbox run --platform bigquery --benchmark tpcds --scale 100 \\",
            "  --platform-option project_id=my-project --output gs://my-bucket/results/",
            "benchbox run --platform bigquery --benchmark tpch --tuning tuned \\",
            "  --output gs://bucket/benchbox/  # Uses partitioning, clustering",
            "benchbox run --platform bigquery --benchmark tpch --table-mode external \\",
            "  --platform-option staging_root=gs://bucket/benchbox/  # External table over GCS Parquet",
        ],
        "Redshift": [
            "benchbox run --platform redshift --benchmark tpch --output s3://bucket/benchbox/",
            "benchbox run --platform redshift --benchmark tpcds --scale 100 \\",
            "  --platform-option iam_role=arn:aws:iam::123456789012:role/RedshiftRole \\",
            "  --output s3://my-bucket/results/",
        ],
        "Firebolt Core": [
            "benchbox run --platform firebolt --benchmark tpch \\",
            "  --platform-option url=http://localhost:3473  # Local Docker",
            "benchbox run --platform firebolt --benchmark tpch --scale 1 \\",
            "  --platform-option url=http://localhost:3473 \\",
            "  --platform-option database=tpch_sf1",
        ],
        "Firebolt Cloud": [
            "benchbox run --platform firebolt --benchmark tpch \\",
            "  --platform-option client_id=YOUR_CLIENT_ID \\",
            "  --platform-option client_secret=YOUR_SECRET \\",
            "  --platform-option account=my-account --platform-option engine=benchmark_engine",
            "benchbox run --platform firebolt --benchmark tpcds --scale 100 \\",
            "  --platform-option client_id=$FIREBOLT_CLIENT_ID \\",
            "  --platform-option client_secret=$FIREBOLT_CLIENT_SECRET \\",
            "  --platform-option account=production --platform-option engine=large_engine",
        ],
        "Presto": [
            "benchbox run --platform presto --benchmark tpch \\",
            "  --platform-option host=presto-coordinator.example.com \\",
            "  --platform-option catalog=hive",
            "benchbox run --platform presto --benchmark tpcds --scale 100 \\",
            "  --platform-option host=localhost --platform-option port=8080 \\",
            "  --platform-option catalog=iceberg --platform-option schema=tpcds_sf100",
            "benchbox run --platform presto --benchmark tpch \\",
            "  --platform-option catalog=memory  # In-memory catalog for testing",
        ],
        "Trino": [
            "benchbox run --platform trino --benchmark tpch \\",
            "  --platform-option host=trino-coordinator.example.com \\",
            "  --platform-option catalog=hive",
            "benchbox run --platform trino --benchmark tpcds --scale 100 \\",
            "  --platform-option host=localhost --platform-option port=8080 \\",
            "  --platform-option catalog=iceberg --platform-option schema=tpcds_sf100",
            "benchbox run --platform trino --benchmark tpch \\",
            "  --platform-option user=benchbox  # Specify Trino user",
        ],
        "Athena": [
            "benchbox run --platform athena --benchmark tpch \\",
            "  --platform-option s3_staging_dir=s3://my-bucket/athena-results/ \\",
            "  --platform-option workgroup=primary",
            "benchbox run --platform athena --benchmark tpcds --scale 100 \\",
            "  --platform-option region=us-west-2 \\",
            "  --platform-option s3_staging_dir=s3://athena-staging/results/ \\",
            "  --platform-option workgroup=benchbox-workgroup",
            "benchbox run --platform athena --benchmark tpch \\",
            "  --platform-option database=benchbox_tpch  # Use existing database",
            "benchbox run --platform athena --benchmark tpch --table-mode external \\",
            "  --platform-option staging_root=s3://my-bucket/benchbox/  # Skip CTAS materialization",
            "# Athena Spark: select Spark engine version",
            "benchbox run --platform athena --benchmark tpch \\",
            "  --platform-option workgroup=my-spark-workgroup \\",
            "  --platform-option s3_staging_dir=s3://my-bucket/staging/ \\",
            '  --platform-option "engine_version=PySpark engine version 3"',
        ],
        "Azure Synapse": [
            "benchbox run --platform azure_synapse --benchmark tpch \\",
            "  --platform-option server=myworkspace.sql.azuresynapse.net \\",
            "  --platform-option database=benchbox",
            "benchbox run --platform azure_synapse --benchmark tpcds --scale 100 \\",
            "  --platform-option server=myworkspace.sql.azuresynapse.net \\",
            "  --platform-option database=tpcds_sf100 --platform-option authentication=ActiveDirectoryInteractive",
            "# Dedicated SQL pool with specific resource class",
            "benchbox run --platform azure_synapse --benchmark tpch \\",
            "  --platform-option server=myworkspace.sql.azuresynapse.net \\",
            "  --platform-option resource_class=staticrc60",
        ],
        "Fabric Warehouse": [
            "benchbox run --platform fabric_warehouse --benchmark tpch \\",
            "  --platform-option server=workspace-guid.datawarehouse.fabric.microsoft.com \\",
            "  --platform-option warehouse=BenchmarkWarehouse",
            "benchbox run --platform fabric_warehouse --benchmark tpcds --scale 100 \\",
            "  --platform-option workspace=my-workspace \\",
            "  --platform-option warehouse=TPC_DS_Benchmark",
            "# Using Azure AD authentication (default)",
            "benchbox run --platform fabric_warehouse --benchmark tpch \\",
            "  --platform-option workspace=analytics-workspace \\",
            "  --platform-option warehouse=PerformanceTests",
        ],
        "PostgreSQL": [
            "benchbox run --platform postgresql --benchmark tpch  # localhost:5432 default",
            "benchbox run --platform postgresql --benchmark tpch \\",
            "  --platform-option host=db.example.com --platform-option port=5432 \\",
            "  --platform-option username=benchbox --platform-option password=secret",
            "benchbox run --platform postgresql --benchmark tpcds --scale 10 \\",
            "  --platform-option database=tpcds_benchmark \\",
            "  --platform-option schema=tpcds_sf10",
            "benchbox run --platform postgresql --benchmark tpch \\",
            "  --platform-option sslmode=require  # Secure connection",
        ],
        "Local Platforms": [
            "benchbox run --platform duckdb --benchmark tpch  # Fastest local option",
            "benchbox run --platform sqlite --benchmark ssb --scale 1  # Baseline comparison",
            "benchbox run --platform postgresql --benchmark tpch  # Requires local PostgreSQL",
        ],
        "DataFrame Platforms": [
            "benchbox run --platform polars --benchmark tpch --mode dataframe  # Fastest DataFrame",
            "benchbox run --platform pandas --benchmark tpch --mode dataframe --scale 0.1",
            "benchbox run --platform datafusion --benchmark tpch --mode dataframe",
            "benchbox run --platform dask --benchmark tpch --mode dataframe --scale 1  # Distributed",
            "benchbox run --platform cudf --benchmark tpch --mode dataframe  # GPU-accelerated",
        ],
        # === Use-Case Examples ===
        "Quick Validation (CI/CD)": [
            "benchbox run --platform duckdb --benchmark tpch --scale 0.01 --queries Q1,Q6",
            "benchbox run --platform duckdb --benchmark tpch --scale 0.01 \\",
            "  --phases power --non-interactive  # Headless CI run",
            "benchbox run --platform snowflake --benchmark tpch --scale 0.01 \\",
            "  --queries Q1,Q3,Q6 --non-interactive --output s3://ci-bucket/",
        ],
        "Full TPC Benchmark": [
            "benchbox run --platform duckdb --benchmark tpch --scale 10 \\",
            "  --phases generate,load,warmup,power,throughput",
            "benchbox run --platform snowflake --benchmark tpcds --scale 100 \\",
            "  --phases generate,load,power,throughput --tuning tuned \\",
            "  --output s3://bucket/tpcds-sf100/",
        ],
        "Platform Comparison": [
            "# Run same benchmark on multiple platforms for comparison",
            "benchbox run --platform duckdb --benchmark tpch --scale 1 --output ./results/duckdb/",
            "benchbox run --platform polars --benchmark tpch --scale 1 --mode dataframe \\",
            "  --output ./results/polars/",
            "benchbox run --platform datafusion --benchmark tpch --scale 1 --mode dataframe \\",
            "  --output ./results/datafusion/",
        ],
        "Data Generation Only": [
            "benchbox run --benchmark tpch --scale 100 --phases generate  # Generate data only",
            "benchbox run --benchmark tpcds --scale 10 --phases generate \\",
            "  --compression zstd:9  # Compressed output",
        ],
        "Export and Analysis": [
            "benchbox export --last --format csv --format html  # Export most recent run",
            "benchbox export result.json --format csv \\",
            "  --output-dir ./analysis/  # Custom output location",
            "# Results can be loaded: python -c \"import json; data = json.load(open('result.json'))\"",
        ],
        # === Standard Configuration ===
        "Query Selection": [
            "benchbox run --platform duckdb --benchmark tpch --queries Q1,Q6,Q17",
            "benchbox run --platform duckdb --benchmark tpcds --queries Q1,Q2,Q3,Q4,Q5",
            "benchbox run --platform duckdb --benchmark tpch --queries Q22  # Single query",
        ],
        "Benchmark Phases": [
            "benchbox run --platform duckdb --benchmark tpch --phases generate",
            "benchbox run --platform duckdb --benchmark tpch --phases generate,load",
            "benchbox run --platform duckdb --benchmark tpch --phases power,throughput",
            "benchbox run --platform duckdb --benchmark tpch --phases warmup,power",
        ],
        "Tuning Configuration": [
            "benchbox run --platform duckdb --benchmark tpch --tuning tuned  # Auto-discovers template",
            "benchbox run --platform duckdb --benchmark tpch --tuning notuning  # Baseline, no tuning",
            "benchbox run --platform duckdb --benchmark tpch --tuning auto  # Smart system defaults",
            "benchbox run --platform duckdb --benchmark tpch \\",
            "  --tuning ./examples/tunings/duckdb/tpch_tuned.yaml  # Explicit tuning file",
            "# Tuning modes:",
            "#   'tuned'    - Auto-discovers examples/tunings/<platform>/<benchmark>_tuned.yaml",
            "#   'notuning' - Disables all optimizations (baseline comparison)",
            "#   'auto'     - Uses smart defaults based on system profile",
            "#   <PATH>     - Loads explicit YAML tuning file",
        ],
        "Tuning Discovery": [
            "benchbox tuning list  # List all available tuning templates",
            "benchbox tuning list --platform duckdb  # Templates for specific platform",
            "benchbox tuning show tuned --platform duckdb --benchmark tpch  # Preview resolution",
            "benchbox tuning show ./my-tuning.yaml  # Preview custom config",
        ],
        "Data Regeneration": [
            "benchbox run --platform duckdb --benchmark tpch --force  # Regenerate all",
            "benchbox run --platform duckdb --benchmark tpch --force datagen  # Data only",
            "benchbox run --platform snowflake --benchmark tpch --force upload \\",
            "  --output s3://bucket/  # Re-upload to cloud",
            "benchbox run --platform snowflake --benchmark tpch --force datagen,upload \\",
            "  --output s3://bucket/  # Regenerate and re-upload",
        ],
        # === Advanced Options ===
        "Dry Run (Preview)": [
            "benchbox run --dry-run ./preview --platform duckdb --benchmark tpch",
            "benchbox run --dry-run /tmp/test --platform snowflake --benchmark tpcds --scale 100",
            "benchbox run --dry-run ./preview --benchmark tpch --phases generate  # Data-only preview",
        ],
        "Compression (Advanced)": [
            "benchbox run --platform duckdb --benchmark tpch --compression zstd",
            "benchbox run --platform duckdb --benchmark tpch --compression zstd:9  # Max compression",
            "benchbox run --platform duckdb --benchmark tpch --compression gzip:6",
            "benchbox run --platform duckdb --benchmark tpch --compression none  # Disable",
        ],
        "Plan Capture (Advanced)": [
            "benchbox run --platform duckdb --benchmark tpch --capture-plans",
            "benchbox run --platform duckdb --benchmark tpch --capture-plans --plan-config sample:0.1",
            "benchbox run --platform duckdb --benchmark tpch --capture-plans --plan-config first:5",
            "benchbox run --platform duckdb --benchmark tpch --capture-plans \\",
            "  --plan-config queries:Q1,Q6,Q17",
        ],
        "Validation (Advanced)": [
            "benchbox run --platform duckdb --benchmark tpch --validation exact",
            "benchbox run --platform duckdb --benchmark tpch --validation loose  # ±5% tolerance",
            "benchbox run --platform duckdb --benchmark tpch --validation full  # All checks",
            "benchbox run --platform duckdb --benchmark tpch --validation disabled",
        ],
    },
}


class BenchBoxHelpFormatter(click.HelpFormatter):
    """Custom help formatter that supports tiered option visibility."""

    def __init__(self, *args: Any, show_hidden: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.show_hidden = show_hidden


class BenchBoxCommand(click.Command):
    """Custom Click command with tiered help support.

    Usage:
        @click.command(cls=BenchBoxCommand)
        @click.option("--verbose", help="Verbose output")
        @click.option("--advanced", hidden=True, help="Advanced option")
        def mycommand(...):
            pass

    Hidden options will only appear when --help-topic all is used.

    Help topics:
        --help               Show common options
        --help-topic all     Show all options including advanced
        --help-topic examples Show usage examples
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        # Remove the default --help option so we can replace it
        self.params = [p for p in self.params if "--help" not in getattr(p, "opts", [])]

        # Add --help flag (basic help) and --help-topic option (advanced help)
        # Standard --help flag shows basic help
        self.params.append(
            click.Option(
                ["--help", "-h"],
                is_flag=True,
                default=False,
                expose_value=False,
                is_eager=True,
                help="Show help message (use --help-topic all/examples for more)",
                callback=self._handle_help_flag,
            )
        )
        # --help-topic for advanced help (all, examples)
        self.params.append(
            click.Option(
                ["--help-topic"],
                type=click.Choice(["all", "examples", "benchmarks"], case_sensitive=False),
                default=None,
                expose_value=False,
                is_eager=True,
                help="Show extended help: 'all' for advanced options, 'examples' for usage examples, 'benchmarks' for benchmark options",
                callback=self._handle_help_topic,
            )
        )

    def _handle_help_flag(self, ctx: click.Context, param: click.Parameter, value: bool) -> None:
        """Handle --help flag (basic help)."""
        if not value:
            return
        click.echo(ctx.get_help(), color=ctx.color)
        ctx.exit(0)

    def _handle_help_topic(self, ctx: click.Context, param: click.Parameter, value: str | None) -> None:
        """Handle --help-topic option (advanced help)."""
        if value is None:
            return

        topic = value.lower().strip()

        if topic == "all":
            # --help-topic all: show all options including advanced
            formatter = ctx.make_formatter()
            self.format_help_all(ctx, formatter)
            click.echo(formatter.getvalue(), color=ctx.color)
            ctx.exit(0)

        elif topic == "examples":
            # --help-topic examples: show categorized examples
            self._show_examples(ctx)
            ctx.exit(0)

        elif topic == "benchmarks":
            # --help-topic benchmarks: show benchmark-specific options
            self._show_benchmark_options(ctx)
            ctx.exit(0)

    @staticmethod
    def _show_benchmark_options(ctx: click.Context) -> None:
        """Display available benchmark-specific options (--benchmark-option)."""
        from benchbox.cli.benchmark_hooks import BenchmarkHookRegistry
        from benchbox.core.benchmark_loader import list_loader_benchmark_ids

        click.echo(
            click.style("\nBenchmark-specific options (--benchmark-option KEY=VALUE):\n", bold=True),
            color=ctx.color,
        )

        # Eagerly import all benchmark modules so their specs register
        from benchbox.core.benchmark_loader import get_benchmark_class

        found_any = False
        for bench_id in sorted(list_loader_benchmark_ids()):
            try:
                get_benchmark_class(bench_id)
            except ValueError:
                continue

            lines = BenchmarkHookRegistry.describe_options(bench_id)
            if not lines:
                continue

            found_any = True
            click.echo(click.style(f"  {bench_id}:", fg="cyan", bold=True), color=ctx.color)
            for line in lines:
                click.echo(f"    {line}", color=ctx.color)
            click.echo("", color=ctx.color)

        if not found_any:
            click.echo("  No benchmarks have registered custom options.", color=ctx.color)

        click.echo(
            click.style("Usage: ", fg="yellow", bold=True)
            + "--benchmark-option taxi_types=yellow,green --benchmark-option year=2020",
            color=ctx.color,
        )

    def _show_examples(self, ctx: click.Context) -> None:
        """Display categorized usage examples."""
        cmd_name = self.name or "run"
        examples = COMMAND_EXAMPLES.get(cmd_name, {})

        if not examples:
            click.echo(f"No examples available for '{cmd_name}'", color=ctx.color)
            return

        click.echo(f"\nUsage examples for 'benchbox {cmd_name}':\n", color=ctx.color)

        for category, cmds in examples.items():
            click.echo(click.style(f"{category}:", fg="cyan", bold=True), color=ctx.color)
            for cmd in cmds:
                click.echo(f"  {cmd}", color=ctx.color)
            click.echo("", color=ctx.color)

        click.echo(
            click.style("Tip: ", fg="yellow", bold=True)
            + "Use --help for options, --help-topic all for advanced options.",
            color=ctx.color,
        )

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Format help, hiding advanced options by default."""
        self.format_usage(ctx, formatter)
        self.format_help_text(ctx, formatter)
        self.format_options(ctx, formatter, show_hidden=False)
        self.format_epilog(ctx, formatter)

    def format_help_all(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Format help showing all options including hidden ones."""
        self.format_usage(ctx, formatter)
        self.format_help_text(ctx, formatter)
        self.format_options(ctx, formatter, show_hidden=True)
        self.format_epilog(ctx, formatter)

    def format_options(self, ctx: click.Context, formatter: click.HelpFormatter, show_hidden: bool = False) -> None:
        """Write options to formatter, optionally including hidden ones.

        Groups options into:
        - Core: platform, benchmark, scale, output
        - Common: phases, queries, tuning, etc.
        - Advanced: (only shown with show_hidden=True)
        """
        # Collect options by visibility
        core_opts: list[tuple[str, str]] = []
        common_opts: list[tuple[str, str]] = []
        advanced_opts: list[tuple[str, str]] = []

        # Define which options belong to which tier
        core_names = {"--platform", "--benchmark", "--scale", "--output"}
        common_names = {
            "--phases",
            "--queries",
            "--tuning",
            "--dry-run",
            "-v",
            "--verbose",
            "-q",
            "--quiet",
            "--force",
            "--help",
            "-h",
            "--non-interactive",
        }

        for param in self.get_params(ctx):
            is_hidden = getattr(param, "hidden", False)

            # Skip hidden options unless showing all
            if is_hidden and not show_hidden:
                continue

            # For hidden options, we need to temporarily unhide to get help record
            if is_hidden and show_hidden:
                param.hidden = False
                rv = param.get_help_record(ctx)
                param.hidden = True
            else:
                rv = param.get_help_record(ctx)

            if rv is None:
                continue

            # Categorize by tier
            if any(name in core_names for name in param.opts):
                core_opts.append(rv)
            elif any(name in common_names for name in param.opts):
                common_opts.append(rv)
            else:
                # Everything else is advanced (if hidden) or common (if not)
                if is_hidden:
                    advanced_opts.append(rv)
                else:
                    common_opts.append(rv)

        # Write grouped options
        if core_opts:
            with formatter.section("Core Options"):
                formatter.write_dl(core_opts)

        if common_opts:
            with formatter.section("Options"):
                formatter.write_dl(common_opts)

        if show_hidden and advanced_opts:
            with formatter.section("Advanced Options"):
                formatter.write_dl(advanced_opts)


class BenchBoxGroup(click.Group):
    """Custom Click group with categorized command help.

    Displays commands grouped by category (Core, Results, Comparison, etc.)
    instead of a flat alphabetical list. Adds color to help output.

    Usage:
        @click.group(cls=BenchBoxGroup)
        def cli():
            pass
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def command(self, *args: Any, **kwargs: Any) -> Any:
        """Override to use BenchBoxCommand by default."""
        kwargs.setdefault("cls", BenchBoxCommand)
        return super().command(*args, **kwargs)

    def format_help_text(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Format help text with colors for examples and headers."""
        text = self.help if self.help else ""
        if not text:
            return

        # Process line by line to add colors
        lines = text.split("\n")
        colored_lines = []

        for line in lines:
            stripped = line.strip()
            # Color "Quick start:" header
            if stripped == "Quick start:":
                colored_lines.append(line.replace("Quick start:", click.style("Quick start:", fg="yellow", bold=True)))
            # Color example commands (lines starting with "benchbox")
            elif stripped.startswith("benchbox "):
                # Split command from description (separated by 2+ spaces)
                indent = len(line) - len(line.lstrip())
                content = line.lstrip()
                # Match: command part, then 2+ spaces, then description
                match = re.match(r"(benchbox\s+\S+(?:\s+-\S+\s+\S+)*(?:\s+\S+)?)\s{2,}(.+)", content)
                if match:
                    cmd_part = match.group(1)
                    desc_part = match.group(2)
                    colored_lines.append(
                        " " * indent + click.style(cmd_part, fg="cyan") + "  " + click.style(desc_part, dim=True)
                    )
                else:
                    # No description found, just color the whole command
                    colored_lines.append(" " * indent + click.style(content, fg="cyan"))
            # Color URLs
            elif "https://" in line or "http://" in line:

                def colorize_url(match: re.Match[str]) -> str:
                    return click.style(match.group(0), fg="blue", underline=True)

                colored_lines.append(re.sub(r"https?://[^\s]+", colorize_url, line))
            else:
                colored_lines.append(line)

        # Write with proper formatting
        text = "\n".join(colored_lines)
        formatter.write_paragraph()
        with formatter.indentation():
            formatter.write_text(text)

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Write categorized commands to the formatter.

        Groups commands by category defined in COMMAND_CATEGORIES.
        Any commands not in a category are listed under "Other".
        """
        commands: list[tuple[str, click.Command]] = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None or cmd.hidden:
                continue
            commands.append((subcommand, cmd))

        if not commands:
            return

        # Build a lookup of command name -> (name, cmd)
        cmd_lookup = {name: (name, cmd) for name, cmd in commands}

        # Track which commands have been categorized
        categorized: set[str] = set()

        # Format each category
        with formatter.section("Commands"):
            for _category_key, (category_name, cmd_names) in COMMAND_CATEGORIES.items():
                # Collect commands in this category that exist
                category_cmds: list[tuple[str, str]] = []
                for cmd_name in cmd_names:
                    if cmd_name in cmd_lookup:
                        name, cmd = cmd_lookup[cmd_name]
                        help_text = cmd.get_short_help_str(limit=formatter.width)
                        # Color: command name green, description dim
                        colored_name = click.style(name, fg="green")
                        colored_help = click.style(help_text, dim=True)
                        category_cmds.append((colored_name, colored_help))
                        categorized.add(cmd_name)

                if category_cmds:
                    # Write category header (cyan bold) and indented commands
                    formatter.write_text(click.style(f"{category_name}:", fg="cyan", bold=True))
                    with formatter.indentation():
                        formatter.write_dl(category_cmds)

            # Collect any uncategorized commands
            other_cmds: list[tuple[str, str]] = []
            for name, cmd in commands:
                if name not in categorized:
                    help_text = cmd.get_short_help_str(limit=formatter.width)
                    colored_name = click.style(name, fg="green")
                    colored_help = click.style(help_text, dim=True)
                    other_cmds.append((colored_name, colored_help))

            if other_cmds:
                formatter.write_text(click.style("Other:", fg="cyan", bold=True))
                with formatter.indentation():
                    formatter.write_dl(other_cmds)


def handle_help_callback(ctx: click.Context, param: click.Parameter, value: str | None) -> None:
    """Standalone callback for --help option with topic support.

    Use this when not using BenchBoxCommand class:

        @click.option("--help", "-h", is_flag=False, flag_value="",
                      default=None, expose_value=False, is_eager=True,
                      callback=handle_help_callback,
                      help="Show help (--help-topic all for advanced)")
    """
    if value is None:
        return

    topic = value.lower().strip() if value else ""

    if topic == "":
        click.echo(ctx.get_help(), color=ctx.color)
        ctx.exit(0)
    elif topic == "all":
        cmd = ctx.command
        if hasattr(cmd, "format_help_all"):
            formatter = ctx.make_formatter()
            cmd.format_help_all(ctx, formatter)  # type: ignore[call-non-callable]
            click.echo(formatter.getvalue(), color=ctx.color)
        else:
            click.echo(ctx.get_help(), color=ctx.color)
        ctx.exit(0)
    elif topic == "examples":
        cmd = ctx.command
        if hasattr(cmd, "_show_examples"):
            cmd._show_examples(ctx)  # type: ignore[call-non-callable]
        else:
            click.echo("No examples available.", color=ctx.color)
        ctx.exit(0)
    elif topic == "benchmarks":
        cmd = ctx.command
        if hasattr(cmd, "_show_benchmark_options"):
            cmd._show_benchmark_options(ctx)  # type: ignore[call-non-callable]
        else:
            click.echo("No benchmark options available.", color=ctx.color)
        ctx.exit(0)
    else:
        click.echo(
            f"Unknown help topic: '{topic}'\nValid topics: all, examples, benchmarks",
            color=ctx.color,
        )
        ctx.exit(1)


# Decorator for marking options as advanced (hidden from default help)
def advanced_option(*args: Any, **kwargs: Any) -> Any:
    """Decorator for advanced options that should be hidden by default.

    Usage:
        @advanced_option("--complex-setting", help="Advanced setting")
        def mycommand(complex_setting):
            pass
    """
    kwargs["hidden"] = True
    return click.option(*args, **kwargs)
