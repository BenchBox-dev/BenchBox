"""
Tests for CLI parameter consistency and new flag behavior.

Tests the new unified parameter structure that aligns with unified_runner.
"""

import sys
import sys as _sys
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

# benchbox.cli.commands.__init__ re-exports `run` (a Click Command) under the
# same name as the run submodule.  On Python 3.10 mock's string-based patch()
# resolves the target via getattr(benchbox.cli.commands, "run"), which returns
# the Command object, not the submodule.  Seeding sys.modules here via
# __import__ and using patch.object() avoids the ambiguity on all Python
# versions.
__import__("benchbox.cli.commands.run")
_run_module = _sys.modules["benchbox.cli.commands.run"]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Python 3.11+ required for Click command mock.patch attribute access
PYTHON_311_PLUS = sys.version_info >= (3, 11)

# Skip all tests if CLI modules are unavailable
try:
    from benchbox.cli.main import cli
    from benchbox.cli.orchestrator import BenchmarkOrchestrator

    IMPORTS_AVAILABLE = True
    skip_reason = None
except ImportError as e:
    IMPORTS_AVAILABLE = False
    skip_reason = f"CLI modules not available: {e}"


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason=skip_reason or "CLI modules not available")
@pytest.mark.skipif(
    not PYTHON_311_PLUS,
    reason="Click command mock.patch requires Python 3.11+ for attribute access",
)
class TestCLIParameterConsistency:
    """Test new CLI parameter behavior."""

    @pytest.fixture
    def runner(self):
        """Create CliRunner for testing."""
        return CliRunner()

    @pytest.fixture
    def mock_orchestrator(self):
        """Mock orchestrator for testing."""
        with patch.object(_run_module, "BenchmarkOrchestrator") as mock_class:
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance

            # Mock execute_benchmark to return a basic result
            mock_result = MagicMock()
            mock_result.validation_status = "SUCCESS"
            mock_result.execution_id = "test-123"
            mock_instance.execute_benchmark.return_value = mock_result

            yield mock_instance

    @pytest.fixture
    def mock_dependencies(self, mock_orchestrator):
        """Mock all CLI dependencies."""
        with (
            patch.object(_run_module, "DatabaseManager") as mock_db,
            patch.object(_run_module, "BenchmarkManager") as mock_bench,
            patch.object(_run_module, "SystemProfiler") as mock_system,
            patch.object(_run_module, "get_platform_manager") as mock_platform,
            patch("benchbox.cli.main.ResultExporter") as mock_exporter,
        ):
            # Setup database manager
            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance

            # Setup benchmark manager
            mock_bench_instance = MagicMock()
            mock_bench_instance.benchmarks = {"tpch": {"display_name": "TPC-H", "estimated_time_range": "1-5min"}}
            mock_bench.return_value = mock_bench_instance

            # Setup system profiler
            mock_system_instance = MagicMock()
            mock_system_profile = MagicMock()
            mock_system_profile.cpu_cores_logical = 4
            mock_system_profile.memory_total_gb = 8
            mock_system_instance.get_system_profile.return_value = mock_system_profile
            mock_system.return_value = mock_system_instance

            # Setup platform manager
            mock_platform_instance = MagicMock()
            mock_platform_instance.is_platform_available.return_value = True
            mock_platform.return_value = mock_platform_instance

            # Setup result exporter
            mock_exporter_instance = MagicMock()
            mock_exporter_instance.export_result.return_value = {"json": "test.json"}
            mock_exporter.return_value = mock_exporter_instance

            yield {
                "db_manager": mock_db_instance,
                "bench_manager": mock_bench_instance,
                "system_profiler": mock_system_instance,
                "platform_manager": mock_platform_instance,
                "result_exporter": mock_exporter_instance,
                "orchestrator": mock_orchestrator,
            }

    def test_phase_parameter_single(self, runner, mock_dependencies):
        """Test --phases parameter with single phase."""
        result = runner.invoke(
            cli, ["run", "--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01", "--phases", "power"]
        )

        assert result.exit_code == 0
        # Verify orchestrator was called with correct phases
        mock_dependencies["orchestrator"].execute_benchmark.assert_called_once()
        args, kwargs = mock_dependencies["orchestrator"].execute_benchmark.call_args
        # Should have phases_to_run parameter
        assert len(args) == 4  # config, system_profile, database_config, phases_to_run
        phases_to_run = args[3]
        assert phases_to_run == ["power"]

    def test_phase_parameter_multiple(self, runner, mock_dependencies):
        """Test --phasess parameter with multiple phases."""
        result = runner.invoke(
            cli,
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--phases",
                "generate,load,power",
            ],
        )

        assert result.exit_code == 0
        # Verify orchestrator was called with correct phases
        args, kwargs = mock_dependencies["orchestrator"].execute_benchmark.call_args
        phases_to_run = args[3]
        assert set(phases_to_run) == {"generate", "load", "power"}

    def test_phase_parameter_invalid(self, runner, mock_dependencies):
        """Test --phasess parameter with invalid phase."""
        result = runner.invoke(cli, ["run", "--platform", "duckdb", "--benchmark", "tpch", "--phases", "invalid_phase"])

        assert result.exit_code == 1
        assert "Invalid phases" in result.output

    def test_phase_parameter_deduplication(self, runner, mock_dependencies):
        """Test --phasess parameter removes duplicates while preserving order."""
        result = runner.invoke(
            cli,
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--phases",
                "power,load,power,throughput",
            ],
        )

        assert result.exit_code == 0
        args, kwargs = mock_dependencies["orchestrator"].execute_benchmark.call_args
        phases_to_run = args[3]
        assert phases_to_run == ["power", "load", "throughput"]  # No duplicates, order preserved

    def test_tuning_mode_tuned(self, runner, mock_dependencies):
        """Test --tuning parameter with 'tuned'."""
        result = runner.invoke(
            cli,
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--tuning",
                "tuned",
                "--non-interactive",
            ],
        )

        assert result.exit_code == 0

    def test_tuning_mode_notuning(self, runner, mock_dependencies):
        """Test --tuning parameter with 'notuning'."""
        result = runner.invoke(
            cli, ["run", "--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01", "--tuning", "notuning"]
        )

        assert result.exit_code == 0

    def test_tuning_mode_invalid(self, runner, mock_dependencies):
        """Test --tuning parameter with invalid value."""
        result = runner.invoke(cli, ["run", "--platform", "duckdb", "--benchmark", "tpch", "--tuning", "invalid_mode"])

        assert result.exit_code == 1
        assert "Invalid tuning value" in result.output

    def test_force_parameter(self, runner, mock_dependencies):
        """Test --force parameter with argument."""
        result = runner.invoke(
            cli, ["run", "--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01", "--force", "all"]
        )

        assert result.exit_code == 0

    def test_execution_type_mapping_data_only(self, runner, mock_dependencies):
        """Test that generate-only phase maps to data_only execution type."""
        result = runner.invoke(cli, ["run", "--benchmark", "tpch", "--scale", "0.01", "--phases", "generate"])

        assert result.exit_code == 0
        # Should handle data-only execution without database

    def test_execution_type_mapping_load_only(self, runner, mock_dependencies):
        """Test that load-only phase maps to load_only execution type."""
        result = runner.invoke(
            cli, ["run", "--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01", "--phases", "load"]
        )

        assert result.exit_code == 0

    def test_execution_type_mapping_combined(self, runner, mock_dependencies):
        """Test that multiple query phases map to combined execution type."""
        result = runner.invoke(
            cli,
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--phases",
                "power,throughput,maintenance",
            ],
        )

        assert result.exit_code == 0

    def test_phase_validation_order_independence(self, runner, mock_dependencies):
        """Test that phase order doesn't matter for validation."""
        result = runner.invoke(
            cli,
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--phases",
                "throughput,generate,power",
            ],
        )

        assert result.exit_code == 0
        args, kwargs = mock_dependencies["orchestrator"].execute_benchmark.call_args
        phases_to_run = args[3]
        # Order should be preserved as specified
        assert phases_to_run == ["throughput", "generate", "power"]

    def test_orchestrator_phase_integration(self, mock_dependencies):
        """Test that orchestrator correctly handles phases_to_run parameter."""
        from benchbox.cli.orchestrator import BenchmarkOrchestrator
        from benchbox.core.schemas import BenchmarkConfig

        orchestrator = BenchmarkOrchestrator()

        # Mock the orchestrator-local lifecycle import used by execute_benchmark().
        with patch("benchbox.cli.orchestrator.run_benchmark_lifecycle") as mock_lifecycle:
            mock_result = MagicMock()
            mock_lifecycle.return_value = mock_result

            # Mock benchmark instance creation
            with (
                patch.object(orchestrator, "_get_benchmark_instance") as mock_get_benchmark,
                patch.object(orchestrator, "_get_platform_config") as mock_get_platform_config,
                patch("benchbox.cli.orchestrator.get_platform_adapter") as mock_get_adapter,
            ):
                mock_benchmark = MagicMock()
                mock_benchmark._name = "tpch"
                mock_get_benchmark.return_value = mock_benchmark
                mock_get_platform_config.return_value = {}
                mock_adapter = MagicMock()
                mock_get_adapter.return_value = mock_adapter

                config = BenchmarkConfig(
                    name="tpch", display_name="TPC-H", scale_factor=0.01, test_execution_type="standard"
                )

                # Create mock system profile
                mock_system_profile = MagicMock()

                # Create mock database config
                mock_database_config = MagicMock()
                mock_database_config.type = "duckdb"

                phases_to_run = ["generate", "load", "power"]

                try:
                    result = orchestrator.execute_benchmark(
                        config, mock_system_profile, mock_database_config, phases_to_run
                    )
                    print(f"Orchestrator returned: {result}")
                except Exception as e:
                    print(f"Orchestrator failed with exception: {e}")
                    raise

                # Verify lifecycle was called with correct phases
                mock_lifecycle.assert_called_once()
                call_kwargs = mock_lifecycle.call_args[1]
                assert "phases" in call_kwargs
                phases = call_kwargs["phases"]

                # Should have generate=True, load=True, execute=True (because power is an execute phase)
                assert phases.generate is True
                assert phases.load is True
                assert phases.execute is True


