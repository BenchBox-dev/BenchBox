"""Tests for benchbox.cli.commands.tuning_group CLI commands via CliRunner.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import sys as _sys
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

__import__("benchbox.cli.commands.tuning_group")
_tuning_module = _sys.modules["benchbox.cli.commands.tuning_group"]

from benchbox.cli.commands.tuning_group import tuning_group
from benchbox.cli.config import ConfigManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _obj():
    return {"config": ConfigManager()}


class TestTuningInitSqlMode:
    def test_init_sql_exits_zero(self, tmp_path):
        runner = CliRunner()
        with patch.object(_tuning_module, "console"):
            mock_cm = MagicMock()
            with patch("benchbox.cli.config.ConfigManager.create_sample_unified_tuning_config", mock_cm):
                result = runner.invoke(
                    tuning_group,
                    ["init", "--platform", "duckdb"],
                    obj=_obj(),
                )
        assert result.exit_code == 0

    def test_init_sql_output_mentions_created(self):
        runner = CliRunner()
        with patch.object(_tuning_module, "console") as mock_console:
            calls = []
            mock_console.print.side_effect = lambda *a, **k: calls.append(str(a))
            with patch("benchbox.cli.config.ConfigManager.create_sample_unified_tuning_config"):
                runner.invoke(
                    tuning_group,
                    ["init", "--platform", "duckdb"],
                    obj=_obj(),
                )
        assert any("created" in call.lower() or "Tuning" in call for call in calls)

    def test_init_sql_output_mentions_run_hint(self):
        runner = CliRunner()
        with patch.object(_tuning_module, "console") as mock_console:
            calls = []
            mock_console.print.side_effect = lambda *a, **k: calls.append(str(a))
            with patch("benchbox.cli.config.ConfigManager.create_sample_unified_tuning_config"):
                runner.invoke(
                    tuning_group,
                    ["init", "--platform", "duckdb"],
                    obj=_obj(),
                )
        assert any("benchbox run" in call or "--tuning" in call for call in calls)

    def test_init_dataframe_mode_on_sql_platform_fails(self):
        runner = CliRunner()
        with patch.object(_tuning_module, "console") as mock_console:
            calls = []
            mock_console.print.side_effect = lambda *a, **k: calls.append(str(a))
            result = runner.invoke(
                tuning_group,
                ["init", "--platform", "duckdb", "--mode", "dataframe"],
                obj=_obj(),
            )
        assert result.exit_code != 0 or any("does not support" in call or "DataFrame" in call for call in calls)

    def test_init_dataframe_mode_on_sql_platform_shows_df_platforms(self):
        runner = CliRunner()
        with patch.object(_tuning_module, "console") as mock_console:
            calls = []
            mock_console.print.side_effect = lambda *a, **k: calls.append(str(a))
            runner.invoke(
                tuning_group,
                ["init", "--platform", "duckdb", "--mode", "dataframe"],
                obj=_obj(),
            )
        assert any("polars" in call.lower() for call in calls)


class TestTuningInitDataframeMode:
    def test_init_polars_dataframe_mode_exits_zero(self):
        runner = CliRunner()
        with (
            patch.object(_tuning_module, "console"),
            patch.object(_tuning_module, "save_dataframe_tuning"),
        ):
            result = runner.invoke(
                tuning_group,
                ["init", "--platform", "polars", "--mode", "dataframe"],
                obj=_obj(),
            )
        assert result.exit_code == 0

    def test_init_polars_smart_defaults_prints_profile(self):
        runner = CliRunner()
        mock_profile = MagicMock()
        mock_summary = {
            "cpu_cores": 8,
            "available_memory_gb": 16.0,
            "memory_category": "high",
            "has_gpu": False,
        }
        with (
            patch.object(_tuning_module, "console") as mock_console,
            patch.object(_tuning_module, "save_dataframe_tuning"),
            patch.object(_tuning_module, "detect_system_profile", return_value=mock_profile),
            patch.object(_tuning_module, "get_profile_summary", return_value=mock_summary),
            patch.object(_tuning_module, "get_smart_defaults", return_value=MagicMock()),
        ):
            calls = []
            mock_console.print.side_effect = lambda *a, **k: calls.append(str(a))
            result = runner.invoke(
                tuning_group,
                ["init", "--platform", "polars", "--mode", "dataframe", "--smart-defaults"],
                obj=_obj(),
            )
        assert result.exit_code == 0
        assert any("smart default" in call.lower() for call in calls)


class TestTuningValidate:
    def test_validate_valid_config_prints_valid(self, tmp_path):
        config_file = tmp_path / "tuning.yaml"
        config_file.write_text("parallelism:\n  worker_count: 4\n")

        runner = CliRunner()
        mock_config = MagicMock()
        mock_config.get_summary.return_value = {
            "setting_count": 1,
            "has_streaming": False,
            "has_gpu": False,
        }
        with (
            patch.object(_tuning_module, "console") as mock_console,
            patch.object(_tuning_module, "load_dataframe_tuning", return_value=mock_config),
            patch.object(_tuning_module, "validate_dataframe_tuning", return_value=[]),
        ):
            calls = []
            mock_console.print.side_effect = lambda *a, **k: calls.append(str(a))
            result = runner.invoke(
                tuning_group,
                ["validate", str(config_file), "--platform", "polars"],
                obj=_obj(),
            )
        assert result.exit_code == 0
        assert any("valid" in call.lower() for call in calls)

    def test_validate_with_errors_shows_error_output(self, tmp_path):
        config_file = tmp_path / "tuning.yaml"
        config_file.write_text("parallelism:\n  worker_count: -1\n")

        runner = CliRunner()
        mock_config = MagicMock()
        mock_issues = [MagicMock(level="error", message="workers must be positive")]
        with (
            patch.object(_tuning_module, "console") as mock_console,
            patch.object(_tuning_module, "load_dataframe_tuning", return_value=mock_config),
            patch.object(_tuning_module, "validate_dataframe_tuning", return_value=mock_issues),
            patch.object(_tuning_module, "has_errors", return_value=True),
            patch.object(_tuning_module, "format_issues", return_value="error: workers must be positive"),
        ):
            calls = []
            mock_console.print.side_effect = lambda *a, **k: calls.append(str(a))
            runner.invoke(
                tuning_group,
                ["validate", str(config_file), "--platform", "polars"],
                obj=_obj(),
            )
        assert any("error" in call.lower() for call in calls)


class TestTuningDefaults:
    def test_defaults_exits_zero(self):
        from benchbox.core.dataframe.tuning import DataFrameTuningConfiguration

        runner = CliRunner()
        real_config = DataFrameTuningConfiguration()
        mock_summary = {
            "cpu_cores": 8,
            "available_memory_gb": 16.0,
            "memory_category": "high",
            "has_gpu": False,
        }
        with (
            patch.object(_tuning_module, "console"),
            patch.object(_tuning_module, "get_smart_defaults", return_value=real_config),
            patch.object(_tuning_module, "detect_system_profile", return_value=MagicMock()),
            patch.object(_tuning_module, "get_profile_summary", return_value=mock_summary),
        ):
            result = runner.invoke(
                tuning_group,
                ["defaults", "--platform", "polars"],
                obj=_obj(),
            )
        assert result.exit_code == 0


class TestTuningList:
    def test_list_exits_zero(self):
        runner = CliRunner()
        with (
            patch.object(_tuning_module, "console"),
            patch.object(_tuning_module, "display_tuning_list"),
        ):
            result = runner.invoke(
                tuning_group,
                ["list"],
                obj=_obj(),
            )
        assert result.exit_code == 0


class TestTuningShow:
    def test_show_calls_display(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("platform: duckdb\n")
        runner = CliRunner()
        mock_resolution = MagicMock()
        mock_resolution.config_file = None  # no file to load
        with (
            patch.object(_tuning_module, "console"),
            patch.object(_tuning_module, "display_tuning_show") as mock_show,
            patch.object(_tuning_module, "resolve_tuning", return_value=mock_resolution),
        ):
            result = runner.invoke(
                tuning_group,
                ["show", str(config_file)],
                obj=_obj(),
            )
        assert result.exit_code == 0
        mock_show.assert_called_once()
