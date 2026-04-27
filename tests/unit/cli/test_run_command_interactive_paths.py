"""Interactive-path coverage tests for the run command."""

from __future__ import annotations

import sys as _sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from benchbox.cli.commands.run import run
from benchbox.cli.tuning_runtime import build_baseline_unified_config
from benchbox.core.schemas import BenchmarkConfig
from benchbox.core.tuning.interface import UnifiedTuningConfiguration

# benchbox.cli.commands.__init__ re-exports `run` (a Click Command) under the
# same name as the run submodule.  On Python 3.10 mock's string-based patch()
# resolves the target via getattr(benchbox.cli.commands, "run"), which returns
# the Command object, not the submodule.  Seeding sys.modules here via
# __import__ and using patch.object() avoids the ambiguity on all Python
# versions.
__import__("benchbox.cli.commands.run")
_run_module = _sys.modules["benchbox.cli.commands.run"]

# Similarly, benchbox.cli.__init__ uses __getattr__-based lazy loading which
# can cause string-based patch() to resolve to a different module object than
# what sys.modules contains on Python 3.10.  Pre-import and seed from
# sys.modules so patch.object() can be used instead.
__import__("benchbox.cli.benchmarks")
_benchmarks_module = _sys.modules["benchbox.cli.benchmarks"]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _Config:
    config_path = "<test-config>"

    def get(self, _key: str, default=None):
        return default

    def validate_config(self) -> bool:
        return True


def _run_obj() -> dict[str, object]:
    return {"config": _Config()}


def _interactive_sys() -> SimpleNamespace:
    return SimpleNamespace(
        stdin=SimpleNamespace(isatty=lambda: True),
        stdout=SimpleNamespace(isatty=lambda: True),
    )


def _tuned_unified_config() -> UnifiedTuningConfiguration:
    config = UnifiedTuningConfiguration()
    config.enable_all_constraints()
    return config


def test_interactive_guided_flow_uses_prompted_values_and_saves_preferences(tmp_path: Path):
    runner = CliRunner()

    profiler = Mock()
    profiler.get_system_profile.return_value = SimpleNamespace(
        cpu_cores_logical=8,
        memory_total_gb=32,
        architecture="x86_64",
        os_type="darwin",
    )
    profiler.display_profile.return_value = None

    db_manager = Mock()
    database_config = SimpleNamespace(type="duckdb", options={}, execution_mode=None)
    db_manager.prompt_execution_style.return_value = "sql-local"
    db_manager.select_database.return_value = database_config

    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        scale_factor=0.01,
        queries=None,
        concurrency=1,
        options={},
    )
    bench_manager = Mock()
    bench_manager.benchmarks = {
        "tpch": {
            "display_name": "TPC-H",
            "estimated_time_range": (2, 10),
            "complexity": "medium",
            "num_queries": 22,
        }
    }
    bench_manager.select_benchmark.return_value = benchmark_config

    orchestrator = Mock()
    result_payload = SimpleNamespace(validation_status="PASSED", execution_id="exec-123", query_results=[])
    guided_config = _tuned_unified_config()

    with ExitStack() as stack:
        stack.enter_context(patch.object(_run_module, "sys", _interactive_sys()))
        stack.enter_context(patch.object(_run_module, "SystemProfiler", return_value=profiler))
        stack.enter_context(patch.object(_run_module, "DatabaseManager", return_value=db_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkManager", return_value=bench_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkOrchestrator", return_value=orchestrator))
        stack.enter_context(patch.object(_run_module, "display_system_recommendations"))
        mock_caps = stack.enter_context(patch.object(_run_module.PlatformRegistry, "get_platform_capabilities"))
        stack.enter_context(patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False))
        stack.enter_context(
            patch.object(_run_module, "normalize_output_root", return_value=str(tmp_path / "normalized"))
        )
        mock_execute = stack.enter_context(
            patch.object(_run_module, "_execute_orchestrated_run", return_value=result_payload)
        )
        stack.enter_context(
            patch.object(
                _run_module,
                "_export_orchestrated_result",
                return_value={"json": str(tmp_path / "results.json")},
            )
        )
        stack.enter_context(patch.object(_run_module, "_render_post_run_charts"))
        stack.enter_context(patch("benchbox.cli.onboarding.check_and_run_first_time_setup", return_value=False))
        stack.enter_context(patch("benchbox.cli.preferences.load_last_run_config", return_value=None))
        mock_save_last_run = stack.enter_context(patch("benchbox.cli.preferences.save_last_run_config"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_mode", return_value="native"))
        stack.enter_context(
            patch.object(_benchmarks_module, "prompt_phases", return_value=["generate", "load", "power"])
        )
        stack.enter_context(patch.object(_benchmarks_module, "prompt_query_subset", return_value=["Q1", "Q6"]))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_official_mode", return_value=(False, None)))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_seed", return_value=77))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_force_regeneration", return_value="upload"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_validation_mode", return_value="loose"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_capture_plans", return_value=True))
        stack.enter_context(
            patch.object(_benchmarks_module, "prompt_output_location", return_value=str(tmp_path / "chosen-output"))
        )
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_format", return_value=("iceberg", "zstd")))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_verbose_output", return_value=2))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_platform_options", return_value={"threads": "8"}))
        stack.enter_context(patch("benchbox.cli.tuning.run_tuning_wizard", return_value=guided_config))
        mock_preview = stack.enter_context(patch("benchbox.cli.dryrun.display_interactive_preview"))
        mock_confirm = stack.enter_context(patch.object(_run_module.Confirm, "ask"))
        mock_caps.return_value = SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False)

        def _confirm_side_effect(prompt, default=False):
            text = str(prompt)
            if "configure tuning options" in text:
                return True
            if "Proceed with execution?" in text:
                return True
            return default

        mock_confirm.side_effect = _confirm_side_effect

        result = runner.invoke(run, [], obj=_run_obj())

    assert result.exit_code == 0, result.output
    db_manager.prompt_execution_style.assert_called_once()
    db_manager.select_database.assert_called_once_with(style_filter="sql-local")
    assert benchmark_config.queries == ["Q1", "Q6"]
    assert benchmark_config.options["validation_mode"] == "loose"
    assert benchmark_config.options["seed"] == 77
    assert benchmark_config.options["table_format"] == "iceberg"
    assert benchmark_config.options["table_format_compression"] == "zstd"
    assert benchmark_config.options["unified_tuning_configuration"] is guided_config
    assert benchmark_config.options["tuning_enabled"] is True
    assert database_config.options["tuning_enabled"] is True
    assert database_config.tuning_enabled is True
    assert database_config.unified_tuning_configuration is guided_config
    mock_preview.assert_called_once()
    orchestrator.set_custom_output_dir.assert_called_once_with(str(tmp_path / "normalized"))
    assert mock_execute.call_args.args[4] == ["generate", "load", "power"]
    assert mock_execute.call_args.kwargs["execution_context"].query_subset == ["Q1", "Q6"]
    mock_save_last_run.assert_called_once()
    save_kwargs = mock_save_last_run.call_args.kwargs
    assert save_kwargs["database"] == "duckdb"
    assert save_kwargs["benchmark"] == "tpch"
    assert save_kwargs["seed"] == 77
    assert save_kwargs["output"] == str(tmp_path / "chosen-output")
    assert save_kwargs["phases"] == ["generate", "load", "power"]