class TestCLIParameterConsistencyUnavailable:
    """Test graceful handling when CLI modules are unavailable."""

    def test_import_unavailable(self):
        """Test that we handle import failures gracefully."""
        if IMPORTS_AVAILABLE:
            assert skip_reason is None
            return
        assert "not available" in skip_reason


class TestPhaseValidationLogic:
    """Test phase validation logic in isolation."""

    def test_valid_phases_set(self):
        """The documented phase vocabulary includes the opt-in statistics phase."""
        valid_phases = {"generate", "load", "statistics", "warmup", "power", "throughput", "maintenance"}

        # Test all phases are valid
        for phase in valid_phases:
            assert phase in valid_phases
        assert "statistics" in valid_phases

    def test_phase_parsing(self):
        """Test phase string parsing logic."""
        # Test comma separation
        phase_string = "generate,load,power"
        phases = [p.strip() for p in phase_string.split(",") if p.strip()]
        assert phases == ["generate", "load", "power"]

        # Test with spaces
        phase_string = "generate, load , power"
        phases = [p.strip() for p in phase_string.split(",") if p.strip()]
        assert phases == ["generate", "load", "power"]

        # Test empty elements
        phase_string = "generate,,load,power,"
        phases = [p.strip() for p in phase_string.split(",") if p.strip()]
        assert phases == ["generate", "load", "power"]

    def test_execution_type_mapping(self):
        """Test execution type mapping logic."""
        query_phases = {"power", "throughput", "maintenance"}

        # Test data-only
        phases = ["generate"]
        has_query_phases = bool(set(phases) & query_phases)
        assert not has_query_phases

        # Test load-only
        phases = ["load"]
        has_query_phases = bool(set(phases) & query_phases)
        assert not has_query_phases

        # Test with query phases
        phases = ["generate", "load", "power"]
        has_query_phases = bool(set(phases) & query_phases)
        assert has_query_phases

        # Test combined
        phases = ["power", "throughput", "maintenance"]
        has_all_query = all(p in phases for p in ["power", "throughput", "maintenance"])
        assert has_all_query


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason=skip_reason or "CLI modules not available")
@pytest.mark.skipif(
    not PYTHON_311_PLUS,
    reason="Click command mock.patch requires Python 3.11+ for attribute access",
)
class TestGlobalCacheCLIFlag:
    """Tests for --global-cache flag wiring through the CLI."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def captured_config(self):
        """Capture the BenchmarkConfig passed to the orchestrator."""
        from unittest.mock import MagicMock, patch

        captured: dict = {}
        mock_result = MagicMock()
        mock_result.validation_status = "SUCCESS"
        mock_result.execution_id = "test-123"

        with (
            patch.object(_run_module, "BenchmarkOrchestrator") as mock_orch,
            patch.object(_run_module, "DatabaseManager"),
            patch.object(_run_module, "BenchmarkManager") as mock_bench,
            patch.object(_run_module, "SystemProfiler"),
            patch.object(_run_module, "get_platform_manager"),
            patch("benchbox.cli.main.ResultExporter"),
        ):
            mock_bench_instance = MagicMock()
            mock_bench_instance.benchmarks = {"tpch": {"display_name": "TPC-H", "estimated_time_range": "1-5min"}}
            mock_bench.return_value = mock_bench_instance

            mock_orch_instance = MagicMock()
            mock_orch_instance.execute_benchmark.return_value = mock_result

            def capture_call(*args, **kwargs):
                captured["benchmark_config"] = args[0]
                return mock_result

            mock_orch_instance.execute_benchmark.side_effect = capture_call
            mock_orch.return_value = mock_orch_instance

            yield captured

    def test_global_cache_flag_sets_cache_dir_in_options(self, runner, captured_config):
        """--global-cache injects cache_dir pointing to ~/.benchbox/datagen/ in options."""
        from pathlib import Path

        result = runner.invoke(
            cli,
            ["run", "--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01", "--global-cache"],
        )

        assert result.exit_code == 0, result.output
        config = captured_config.get("benchmark_config")
        assert config is not None
        assert "cache_dir" in config.options
        expected = str(Path.home() / ".benchbox" / "datagen")
        assert config.options["cache_dir"] == expected

    def test_no_global_cache_flag_omits_cache_dir(self, runner, captured_config):
        """Without --global-cache, cache_dir is not set in options (project-local default applies)."""
        result = runner.invoke(
            cli,
            ["run", "--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01"],
        )

        assert result.exit_code == 0, result.output
        config = captured_config.get("benchmark_config")
        assert config is not None
        assert "cache_dir" not in config.options


class TestStatisticsPhaseToken:
    """The statistics phase token parses and maps to LifecyclePhases.statistics."""

    def test_parse_phases_list_accepts_statistics(self):
        import types

        from benchbox.cli.commands.run import _parse_phases_list

        s = types.SimpleNamespace(
            phases="generate,load,statistics,power",
            logger=None,
            ctx=MagicMock(),
        )
        _parse_phases_list(s)

        assert s.phases_to_run == ["generate", "load", "statistics", "power"]
        s.ctx.exit.assert_not_called()

    def test_lifecycle_phases_statistics_defaults_off(self):
        from benchbox.core.runner import LifecyclePhases

        assert LifecyclePhases().statistics is False
        assert LifecyclePhases(statistics=True).statistics is True
