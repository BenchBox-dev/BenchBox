"""Deprecated df-tuning compatibility command group."""

from pathlib import Path
from typing import Any

import click
from rich.panel import Panel
from rich.text import Text

from benchbox.cli.shared import console
from benchbox.core.dataframe.tuning import (
    DataFrameTuningConfiguration,
    detect_system_profile,
    format_issues,
    get_profile_summary,
    get_smart_defaults,
    has_errors,
    load_dataframe_tuning,
    save_dataframe_tuning,
    validate_dataframe_tuning,
)

DATAFRAME_PLATFORMS = ["polars", "pandas", "dask", "modin", "cudf"]
PROFILES = ["default", "optimized", "streaming", "memory-constrained", "gpu"]


@click.group("df-tuning", hidden=True)
def df_tuning_group():
    """Deprecated DataFrame tuning commands. Use `benchbox tuning` instead."""
    console.print("[yellow]Warning: 'df-tuning' is deprecated. Use 'benchbox tuning' commands instead.[/yellow]\n")


def _panel(title: str) -> None:
    console.print(Panel.fit(Text(title, style="bold cyan"), style="cyan"))


@df_tuning_group.command("create-sample")
@click.option("--platform", type=click.Choice(DATAFRAME_PLATFORMS, case_sensitive=False), required=True)
@click.option("--profile", type=click.Choice(PROFILES), default="default")
@click.option("--output", type=str, default=None)
@click.option("--smart-defaults", is_flag=True)
def create_sample(platform, profile, output, smart_defaults):
    """Create a sample deprecated DataFrame tuning configuration."""
    platform = platform.lower()
    _panel(f"Creating DataFrame Tuning Configuration for {platform.title()}")
    output_path = Path(output or f"{platform}_{profile.replace('-', '_')}.yaml")

    try:
        config = get_smart_defaults(platform) if smart_defaults else _create_profile_config(platform, profile)
        if smart_defaults:
            _display_smart_defaults_info(platform)
        save_dataframe_tuning(config, output_path)
        console.print("\n[green]Sample DataFrame tuning configuration created[/green]")
        console.print(f"File: [cyan]{output_path}[/cyan]")
        console.print(f"Platform: [yellow]{platform}[/yellow]")
        console.print(f"Profile: [yellow]{profile}[/yellow]")
        _print_enabled_settings(config)
        console.print("\nEdit this file to customize tuning settings for your benchmarks.")
        console.print(f"Use with: [cyan]benchbox run --tuning {output_path}[/cyan]")
    except Exception as e:
        console.print(f"[red]Failed to create sample configuration: {e}[/red]")
        raise click.Abort() from e


def _display_smart_defaults_info(_platform: str) -> None:
    console.print("[blue]Using smart defaults based on detected system profile[/blue]")
    summary = get_profile_summary(detect_system_profile())
    console.print(f"  CPU cores: {summary['cpu_cores']}")
    console.print(f"  Available memory: {summary['available_memory_gb']:.1f} GB")
    console.print(f"  Memory category: {summary['memory_category']}")
    if summary["has_gpu"]:
        console.print(f"  GPU memory: {summary['gpu_memory_gb']:.1f} GB")


def _create_profile_config(platform: str, profile: str) -> DataFrameTuningConfiguration:
    """Create the legacy profile presets used by the hidden command."""
    config = DataFrameTuningConfiguration()
    if profile == "optimized":
        config.execution.lazy_evaluation = True
        if platform == "polars":
            config.execution.engine_affinity = "in-memory"
        elif platform == "dask":
            config.parallelism.worker_count = 4
            config.parallelism.threads_per_worker = 2
        elif platform == "cudf":
            config.gpu.enabled = True
            config.gpu.pool_type = "pool"
    elif profile == "streaming":
        config.execution.streaming_mode = True
        config.memory.chunk_size = 100_000
        if platform == "polars":
            config.execution.engine_affinity = "streaming"
    elif profile == "memory-constrained":
        config.execution.streaming_mode = True
        config.memory.chunk_size = 50_000
        config.memory.spill_to_disk = True
        if platform == "dask":
            config.memory.memory_limit = "2GB"
    elif profile == "gpu":
        if platform != "cudf":
            console.print("[yellow]Warning: GPU profile is only applicable to cuDF[/yellow]")
        config.gpu.enabled = True
        config.gpu.pool_type = "pool"
        config.gpu.spill_to_host = True
    return config


def _print_enabled_settings(config: DataFrameTuningConfiguration) -> None:
    enabled = config.get_enabled_settings()
    if not enabled:
        console.print("\nNo custom settings enabled (using defaults)")
        return
    console.print(f"\nEnabled settings ({len(enabled)}):")
    for setting in sorted(enabled, key=lambda x: x.value):
        console.print(f"  - {setting.value}")