def test_interactive_execution_type_derived_from_phases(tmp_path: Path):
    """After the dead 'Test Execution Type' prompt was removed, execution type must
    follow the phases selected in the wizard (single source of truth)."""
    runner = CliRunner()

    profiler = Mock()
    profiler.get_system_profile.return_value = SimpleNamespace(
        cpu_cores_logical=8,
        memory_total_gb=32,
        architecture="x86_64",
        os_type="darwin",
    )
    profiler.display_profile.return_value = None

    db_manager = Mock()
    database_config = SimpleNamespace(type="duckdb", options={}, execution_mode=None)
    db_manager.prompt_execution_style.return_value = "sql-local"
    db_manager.select_database.return_value = database_config

    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        scale_factor=0.01,
        queries=None,
        concurrency=1,
        options={},
    )
    bench_manager = Mock()
    bench_manager.benchmarks = {
        "tpch": {
            "display_name": "TPC-H",
            "estimated_time_range": (2, 10),
            "complexity": "medium",
            "num_queries": 22,
        }
    }
    bench_manager.select_benchmark.return_value = benchmark_config

    orchestrator = Mock()
    result_payload = SimpleNamespace(validation_status="PASSED", execution_id="exec-123", query_results=[])

    with ExitStack() as stack:
        stack.enter_context(patch.object(_run_module, "sys", _interactive_sys()))
        stack.enter_context(patch.object(_run_module, "SystemProfiler", return_value=profiler))
        stack.enter_context(patch.object(_run_module, "DatabaseManager", return_value=db_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkManager", return_value=bench_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkOrchestrator", return_value=orchestrator))
        stack.enter_context(patch.object(_run_module, "display_system_recommendations"))
        mock_caps = stack.enter_context(patch.object(_run_module.PlatformRegistry, "get_platform_capabilities"))
        stack.enter_context(patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False))
        stack.enter_context(
            patch.object(_run_module, "normalize_output_root", return_value=str(tmp_path / "normalized"))
        )
        mock_execute = stack.enter_context(
            patch.object(_run_module, "_execute_orchestrated_run", return_value=result_payload)
        )
        stack.enter_context(
            patch.object(
                _run_module,
                "_export_orchestrated_result",
                return_value={"json": str(tmp_path / "results.json")},
            )
        )
        stack.enter_context(patch.object(_run_module, "_render_post_run_charts"))
        stack.enter_context(patch("benchbox.cli.onboarding.check_and_run_first_time_setup", return_value=False))
        stack.enter_context(patch("benchbox.cli.preferences.load_last_run_config", return_value=None))
        stack.enter_context(patch("benchbox.cli.preferences.save_last_run_config"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_mode", return_value="native"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_phases", return_value=["throughput"]))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_query_subset", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_official_mode", return_value=(False, None)))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_seed", return_value=42))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_force_regeneration", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_validation_mode", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_capture_plans", return_value=False))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_output_location", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_format", return_value=(None, None)))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_verbose_output", return_value=0))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_platform_options", return_value={}))
        stack.enter_context(patch("benchbox.cli.tuning.run_tuning_wizard"))
        stack.enter_context(patch("benchbox.cli.dryrun.display_interactive_preview"))
        mock_confirm = stack.enter_context(patch.object(_run_module.Confirm, "ask"))
        mock_caps.return_value = SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False)

        def _confirm_side_effect(prompt, default=False):
            text = str(prompt)
            if "configure tuning options" in text:
                return False
            if "Proceed with execution?" in text:
                return True
            return default

        mock_confirm.side_effect = _confirm_side_effect

        result = runner.invoke(run, [], obj=_run_obj())

    assert result.exit_code == 0, result.output
    assert mock_execute.called
    # Phase-derived execution type is the single source of truth - and is now also
    # written back to the BenchmarkConfig so save_last_run_config sees it.
    assert benchmark_config.test_execution_type == "throughput"


