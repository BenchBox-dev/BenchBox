"""Platform management and detection for BenchBox CLI.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import sys
from pathlib import Path
from typing import Any, Optional

import click
import yaml
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, InvalidResponse, Prompt
from rich.table import Table
from rich.text import Text

from benchbox.cli.platform_readiness import (
    PlatformReadinessResult,
    check_platform_readiness,
    has_readiness_failures,
)
from benchbox.core.platform_manifest import DefaultMode, get_platform_alias_modes, get_platform_aliases
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.core.schemas import LibraryInfo, PlatformInfo
from benchbox.utils.printing import quiet_console

console = quiet_console

# CLI spellings are a scoped platform-manifest projection. DataFrame ``-df``
# aliases carry explicit mode semantics in the manifest; ``benchbox run``
# captures that suffix before calling this normalizer.
PLATFORM_ALIASES: dict[str, str] = get_platform_aliases("cli")
PLATFORM_ALIAS_MODES: dict[str, DefaultMode] = get_platform_alias_modes("cli")


def normalize_platform_name(name: str) -> str:
    """Normalize platform name: lowercase and resolve aliases."""
    normalized = name.lower()
    return PLATFORM_ALIASES.get(normalized, normalized)


def get_platform_alias_mode(name: str) -> DefaultMode | None:
    """Return an execution mode explicitly implied by a scoped CLI alias."""
    return PLATFORM_ALIAS_MODES.get(name.lower())


_SUPPORT_STATUS_STYLES = {
    "stable": "green",
    "beta": "cyan",
    "experimental": "yellow",
    "deprecated": "red",
}


#: Tier order for display: the tiers a user can rely on come first, and an
#: unrecognised status sorts last rather than being folded into a known tier.
_SUPPORT_STATUS_ORDER = ("stable", "beta", "experimental", "deprecated")


def _support_tier_rank(support_status: str | None) -> tuple[int, str]:
    if not support_status or support_status not in _SUPPORT_STATUS_ORDER:
        return (len(_SUPPORT_STATUS_ORDER), support_status or "")
    return (_SUPPORT_STATUS_ORDER.index(support_status), "")


def _platforms_by_support_tier(platforms: dict) -> list[tuple[str, Any]]:
    """Order platforms by support tier, then by display name within a tier.

    Stable rows first answers "which of these actually work" without the user
    reading all 51. Ordering is stable within a tier so the table does not
    reshuffle between runs.
    """
    return sorted(
        platforms.items(),
        key=lambda item: (_support_tier_rank(item[1].support_status), item[1].display_name.lower()),
    )


def _support_tier_counts(platforms: dict) -> dict[str, int]:
    """Count platforms per support tier, in display order."""
    counts: dict[str, int] = {}
    for _name, info in _platforms_by_support_tier(platforms):
        tier = info.support_status if info.support_status else "unknown"
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def _format_support_status(support_status: str | None) -> str:
    """Render a platform's product support tier for display.

    This is the registry's `support_status`, not local driver availability. An
    unrecognised or absent status renders as "unknown" rather than defaulting to
    a tier, so the CLI never invents a support promise the registry did not make.
    """
    if not support_status:
        return "[dim]unknown[/dim]"
    style = _SUPPORT_STATUS_STYLES.get(support_status)
    if style is None:
        return f"[dim]{support_status}[/dim]"
    return f"[{style}]{support_status}[/{style}]"


class NumberedSelectPrompt(Prompt):
    """A prompt that displays numbered options and accepts number or name input.

    Displays a numbered list of options and allows users to select by:
    - Entering the number (e.g., "1", "2", "3")
    - Entering the option name/value (e.g., "enable", "duckdb")

    Example usage:
        action = NumberedSelectPrompt.ask(
            "What would you like to do?",
            options=[
                ("enable", "Enable platform"),
                ("disable", "Disable platform"),
                ("done", "Done"),
            ],
            default="done",
        )
    """

    def __init__(
        self,
        prompt: str,
        *,
        options: list[tuple[str, str]],
        default: str | None = None,
        console: Any = None,
    ):
        """Initialize the numbered select prompt.

        Args:
            prompt: The prompt text to display
            options: List of (value, label) tuples. Value is returned, label is displayed.
            default: Default value (must match a value from options)
            console: Rich console instance
        """
        self.options = options
        self._value_to_number = {value: i + 1 for i, (value, _) in enumerate(options)}
        self._number_to_value = {i + 1: value for i, (value, _) in enumerate(options)}
        self._valid_values = {value for value, _ in options}
        self._default_value = default

        super().__init__(
            prompt,
            console=console or quiet_console,
        )

    def make_prompt(self, default: str) -> Text:
        """Build the prompt text with numbered options displayed above."""
        # Display numbered options
        for i, (value, label) in enumerate(self.options, 1):
            default_marker = " (default)" if value == self._default_value else ""
            self.console.print(f"  [cyan]{i}.[/cyan] {label}{default_marker}")

        self.console.print()

        # Build the input prompt
        prompt_text = Text()
        prompt_text.append(self.prompt)
        prompt_text.append(" ")
        prompt_text.append(f"[1-{len(self.options)}]", style="dim")
        if self._default_value:
            default_num = self._value_to_number[self._default_value]
            prompt_text.append(f" ({default_num})", style="dim")
        prompt_text.append(self.prompt_suffix)
        return prompt_text

    def process_response(self, value: str) -> str:
        """Process the response, accepting either number or name."""
        value = value.strip()

        # Empty input with default
        if not value and self._default_value:
            return self._default_value

        # Try as number first
        try:
            num = int(value)
            if num in self._number_to_value:
                return self._number_to_value[num]
            raise InvalidResponse(f"[red]Invalid selection: {num}. Enter 1-{len(self.options)}.[/red]")
        except ValueError:
            pass

        # Try as value/name (case-insensitive)
        value_lower = value.lower()
        for opt_value, _ in self.options:
            if opt_value.lower() == value_lower:
                return opt_value

        # Not found
        valid_names = ", ".join(v for v, _ in self.options)
        raise InvalidResponse(f"[red]Invalid selection: '{value}'. Enter 1-{len(self.options)} or: {valid_names}[/red]")

    @classmethod
    def ask(
        cls,
        prompt: str,
        *,
        options: list[tuple[str, str]],
        default: str | None = None,
        console: Any = None,
    ) -> str:
        """Display numbered options and prompt for selection.

        Args:
            prompt: The question/prompt to display
            options: List of (value, label) tuples
            default: Default value to use if user presses Enter
            console: Rich console instance

        Returns:
            The selected option's value
        """
        _prompt = cls(prompt, options=options, default=default, console=console)
        return _prompt()


def numbered_platform_select(
    prompt: str,
    platforms: dict[str, "PlatformInfo"],
    *,
    filter_func: Any = None,
    group_by_status: bool = True,
    console_instance: Any = None,
) -> str | None:
    """Display platforms as a numbered list and prompt for selection.

    Args:
        prompt: The prompt text to display
        platforms: Dictionary of platform name -> PlatformInfo
        filter_func: Optional function to filter platforms (receives PlatformInfo, returns bool)
        group_by_status: If True, group platforms by enabled/available/missing status
        console_instance: Rich console instance

    Returns:
        Selected platform name, or None if cancelled
    """
    _console = console_instance or console

    filtered = {name: info for name, info in platforms.items() if filter_func(info)} if filter_func else platforms

    if not filtered:
        _console.print("[yellow]No platforms match the criteria.[/yellow]")
        return None

    options = _build_platform_options(filtered, group_by_status, _console)

    _console.print()
    return _prompt_platform_selection(prompt, options, filtered, _console)


def _build_platform_options(
    filtered: dict[str, "PlatformInfo"], group_by_status: bool, _console: Any
) -> list[tuple[str, str]]:
    """Build numbered options list from platforms, optionally grouped by status."""
    options: list[tuple[str, str]] = []

    if group_by_status:
        groups = [
            ("Enabled", "bold green", [(n, i) for n, i in filtered.items() if i.enabled]),
            (
                "Available (not enabled)",
                "bold yellow",
                [(n, i) for n, i in filtered.items() if i.available and not i.enabled],
            ),
            ("Missing dependencies", "bold red", [(n, i) for n, i in filtered.items() if not i.available]),
        ]
        for label, style, members in groups:
            if members:
                _console.print(f"\n[{style}]{label}:[/{style}]")
                for name, info in sorted(members, key=lambda x: x[1].display_name):
                    num = len(options) + 1
                    _console.print(f"  [cyan]{num}.[/cyan] {info.display_name} [dim]({name})[/dim]")
                    options.append((name, info.display_name))
    else:
        for name, info in sorted(filtered.items(), key=lambda x: x[1].display_name):
            num = len(options) + 1
            _console.print(f"  [cyan]{num}.[/cyan] {info.display_name} [dim]({name})[/dim]")
            options.append((name, info.display_name))

    return options


def _prompt_platform_selection(
    prompt: str, options: list[tuple[str, str]], filtered: dict[str, Any], _console: Any
) -> str | None:
    """Prompt user to select a platform by number or name."""
    prompt_text = f"{prompt} [1-{len(options)}]"

    while True:
        response = Prompt.ask(prompt_text, console=_console)
        response = response.strip()

        if not response:
            return None

        try:
            num = int(response)
            if 1 <= num <= len(options):
                return options[num - 1][0]
            _console.print(f"[red]Invalid selection: {num}. Enter 1-{len(options)}.[/red]")
            continue
        except ValueError:
            pass

        normalized = normalize_platform_name(response)
        if normalized in filtered:
            return normalized

        _console.print(f"[red]Unknown platform: '{response}'. Enter a number or platform name.[/red]")


class PlatformManager:
    """Manages platform detection, configuration, and CLI commands."""

    def __init__(self, config_path: Optional[Path] = None):
        self.console = quiet_console
        self.config_path = config_path or Path.home() / ".benchbox" / "platforms.yaml"
        self._config = self._load_config()

    @property
    def platform_registry(self) -> dict[str, Any]:
        """Get platform registry metadata for all platforms."""
        return PlatformRegistry.get_all_platform_metadata()

    def _detect_library(self, lib_spec: dict[str, Any]) -> LibraryInfo:
        """Detect a single library."""
        return PlatformRegistry.detect_library(lib_spec)

    def _load_config(self) -> dict[str, Any]:
        """Load platform configuration from file."""
        if not self.config_path.exists():
            return {"enabled_platforms": PlatformRegistry.get_platform_names()}

        try:
            with open(self.config_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to load platform config: {e}[/yellow]")
            return {"enabled_platforms": PlatformRegistry.get_platform_names()}

    def _save_config(self):
        """Save platform configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(self._config, f, default_flow_style=False)
        except Exception as e:
            console.print(f"[red]Error: Failed to save platform config: {e}[/red]")

    def detect_platforms(self) -> dict[str, PlatformInfo]:
        """Detect all platforms and their availability."""
        platforms = {}
        # Use all platforms in metadata registry instead of just those with adapters
        all_platform_names = list(self.platform_registry.keys())
        available_platform_names = PlatformRegistry.get_available_platforms()

        # Enabled platforms from config
        enabled_platforms = self._config.get("enabled_platforms", available_platform_names)

        for platform_name in all_platform_names:
            platform_info = PlatformRegistry.get_platform_info(platform_name)
            if platform_info:
                # Override enabled status with config
                platform_info.enabled = platform_name in enabled_platforms and platform_info.available
                platforms[platform_name] = platform_info

        return platforms

    def get_available_platforms(self) -> list[str]:
        """Get list of available platform names (detected as available)."""
        detected = self.detect_platforms()
        return [name for name, info in detected.items() if info.available]

    def get_enabled_platforms(self) -> list[str]:
        """Get list of enabled platform names."""
        platforms = self.detect_platforms()
        return [name for name, info in platforms.items() if info.enabled]

    def get_valid_platforms_for_cli(self) -> list[str]:
        """Get list of platform names that should be shown in CLI choices."""
        return self.get_enabled_platforms()

    def is_platform_available(self, platform_name: str) -> bool:
        """Check if a specific platform is available."""
        return PlatformRegistry.is_platform_available(platform_name)

    def enable_platform(self, platform_name: str) -> bool:
        """Enable a platform."""
        platform_info = PlatformRegistry.get_platform_info(platform_name)

        if not platform_info:
            return False

        if not platform_info.available:
            return False

        enabled_platforms = set(self._config.get("enabled_platforms", []))
        enabled_platforms.add(platform_name)
        self._config["enabled_platforms"] = list(enabled_platforms)
        self._save_config()
        return True

    def disable_platform(self, platform_name: str) -> bool:
        """Disable a platform."""
        platform_info = PlatformRegistry.get_platform_info(platform_name)
        if not platform_info:
            return False

        enabled_platforms = set(self._config.get("enabled_platforms", []))
        enabled_platforms.discard(platform_name)
        self._config["enabled_platforms"] = list(enabled_platforms)
        self._save_config()
        return True

    def get_installation_guide(self, platform_name: str) -> Optional[dict[str, Any]]:
        """Get detailed installation guide for a platform."""
        platform_info = PlatformRegistry.get_platform_info(platform_name)
        if not platform_info:
            return None

        missing_libs = [lib for lib in platform_info.libraries if not lib.installed]

        return {
            "platform": platform_info.display_name,
            "description": platform_info.description,
            "installation_command": platform_info.installation_command,
            "requirements": platform_info.requirements,
            "missing_libraries": [lib.name for lib in missing_libs],
            "available": platform_info.available,
            "category": platform_info.category,
        }

    def display_platform_status(self, detail: bool = False):
        """Display the platform status table.

        The default view is deliberately narrow. With 51 platforms, the full
        table does not fit an 80-column terminal: Rich truncates every
        informative header to an ellipsis and wraps Description into six rows
        of single-word fragments per platform, which destroys exactly the
        answer the user came for -- which of these platforms actually work.

        So Category and Description move behind ``--detail``, and rows are
        ordered by support tier with a per-tier count in the summary. Nothing
        is hidden or gated: every platform still appears, and every row still
        carries its tier, per
        ``_project/decisions/architecture-support-tier-commitment.md``.

        Args:
            detail: Restore the Category and Description columns.
        """
        platforms = self.detect_platforms()

        table = Table(title="BenchBox Platform Status")
        table.add_column("Platform", style="cyan", no_wrap=True)
        # "Driver" is local dependency availability; "Support" is the product
        # support tier from the registry. They are independent: a stable platform
        # can be Missing locally, and an installed driver implies nothing about
        # the tier. See docs/reference/public-contracts.md ("Support Status
        # Taxonomy"), which states the two must not be conflated.
        table.add_column("Driver", style="bold")
        table.add_column("Support", style="bold")
        table.add_column("Libraries", style="dim")
        if detail:
            table.add_column("Category", style="magenta")
            table.add_column("Description", style="dim")

        for name, info in _platforms_by_support_tier(platforms):
            # Driver column - is the local dependency installed?
            if info.enabled:
                status = "[green]✅ Enabled[/green]"
            elif info.available:
                status = "[yellow]○ Available[/yellow]"
            else:
                status = "[red]❌ Missing[/red]"

            # Support column - product support tier, independent of the above
            support = _format_support_status(info.support_status)

            # Libraries column
            lib_statuses = []
            for lib in info.libraries:
                if lib.installed:
                    version_str = f" ({lib.version})" if lib.version else ""
                    lib_statuses.append(f"[green]{lib.name}{version_str}[/green]")
                else:
                    lib_statuses.append(f"[red]{lib.name}[/red]")

            libraries = ", ".join(lib_statuses)

            row = [info.display_name, status, support, libraries]
            if detail:
                category = info.category if info.category else "database"
                row.extend([category.title(), info.description])
            table.add_row(*row)

        self.console.print(table)

        # Show summary
        total_platforms = len(platforms)
        available_count = sum(1 for p in platforms.values() if p.available)
        enabled_count = sum(1 for p in platforms.values() if p.enabled)

        summary = f"[bold]Summary:[/bold] {enabled_count} enabled, {available_count} available, {total_platforms} total"
        self.console.print(f"\n{summary}")
        tier_counts = _support_tier_counts(platforms)
        if tier_counts:
            tiers = ", ".join(f"{count} {tier}" for tier, count in tier_counts.items())
            self.console.print(f"[bold]By support tier:[/bold] {tiers}")
        if not detail:
            self.console.print("[dim]Run with --detail for category and description.[/dim]")

    def emit_platform_json(self) -> None:
        """Emit the full platform record as JSON on stdout.

        The narrow default table drops columns to stay readable. This is the
        path that loses nothing, so a script never has to parse the table.
        Printed through ``print`` rather than the Rich console so the output
        is exactly JSON, with no wrapping or markup.
        """
        platforms = self.detect_platforms()
        payload = [
            {
                "name": name,
                "display_name": info.display_name,
                "support_status": info.support_status,
                "category": info.category,
                "description": info.description,
                "enabled": info.enabled,
                "available": info.available,
                "installation_command": info.installation_command,
                "libraries": [
                    {"name": lib.name, "installed": lib.installed, "version": lib.version} for lib in info.libraries
                ],
            }
            for name, info in _platforms_by_support_tier(platforms)
        ]
        print(json.dumps({"platforms": payload}, indent=2))

    def display_platform_list(self, show_all: bool = True):
        """Display platform list for 'benchbox platforms list' command.

        Note: Database selection uses a different table-based display.
        """
        platforms = self.detect_platforms()

        self.console.print("[bold cyan]BenchBox Platforms[/bold cyan]\n")

        for name, info in platforms.items():
            if not show_all and not info.available:
                continue

            status_icon = "✅" if info.enabled else ("○" if info.available else "❌")
            status_color = "green" if info.enabled else ("yellow" if info.available else "red")

            support = _format_support_status(info.support_status)
            self.console.print(
                f"[{status_color}]{status_icon}[/{status_color}] {info.display_name} ({name}) - {support}"
            )
            self.console.print(f"   {info.description}")

            if not info.available:
                self.console.print(f"   [dim]Install: {info.installation_command}[/dim]")

            self.console.print()

    def display_platform_deployments(self, filter_platform: Optional[str] = None):
        """Display platform deployment modes.

        Args:
            filter_platform: Optional platform name to filter results
        """
        platforms = self.detect_platforms()

        table = Table(title="Platform Deployment Modes")
        table.add_column("Platform", style="cyan", no_wrap=True)
        table.add_column("Mode", style="bold")
        table.add_column("Type", style="magenta")
        table.add_column("Default", style="dim")
        table.add_column("Requirements", style="dim")

        has_deployments = False

        for name, info in sorted(platforms.items()):
            if filter_platform and name != filter_platform:
                continue

            # Get deployment modes from registry
            caps = PlatformRegistry.get_platform_capabilities(name)
            if not caps or not caps.deployment_modes:
                continue

            has_deployments = True
            default_deployment = caps.default_deployment

            for mode_name, deployment_cap in caps.deployment_modes.items():
                is_default = "✓" if mode_name == default_deployment else ""

                # Build requirements list
                requirements = []
                if deployment_cap.requires_credentials:
                    requirements.append("credentials")
                if deployment_cap.requires_cloud_storage:
                    requirements.append("cloud storage")
                if deployment_cap.requires_network:
                    requirements.append("network")
                req_str = ", ".join(requirements) if requirements else "-"

                # Format: platform:mode for CLI usage
                cli_name = f"{name}:{mode_name}"

                table.add_row(
                    info.display_name,
                    cli_name,
                    deployment_cap.mode,
                    is_default,
                    req_str,
                )

        if has_deployments:
            self.console.print(table)
            self.console.print()
            self.console.print("[dim]Usage: benchbox run --platform <platform>:<mode> --benchmark tpch[/dim]")
            self.console.print("[dim]Example: benchbox run --platform clickhouse-server --benchmark tpch[/dim]")
        else:
            self.console.print("[yellow]No platforms with deployment modes configured.[/yellow]")


