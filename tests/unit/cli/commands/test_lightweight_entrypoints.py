"""Coverage tests for lightweight CLI entrypoints."""

from __future__ import annotations

import builtins
import json
import sys as _sys
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from rich.panel import Panel

from benchbox.cli.app import main as app_main, version_callback, version_json_callback
from benchbox.cli.commands.benchmarks import list_benchmarks
from benchbox.cli.commands.config import validate

__import__("benchbox.cli.commands.profile")
_profile_module = _sys.modules["benchbox.cli.commands.profile"]

__import__("benchbox.cli.commands.benchmarks")
_benchmarks_module = _sys.modules["benchbox.cli.commands.benchmarks"]

from benchbox.cli.commands.profile import profile

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _raise_import_error_for(target: str):
    real_import = builtins.__import__

    def _import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == target:
            raise ImportError(f"missing {target}")
        return real_import(name, globals, locals, fromlist, level)

    return _import


def test_validate_command_reports_success_and_failure() -> None:
    runner = CliRunner()
    config_manager = MagicMock()

    config_manager.validate_config.return_value = True
    with patch("benchbox.cli.commands.config.console.print") as console_print:
        result = runner.invoke(validate, obj={"config": config_manager})

    assert result.exit_code == 0
    console_print.assert_called_once_with("[green]✅ Configuration is valid[/green]")

    config_manager.validate_config.return_value = False
    with patch("benchbox.cli.commands.config.console.print") as console_print:
        result = runner.invoke(validate, obj={"config": config_manager})

    assert result.exit_code == 0
    console_print.assert_called_once_with("[red]❌ Configuration validation failed[/red]")


def test_profile_command_renders_panel_and_uses_system_profiler() -> None:
    runner = CliRunner()
    profiler = MagicMock()
    profiler.get_system_profile.return_value = {"cpu": "fast"}

    with (
        patch.object(_profile_module.console, "print") as console_print,
        patch.object(_profile_module, "SystemProfiler", return_value=profiler),
    ):
        result = runner.invoke(profile, obj={})

    assert result.exit_code == 0
    assert isinstance(console_print.call_args.args[0], Panel)
    profiler.get_system_profile.assert_called_once_with()
    profiler.display_profile.assert_called_once_with({"cpu": "fast"}, detailed=True)


def test_benchmarks_list_command_renders_panel_and_lists_benchmarks() -> None:
    runner = CliRunner()
    manager = MagicMock()

    with (
        patch.object(_benchmarks_module.console, "print") as console_print,
        patch.object(_benchmarks_module, "BenchmarkManager", return_value=manager),
    ):
        result = runner.invoke(list_benchmarks, obj={})

    assert result.exit_code == 0
    assert isinstance(console_print.call_args.args[0], Panel)
    manager.list_available_benchmarks.assert_called_once_with()


def test_version_callbacks_use_importerror_fallbacks() -> None:
    ctx = MagicMock()
    ctx.resilient_parsing = False
    ctx.exit.side_effect = SystemExit

    with (
        patch("click.echo") as echo,
        patch("builtins.__import__", side_effect=_raise_import_error_for("benchbox.utils.version")),
        pytest.raises(SystemExit),
    ):
        version_callback(ctx, MagicMock(), True)

    assert echo.call_args.args[0].startswith("BenchBox Version: ")

    with (
        patch("click.echo") as echo,
        patch("builtins.__import__", side_effect=_raise_import_error_for("benchbox.utils.version")),
        pytest.raises(SystemExit),
    ):
        version_json_callback(ctx, MagicMock(), True)

    payload = json.loads(echo.call_args.args[0])
    assert "benchbox_version" in payload


def test_app_main_invokes_click_group() -> None:
    with patch("benchbox.cli.app.cli") as cli_entry:
        app_main()

    cli_entry.assert_called_once_with()