def test_interactive_dataframe_tuning_acceptance_applies_runtime_defaults(tmp_path: Path):
    """Accepting tuning for a DataFrame platform must populate runtime DataFrame tuning."""
    runner = CliRunner()

    profiler = Mock()
    profiler.get_system_profile.return_value = SimpleNamespace(
        cpu_cores_logical=8,
        memory_total_gb=32,
        architecture="x86_64",
        os_type="darwin",
    )
    profiler.display_profile.return_value = None

    db_manager = Mock()
    database_config = SimpleNamespace(type="polars-df", options={}, execution_mode="dataframe")
    db_manager.prompt_execution_style.return_value = "dataframe-local"
    db_manager.select_database.return_value = database_config

    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        scale_factor=0.01,
        queries=None,
        concurrency=1,
        options={},
    )
    bench_manager = Mock()
    bench_manager.benchmarks = {
        "tpch": {
            "display_name": "TPC-H",
            "estimated_time_range": (2, 10),
            "complexity": "medium",
            "num_queries": 22,
        }
    }
    bench_manager.select_benchmark.return_value = benchmark_config

    orchestrator = Mock()
    result_payload = SimpleNamespace(validation_status="PASSED", execution_id="exec-123", query_results=[])
    df_tuning_config = SimpleNamespace(name="df-smart-defaults")
    guided_config = _tuned_unified_config()

    with ExitStack() as stack:
        stack.enter_context(patch.object(_run_module, "sys", _interactive_sys()))
        stack.enter_context(patch.object(_run_module, "SystemProfiler", return_value=profiler))
        stack.enter_context(patch.object(_run_module, "DatabaseManager", return_value=db_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkManager", return_value=bench_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkOrchestrator", return_value=orchestrator))
        stack.enter_context(patch.object(_run_module, "display_system_recommendations"))
        mock_caps = stack.enter_context(patch.object(_run_module.PlatformRegistry, "get_platform_capabilities"))
        stack.enter_context(patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False))
        stack.enter_context(
            patch.object(_run_module, "normalize_output_root", return_value=str(tmp_path / "normalized"))
        )
        stack.enter_context(patch.object(_run_module, "_execute_orchestrated_run", return_value=result_payload))
        stack.enter_context(
            patch.object(
                _run_module,
                "_export_orchestrated_result",
                return_value={"json": str(tmp_path / "results.json")},
            )
        )
        stack.enter_context(patch.object(_run_module, "_render_post_run_charts"))
        stack.enter_context(patch("benchbox.cli.onboarding.check_and_run_first_time_setup", return_value=False))
        stack.enter_context(patch("benchbox.cli.preferences.load_last_run_config", return_value=None))
        stack.enter_context(patch("benchbox.cli.preferences.save_last_run_config"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_mode", return_value="native"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_phases", return_value=["power"]))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_query_subset", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_official_mode", return_value=(False, None)))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_seed", return_value=42))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_force_regeneration", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_validation_mode", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_capture_plans", return_value=False))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_output_location", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_format", return_value=(None, None)))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_verbose_output", return_value=0))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_platform_options", return_value={}))
        stack.enter_context(patch("benchbox.cli.tuning.run_tuning_wizard", return_value=guided_config))
        stack.enter_context(patch("benchbox.cli.dryrun.display_interactive_preview"))
        mock_df_defaults = stack.enter_context(
            patch("benchbox.core.dataframe.tuning.get_smart_defaults", return_value=df_tuning_config)
        )
        mock_confirm = stack.enter_context(patch.object(_run_module.Confirm, "ask"))
        mock_caps.return_value = SimpleNamespace(default_mode="dataframe", supports_sql=False, supports_dataframe=True)

        def _confirm_side_effect(prompt, default=False):
            text = str(prompt)
            if "configure tuning options" in text:
                return True
            if "Proceed with execution?" in text:
                return True
            return default

        mock_confirm.side_effect = _confirm_side_effect

        result = runner.invoke(run, [], obj=_run_obj())

    assert result.exit_code == 0, result.output
    mock_df_defaults.assert_called_once_with("polars-df")
    assert benchmark_config.options["df_tuning_config"] is df_tuning_config
    assert database_config.tuning_enabled is True
    assert database_config.unified_tuning_configuration is guided_config


