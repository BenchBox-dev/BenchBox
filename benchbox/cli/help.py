"""Custom help formatting for BenchBox CLI.

This module provides a tiered help system that shows only common options by default,
with advanced options revealed via --help-topic all.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import re
from importlib import resources
from typing import Any, cast

import click
import yaml


# Static help catalogs live in package data so the CLI keeps import-time public
# constants without embedding hundreds of command example lines in code.
def _load_help_catalog() -> dict[str, Any]:
    with resources.files("benchbox.data").joinpath("cli_help_catalog.yaml").open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("cli_help_catalog.yaml must contain a mapping")
    return cast("dict[str, Any]", payload)


_HELP_CATALOG = _load_help_catalog()

# Valid help topics
HELP_TOPICS = tuple(_HELP_CATALOG["help_topics"])

# Command categories for grouped help display. Order matters.
COMMAND_CATEGORIES: dict[str, tuple[str, list[str]]] = {
    key: (str(value[0]), list(value[1]))
    for key, value in cast("dict[str, list[Any]]", _HELP_CATALOG["command_categories"]).items()
}

# Examples registry - commands can register their examples here.
COMMAND_EXAMPLES: dict[str, dict[str, list[str]]] = cast(
    "dict[str, dict[str, list[str]]]", _HELP_CATALOG["command_examples"]
)


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
        from benchbox.core.benchmark_loader import get_core_benchmark_class

        found_any = False
        for bench_id in sorted(list_loader_benchmark_ids()):
            try:
                get_core_benchmark_class(bench_id)
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

        click.echo(
            click.style("\nApproximate aggregate guidance:\n", bold=True),
            color=ctx.color,
        )
        click.echo(
            "  read_primitives covers one-shot approximate aggregates "
            "(approx_count_distinct_*, approx_quantile*, approx_top_k_*).",
            color=ctx.color,
        )
        click.echo(
            "  Cross-engine function reference: docs/benchmarks/read-primitives-approximate-functions.md",
            color=ctx.color,
        )
        click.echo(
            "  write_primitives sketch category covers persist + merge + requery "
            "for DataSketches Theta / KLL / Top-K (sketch_query_*_merge / _combine).",
            color=ctx.color,
        )
        click.echo(
            "  Cross-engine sketch reference: docs/benchmarks/write-primitives-sketch-functions.md",
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