# Global platform manager instance
_platform_manager: Optional[PlatformManager] = None


def get_platform_manager() -> PlatformManager:
    """Get the global platform manager instance."""
    global _platform_manager
    if _platform_manager is None:
        _platform_manager = PlatformManager()
    return _platform_manager


def _readiness_platform_name(requested_platform: str, normalized_platform: str) -> str:
    """Preserve explicit DataFrame aliases for readiness messages."""
    requested = requested_platform.lower()
    return requested if requested.endswith("-df") else normalized_platform


def _append_readiness_details(panel_content: list[str], results: tuple[PlatformReadinessResult, ...]) -> None:
    """Append readiness details to a rich panel content list."""
    if not results:
        return

    panel_content.append("\n[bold]Readiness:[/bold]")
    for result in results:
        status_text = "Ready" if result.ready else "Environment skip"
        status_color = "green" if result.ready else "yellow"
        panel_content.append(f"  [{status_color}]{status_text}:[/{status_color}] {escape(result.summary)}")
        if result.detail:
            panel_content.append(f"    [dim]{escape(result.detail)}[/dim]")
        if result.remediation and not result.ready:
            panel_content.append(f"    [dim]Fix: {escape(result.remediation)}[/dim]")


def _print_readiness_details(results: tuple[PlatformReadinessResult, ...]) -> None:
    """Print readiness details under a platform check row."""
    for result in results:
        label = "ready" if result.ready else "environment skip"
        color = "green" if result.ready else "yellow"
        console.print(f"   [{color}]{label}:[/{color}] {escape(result.summary)}")
        if result.detail:
            console.print(f"      [dim]{escape(result.detail)}[/dim]")
        if result.remediation and not result.ready:
            console.print(f"      [dim]Fix: {escape(result.remediation)}[/dim]")