def test_interactive_wizard_baseline_maps_to_notuning_for_external_mode(tmp_path: Path):
    """Wizard baseline mode must not be re-labeled as tuned after Step 5."""
    runner = CliRunner()

    profiler = Mock()
    profiler.get_system_profile.return_value = SimpleNamespace(
        cpu_cores_logical=8,
        memory_total_gb=32,
        architecture="x86_64",
        os_type="darwin",
    )
    profiler.display_profile.return_value = None

    db_manager = Mock()
    database_config = SimpleNamespace(type="duckdb", options={}, execution_mode=None)
    db_manager.prompt_execution_style.return_value = "sql-local"
    db_manager.select_database.return_value = database_config

    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        scale_factor=0.01,
        queries=None,
        concurrency=1,
        options={},
    )
    bench_manager = Mock()
    bench_manager.benchmarks = {
        "tpch": {
            "display_name": "TPC-H",
            "estimated_time_range": (2, 10),
            "complexity": "medium",
            "num_queries": 22,
        }
    }
    bench_manager.select_benchmark.return_value = benchmark_config

    orchestrator = Mock()
    result_payload = SimpleNamespace(validation_status="PASSED", execution_id="exec-123", query_results=[])
    baseline_config = build_baseline_unified_config()

    with ExitStack() as stack:
        stack.enter_context(patch.object(_run_module, "sys", _interactive_sys()))
        stack.enter_context(patch.object(_run_module, "SystemProfiler", return_value=profiler))
        stack.enter_context(patch.object(_run_module, "DatabaseManager", return_value=db_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkManager", return_value=bench_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkOrchestrator", return_value=orchestrator))
        stack.enter_context(patch.object(_run_module, "display_system_recommendations"))
        mock_caps = stack.enter_context(patch.object(_run_module.PlatformRegistry, "get_platform_capabilities"))
        stack.enter_context(patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False))
        stack.enter_context(
            patch.object(_run_module, "normalize_output_root", return_value=str(tmp_path / "normalized"))
        )
        mock_execute = stack.enter_context(
            patch.object(_run_module, "_execute_orchestrated_run", return_value=result_payload)
        )
        stack.enter_context(
            patch.object(
                _run_module,
                "_export_orchestrated_result",
                return_value={"json": str(tmp_path / "results.json")},
            )
        )
        stack.enter_context(patch.object(_run_module, "_render_post_run_charts"))
        stack.enter_context(patch("benchbox.cli.onboarding.check_and_run_first_time_setup", return_value=False))
        stack.enter_context(patch("benchbox.cli.preferences.load_last_run_config", return_value=None))
        mock_save_last_run = stack.enter_context(patch("benchbox.cli.preferences.save_last_run_config"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_mode", return_value="external"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_phases", return_value=["power"]))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_query_subset", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_official_mode", return_value=(False, None)))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_seed", return_value=42))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_force_regeneration", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_validation_mode", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_capture_plans", return_value=False))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_output_location", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_format", return_value=(None, None)))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_verbose_output", return_value=0))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_platform_options", return_value={}))
        stack.enter_context(patch("benchbox.cli.tuning.run_tuning_wizard", return_value=baseline_config))
        mock_preview = stack.enter_context(patch("benchbox.cli.dryrun.display_interactive_preview"))
        mock_confirm = stack.enter_context(patch.object(_run_module.Confirm, "ask"))
        mock_caps.return_value = SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False)

        def _confirm_side_effect(prompt, default=False):
            text = str(prompt)
            if "configure tuning options" in text:
                return True
            if "Proceed with execution?" in text:
                return True
            return default

        mock_confirm.side_effect = _confirm_side_effect

        result = runner.invoke(run, [], obj=_run_obj())

    assert result.exit_code == 0, result.output
    assert mock_execute.called
    assert benchmark_config.options["tuning_enabled"] is False
    assert database_config.tuning_enabled is False
    assert database_config.unified_tuning_configuration is baseline_config
    mock_preview.assert_called_once()
    assert mock_preview.call_args.kwargs["tuning"] is None
    mock_save_last_run.assert_called_once()
    assert mock_save_last_run.call_args.kwargs["tuning_mode"] == "notuning"


def test_interactive_dataframe_wizard_baseline_skips_runtime_defaults(tmp_path: Path):
    """Wizard baseline mode must not trigger DataFrame smart defaults."""
    runner = CliRunner()

    profiler = Mock()
    profiler.get_system_profile.return_value = SimpleNamespace(
        cpu_cores_logical=8,
        memory_total_gb=32,
        architecture="x86_64",
        os_type="darwin",
    )
    profiler.display_profile.return_value = None

    db_manager = Mock()
    database_config = SimpleNamespace(type="polars-df", options={}, execution_mode="dataframe")
    db_manager.prompt_execution_style.return_value = "dataframe-local"
    db_manager.select_database.return_value = database_config

    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        scale_factor=0.01,
        queries=None,
        concurrency=1,
        options={},
    )
    bench_manager = Mock()
    bench_manager.benchmarks = {
        "tpch": {
            "display_name": "TPC-H",
            "estimated_time_range": (2, 10),
            "complexity": "medium",
            "num_queries": 22,
        }
    }
    bench_manager.select_benchmark.return_value = benchmark_config

    orchestrator = Mock()
    result_payload = SimpleNamespace(validation_status="PASSED", execution_id="exec-123", query_results=[])
    baseline_config = build_baseline_unified_config()

    with ExitStack() as stack:
        stack.enter_context(patch.object(_run_module, "sys", _interactive_sys()))
        stack.enter_context(patch.object(_run_module, "SystemProfiler", return_value=profiler))
        stack.enter_context(patch.object(_run_module, "DatabaseManager", return_value=db_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkManager", return_value=bench_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkOrchestrator", return_value=orchestrator))
        stack.enter_context(patch.object(_run_module, "display_system_recommendations"))
        mock_caps = stack.enter_context(patch.object(_run_module.PlatformRegistry, "get_platform_capabilities"))
        stack.enter_context(patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False))
        stack.enter_context(
            patch.object(_run_module, "normalize_output_root", return_value=str(tmp_path / "normalized"))
        )
        stack.enter_context(patch.object(_run_module, "_execute_orchestrated_run", return_value=result_payload))
        stack.enter_context(
            patch.object(
                _run_module,
                "_export_orchestrated_result",
                return_value={"json": str(tmp_path / "results.json")},
            )
        )
        stack.enter_context(patch.object(_run_module, "_render_post_run_charts"))
        stack.enter_context(patch("benchbox.cli.onboarding.check_and_run_first_time_setup", return_value=False))
        stack.enter_context(patch("benchbox.cli.preferences.load_last_run_config", return_value=None))
        mock_save_last_run = stack.enter_context(patch("benchbox.cli.preferences.save_last_run_config"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_mode", return_value="native"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_phases", return_value=["power"]))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_query_subset", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_official_mode", return_value=(False, None)))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_seed", return_value=42))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_force_regeneration", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_validation_mode", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_capture_plans", return_value=False))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_output_location", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_format", return_value=(None, None)))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_verbose_output", return_value=0))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_platform_options", return_value={}))
        stack.enter_context(patch("benchbox.cli.tuning.run_tuning_wizard", return_value=baseline_config))
        mock_preview = stack.enter_context(patch("benchbox.cli.dryrun.display_interactive_preview"))
        mock_df_defaults = stack.enter_context(patch("benchbox.core.dataframe.tuning.get_smart_defaults"))
        mock_confirm = stack.enter_context(patch.object(_run_module.Confirm, "ask"))
        mock_caps.return_value = SimpleNamespace(default_mode="dataframe", supports_sql=False, supports_dataframe=True)

        def _confirm_side_effect(prompt, default=False):
            text = str(prompt)
            if "configure tuning options" in text:
                return True
            if "Proceed with execution?" in text:
                return True
            return default

        mock_confirm.side_effect = _confirm_side_effect

        result = runner.invoke(run, [], obj=_run_obj())

    assert result.exit_code == 0, result.output
    mock_df_defaults.assert_not_called()
    assert benchmark_config.options["tuning_enabled"] is False
    assert database_config.tuning_enabled is False
    assert "df_tuning_config" not in benchmark_config.options
    mock_preview.assert_called_once()
    assert mock_preview.call_args.kwargs["tuning"] is None
    mock_save_last_run.assert_called_once()
    assert mock_save_last_run.call_args.kwargs["tuning_mode"] == "notuning"