@df_tuning_group.command("validate")
@click.argument("config_file", type=click.Path(exists=True))
@click.option("--platform", type=click.Choice(DATAFRAME_PLATFORMS, case_sensitive=False), required=True)
def validate(config_file, platform):
    """Validate a deprecated DataFrame tuning file."""
    _panel("Validating DataFrame Tuning Configuration")
    try:
        config = load_dataframe_tuning(config_file)
        console.print(f"Loaded: [cyan]{config_file}[/cyan]")
        issues = validate_dataframe_tuning(config, platform)
        if issues:
            console.print(f"\n{format_issues(issues)}")
            if has_errors(issues):
                console.print("\n[red]Configuration has errors that must be fixed[/red]")
                raise click.Abort()
            console.print("\n[yellow]Configuration is valid but has warnings[/yellow]")
        else:
            console.print(f"\n[green]Configuration is valid for {platform}[/green]")
        _print_config_summary(config)
    except click.Abort:
        raise
    except Exception as e:
        console.print(f"[red]Failed to validate configuration: {e}[/red]")
        raise click.Abort() from e


def _print_config_summary(config: DataFrameTuningConfiguration) -> None:
    summary = config.get_summary()
    console.print("\n[bold]Configuration Summary:[/bold]")
    console.print(f"  Enabled settings: {summary['setting_count']}")
    console.print(f"  Has streaming: {summary['has_streaming']}")
    console.print(f"  Has GPU: {summary['has_gpu']}")


@df_tuning_group.command("show-defaults")
@click.option("--platform", type=click.Choice(DATAFRAME_PLATFORMS, case_sensitive=False), required=True)
def show_defaults(platform):
    """Show smart defaults for a DataFrame platform."""
    _panel(f"Smart Defaults for {platform.title()}")
    summary = get_profile_summary(detect_system_profile())
    _print_system_profile(summary)
    config = get_smart_defaults(platform)
    console.print(f"\n[bold]Recommended Settings for {platform.title()}:[/bold]")
    _display_config_settings_table(config)
    console.print(f"\n[dim]To use these settings: benchbox run --platform {platform}-df --tuning auto[/dim]")


def _print_system_profile(summary: dict[str, Any]) -> None:
    console.print("\n[bold]Detected System Profile:[/bold]")
    rows = [
        ("CPU Cores", summary["cpu_cores"]),
        ("Available Memory", f"{summary['available_memory_gb']:.1f} GB"),
        ("Memory Category", summary["memory_category"]),
        ("GPU Available", "Yes" if summary["has_gpu"] else "No"),
    ]
    if summary["has_gpu"]:
        rows.extend([("GPU Memory", f"{summary['gpu_memory_gb']:.1f} GB"), ("GPU Count", summary["gpu_device_count"])])
    for label, value in rows:
        console.print(f"  {label}: {value}")


def _display_config_settings_table(config: DataFrameTuningConfiguration, target_console=console) -> None:
    rows = []
    for category, source, fields in [
        ("Parallelism", config.parallelism, ["thread_count", "worker_count", "threads_per_worker"]),
        ("Memory", config.memory, ["memory_limit", "chunk_size", "spill_to_disk"]),
        ("Execution", config.execution, ["streaming_mode", "engine_affinity"]),
        ("Data Types", config.data_types, ["dtype_backend", "auto_categorize_strings"]),
        ("I/O", config.io, ["memory_map"]),
        ("GPU", config.gpu, ["enabled", "device_id", "pool_type", "spill_to_host"]),
    ]:
        rows.extend(_non_default_rows(category, source, fields))
    target_console.print(
        "\n".join(rows) if rows else "  [dim]Using default settings (no custom configuration needed)[/dim]"
    )


def _non_default_rows(category: str, source: Any, fields: list[str]) -> list[str]:
    rows = []
    for field in fields:
        value = getattr(source, field)
        if value in (None, False) or (field == "dtype_backend" and value == "numpy_nullable"):
            continue
        rows.append(f"  {category}.{field}: {value}")
    return rows


@df_tuning_group.command("list-platforms")
def list_platforms():
    """List DataFrame tuning platforms."""
    _panel("DataFrame Platforms")
    for row in [
        ("polars", "Expression", "Lazy evaluation, streaming, thread control", "No"),
        ("pandas", "Pandas", "dtype_backend, categorical strings", "No"),
        ("dask", "Pandas", "Distributed, worker/thread control, spill to disk", "No"),
        ("modin", "Pandas", "Engine selection, parallelization", "No"),
        ("cudf", "Pandas", "GPU acceleration, memory pools, spill to host", "Yes"),
    ]:
        console.print(f"  {row[0]} ({row[1]}): {row[2]} | GPU: {row[3]}")
    console.print("\n[dim]Use 'benchbox df-tuning show-defaults --platform <name>' for details[/dim]")