# CLI Commands


@click.group()
def platforms():
    """Manage database platform adapters."""


@platforms.command("list")
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    help="Show all platforms including unavailable ones",
)
@click.option(
    "--format",
    type=click.Choice(["table", "simple", "json"]),
    default="table",
    help="Output format",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit the full platform records as JSON",
)
@click.option(
    "--detail",
    is_flag=True,
    help="Add the category and description columns (needs a wide terminal)",
)
@click.option(
    "--show-deployments",
    is_flag=True,
    help="Show available deployment modes (local, server, cloud) per platform",
)
def list_platforms(show_all: bool, format: str, json_output: bool, detail: bool, show_deployments: bool):
    """List all available platforms and their status.

    The default table is ordered by support tier and omits category and
    description so it stays readable at 80 columns. Use --detail to add them
    back, or --json/--format json for the full record.

    Use --show-deployments to see available deployment modes for platforms
    that support multiple deployment targets (e.g., clickhouse-local, clickhouse-server).
    """
    manager = get_platform_manager()

    if show_deployments:
        manager.display_platform_deployments()
    elif json_output or format == "json":
        manager.emit_platform_json()
    elif format == "table":
        manager.display_platform_status(detail=detail)
    else:
        manager.display_platform_list(show_all=show_all)


@platforms.command("status")
@click.argument("platform", required=False)
def platform_status(platform: Optional[str]):
    """Show detailed status for all platforms or a specific platform."""
    manager = get_platform_manager()

    if platform:
        requested_platform = platform
        platform = normalize_platform_name(platform)
        # Show detailed status for specific platform
        platforms_info = manager.detect_platforms()

        if platform not in platforms_info:
            console.print(f"[red]❌ Unknown platform: {platform}[/red]")
            available = list(platforms_info.keys())
            console.print(f"Available platforms: {', '.join(available)}")
            sys.exit(1)

        info = platforms_info[platform]

        # Detailed panel
        status_color = "green" if info.enabled else ("yellow" if info.available else "red")
        status_text = "Enabled" if info.enabled else ("Available" if info.available else "Missing Dependencies")

        panel_content = []
        panel_content.append(f"[bold]Name:[/bold] {info.display_name}")
        panel_content.append(f"[bold]Description:[/bold] {info.description}")
        panel_content.append(f"[bold]Status:[/bold] [{status_color}]{status_text}[/{status_color}]")
        panel_content.append(f"[bold]Category:[/bold] {info.category.title()}")

        # Library details
        panel_content.append("\n[bold]Libraries:[/bold]")
        for lib in info.libraries:
            lib_status = "✅" if lib.installed else "❌"
            lib_color = "green" if lib.installed else "red"
            version_info = f" (v{lib.version})" if lib.version else ""
            panel_content.append(f"  [{lib_color}]{lib_status} {lib.name}{version_info}[/{lib_color}]")
            if not lib.installed and lib.import_error:
                panel_content.append(f"    [dim]Error: {lib.import_error}[/dim]")

        # Installation info
        if not info.available:
            panel_content.append("\n[bold]Installation:[/bold]")
            panel_content.append(f"  {info.installation_command}")
            panel_content.append("\n[bold]Requirements:[/bold]")
            for req in info.requirements:
                panel_content.append(f"  • {req}")

        readiness_platform = _readiness_platform_name(requested_platform, platform)
        _append_readiness_details(panel_content, check_platform_readiness(readiness_platform))

        console.print(
            Panel(
                "\n".join(panel_content),
                title=f"Platform: {info.display_name}",
                border_style=status_color,
            )
        )
    else:
        # Show status for all platforms
        manager.display_platform_status()