def test_fallback_wizard_baseline_reclassifies_runtime_state_for_dataframe_platform(tmp_path: Path):
    """Fallback wizard baseline must persist notuning and skip DataFrame defaults."""
    runner = CliRunner()

    profiler = Mock()
    profiler.get_system_profile.return_value = SimpleNamespace(
        cpu_cores_logical=8,
        memory_total_gb=32,
        architecture="x86_64",
        os_type="darwin",
    )
    profiler.display_profile.return_value = None

    database_config = SimpleNamespace(
        type="polars-df",
        options={},
        execution_mode="dataframe",
        driver_version_actual=None,
        driver_version_resolved=None,
    )
    db_manager = Mock()
    db_manager.create_config.return_value = database_config

    bench_manager = Mock()
    bench_manager.benchmarks = {
        "tpch": {
            "display_name": "TPC-H",
            "estimated_time_range": (2, 10),
            "complexity": "medium",
            "num_queries": 22,
        }
    }
    bench_manager.validate_scale_factor.return_value = None

    orchestrator = Mock()
    result_payload = SimpleNamespace(validation_status="PASSED", execution_id="exec-123", query_results=[])
    baseline_config = build_baseline_unified_config()

    with ExitStack() as stack:
        stack.enter_context(patch.object(_run_module, "SystemProfiler", return_value=profiler))
        stack.enter_context(patch.object(_run_module, "DatabaseManager", return_value=db_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkManager", return_value=bench_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkOrchestrator", return_value=orchestrator))
        stack.enter_context(patch.object(_run_module, "display_system_recommendations"))
        stack.enter_context(
            patch.object(
                _run_module.PlatformRegistry,
                "get_platform_capabilities",
                return_value=SimpleNamespace(default_mode="dataframe", supports_sql=False, supports_dataframe=True),
            )
        )
        stack.enter_context(patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False))
        mock_execute = stack.enter_context(
            patch.object(_run_module, "_execute_orchestrated_run", return_value=result_payload)
        )
        stack.enter_context(
            patch.object(
                _run_module,
                "_export_orchestrated_result",
                return_value={"json": str(tmp_path / "results.json")},
            )
        )
        stack.enter_context(patch.object(_run_module, "_render_post_run_charts"))
        stack.enter_context(patch("benchbox.cli.onboarding.check_and_run_first_time_setup", return_value=False))
        stack.enter_context(patch("benchbox.cli.preferences.load_last_run_config", return_value=None))
        mock_save_last_run = stack.enter_context(patch("benchbox.cli.preferences.save_last_run_config"))
        stack.enter_context(patch("benchbox.cli.tuning.run_tuning_wizard", return_value=baseline_config))
        mock_df_defaults = stack.enter_context(patch("benchbox.core.dataframe.tuning.get_smart_defaults"))
        mock_confirm = stack.enter_context(patch.object(_run_module.Confirm, "ask"))

        def _confirm_side_effect(prompt, default=False):
            text = str(prompt)
            if "configure tuning options" in text:
                return True
            return default

        mock_confirm.side_effect = _confirm_side_effect

        result = runner.invoke(
            run,
            ["--platform", "polars-df", "--benchmark", "tpch", "--tuning", "tuned"],
            obj=_run_obj(),
        )

    assert result.exit_code == 0, result.output
    mock_df_defaults.assert_not_called()
    db_overrides = db_manager.create_config.call_args.args[2]
    assert db_overrides["tuning_enabled"] is False
    assert db_overrides["unified_tuning_configuration"] is baseline_config
    assert "df_tuning_config" not in db_overrides
    executed_benchmark_config = mock_execute.call_args.args[1]
    assert executed_benchmark_config.options["tuning_enabled"] is False
    assert executed_benchmark_config.options["unified_tuning_configuration"] is baseline_config
    assert "df_tuning_config" not in executed_benchmark_config.options
    mock_save_last_run.assert_called_once()
    assert mock_save_last_run.call_args.kwargs["tuning_mode"] == "notuning"


