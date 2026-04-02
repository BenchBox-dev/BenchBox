"""Behavioral tests for onboarding and deprecated df-tuning CLI flows."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from rich.panel import Panel

from benchbox.cli.app import cli
from benchbox.cli.commands.df_tuning import _create_profile_config
from benchbox.cli.onboarding import (
    _create_benchmark_help,
    _create_concurrency_help,
    _create_scale_factor_help,
    _create_tuning_help,
    _get_first_run_marker_path,
    _get_help_content,
    _run_interactive_tour,
    _show_benchmarks_overview,
    _show_key_concepts,
    _show_scale_factor_guide,
    _show_tuning_modes,
    _show_welcome_message,
    check_and_run_first_time_setup,
    show_contextual_help,
)
from benchbox.core.dataframe.tuning import DataFrameTuningConfiguration

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestFirstRunOnboarding:
    """Tests for first-run onboarding behavior."""

    def test_non_interactive_terminal_skips_onboarding(self):
        """Onboarding should not run in non-interactive contexts."""
        with (
            patch.object(sys.stdin, "isatty", return_value=False),
            patch.object(sys.stdout, "isatty", return_value=False),
        ):
            assert check_and_run_first_time_setup() is False

    def test_first_run_creates_marker_and_runs_tour(self, tmp_path: Path):
        """First interactive run should create marker and offer the tour."""
        marker_path = tmp_path / "first_run_complete"

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.object(sys.stdout, "isatty", return_value=True),
            patch("benchbox.cli.onboarding._get_first_run_marker_path", return_value=marker_path),
            patch("benchbox.cli.onboarding._show_welcome_message") as mock_welcome,
            patch("benchbox.cli.onboarding._run_interactive_tour") as mock_tour,
            patch("benchbox.cli.onboarding.Confirm.ask", return_value=True),
        ):
            assert check_and_run_first_time_setup() is True

        assert marker_path.exists()
        mock_welcome.assert_called_once()
        mock_tour.assert_called_once()

    def test_existing_marker_skips_first_run_flow(self, tmp_path: Path):
        """Existing marker should short-circuit the onboarding flow."""
        marker_path = tmp_path / "first_run_complete"
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text("done\n", encoding="utf-8")

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.object(sys.stdout, "isatty", return_value=True),
            patch("benchbox.cli.onboarding._get_first_run_marker_path", return_value=marker_path),
            patch("benchbox.cli.onboarding._show_welcome_message") as mock_welcome,
        ):
            assert check_and_run_first_time_setup() is False

        mock_welcome.assert_not_called()

    def test_interactive_tour_stops_when_user_declines_next_step(self):
        """The tour should stop at the first declined continuation prompt."""
        with (
            patch("benchbox.cli.onboarding._show_key_concepts") as show_key,
            patch("benchbox.cli.onboarding._show_benchmarks_overview") as show_benchmarks,
            patch("benchbox.cli.onboarding._show_tuning_modes") as show_tuning,
            patch("benchbox.cli.onboarding._show_scale_factor_guide") as show_scale,
            patch("benchbox.cli.onboarding.Confirm.ask", side_effect=[False]),
        ):
            _run_interactive_tour()

        show_key.assert_called_once()
        show_benchmarks.assert_not_called()
        show_tuning.assert_not_called()
        show_scale.assert_not_called()

    def test_interactive_tour_stops_after_benchmarks_overview_when_second_prompt_declined(self):
        """Declining after the benchmarks overview should stop before tuning mode guidance."""
        with (
            patch("benchbox.cli.onboarding._show_key_concepts") as show_key,
            patch("benchbox.cli.onboarding._show_benchmarks_overview") as show_benchmarks,
            patch("benchbox.cli.onboarding._show_tuning_modes") as show_tuning,
            patch("benchbox.cli.onboarding._show_scale_factor_guide") as show_scale,
            patch("benchbox.cli.onboarding.Confirm.ask", side_effect=[True, False]),
        ):
            _run_interactive_tour()

        show_key.assert_called_once()
        show_benchmarks.assert_called_once()
        show_tuning.assert_not_called()
        show_scale.assert_not_called()

    def test_interactive_tour_stops_after_tuning_modes_when_third_prompt_declined(self):
        """Declining before the scale factor step should still execute the tuning mode panel."""
        with (
            patch("benchbox.cli.onboarding._show_key_concepts") as show_key,
            patch("benchbox.cli.onboarding._show_benchmarks_overview") as show_benchmarks,
            patch("benchbox.cli.onboarding._show_tuning_modes") as show_tuning,
            patch("benchbox.cli.onboarding._show_scale_factor_guide") as show_scale,
            patch("benchbox.cli.onboarding.Confirm.ask", side_effect=[True, True, False]),
        ):
            _run_interactive_tour()

        show_key.assert_called_once()
        show_benchmarks.assert_called_once()
        show_tuning.assert_called_once()
        show_scale.assert_not_called()

    def test_contextual_help_known_and_unknown_contexts(self):
        """Known contexts render help; unknown ones remain quiet."""
        with patch("benchbox.cli.onboarding.console.print") as mock_print:
            show_contextual_help("benchmark_selection")

        assert mock_print.called
        assert _get_help_content("benchmark_selection") is not None
        assert _get_help_content("unknown-context") is None

        with patch("benchbox.cli.onboarding.console.print") as mock_print:
            show_contextual_help("unknown-context")

        mock_print.assert_not_called()

    def test_first_run_marker_path_uses_home_directory(self):
        """The first-run marker should live in ~/.benchbox."""
        with patch("benchbox.cli.onboarding.Path.home", return_value=Path("/tmp/home")):
            marker = _get_first_run_marker_path()

        assert marker == Path("/tmp/home/.benchbox/first_run_complete")

    def test_show_welcome_message_renders_getting_started_panel(self):
        """Welcome message should render the Getting Started panel."""
        with patch("benchbox.cli.onboarding.console.print") as mock_print:
            _show_welcome_message()

        panel = mock_print.call_args.args[0]
        assert isinstance(panel, Panel)
        assert "Getting Started" in panel.title
        assert "BenchBox" in panel.renderable.plain

    @pytest.mark.parametrize(
        ("helper", "expected_title"),
        [
            (_show_key_concepts, "Key Concepts"),
            (_show_benchmarks_overview, "Popular Benchmarks"),
            (_show_tuning_modes, "Tuning Modes"),
            (_show_scale_factor_guide, "Scale Factor Guide"),
        ],
    )
    def test_onboarding_panels_render_expected_titles(self, helper, expected_title):
        """Each onboarding helper should render its expected panel title."""
        with patch("benchbox.cli.onboarding.console.print") as mock_print:
            helper()

        panels = [call.args[0] for call in mock_print.call_args_list if call.args and isinstance(call.args[0], Panel)]
        assert panels, "expected helper to print a Panel"
        panel = panels[0]
        assert isinstance(panel, Panel)
        assert expected_title in panel.title

    def test_interactive_tour_runs_all_steps_and_completion_message(self):
        """Accepting all prompts should run the full tour and print completion output."""
        with (
            patch("benchbox.cli.onboarding.console.print") as mock_print,
            patch("benchbox.cli.onboarding.Confirm.ask", side_effect=[True, True, True]),
        ):
            _run_interactive_tour()

        printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
        assert "Tour complete" in printed
        assert "ready to run your first benchmark" in printed

    @pytest.mark.parametrize(
        ("context", "expected_text"),
        [
            ("benchmark_selection", "Choosing a Benchmark"),
            ("scale_factor", "Scale Factor Selection"),
            ("tuning_mode", "Tuning Modes"),
            ("concurrency", "Concurrent Streams"),
        ],
    )
    def test_help_content_helpers_return_expected_text(self, context: str, expected_text: str):
        """Help text lookup should return the matching explanatory content."""
        help_text = _get_help_content(context)

        assert help_text is not None
        assert expected_text in help_text.plain

    def test_help_content_factory_functions_include_key_guidance(self):
        """The individual help text factories should include their core guidance."""
        assert "TPC-H" in _create_benchmark_help().plain
        assert "0.01" in _create_scale_factor_help().plain
        assert "notuning" in _create_tuning_help().plain
        assert "1 stream" in _create_concurrency_help().plain

    def test_show_contextual_help_wraps_known_context_in_panel(self):
        """Known help contexts should render a titled Panel."""
        with patch("benchbox.cli.onboarding.console.print") as mock_print:
            show_contextual_help("tuning_mode")

        panels = [call.args[0] for call in mock_print.call_args_list if call.args and isinstance(call.args[0], Panel)]
        assert len(panels) == 1
        assert panels[0].title == "Help: Tuning Mode"


class TestDfTuningHelpers:
    """Tests for df-tuning helper behavior."""

    def test_create_profile_config_for_polars_optimized(self):
        """Optimized Polars profile should enable lazy in-memory execution."""
        config = _create_profile_config("polars", "optimized")

        assert isinstance(config, DataFrameTuningConfiguration)
        assert config.execution.lazy_evaluation is True
        assert config.execution.engine_affinity == "in-memory"

    def test_create_profile_config_memory_constrained_dask(self):
        """Memory-constrained Dask profile should spill and limit memory."""
        config = _create_profile_config("dask", "memory-constrained")

        assert config.execution.streaming_mode is True
        assert config.memory.spill_to_disk is True
        assert config.memory.memory_limit == "2GB"

    def test_create_profile_config_gpu_warns_for_non_cudf(self):
        """GPU profile should still enable GPU config and warn for non-cuDF platforms."""
        with patch("benchbox.cli.commands.df_tuning.console.print") as mock_print:
            config = _create_profile_config("polars", "gpu")

        assert config.gpu.enabled is True
        assert any("GPU profile is only applicable to cuDF" in str(call) for call in mock_print.call_args_list)


class TestDfTuningCli:
    """Tests for deprecated df-tuning command flows."""

    def test_create_sample_command_writes_output(self, tmp_path: Path):
        """create-sample should write a tuning file and report the chosen profile."""
        runner = CliRunner()
        output_path = tmp_path / "polars_optimized.yaml"

        result = runner.invoke(
            cli,
            [
                "df-tuning",
                "create-sample",
                "--platform",
                "polars",
                "--profile",
                "optimized",
                "--output",
                str(output_path),
            ],
        )

        assert result.exit_code == 0
        assert output_path.exists()
        assert "Sample DataFrame tuning configuration created" in result.output
        assert "optimized" in result.output.lower()

    def test_validate_command_reports_success(self, tmp_path: Path):
        """validate should report a valid configuration when no issues are returned."""
        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("placeholder: true\n", encoding="utf-8")
        config = MagicMock()
        config.get_summary.return_value = {
            "setting_count": 1,
            "has_streaming": True,
            "has_gpu": False,
        }

        with (
            patch("benchbox.cli.commands.df_tuning.load_dataframe_tuning", return_value=config),
            patch("benchbox.cli.commands.df_tuning.validate_dataframe_tuning", return_value=[]),
        ):
            result = runner.invoke(cli, ["df-tuning", "validate", str(config_path), "--platform", "polars"])

        assert result.exit_code == 0
        assert "Configuration is valid for polars" in result.output

    def test_validate_command_aborts_on_errors(self, tmp_path: Path):
        """validate should fail when the validator reports errors."""
        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("placeholder: true\n", encoding="utf-8")
        issues = [{"severity": "error", "message": "bad config"}]

        with (
            patch("benchbox.cli.commands.df_tuning.load_dataframe_tuning", return_value=MagicMock()),
            patch("benchbox.cli.commands.df_tuning.validate_dataframe_tuning", return_value=issues),
            patch("benchbox.cli.commands.df_tuning.format_issues", return_value="formatted issues"),
            patch("benchbox.cli.commands.df_tuning.has_errors", return_value=True),
        ):
            result = runner.invoke(cli, ["df-tuning", "validate", str(config_path), "--platform", "polars"])

        assert result.exit_code != 0
        assert "Configuration has errors that must be fixed" in result.output

    def test_show_defaults_command_displays_detected_profile(self):
        """show-defaults should render system profile and recommended settings."""
        runner = CliRunner()
        config = DataFrameTuningConfiguration()
        config.execution.streaming_mode = True

        with (
            patch("benchbox.cli.commands.df_tuning.detect_system_profile", return_value=MagicMock()),
            patch(
                "benchbox.cli.commands.df_tuning.get_profile_summary",
                return_value={
                    "cpu_cores": 8,
                    "available_memory_gb": 16.0,
                    "memory_category": "medium",
                    "has_gpu": False,
                },
            ),
            patch("benchbox.cli.commands.df_tuning.get_smart_defaults", return_value=config),
        ):
            result = runner.invoke(cli, ["df-tuning", "show-defaults", "--platform", "polars"])

        assert result.exit_code == 0
        assert "Detected System Profile" in result.output
        assert "Recommended Settings for Polars" in result.output

    def test_list_platforms_command_displays_platform_table(self):
        """list-platforms should print the supported DataFrame platforms."""
        runner = CliRunner()
        result = runner.invoke(cli, ["df-tuning", "list-platforms"])

        assert result.exit_code == 0
        assert "DataFrame Platforms" in result.output
        assert "polars" in result.output.lower()
        assert "cudf" in result.output.lower()
