"""Command registration utilities for the BenchBox CLI."""

from __future__ import annotations

import click

from benchbox.cli.platform import platforms

from .aggregate import aggregate
from .benchmarks import benchmarks
from .calculate_qphh import calculate_qphh
from .checks import check_dependencies
from .compare import compare
from .compare_dataframes import compare_dataframes
from .compare_plans import compare_plans
from .config import validate
from .convert import convert
from .datagen import datagen
from .df_tuning import df_tuning_group
from .download_answers import download_answers
from .explorer import explorer_group
from .export import export
from .metrics import metrics_group
from .plan_history import plan_history
from .profile import profile
from .publish import publish, publish_bundle
from .report import report
from .results import results
from .run import PlatformOptionParamType, run, setup_verbose_logging
from .run_official import run_official
from .setup import setup_credentials
from .shell import shell
from .show_plan import show_plan
from .submit import submit
from .tuning import create_sample_tuning
from .tuning_group import tuning_group
from .visualize import visualize

COMMANDS = (
    run,
    run_official,
    publish,
    compare,
    compare_dataframes,
    compare_plans,
    convert,
    plan_history,
    show_plan,
    datagen,
    aggregate,
    metrics_group,  # New unified metrics group
    calculate_qphh,  # Deprecated: hidden, kept for backwards compatibility
    shell,
    profile,
    benchmarks,
    validate,
    tuning_group,  # New unified tuning group
    create_sample_tuning,  # Deprecated: hidden, kept for backwards compatibility
    df_tuning_group,  # Deprecated: hidden, kept for backwards compatibility
    explorer_group,
    export,
    submit,
    check_dependencies,
    download_answers,
    results,
    report,
    setup_credentials,
    platforms,
    visualize,
)


def register_commands(cli: click.Group) -> None:
    """Attach all CLI commands to the provided click group."""
    for command in COMMANDS:
        cli.add_command(command)


__all__ = [
    "COMMANDS",
    "register_commands",
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
    "explorer_group",
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