def test_interactive_tuning_declined_sets_notuning_state(tmp_path: Path):
    """Declining tuning must set tuning_enabled=False and suppress --tuning in the preview."""
    runner = CliRunner()

    profiler = Mock()
    profiler.get_system_profile.return_value = SimpleNamespace(
        cpu_cores_logical=8,
        memory_total_gb=32,
        architecture="x86_64",
        os_type="darwin",
    )
    profiler.display_profile.return_value = None

    db_manager = Mock()
    database_config = SimpleNamespace(type="duckdb", options={}, execution_mode=None)
    db_manager.prompt_execution_style.return_value = "sql-local"
    db_manager.select_database.return_value = database_config

    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        scale_factor=0.01,
        queries=None,
        concurrency=1,
        options={},
    )
    bench_manager = Mock()
    bench_manager.benchmarks = {
        "tpch": {
            "display_name": "TPC-H",
            "estimated_time_range": (2, 10),
            "complexity": "medium",
            "num_queries": 22,
        }
    }
    bench_manager.select_benchmark.return_value = benchmark_config

    orchestrator = Mock()
    result_payload = SimpleNamespace(validation_status="PASSED", execution_id="exec-123", query_results=[])

    with ExitStack() as stack:
        stack.enter_context(patch.object(_run_module, "sys", _interactive_sys()))
        stack.enter_context(patch.object(_run_module, "SystemProfiler", return_value=profiler))
        stack.enter_context(patch.object(_run_module, "DatabaseManager", return_value=db_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkManager", return_value=bench_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkOrchestrator", return_value=orchestrator))
        stack.enter_context(patch.object(_run_module, "display_system_recommendations"))
        mock_caps = stack.enter_context(patch.object(_run_module.PlatformRegistry, "get_platform_capabilities"))
        stack.enter_context(patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False))
        stack.enter_context(
            patch.object(_run_module, "normalize_output_root", return_value=str(tmp_path / "normalized"))
        )
        mock_execute = stack.enter_context(
            patch.object(_run_module, "_execute_orchestrated_run", return_value=result_payload)
        )
        stack.enter_context(
            patch.object(
                _run_module,
                "_export_orchestrated_result",
                return_value={"json": str(tmp_path / "results.json")},
            )
        )
        stack.enter_context(patch.object(_run_module, "_render_post_run_charts"))
        stack.enter_context(patch("benchbox.cli.onboarding.check_and_run_first_time_setup", return_value=False))
        stack.enter_context(patch("benchbox.cli.preferences.load_last_run_config", return_value=None))
        stack.enter_context(patch("benchbox.cli.preferences.save_last_run_config"))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_mode", return_value="native"))
        stack.enter_context(
            patch.object(_benchmarks_module, "prompt_phases", return_value=["generate", "load", "power"])
        )
        stack.enter_context(patch.object(_benchmarks_module, "prompt_query_subset", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_official_mode", return_value=(False, None)))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_seed", return_value=42))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_force_regeneration", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_validation_mode", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_capture_plans", return_value=False))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_output_location", return_value=None))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_table_format", return_value=(None, None)))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_verbose_output", return_value=0))
        stack.enter_context(patch.object(_benchmarks_module, "prompt_platform_options", return_value={}))
        mock_wizard = stack.enter_context(patch("benchbox.cli.tuning.run_tuning_wizard"))
        mock_preview = stack.enter_context(patch("benchbox.cli.dryrun.display_interactive_preview"))
        mock_confirm = stack.enter_context(patch.object(_run_module.Confirm, "ask"))
        mock_caps.return_value = SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False)

        def _confirm_side_effect(prompt, default=False):
            text = str(prompt)
            if "configure tuning options" in text:
                return False  # Decline tuning
            if "Proceed with execution?" in text:
                return True
            return default

        mock_confirm.side_effect = _confirm_side_effect

        result = runner.invoke(run, [], obj=_run_obj())

    assert result.exit_code == 0, result.output
    assert mock_execute.called
    # Wizard must NOT be called when user declines
    mock_wizard.assert_not_called()
    # Tuning state must reflect decline
    assert benchmark_config.options["tuning_enabled"] is False
    assert database_config.options["tuning_enabled"] is False
    assert database_config.tuning_enabled is False
    baseline_config = database_config.unified_tuning_configuration
    assert baseline_config.primary_keys.enabled is False
    assert baseline_config.foreign_keys.enabled is False
    assert baseline_config.unique_constraints.enabled is False
    assert baseline_config.check_constraints.enabled is False
    # No DataFrame tuning config when tuning is declined for a SQL platform
    assert "df_tuning_config" not in benchmark_config.options
    # Preview must suppress --tuning
    mock_preview.assert_called_once()
    assert mock_preview.call_args.kwargs["tuning"] is None


def test_interactive_cloud_platform_stops_when_credentials_are_missing():
    runner = CliRunner()

    profiler = Mock()
    profiler.get_system_profile.return_value = SimpleNamespace(
        cpu_cores_logical=8,
        memory_total_gb=16,
        architecture="x86_64",
        os_type="darwin",
    )
    profiler.display_profile.return_value = None

    db_manager = Mock()
    db_manager.prompt_execution_style.return_value = "cloud-sql"
    db_manager.select_database.return_value = SimpleNamespace(type="snowflake", options={}, execution_mode=None)
    bench_manager = Mock()

    with ExitStack() as stack:
        stack.enter_context(patch.object(_run_module, "sys", _interactive_sys()))
        stack.enter_context(patch.object(_run_module, "SystemProfiler", return_value=profiler))
        stack.enter_context(patch.object(_run_module, "DatabaseManager", return_value=db_manager))
        stack.enter_context(patch.object(_run_module, "BenchmarkManager", return_value=bench_manager))
        stack.enter_context(patch.object(_run_module, "display_system_recommendations"))
        mock_caps = stack.enter_context(patch.object(_run_module.PlatformRegistry, "get_platform_capabilities"))
        stack.enter_context(patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=True))
        stack.enter_context(patch.object(_run_module, "check_and_setup_platform_credentials", return_value=False))
        stack.enter_context(patch("benchbox.cli.onboarding.check_and_run_first_time_setup", return_value=False))
        stack.enter_context(patch("benchbox.cli.preferences.load_last_run_config", return_value=None))
        mock_caps.return_value = SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False)

        result = runner.invoke(run, [], obj=_run_obj())

    assert result.exit_code == 1
    assert "Cannot proceed without SNOWFLAKE credentials" in result.output
    bench_manager.select_benchmark.assert_not_called()