@platforms.command("enable")
@click.argument("platform")
@click.option("--force", is_flag=True, help="Enable platform even if dependencies are missing")
def enable_platform(platform: str, force: bool):
    """Enable a database platform."""
    platform = normalize_platform_name(platform)
    manager = get_platform_manager()
    platforms_info = manager.detect_platforms()

    if platform not in platforms_info:
        console.print(f"[red]❌ Unknown platform: {platform}[/red]")
        available = list(platforms_info.keys())
        console.print(f"Available platforms: {', '.join(available)}")
        sys.exit(1)

    info = platforms_info[platform]

    # Check if already enabled
    if info.enabled:
        console.print(f"[yellow]Platform {info.display_name} is already enabled[/yellow]")
        sys.exit(0)

    # Check availability
    if not info.available and not force:
        console.print(f"[red]❌ Cannot enable {info.display_name}: missing required dependencies[/red]")
        console.print("\nTo install dependencies:")
        console.print(f"  {info.installation_command}")
        console.print("\nOr use --force to enable anyway (may cause runtime errors)")
        sys.exit(1)

    # Enable the platform
    if manager.enable_platform(platform):
        if info.available:
            console.print(f"[green]✅ Enabled platform: {info.display_name}[/green]")
        else:
            console.print(f"[yellow]⚠️ Enabled platform: {info.display_name} (dependencies missing)[/yellow]")
        sys.exit(0)
    else:
        console.print(f"[red]❌ Failed to enable platform: {info.display_name}[/red]")
        sys.exit(1)


