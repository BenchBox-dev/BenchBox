"""Lazy command registration utilities for the BenchBox CLI."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

import click


@dataclass(frozen=True)
class CommandSpec:
    name: str
    module: str
    attr: str
    help: str
    hidden: bool = False
    deprecated: bool | str = False


COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec("run", "benchbox.cli.commands.run", "run", "Run benchmarks."),
    CommandSpec(
        "run-official",
        "benchbox.cli.commands.run_official",
        "run_official",
        "Run official benchmark phases.",
        True,
        True,
    ),
    CommandSpec("auth", "benchbox.cli.commands.auth", "auth", "Manage hosted result-submission credentials."),
    CommandSpec("publish", "benchbox.cli.commands.publish", "publish", "Publish and track schema-v2 result bundles."),
    CommandSpec(
        "compare",
        "benchbox.cli.commands.compare",
        "compare",
        "Compare benchmark results, query plans, or run cross-platform benchmarks.",
    ),
    CommandSpec(
        "compare-dataframes",
        "benchbox.cli.commands.compare_dataframes",
        "compare_dataframes",
        "Compare DataFrame platforms.",
        True,
        True,
    ),
    CommandSpec(
        "compare-plans",
        "benchbox.cli.commands.compare_plans",
        "compare_plans",
        "Compare captured query plans.",
        True,
        True,
    ),
    CommandSpec(
        "convert", "benchbox.cli.commands.convert", "convert", "Convert benchmark data to optimized table formats."
    ),
    CommandSpec(
        "plan-history", "benchbox.cli.commands.plan_history", "plan_history", "Show plan evolution history for a query."
    ),
    CommandSpec("show-plan", "benchbox.cli.commands.show_plan", "show_plan", "Display query plan as ASCII tree."),
    CommandSpec(
        "datagen", "benchbox.cli.commands.datagen", "datagen", "Generate benchmark data without running queries."
    ),
    CommandSpec(
        "aggregate",
        "benchbox.cli.commands.aggregate",
        "aggregate",
        "Aggregate multiple benchmark results into performance trends.",
    ),
    CommandSpec(
        "metrics", "benchbox.cli.commands.metrics", "metrics_group", "Calculate benchmark performance metrics."
    ),
    CommandSpec(
        "calculate-qphh",
        "benchbox.cli.commands.calculate_qphh",
        "calculate_qphh",
        "Calculate TPC-H QphH metric.",
        True,
        True,
    ),
    CommandSpec(
        "shell", "benchbox.cli.commands.shell", "shell", "Launch an interactive SQL shell for a database platform."
    ),
    CommandSpec(
        "profile",
        "benchbox.cli.commands.profile",
        "profile",
        "Profile the current system and provide optimization recommendations.",
    ),
    CommandSpec("benchmarks", "benchbox.cli.commands.benchmarks", "benchmarks", "Manage benchmark suites."),
    CommandSpec(
        "validate",
        "benchbox.cli.commands.config",
        "validate",
        "Validate BenchBox configuration files for syntax and completeness.",
    ),
    CommandSpec("tuning", "benchbox.cli.commands.tuning_group", "tuning_group", "Tuning configuration commands."),
    CommandSpec(
        "create-sample-tuning",
        "benchbox.cli.commands.tuning",
        "create_sample_tuning",
        "Create sample tuning configuration.",
        True,
    ),
    CommandSpec("df-tuning", "benchbox.cli.commands.df_tuning", "df_tuning_group", "DataFrame tuning commands.", True),
    CommandSpec("export", "benchbox.cli.commands.export", "export", "Export benchmark results to various formats."),
    CommandSpec(
        "submit",
        "benchbox.cli.commands.submit",
        "submit",
        "Submit a benchmark result bundle to the BenchBox results platform.",
    ),
    CommandSpec(
        "check-deps",
        "benchbox.cli.commands.checks",
        "check_dependencies",
        "Check dependency status and provide installation guidance.",
    ),
    CommandSpec(
        "download-answers",
        "benchbox.cli.commands.download_answers",
        "download_answers",
        "Pre-download TPC answer files for offline validation.",
    ),
    CommandSpec(
        "results", "benchbox.cli.commands.results", "results", "Show exported benchmark results and execution history."
    ),
    CommandSpec(
        "report", "benchbox.cli.commands.report", "report", "Historical result analysis and platform rankings."
    ),
    CommandSpec(
        "setup", "benchbox.cli.commands.setup", "setup_credentials", "Interactive setup for cloud platform credentials."
    ),
    CommandSpec("platforms", "benchbox.cli.platform", "platforms", "Manage database platform adapters."),
    CommandSpec(
        "visualize", "benchbox.cli.commands.visualize", "visualize", "Generate ASCII charts from BenchBox results."
    ),
)


class LazyCommand(click.Command):
    """Click command proxy that imports the real command only when needed."""

    def __init__(self, spec: CommandSpec) -> None:
        super().__init__(
            spec.name, help=spec.help, short_help=spec.help, hidden=spec.hidden, deprecated=spec.deprecated
        )
        self._spec = spec
        self._resolved: click.Command | None = None

    def _load(self) -> click.Command:
        if self._resolved is None:
            module = importlib.import_module(self._spec.module)
            self._resolved = getattr(module, self._spec.attr)
        return self._resolved

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: click.Context | None = None,
        **extra: Any,
    ) -> click.Context:
        return self._load().make_context(info_name, args, parent=parent, **extra)

    def get_short_help_str(self, limit: int = 45) -> str:
        return click.Command.get_short_help_str(self, limit)

    def get_params(self, ctx: click.Context) -> list[click.Parameter]:
        return self._load().get_params(ctx)

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        return self._load().format_help(ctx, formatter)

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        return self._load().parse_args(ctx, args)

    def invoke(self, ctx: click.Context) -> Any:
        return self._load().invoke(ctx)


COMMANDS = tuple(LazyCommand(spec) for spec in COMMAND_SPECS)

_COMMAND_ATTRS = {spec.attr: spec for spec in COMMAND_SPECS}
_EXTRA_EXPORTS = {
    "PlatformOptionParamType": ("benchbox.cli.commands.run", "PlatformOptionParamType"),
    "setup_verbose_logging": ("benchbox.cli.commands.run", "setup_verbose_logging"),
    "publish_bundle": ("benchbox.cli.commands.publish", "publish_bundle"),
}


def register_commands(cli: click.Group) -> None:
    """Attach all CLI commands to the provided click group."""
    for command in COMMANDS:
        cli.add_command(command)


def __getattr__(name: str) -> Any:
    spec = _COMMAND_ATTRS.get(name)
    if spec is not None:
        return getattr(importlib.import_module(spec.module), spec.attr)
    extra = _EXTRA_EXPORTS.get(name)
    if extra is not None:
        module_path, attr = extra
        return getattr(importlib.import_module(module_path), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "COMMANDS",
    "COMMAND_SPECS",
    "LazyCommand",
    "register_commands",
    "auth",
    "run",
    "publish",
    "publish_bundle",
    "run_official",
    "compare",
    "compare_dataframes",
    "compare_plans",
    "convert",
    "plan_history",
    "show_plan",
    "datagen",
    "aggregate",
    "metrics_group",
    "calculate_qphh",
    "shell",
    "profile",
    "benchmarks",
    "validate",
    "tuning_group",
    "create_sample_tuning",
    "df_tuning_group",
    "export",
    "submit",
    "check_dependencies",
    "download_answers",
    "results",
    "report",
    "setup_credentials",
    "platforms",
    "visualize",
    "PlatformOptionParamType",
    "setup_verbose_logging",
]