# ---------------------------------------------------------------------------
# Non-interactive validation tests (option parsing & error paths)
# ---------------------------------------------------------------------------


def _non_interactive_base_patches():
    """Return a context manager with all infrastructure patches for non-interactive runs."""
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch("benchbox.cli.onboarding.check_and_run_first_time_setup", return_value=False))
    stack.enter_context(patch("benchbox.cli.preferences.load_last_run_config", return_value=None))
    stack.enter_context(patch.object(_run_module, "SystemProfiler"))
    stack.enter_context(patch.object(_run_module, "display_system_recommendations"))
    return stack


class TestRunCommandValidation:
    """Validation-path tests for the run command (no real execution)."""

    def test_quiet_and_verbose_flags_conflict(self):
        runner = CliRunner()
        with _non_interactive_base_patches():
            result = runner.invoke(
                run,
                ["--quiet", "-v", "--platform", "duckdb", "--benchmark", "tpch", "--non-interactive"],
                obj=_run_obj(),
            )
        assert result.exit_code != 0
        assert "--quiet cannot be used with -v/-vv flags" in result.output

    def test_official_mode_rejects_non_compliant_scale_factor(self):
        runner = CliRunner()
        with _non_interactive_base_patches():
            result = runner.invoke(
                run,
                ["--official", "--scale", "0.5", "--platform", "duckdb", "--benchmark", "tpch", "--non-interactive"],
                obj=_run_obj(),
            )
        assert result.exit_code != 0
        assert "not TPC-compliant" in result.output

    def test_official_mode_accepts_compliant_scale_factor(self):
        runner = CliRunner()
        # Scale 1 is TPC-compliant - should NOT get the "not TPC-compliant" error
        # (it will fail later due to missing execution, but not at scale validation)
        with _non_interactive_base_patches() as stack:
            stack.enter_context(patch.object(_run_module, "_execute_orchestrated_run", side_effect=SystemExit(0)))
            stack.enter_context(
                patch.object(
                    _run_module.PlatformRegistry,
                    "get_platform_capabilities",
                    return_value=SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False),
                )
            )
            stack.enter_context(
                patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False)
            )
            result = runner.invoke(
                run,
                ["--official", "--scale", "1", "--platform", "duckdb", "--benchmark", "tpch", "--non-interactive"],
                obj=_run_obj(),
            )
        # Should NOT show scale factor error
        assert "not TPC-compliant" not in result.output

    def test_invalid_phases_rejected(self):
        runner = CliRunner()
        with _non_interactive_base_patches():
            result = runner.invoke(
                run,
                [
                    "--phases",
                    "generate,badphase,power",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--non-interactive",
                ],
                obj=_run_obj(),
            )
        assert result.exit_code != 0
        assert "Invalid phases" in result.output or "badphase" in result.output

    def test_queries_empty_string_rejected(self):
        runner = CliRunner()
        with _non_interactive_base_patches():
            result = runner.invoke(
                run,
                ["--queries", "  ,  ", "--platform", "duckdb", "--benchmark", "tpch", "--non-interactive"],
                obj=_run_obj(),
            )
        assert result.exit_code != 0
        assert "--queries flag provided but no valid query IDs found" in result.output

    def test_queries_too_many_rejected(self):
        runner = CliRunner()
        many_queries = ",".join(f"Q{i}" for i in range(1, 103))
        with _non_interactive_base_patches():
            result = runner.invoke(
                run,
                ["--queries", many_queries, "--platform", "duckdb", "--benchmark", "tpch", "--non-interactive"],
                obj=_run_obj(),
            )
        assert result.exit_code != 0
        assert "Too many queries" in result.output

    def test_queries_too_long_id_rejected(self):
        runner = CliRunner()
        long_id = "Q" + "x" * 20  # 21 chars, exceeds max 20
        with _non_interactive_base_patches():
            result = runner.invoke(
                run,
                ["--queries", long_id, "--platform", "duckdb", "--benchmark", "tpch", "--non-interactive"],
                obj=_run_obj(),
            )
        assert result.exit_code != 0
        assert "Query ID too long (max 20 chars)" in result.output

    def test_non_interactive_missing_benchmark_rejected(self):
        runner = CliRunner()
        with _non_interactive_base_patches():
            result = runner.invoke(
                run,
                ["--non-interactive", "--platform", "duckdb"],
                obj=_run_obj(),
            )
        assert result.exit_code != 0
        assert "--benchmark" in result.output or "Missing" in result.output

    def test_non_interactive_missing_platform_for_power_phase_rejected(self):
        runner = CliRunner()
        with _non_interactive_base_patches():
            result = runner.invoke(
                run,
                ["--non-interactive", "--benchmark", "tpch", "--phases", "power"],
                obj=_run_obj(),
            )
        assert result.exit_code != 0
        assert "--platform" in result.output or "Missing" in result.output

    def test_platform_option_without_platform_rejected(self):
        runner = CliRunner()
        with _non_interactive_base_patches():
            result = runner.invoke(
                run,
                ["--platform-option", "key=value", "--benchmark", "tpch", "--non-interactive"],
                obj=_run_obj(),
            )
        assert result.exit_code != 0
        assert "Platform options require a --platform selection" in result.output

    def test_official_with_seed_shows_compliance_banner(self):
        """--official with --seed shows the TPC compliance banner."""
        runner = CliRunner()
        with _non_interactive_base_patches() as stack:
            stack.enter_context(patch.object(_run_module, "_execute_orchestrated_run", side_effect=SystemExit(0)))
            stack.enter_context(
                patch.object(
                    _run_module.PlatformRegistry,
                    "get_platform_capabilities",
                    return_value=SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False),
                )
            )
            stack.enter_context(
                patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False)
            )
            result = runner.invoke(
                run,
                [
                    "--official",
                    "--scale",
                    "1",
                    "--seed",
                    "42",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--non-interactive",
                ],
                obj=_run_obj(),
            )
        assert "TPC-Compliant" in result.output
        assert "Seed: 42" in result.output

    def test_official_without_seed_warns_about_reproducibility(self):
        """--official without --seed shows reproducibility warning."""
        runner = CliRunner()
        with _non_interactive_base_patches() as stack:
            stack.enter_context(patch.object(_run_module, "_execute_orchestrated_run", side_effect=SystemExit(0)))
            stack.enter_context(
                patch.object(
                    _run_module.PlatformRegistry,
                    "get_platform_capabilities",
                    return_value=SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False),
                )
            )
            stack.enter_context(
                patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False)
            )
            result = runner.invoke(
                run,
                ["--official", "--scale", "1", "--platform", "duckdb", "--benchmark", "tpch", "--non-interactive"],
                obj=_run_obj(),
            )
        assert "No --seed specified" in result.output or "seed" in result.output.lower()

    def test_compression_flag_accepted_zstd(self):
        """--compression zstd should be accepted without validation error."""
        runner = CliRunner()
        with _non_interactive_base_patches() as stack:
            stack.enter_context(patch.object(_run_module, "_execute_orchestrated_run", side_effect=SystemExit(0)))
            stack.enter_context(
                patch.object(
                    _run_module.PlatformRegistry,
                    "get_platform_capabilities",
                    return_value=SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False),
                )
            )
            stack.enter_context(
                patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False)
            )
            result = runner.invoke(
                run,
                [
                    "--compression",
                    "zstd",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--non-interactive",
                ],
                obj=_run_obj(),
            )
        # Flag was accepted: no parse error and command reached execution (mocked SystemExit(0))
        assert "Invalid value for '--compression'" not in result.output
        assert result.exit_code == 0

    def test_compression_flag_accepted_none(self):
        """--compression none should be accepted without error."""
        runner = CliRunner()
        with _non_interactive_base_patches() as stack:
            stack.enter_context(patch.object(_run_module, "_execute_orchestrated_run", side_effect=SystemExit(0)))
            stack.enter_context(
                patch.object(
                    _run_module.PlatformRegistry,
                    "get_platform_capabilities",
                    return_value=SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False),
                )
            )
            stack.enter_context(
                patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False)
            )
            result = runner.invoke(
                run,
                ["--compression", "none", "--platform", "duckdb", "--benchmark", "tpch", "--non-interactive"],
                obj=_run_obj(),
            )
        assert "Invalid value for '--compression'" not in result.output
        assert result.exit_code == 0

    def test_validation_flag_accepted_loose(self):
        """--validation loose should be accepted without parse error."""
        runner = CliRunner()
        with _non_interactive_base_patches() as stack:
            stack.enter_context(patch.object(_run_module, "_execute_orchestrated_run", side_effect=SystemExit(0)))
            stack.enter_context(
                patch.object(
                    _run_module.PlatformRegistry,
                    "get_platform_capabilities",
                    return_value=SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False),
                )
            )
            stack.enter_context(
                patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False)
            )
            result = runner.invoke(
                run,
                ["--validation", "loose", "--platform", "duckdb", "--benchmark", "tpch", "--non-interactive"],
                obj=_run_obj(),
            )
        assert "Invalid value for '--validation'" not in result.output
        assert result.exit_code == 0

    def test_tuning_flag_accepted_notuning(self):
        """--tuning notuning (default) should be accepted without error."""
        runner = CliRunner()
        with _non_interactive_base_patches() as stack:
            stack.enter_context(patch.object(_run_module, "_execute_orchestrated_run", side_effect=SystemExit(0)))
            stack.enter_context(
                patch.object(
                    _run_module.PlatformRegistry,
                    "get_platform_capabilities",
                    return_value=SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False),
                )
            )
            stack.enter_context(
                patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False)
            )
            result = runner.invoke(
                run,
                ["--tuning", "notuning", "--platform", "duckdb", "--benchmark", "tpch", "--non-interactive"],
                obj=_run_obj(),
            )
        assert "Invalid value for '--tuning'" not in result.output
        assert result.exit_code == 0

    def test_platform_option_with_platform_parsed(self):
        """--platform-option KEY=VALUE with --platform should be parsed without rejection."""
        runner = CliRunner()
        with _non_interactive_base_patches() as stack:
            stack.enter_context(patch.object(_run_module, "_execute_orchestrated_run", side_effect=SystemExit(0)))
            stack.enter_context(
                patch.object(
                    _run_module.PlatformRegistry,
                    "get_platform_capabilities",
                    return_value=SimpleNamespace(default_mode="sql", supports_sql=True, supports_dataframe=False),
                )
            )
            stack.enter_context(
                patch.object(_run_module.PlatformRegistry, "requires_cloud_storage", return_value=False)
            )
            result = runner.invoke(
                run,
                [
                    "--platform-option",
                    "driver_version=1.2.0",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--non-interactive",
                ],
                obj=_run_obj(),
            )
        # Flag was accepted (no parse rejection); driver version error is a runtime failure, not a parse error
        assert "Platform options require a --platform selection" not in result.output
        assert result.exit_code != 2  # Click exits with 2 on parse/usage errors
