"""Compatibility layer for the BenchBox CLI entry point.

This module preserves the historic `benchbox.cli.main` import path while
delegating actual command implementations to the modular CLI package.
"""

from __future__ import annotations

from benchbox.cli.app import CLI_HELP, cli, main, version_callback
from benchbox.cli.benchmarks import BenchmarkConfig, BenchmarkManager
from benchbox.cli.commands import (
    PlatformOptionParamType,
    auth,
    benchmarks,
    check_dependencies,
    create_sample_tuning,
    export,
    profile,
    results,
    run,
    setup_verbose_logging,
    validate,
)
from benchbox.cli.config import ConfigManager
from benchbox.cli.database import DatabaseManager
from benchbox.cli.exceptions import (
    CloudStorageError,
    ErrorContext,
    ValidationError,
    ValidationRules,
    create_error_handler,
)
from benchbox.cli.orchestrator import BenchmarkOrchestrator
from benchbox.cli.output import ResultExporter
from benchbox.cli.platform import get_platform_manager, platforms
from benchbox.cli.platform_hooks import PlatformHookRegistry, PlatformOptionError
from benchbox.cli.presentation.system import display_system_recommendations as _display_system_recommendations
from benchbox.cli.shared import console, set_quiet_output, silence_output
from benchbox.cli.system import SystemProfiler
from benchbox.utils.cloud_storage import is_cloud_path
from benchbox.utils.output_path import normalize_output_root


def get_config_manager() -> ConfigManager:
    """Factory indirection so tests can patch ConfigManager via this module."""

    return ConfigManager()


__all__ = [
    "CLI_HELP",
    "PlatformOptionParamType",
    "auth",
    "BenchmarkConfig",
    "BenchmarkManager",
    "DatabaseManager",
    "ConfigManager",
    "get_config_manager",
    "BenchmarkOrchestrator",
    "ResultExporter",
    "PlatformHookRegistry",
    "PlatformOptionError",
    "create_error_handler",
    "CloudStorageError",
    "ErrorContext",
    "ValidationError",
    "ValidationRules",
    "get_platform_manager",
    "platforms",
    "SystemProfiler",
    "console",
    "set_quiet_output",
    "silence_output",
    "is_cloud_path",
    "normalize_output_root",
    "version_callback",
    "cli",
    "run",
    "profile",
    "benchmarks",
    "validate",
    "create_sample_tuning",
    "export",
    "check_dependencies",
    "results",
    "setup_verbose_logging",
    "_display_system_recommendations",
    "main",
]


if __name__ == "__main__":
    main()