@platforms.command("disable")
@click.argument("platform")
def disable_platform(platform: str):
    """Disable a database platform."""
    platform = normalize_platform_name(platform)
    manager = get_platform_manager()
    platforms_info = manager.detect_platforms()

    if platform not in platforms_info:
        console.print(f"[red]❌ Unknown platform: {platform}[/red]")
        available = list(platforms_info.keys())
        console.print(f"Available platforms: {', '.join(available)}")
        sys.exit(1)

    info = platforms_info[platform]

    # Check if already disabled
    if not info.enabled:
        console.print(f"[yellow]Platform {info.display_name} is already disabled[/yellow]")
        sys.exit(0)

    # Confirm disabling
    if not Confirm.ask(f"Disable platform {info.display_name}?"):
        console.print("Cancelled")
        sys.exit(0)

    # Disable the platform
    if manager.disable_platform(platform):
        console.print(f"[yellow]○ Disabled platform: {info.display_name}[/yellow]")
        sys.exit(0)
    else:
        console.print(f"[red]❌ Failed to disable platform: {info.display_name}[/red]")
        sys.exit(1)


@platforms.command("install")
@click.argument("platform")
@click.option("--dry-run", is_flag=True, help="Show installation commands without executing")
def install_platform(platform: str, dry_run: bool):
    """Guide installation of platform dependencies."""
    platform = normalize_platform_name(platform)
    manager = get_platform_manager()
    guide = manager.get_installation_guide(platform)

    if not guide:
        console.print(f"[red]❌ Unknown platform: {platform}[/red]")
        platforms_info = manager.detect_platforms()
        available = list(platforms_info.keys())
        console.print(f"Available platforms: {', '.join(available)}")
        sys.exit(1)

    # Type checker doesn't understand that sys.exit prevents execution
    assert guide is not None

    # Show installation guide
    console.print(
        Panel.fit(
            Text(f"Installation Guide: {guide['platform']}", style="bold cyan"),
            style="cyan",
        )
    )

    console.print(f"\n[bold]Platform:[/bold] {guide['platform']}")
    console.print(f"[bold]Description:[/bold] {guide['description']}")
    console.print(f"[bold]Category:[/bold] {guide['category'].title()}")

    if guide["available"]:
        console.print("[bold]Status:[/bold] [green]Already installed and available[/green]")
        console.print(f"\nUse [cyan]benchbox platforms enable {platform}[/cyan] to enable this platform.")
        sys.exit(0)

    console.print("[bold]Status:[/bold] [red]Missing dependencies[/red]")

    if guide["missing_libraries"]:
        console.print("\n[bold]Missing Libraries:[/bold]")
        for lib in guide["missing_libraries"]:
            console.print(f"  • {lib}")

    console.print("\n[bold]Installation Command:[/bold]")
    console.print(f"  [cyan]{guide['installation_command']}[/cyan]")

    console.print("\n[bold]Requirements:[/bold]")
    for req in guide["requirements"]:
        console.print(f"  • {req}")

    if dry_run:
        console.print("\n[yellow]Dry run mode: No installation performed[/yellow]")
        sys.exit(0)

    console.print(f"\nAfter installation, run: [cyan]benchbox platforms enable {platform}[/cyan]")
    sys.exit(0)


