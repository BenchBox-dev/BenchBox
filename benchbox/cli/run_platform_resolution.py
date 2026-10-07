"""Platform and benchmark selection resolution for ``benchbox run``.

This module hosts the preamble steps that turn raw ``--platform`` /
``--benchmark`` CLI values into resolved, validated run state: benchmark-name
normalization, platform/benchmark option parsing, platform and execution-mode
resolution with availability checks, the benchmark compatibility gate, and the
interactive wizard's mode resolution. The helpers operate on the command's
namespace state and are re-exported through
:mod:`benchbox.cli.commands.run` so existing imports keep working.
"""

from __future__ import annotations

import logging
import types
from collections.abc import Iterable
from typing import Any

import click
from rich.markup import escape

from benchbox.cli.benchmark_hooks import BenchmarkHookRegistry, BenchmarkOptionError
from benchbox.cli.platform import (
    get_platform_alias_mode,
    normalize_platform_name,
    resolve_platform_selector,
)
from benchbox.cli.platform_hooks import PlatformHookRegistry, PlatformOptionError
from benchbox.cli.shared import console, set_quiet_output
from benchbox.cli.verbose_logging import setup_verbose_logging
from benchbox.core.benchmark_registry import get_benchmark_default_scale
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.platforms import is_dataframe_platform, list_available_dataframe_platforms
from benchbox.platforms.adapter_factory import _reject_removed_platform

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
    """Exit with error when --table-mode external is combined with a tuning-bearing --tuning value."""
    console.print("[red]❌ Error: --table-mode external is incompatible with tuning enabled[/red]")
    console.print("[yellow]Use --table-mode native, or --tuning notuning[/yellow]")
    if logger:
        logger.error("Invalid flag combination: --table-mode external with tuning enabled")
    ctx.exit(1)


def _tuning_arg_is_tuning_bearing(tuning_arg: str | None) -> bool:
    """Whether a raw `--tuning` argument selects a tuning-bearing resolution.

    Mirrors the outcomes `TuningResolution` can produce without requiring
    resolution to have already run: `notuning` is the only raw keyword that
    resolves to a disabled configuration. `tuned` (which may still resolve to
    either a curated template or `tuned-fallback` -- both tuning-bearing per
    ADR-2), `auto` (smart defaults, always enabled), and any other value (a
    custom tuning file path, recorded as `custom`) are all tuning-bearing.
    """
    if not tuning_arg:
        return False
    return tuning_arg.strip().lower() != "notuning"


def _apply_dataframe_suffix_mode(s: types.SimpleNamespace) -> None:
    """Treat a trailing ``-df`` platform suffix as an explicit DataFrame-mode request.

    Must run before PLATFORM_ALIASES normalization, which maps ``-df`` names to
    their base platform. For dual-mode platforms whose registry default is SQL
    (datafusion, lakesail) that erases the request and the run silently selects
    the SQL adapter. An explicit --mode flag still wins, matching adapter-factory
    precedence (explicit mode > -df suffix > platform default).
    """
    if s.mode is None and s.platform:
        s.mode = get_platform_alias_mode(s.platform)


def _apply_ducklake_deployment_suffix(s: types.SimpleNamespace) -> None:
    """Turn ``ducklake:<mode>`` shorthand into an explicit platform option."""
    if not s.platform or not s.platform.lower().startswith("ducklake:"):
        return
    platform, mode = s.platform.split(":", 1)
    if mode not in ("local", "local_catalog_s3", "postgres_catalog", "postgres_catalog_s3"):
        return
    s.platform = platform
    pairs = list(s.platform_option_pairs or ())
    if not any(key.casefold() == "deployment_mode" for key, _value in pairs):
        pairs.insert(0, ("deployment_mode", mode))
    s.platform_option_pairs = tuple(pairs)


def _parse_plat_bench_options(s: types.SimpleNamespace) -> None:
    """Parse --platform-option and --benchmark-option flags; set state fields."""
    s.logger, s.verbosity_settings = setup_verbose_logging(s.verbose, quiet=bool(s.quiet))
    set_quiet_output(s.verbosity_settings.quiet)
    s.ctx.obj["verbosity"] = s.verbosity_settings
    s.verbosity_payload = s.verbosity_settings.to_config()

    _apply_dataframe_suffix_mode(s)
    _apply_ducklake_deployment_suffix(s)
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
            from benchbox.core.benchmark_loader import get_core_benchmark_class

            get_core_benchmark_class(s.benchmark)
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

    if s.table_mode == "external" and _tuning_arg_is_tuning_bearing(s.tuning):
        _reject_external_tuned(console, s.logger, s.ctx)


def _apply_benchmark_default_scale(s: types.SimpleNamespace) -> None:
    """Use the selected benchmark's registry default when --scale was omitted."""
    if not s.benchmark:
        return

    s.benchmark = normalize_benchmark_name(s.benchmark)
    if not hasattr(s.ctx, "get_parameter_source"):
        return

    try:
        scale_source = s.ctx.get_parameter_source("scale")
    except Exception:
        return

    if scale_source == click.core.ParameterSource.DEFAULT:
        s.scale = get_benchmark_default_scale(s.benchmark, fallback=s.scale)


def _platform_option_sources_for_state(s: types.SimpleNamespace) -> dict[str, str]:
    """Return source provenance for parsed platform options in the current CLI state."""
    if not s.platform_key or not s.parsed_platform_options:
        return {}

    explicit_keys = _explicit_platform_option_keys(s.platform_key, s.platform_option_pairs or ())
    defaults = PlatformHookRegistry.get_default_options(s.platform_key)
    sources: dict[str, str] = {}
    for key in s.parsed_platform_options:
        if key in explicit_keys:
            sources[key] = "cli_option"
        elif key in defaults:
            sources[key] = "registered_default"
        else:
            sources[key] = "requested"
    return sources


