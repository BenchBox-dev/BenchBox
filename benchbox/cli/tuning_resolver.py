"""Tuning file resolution with explicit transparency.

This module provides transparent tuning configuration resolution, ensuring users
always know exactly which tuning file is being used and where it came from.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from logging import Logger

    from benchbox.cli.config import ConfigManager
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration

_REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_template_reference(config_file: Path | None, repo_root: Path | None = None) -> str | None:
    """Compute a shareable reference for a tuning template file.

    Returns a repo-relative POSIX path when the file lives inside the
    BenchBox repository. Otherwise returns ``"<basename>:<16-hex-content-hash>"``
    so the reference stays stable and identifying without leaking the local
    filesystem layout. Never returns a raw absolute path - result bundles are
    shared across machines and users (see ADR-1 / must_preserve).

    Args:
        config_file: Resolved path to the tuning template file, or None.
        repo_root: Override for the repo root (tests only); defaults to the
            BenchBox checkout containing this module.

    Returns:
        A repo-relative path string, a basename+hash reference, or None if
        no config file was used.
    """
    if config_file is None:
        return None
    resolved = Path(config_file).resolve()
    root = repo_root if repo_root is not None else _REPO_ROOT
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        pass
    try:
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()[:16]
    except OSError:
        digest = "unreadable"
    return f"{resolved.name}:{digest}"


class TuningMode(Enum):
    """Tuning mode specifier."""

    TUNED = "tuned"
    NOTUNING = "notuning"
    AUTO = "auto"
    CUSTOM_FILE = "custom_file"


class TuningSource(Enum):
    """Source of the tuning configuration."""

    EXPLICIT_FILE = "explicit_file"  # User provided a file path
    AUTO_DISCOVERED = "auto_discovered"  # Found via template discovery
    SMART_DEFAULTS = "smart_defaults"  # Generated from system profile
    BASELINE = "baseline"  # No tuning (all disabled)
    INTERACTIVE_WIZARD = "wizard"  # User configured via wizard
    FALLBACK = "fallback"  # Fallback to basic config (template not found)


@dataclass
class TuningResolution:
    """Result of tuning resolution with full transparency metadata."""

    mode: TuningMode
    source: TuningSource
    enabled: bool
    config_file: Path | None = None
    searched_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info_messages: list[str] = field(default_factory=list)

    @property
    def source_description(self) -> str:
        """Human-readable description of where the config came from."""
        descriptions = {
            TuningSource.EXPLICIT_FILE: f"Loaded from explicit path: {self.config_file}",
            TuningSource.AUTO_DISCOVERED: f"Auto-discovered template: {self.config_file}",
            TuningSource.SMART_DEFAULTS: "Generated from system profile (auto mode)",
            TuningSource.BASELINE: "Baseline mode (all optimizations disabled)",
            TuningSource.INTERACTIVE_WIZARD: "Configured via interactive wizard",
            TuningSource.FALLBACK: "Fallback to basic constraints (no template found)",
        }
        return descriptions.get(self.source, "Unknown source")


def get_tuning_template_paths(platform: str, benchmark: str) -> list[Path]:
    """Get all paths that will be searched for tuning templates.

    Search order (highest priority first):
    1. BENCHBOX_TUNING_PATH environment variable (if set)
    2. Project-relative path: examples/tunings/{platform}/{benchmark}_tuned.yaml
    3. Current working directory: {platform}/{benchmark}_tuned.yaml

    The BENCHBOX_TUNING_PATH can be set to a custom directory containing
    platform-specific tuning templates following the same structure:
        $BENCHBOX_TUNING_PATH/{platform}/{benchmark}_tuned.yaml

    Args:
        platform: Platform name (e.g., 'duckdb', 'snowflake')
        benchmark: Benchmark name (e.g., 'tpch', 'tpcds')

    Returns:
        List of paths in search order (first match wins)
    """
    paths = []

    # 1. Environment variable override path (highest priority)
    env_path = os.environ.get("BENCHBOX_TUNING_PATH")
    if env_path:
        env_template = Path(env_path) / f"{platform.lower()}" / f"{benchmark.lower()}_tuned.yaml"
        paths.append(env_template)

    # 2. Project-relative path (standard location)
    primary = Path(f"examples/tunings/{platform.lower()}/{benchmark.lower()}_tuned.yaml")
    paths.append(primary)

    # 3. Current working directory fallback
    cwd_template = Path(f"{platform.lower()}/{benchmark.lower()}_tuned.yaml")
    if cwd_template != primary:  # Avoid duplicate if cwd is project root
        paths.append(cwd_template)

    return paths


def list_available_tuning_templates(
    platform: str | None = None,
    benchmark: str | None = None,
    base_path: Path | None = None,
) -> dict[str, list[Path]]:
    """List all available tuning templates, optionally filtered.

    Args:
        platform: Filter to specific platform (optional)
        benchmark: Filter to specific benchmark (optional)
        base_path: Base path for tuning files (default: examples/tunings)

    Returns:
        Dictionary mapping platform names to list of available template paths
    """
    if base_path is None:
        base_path = Path("examples/tunings")

    templates: dict[str, list[Path]] = {}

    if not base_path.exists():
        return templates

    for platform_dir in base_path.iterdir():
        if not platform_dir.is_dir():
            continue

        platform_name = platform_dir.name

        # Filter by platform if specified
        if platform and platform.lower() != platform_name.lower():
            continue

        platform_templates = []
        for template_file in platform_dir.glob("*.yaml"):
            # Filter by benchmark if specified
            if benchmark and not template_file.stem.lower().startswith(benchmark.lower()):
                continue

            platform_templates.append(template_file)

        if platform_templates:
            templates[platform_name] = sorted(platform_templates)

    return templates


def resolve_tuning(
    tuning_arg: str,
    platform: str | None,
    benchmark: str | None,
    config_manager: ConfigManager,
    console: Console,
    logger: Logger | None = None,
    quiet: bool = False,
    non_interactive: bool = False,
) -> TuningResolution:
    """Resolve tuning configuration with full transparency.

    This function determines the tuning configuration to use based on the
    --tuning argument, providing clear feedback about what was resolved.

    Args:
        tuning_arg: The --tuning argument value
        platform: Target platform name
        benchmark: Target benchmark name
        config_manager: Configuration manager instance
        console: Rich console for output
        logger: Optional logger for debug output
        quiet: Suppress informational output
        non_interactive: Disable interactive prompts

    Returns:
        TuningResolution with full metadata about the resolution
    """
    tuning_lower = tuning_arg.lower()

    # Keyword checks (Cases 1-3) all run before the path-existence check (Case 4)
    # so that a local file/directory named like a keyword (e.g. "./tuned") can
    # never shadow the keyword's meaning.

    # === Case 1: notuning - baseline mode ===
    if tuning_lower == "notuning":
        return _resolve_notuning(logger)

    # === Case 2: auto - smart defaults from system profile ===
    if tuning_lower == "auto":
        return _resolve_auto(logger)

    # === Case 3: tuned - auto-discovery or fallback ===
    if tuning_lower == "tuned":
        return _resolve_tuned(platform, benchmark, config_manager, logger)

    # === Case 4: Explicit file path ===
    tuning_path = Path(tuning_arg)
    if tuning_path.exists():
        return _resolve_explicit_file(tuning_path, logger)

    # === Case 5: Invalid value (not a keyword and file doesn't exist) ===
    _raise_invalid_tuning_value(tuning_arg)


def _resolve_notuning(logger: Logger | None) -> TuningResolution:
    """Resolve notuning (baseline) mode."""
    resolution = TuningResolution(
        mode=TuningMode.NOTUNING,
        source=TuningSource.BASELINE,
        enabled=False,
    )
    resolution.info_messages.append("Tuning disabled: running baseline comparison (no optimizations)")
    if logger:
        logger.debug("Tuning mode: notuning (baseline)")
    return resolution


def _resolve_auto(logger: Logger | None) -> TuningResolution:
    """Resolve auto (smart defaults) mode."""
    resolution = TuningResolution(
        mode=TuningMode.AUTO,
        source=TuningSource.SMART_DEFAULTS,
        enabled=True,
    )
    resolution.info_messages.append("Tuning mode: auto (using smart defaults based on system profile)")
    if logger:
        logger.debug("Tuning mode: auto (smart defaults)")
    return resolution


def _resolve_explicit_file(tuning_path: Path, logger: Logger | None) -> TuningResolution:
    """Resolve an explicit file path."""
    resolution = TuningResolution(
        mode=TuningMode.CUSTOM_FILE,
        source=TuningSource.EXPLICIT_FILE,
        enabled=True,
        config_file=tuning_path.resolve(),
    )
    resolution.info_messages.append(f"Tuning: loading configuration from {resolution.config_file}")
    if logger:
        logger.debug(f"Tuning mode: explicit file ({resolution.config_file})")
    return resolution


def _resolve_tuned(
    platform: str | None,
    benchmark: str | None,
    config_manager: ConfigManager,
    logger: Logger | None,
) -> TuningResolution:
    """Resolve tuned mode with auto-discovery or fallback."""
    resolution = TuningResolution(
        mode=TuningMode.TUNED,
        source=TuningSource.FALLBACK,
        enabled=True,
    )

    # First, check if there's a default config file in config
    default_config = config_manager.get("tuning.default_config_file")
    if default_config:
        default_path = Path(default_config)
        if default_path.exists():
            resolution.source = TuningSource.EXPLICIT_FILE
            resolution.config_file = default_path.resolve()
            resolution.info_messages.append(
                f"Tuning: using default config from benchbox.yaml: {resolution.config_file}"
            )
            if logger:
                logger.debug(f"Tuning mode: tuned (config file default: {resolution.config_file})")
            return resolution
        else:
            resolution.warnings.append(f"Default tuning config '{default_config}' from benchbox.yaml not found")

    if platform and benchmark:
        search_paths = get_tuning_template_paths(platform, benchmark)
        resolution.searched_paths = search_paths

        for path in search_paths:
            if path.exists():
                resolution.source = TuningSource.AUTO_DISCOVERED
                resolution.config_file = path.resolve()
                resolution.info_messages.append(f"Tuning: auto-discovered template at {resolution.config_file}")
                if logger:
                    logger.debug(f"Tuning mode: tuned (auto-discovered: {resolution.config_file})")
                return resolution

        resolution.warnings.append(
            f"No tuning template found for {platform}/{benchmark}. Searched: {', '.join(str(p) for p in search_paths)}"
        )
        resolution.info_messages.append("Tuning: using basic constraints (no optimized template available)")
        if logger:
            logger.debug("Tuning mode: tuned (fallback - no template found)")
    else:
        resolution.warnings.append("Cannot auto-discover tuning template without platform and benchmark specified")
        resolution.info_messages.append("Tuning: using basic constraints")
        if logger:
            logger.debug("Tuning mode: tuned (fallback - no platform/benchmark)")

    return resolution


def _raise_invalid_tuning_value(tuning_arg: str) -> None:
    """Raise ValueError for invalid tuning argument."""
    if "/" in tuning_arg or "\\" in tuning_arg or tuning_arg.endswith(".yaml"):
        raise ValueError(
            f"Tuning file not found: '{tuning_arg}'\n"
            f"Please verify the file exists at the specified path.\n"
            f"Use 'benchbox tuning list' to see available templates."
        )
    else:
        raise ValueError(
            f"Invalid tuning value: '{tuning_arg}'\n"
            f"Valid options:\n"
            f"  'tuned'    - Enable optimizations (auto-discovers template)\n"
            f"  'notuning' - Disable all optimizations (baseline mode)\n"
            f"  'auto'     - Use smart defaults based on system profile\n"
            f"  PATH       - Path to custom YAML config file\n"
            f"\nUse 'benchbox tuning list' to see available templates."
        )


def display_tuning_resolution(
    resolution: TuningResolution,
    console: Console,
    verbose: bool = False,
) -> None:
    """Display tuning resolution information to the user.

    Args:
        resolution: The resolved tuning configuration
        console: Rich console for output
        verbose: Show additional details
    """
    # Always show the primary info message
    for msg in resolution.info_messages:
        if resolution.source == TuningSource.BASELINE:
            console.print(f"[dim]{msg}[/dim]")
        elif resolution.source in (TuningSource.AUTO_DISCOVERED, TuningSource.EXPLICIT_FILE):
            console.print(f"[green]{msg}[/green]")
        else:
            console.print(f"[blue]{msg}[/blue]")

    # Show warnings
    for warning in resolution.warnings:
        console.print(f"[yellow]Warning: {warning}[/yellow]")

    # In verbose mode, show additional details
    if verbose and resolution.searched_paths:
        console.print("[dim]Searched paths:[/dim]")
        for path in resolution.searched_paths:
            exists_marker = "[green]found[/green]" if path.exists() else "[dim]not found[/dim]"
            console.print(f"  [dim]{path}[/dim] ({exists_marker})")


def display_tuning_list(
    console: Console,
    platform: str | None = None,
    benchmark: str | None = None,
) -> None:
    """Display available tuning templates.

    Args:
        console: Rich console for output
        platform: Filter to specific platform (optional)
        benchmark: Filter to specific benchmark (optional)
    """
    templates = list_available_tuning_templates(platform, benchmark)

    if not templates:
        if platform or benchmark:
            console.print(
                f"[yellow]No tuning templates found"
                f"{f' for platform {platform}' if platform else ''}"
                f"{f' and benchmark {benchmark}' if benchmark else ''}[/yellow]"
            )
        else:
            console.print("[yellow]No tuning templates found in examples/tunings/[/yellow]")

        console.print("\n[dim]Templates should be placed in examples/tunings/<platform>/<benchmark>_tuned.yaml[/dim]")
        return

    table = Table(title="Available Tuning Templates", show_header=True)
    table.add_column("Platform", style="cyan")
    table.add_column("Template", style="green")
    table.add_column("Path", style="dim")

    for platform_name, template_files in sorted(templates.items()):
        for template_file in template_files:
            # Extract benchmark name from filename
            template_name = template_file.stem  # e.g., "tpch_tuned"
            table.add_row(
                platform_name,
                template_name,
                str(template_file),
            )

    console.print(table)

    # Show usage hint
    console.print("\n[bold]Usage:[/bold]")
    console.print("  [cyan]benchbox run --tuning tuned[/cyan]   Auto-discovers template for platform/benchmark")
    console.print("  [cyan]benchbox run --tuning <path>[/cyan]  Uses specific template file")
    console.print("\n[dim]Template discovery pattern: examples/tunings/<platform>/<benchmark>_tuned.yaml[/dim]")


def display_tuning_show(
    console: Console,
    config: UnifiedTuningConfiguration | None,
    resolution: TuningResolution,
) -> None:
    """Display the resolved tuning configuration details.

    Args:
        console: Rich console for output
        config: The loaded tuning configuration (may be None if loading failed)
        resolution: Resolution metadata
    """
    import yaml
    from rich.syntax import Syntax

    # Build panel content
    content_lines = [
        f"[bold]Source:[/bold] {resolution.source_description}",
        f"[bold]Mode:[/bold] {resolution.mode.value}",
        f"[bold]Enabled:[/bold] {'Yes' if resolution.enabled else 'No'}",
    ]

    if resolution.config_file:
        content_lines.append(f"[bold]File:[/bold] {resolution.config_file}")

    panel = Panel(
        "\n".join(content_lines),
        title="Tuning Resolution",
        border_style="cyan",
    )
    console.print(panel)

    # Show configuration content (explicit None check for type safety)
    if config is not None:
        console.print("\n[bold]Configuration:[/bold]")
        config_dict = config.to_dict()
        config_yaml = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
        syntax = Syntax(config_yaml, "yaml", theme="monokai", line_numbers=True)
        console.print(syntax)
