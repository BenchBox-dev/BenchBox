"""Lazy compatibility layer for the historic ``benchbox.cli.main`` path."""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS = {
    "CLI_HELP": ("benchbox.cli.app", "CLI_HELP"),
    "version_callback": ("benchbox.cli.app", "version_callback"),
    "cli": ("benchbox.cli.app", "cli"),
    "main": ("benchbox.cli.app", "main"),
    "PlatformOptionParamType": ("benchbox.cli.commands", "PlatformOptionParamType"),
    "auth": ("benchbox.cli.commands", "auth"),
    "run": ("benchbox.cli.commands", "run"),
    "profile": ("benchbox.cli.commands", "profile"),
    "benchmarks": ("benchbox.cli.commands", "benchmarks"),
    "validate": ("benchbox.cli.commands", "validate"),
    "create_sample_tuning": ("benchbox.cli.commands", "create_sample_tuning"),
    "export": ("benchbox.cli.commands", "export"),
    "check_dependencies": ("benchbox.cli.commands", "check_dependencies"),
    "results": ("benchbox.cli.commands", "results"),
    "setup_verbose_logging": ("benchbox.cli.commands", "setup_verbose_logging"),
    "BenchmarkConfig": ("benchbox.cli.benchmarks", "BenchmarkConfig"),
    "BenchmarkManager": ("benchbox.cli.benchmarks", "BenchmarkManager"),
    "ConfigManager": ("benchbox.cli.config", "ConfigManager"),
    "DatabaseManager": ("benchbox.cli.database", "DatabaseManager"),
    "CloudStorageError": ("benchbox.cli.exceptions", "CloudStorageError"),
    "ErrorContext": ("benchbox.cli.exceptions", "ErrorContext"),
    "ValidationError": ("benchbox.cli.exceptions", "ValidationError"),
    "ValidationRules": ("benchbox.cli.exceptions", "ValidationRules"),
    "create_error_handler": ("benchbox.cli.exceptions", "create_error_handler"),
    "BenchmarkOrchestrator": ("benchbox.cli.orchestrator", "BenchmarkOrchestrator"),
    "ResultExporter": ("benchbox.cli.output", "ResultExporter"),
    "get_platform_manager": ("benchbox.cli.platform", "get_platform_manager"),
    "platforms": ("benchbox.cli.platform", "platforms"),
    "PlatformHookRegistry": ("benchbox.cli.platform_hooks", "PlatformHookRegistry"),
    "PlatformOptionError": ("benchbox.cli.platform_hooks", "PlatformOptionError"),
    "_display_system_recommendations": (
        "benchbox.cli.presentation.system",
        "display_system_recommendations",
    ),
    "console": ("benchbox.cli.shared", "console"),
    "set_quiet_output": ("benchbox.cli.shared", "set_quiet_output"),
    "silence_output": ("benchbox.cli.shared", "silence_output"),
    "SystemProfiler": ("benchbox.cli.system", "SystemProfiler"),
    "is_cloud_path": ("benchbox.utils.cloud_storage", "is_cloud_path"),
    "normalize_output_root": ("benchbox.utils.output_path", "normalize_output_root"),
}

__all__ = [*_EXPORTS, "get_config_manager"]


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr = target
    value = getattr(importlib.import_module(module_path), attr)
    globals()[name] = value
    return value


def get_config_manager() -> Any:
    """Factory indirection so tests can patch ConfigManager via this module."""
    return __getattr__("ConfigManager")()


if __name__ == "__main__":
    __getattr__("main")()