@platforms.command("check")
@click.argument("platforms_to_check", nargs=-1)
@click.option("--enabled-only", is_flag=True, help="Check only enabled platforms")
def check_platforms(platforms_to_check: tuple, enabled_only: bool):
    """Check platform availability and configuration."""
    manager = get_platform_manager()
    platforms_info = manager.detect_platforms()

    if not platforms_to_check:
        selected_platforms = (
            tuple((p, p) for p in manager.get_enabled_platforms())
            if enabled_only
            else tuple((p, p) for p in platforms_info.keys())
        )
    else:
        # Normalize platform names (case + aliases), preserving the requested name for readiness context.
        selected_platforms = tuple((p, normalize_platform_name(p)) for p in platforms_to_check)

    if not selected_platforms:
        console.print("[yellow]No platforms to check[/yellow]")
        sys.exit(0)

    console.print("[bold cyan]Platform Check Results[/bold cyan]\n")

    all_good = True
    for requested_platform, platform in selected_platforms:
        if platform not in platforms_info:
            console.print(f"[red]❌ {platform}: Unknown platform[/red]")
            all_good = False
            continue

        info = platforms_info[platform]
        readiness_platform = _readiness_platform_name(requested_platform, platform)
        readiness_results = check_platform_readiness(readiness_platform)
        readiness_failed = has_readiness_failures(readiness_results)

        # Disabled platforms are always informational. A readiness failure on
        # an available-but-disabled platform must not fail `platforms check`,
        # since the user has opted out of running it; only an enabled platform
        # with a failed readiness probe is a real environment problem.
        if info.available and not info.enabled:
            console.print(f"[yellow]○ {info.display_name}: Available but disabled[/yellow]")
        elif info.available and readiness_failed:
            console.print(f"[yellow]⚠️ {info.display_name}: Environment not ready[/yellow]")
            all_good = False
        elif info.enabled and info.available:
            console.print(f"[green]✅ {info.display_name}: Ready[/green]")
        else:
            console.print(f"[red]❌ {info.display_name}: Missing dependencies[/red]")
            console.print(f"   Install: {info.installation_command}")
            all_good = False

        _print_readiness_details(readiness_results)

    if all_good:
        console.print("\n[green]All checked platforms are ready![/green]")
        sys.exit(0)
    else:
        console.print("\n[red]Some platforms need attention[/red]")
        sys.exit(1)