def _explicit_platform_option_keys(platform_key: str, pairs: Iterable[tuple[str, str]]) -> set[str]:
    specs = PlatformHookRegistry.list_option_specs(platform_key)
    alias_index = {alias.lower(): name for name, spec in specs.items() for alias in spec.aliases}
    explicit: set[str] = set()
    for key, _value in pairs:
        normalized = key.lower()
        explicit.add(normalized if normalized in specs else alias_index.get(normalized, normalized))
    return explicit


def _platform_option_config_entries(s: types.SimpleNamespace) -> dict[str, Any]:
    if not s.parsed_platform_options:
        return {}
    entries: dict[str, Any] = {"platform_options": dict(s.parsed_platform_options)}
    sources = _platform_option_sources_for_state(s)
    if sources:
        entries["platform_option_sources"] = sources
    return entries


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


def _validate_not_removed_platform(s: types.SimpleNamespace) -> bool:
    """Reject selectors for platforms removed from BenchBox."""
    raw_platform = getattr(s, "platform", None)
    for candidate in (raw_platform, getattr(s, "platform_key", None)):
        if not candidate:
            continue
        try:
            _reject_removed_platform(candidate)
        except ValueError as exc:
            console.print(f"[red]❌ {exc}[/red]")
            if s.logger:
                s.logger.error(str(exc))
            if hasattr(s, "ctx") and s.ctx is not None and hasattr(s.ctx, "exit"):
                s.ctx.exit(1)
                return False
            raise
    return True


def _resolve_platform_mode(s: types.SimpleNamespace) -> None:
    """Validate platform, resolve execution mode, and check availability."""
    s.resolved_mode = None
    if not _validate_not_removed_platform(s):
        return
    if not s.platform_key:
        return

    try:
        platform_key = resolve_platform_selector(s.platform_key)
    except ValueError as exc:
        console.print(f"[red]❌ {escape(str(exc))}[/red]")
        if s.logger:
            s.logger.error(str(exc))
        s.ctx.exit(1)
        return

    caps = PlatformRegistry.get_platform_capabilities(platform_key)
    if caps is None:
        is_df_platform_legacy = is_dataframe_platform(platform_key)
        is_df_available = is_df_platform_legacy and list_available_dataframe_platforms().get(platform_key, False)
        if not is_df_available and not s.dry_run:
            from benchbox.utils.dependencies import get_install_command

            console.print(f"[red]❌ Platform '{platform_key}' is not available (missing dependencies)[/red]")
            install_cmd = get_install_command(platform_key)
            console.print(f"Run [cyan]{escape(install_cmd)}[/cyan] to install dependencies.")
            s.ctx.exit(1)
        s.resolved_mode = "dataframe"
    else:
        if s.mode is not None:
            if not PlatformRegistry.supports_mode(platform_key, s.mode):
                supported_modes = []
                if caps.supports_sql:
                    supported_modes.append("sql")
                if caps.supports_dataframe:
                    supported_modes.append("dataframe")
                console.print(f"[red]❌ Platform '{platform_key}' does not support {s.mode} mode[/red]")
                console.print(f"[yellow]Supported modes: {', '.join(supported_modes)}[/yellow]")
                if s.logger:
                    s.logger.error(f"Platform {platform_key} does not support mode: {s.mode}")
                s.ctx.exit(1)
            s.resolved_mode = s.mode
        else:
            s.resolved_mode = caps.default_mode

        if s.resolved_mode == "sql":
            if platform_key == "polars":
                try:
                    import polars  # noqa: F401

                    is_available = True
                except ImportError:
                    is_available = False
            else:
                is_available = s.platform_manager.is_platform_available(platform_key)
        else:
            is_available = caps.supports_dataframe
            if is_available and platform_key in ["polars", "pandas", "cudf", "dask"]:
                df_platforms = list_available_dataframe_platforms()
                legacy_key = f"{platform_key}-df"
                is_available = df_platforms.get(legacy_key, df_platforms.get(platform_key, False))

        if not is_available and not s.dry_run:
            from benchbox.utils.dependencies import get_install_command

            console.print(f"[red]❌ Platform '{platform_key}' is not available (missing dependencies)[/red]")
            install_cmd = get_install_command(platform_key)
            console.print(f"Run [cyan]{escape(install_cmd)}[/cyan] to install dependencies.")
            s.ctx.exit(1)

    if s.logger and s.resolved_mode:
        s.logger.debug(f"Resolved execution mode for {platform_key}: {s.resolved_mode}")


def _check_benchmark_platform_compatibility(s: types.SimpleNamespace) -> None:
    """Reject benchmark+platform combinations that always fail before any execution begins."""
    if not s.platform_key or not s.benchmark:
        return

    try:
        gated_platform = resolve_platform_selector(s.platform_key)
    except ValueError:
        gated_platform = s.platform_key

    block_reason = PlatformRegistry.get_benchmark_block_reason(gated_platform, s.benchmark)

    if block_reason is None:
        return

    console.print(f"[red]❌ Benchmark '{s.benchmark}' is not compatible with platform '{s.platform_key}'[/red]")
    console.print(f"[yellow]{block_reason}[/yellow]")
    if s.logger:
        s.logger.error(f"Benchmark '{s.benchmark}' is incompatible with platform '{s.platform_key}': {block_reason}")
    s.ctx.exit(1)


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
        s.resolved_mode = s.mode if s.mode is not None else "sql"
        s.database_config.execution_mode = s.resolved_mode
