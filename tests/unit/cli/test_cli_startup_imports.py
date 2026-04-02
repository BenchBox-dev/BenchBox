"""Regression tests for CLI startup import isolation."""

from __future__ import annotations

import importlib
import sys

import pytest
from click.testing import CliRunner

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _clear_modules(monkeypatch: pytest.MonkeyPatch, *prefixes: str) -> None:
    """Remove cached modules so imports in this test run through package init code again."""
    for module_name in list(sys.modules):
        if any(module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in prefixes):
            monkeypatch.delitem(sys.modules, module_name, raising=False)


def test_importing_conversion_submodule_does_not_import_lifecycle_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing conversion helpers should not pull in the lifecycle runner package."""
    _clear_modules(monkeypatch, "benchbox.core.runner", "benchbox.monitoring")

    conversion_module = importlib.import_module("benchbox.core.runner.conversion")

    assert conversion_module.FormatConversionOrchestrator.__name__ == "FormatConversionOrchestrator"
    assert "benchbox.core.runner.runner" not in sys.modules
    assert "benchbox.monitoring" not in sys.modules
    assert "benchbox.monitoring.report" not in sys.modules


def test_setup_help_does_not_require_textcharts(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI startup should not require charting dependencies for unrelated commands."""
    _clear_modules(
        monkeypatch,
        "benchbox.cli.main",
        "benchbox.cli.app",
        "benchbox.cli.commands",
        "benchbox.core.runner",
        "benchbox.monitoring",
        "benchbox.core.visualization",
    )
    monkeypatch.setitem(sys.modules, "textcharts", None)
    monkeypatch.setitem(sys.modules, "textcharts.base", None)
    monkeypatch.setitem(sys.modules, "textcharts.line_chart", None)

    cli = importlib.import_module("benchbox.cli.main").cli
    result = CliRunner().invoke(cli, ["setup", "--help"])

    assert result.exit_code == 0
    assert "Interactive setup for cloud platform credentials" in result.output