@platforms.command("setup")
@click.option("--interactive/--non-interactive", default=True, help="Interactive setup mode")
def setup_platforms(interactive: bool):
    """Interactive platform setup wizard."""
    manager = get_platform_manager()
    platforms_info = manager.detect_platforms()

    console.print(Panel.fit(Text("BenchBox Platform Setup", style="bold cyan"), style="cyan"))

    if not interactive:
        console.print("\n[yellow]Non-interactive mode: Enabling all available platforms[/yellow]")
        enabled_count = 0
        for name, info in platforms_info.items():
            if info.available and not info.enabled and manager.enable_platform(name):
                console.print(f"[green]✅ Enabled: {info.display_name}[/green]")
                enabled_count += 1

        console.print(f"\n[bold]Summary:[/bold] Enabled {enabled_count} platforms")
        sys.exit(0)

    console.print("\nThis wizard will help you set up database platforms for BenchBox.")
    console.print("You can enable/disable platforms and get installation guidance.\n")

    # Show current status summary
    enabled_count = sum(1 for info in platforms_info.values() if info.enabled)
    available_count = sum(1 for info in platforms_info.values() if info.available)
    missing_count = sum(1 for info in platforms_info.values() if not info.available)

    console.print(
        f"[bold]Current Status:[/bold] {enabled_count} enabled, {available_count} available, {missing_count} missing dependencies\n"
    )

    # Define action options for numbered menu
    action_options = [
        ("enable", "Enable a platform"),
        ("disable", "Disable a platform"),
        ("install", "Get installation guide"),
        ("status", "Show detailed status"),
        ("done", "Done - exit setup"),
    ]

    # Interactive platform management
    while True:
        action = NumberedSelectPrompt.ask(
            "What would you like to do?",
            options=action_options,
            default="done",
            console=console,
        )

        if action == "done":
            break
        elif action == "status":
            manager.display_platform_status()
        elif action == "install":
            console.print("\n[bold]Select platform for installation guide:[/bold]")
            platform = numbered_platform_select(
                "Platform",
                platforms_info,
                filter_func=lambda info: not info.available,
                group_by_status=False,
                console_instance=console,
            )
            if platform:
                assert install_platform.callback is not None
                install_platform.callback(platform, dry_run=False)
            else:
                console.print("[yellow]No platforms with missing dependencies.[/yellow]")
        elif action == "enable":
            console.print("\n[bold]Select platform to enable:[/bold]")
            platform = numbered_platform_select(
                "Platform",
                platforms_info,
                filter_func=lambda info: info.available and not info.enabled,
                group_by_status=False,
                console_instance=console,
            )
            if platform:
                assert enable_platform.callback is not None
                enable_platform.callback(platform, force=False)
            else:
                console.print("[yellow]No available platforms to enable.[/yellow]")
        elif action == "disable":
            console.print("\n[bold]Select platform to disable:[/bold]")
            platform = numbered_platform_select(
                "Platform",
                platforms_info,
                filter_func=lambda info: info.enabled,
                group_by_status=False,
                console_instance=console,
            )
            if platform:
                assert disable_platform.callback is not None
                disable_platform.callback(platform)
            else:
                console.print("[yellow]No enabled platforms to disable.[/yellow]")

        # Refresh platform info
        platforms_info = manager.detect_platforms()
        console.print()

    console.print("[green]Platform setup complete![/green]")

    # Show final summary
    enabled_count = sum(1 for info in platforms_info.values() if info.enabled)
    available_count = sum(1 for info in platforms_info.values() if info.available)

    console.print(f"\n[bold]Final Status:[/bold] {enabled_count} enabled, {available_count} available")
