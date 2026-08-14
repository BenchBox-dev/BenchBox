"""The core run service: configuration resolution and execution orchestration.

`one-engine-core-run-service` w2. The characterization suite in
tests/unit/cli/test_run_config_resolution_characterization.py already runs
through this code, because BenchmarkOrchestrator._prepare_run_config now
delegates here -- that is the pure-move proof. What this module adds is the
service's own contract: that it can be called with no CLI object at all, and
that core stays below platforms and cli.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from benchbox.core.config import BenchmarkConfig
from benchbox.core.constants import GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS
from benchbox.core.run_service import (
    SilentVerbosity,
    resolve_run_config,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_SERVICE_SOURCE = REPO_ROOT / "benchbox/core/run_service.py"


def _config(**kwargs) -> BenchmarkConfig:
    return BenchmarkConfig(
        name=kwargs.pop("name", "tpch"),
        display_name=kwargs.pop("display_name", "TPC-H"),
        scale_factor=kwargs.pop("scale_factor", 1.0),
        **kwargs,
    )


class TestLayering:
    """The constraint that shapes every signature in the module."""

    def test_run_service_does_not_export_unused_request_or_plan_models(self):
        import benchbox.core.run_service as run_service

        assert not hasattr(run_service, "RunRequest")
        assert not hasattr(run_service, "RunPlan")

    def test_run_service_imports_neither_platforms_nor_cli(self):
        tree = ast.parse(RUN_SERVICE_SOURCE.read_text(encoding="utf-8"))
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}

        offenders = [m for m in modules if m.startswith(("benchbox.platforms", "benchbox.cli"))]

        assert offenders == []

    def test_the_service_resolves_without_importing_the_cli(self):
        """A caller with no CLI must get a RunConfig, not an ImportError."""
        run_config = resolve_run_config(_config(), database_path="/tmp/x.duckdb", verbosity=SilentVerbosity())

        assert run_config.connection["database_path"] == "/tmp/x.duckdb"


class TestResolveRunConfig:
    def test_a_path_object_is_stringified(self):
        run_config = resolve_run_config(_config(), database_path=Path("/tmp/db.duckdb"), verbosity=SilentVerbosity())

        assert run_config.connection["database_path"] == "/tmp/db.duckdb"
        assert isinstance(run_config.connection["database_path"], str)

    def test_defaults_match_the_core_constants(self):
        run_config = resolve_run_config(_config(), database_path="x", verbosity=SilentVerbosity())

        assert run_config.iterations == GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS

    def test_silent_verbosity_produces_a_quiet_run_config(self):
        """The value MCP will pass, having no console to configure."""
        run_config = resolve_run_config(_config(), database_path="x", verbosity=SilentVerbosity())

        assert run_config.quiet is True
        assert run_config.verbose is False
        assert run_config.very_verbose is False
        assert run_config.verbose_level == 0

    def test_the_caller_options_mapping_is_not_mutated(self):
        options = {"seed": 3}
        snapshot = dict(options)

        resolve_run_config(_config(options=options), database_path="x", verbosity=SilentVerbosity())

        assert options == snapshot


class TestOrchestratorDelegatesRatherThanDuplicates:
    """A reintroduced local copy is how these surfaces drifted apart before."""

    def test_orchestrator_produces_the_same_run_config_as_the_service(self, tmp_path):
        from benchbox.cli.orchestrator import BenchmarkOrchestrator

        class _DatabaseConfig:
            type = "duckdb"

        orchestrator = BenchmarkOrchestrator(base_dir=str(tmp_path))
        config = _config(options={"seed": 5, "power_iterations": 2}, queries=["1"])

        via_cli = orchestrator._prepare_run_config(config, _DatabaseConfig())
        database_path = orchestrator.directory_manager.get_database_path(
            config.name, config.scale_factor, "duckdb", tuning_config=None
        )
        via_core = resolve_run_config(config, database_path=database_path, verbosity=orchestrator._verbosity)

        assert via_cli.model_dump() == via_core.model_dump()

    def test_orchestrator_no_longer_defines_its_own_resolution(self):
        source = (REPO_ROOT / "benchbox/cli/orchestrator.py").read_text(encoding="utf-8")

        assert "resolve_run_config" in source
        # The moved arithmetic must not survive alongside the delegation.
        assert "GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS" not in source


class TestExecutionPort:
    """w3: orchestration in core, adapter construction injected by the surface."""

    @staticmethod
    def _phases(**kwargs):
        from benchbox.core.run_service import resolve_lifecycle_phases

        return resolve_lifecycle_phases(kwargs.get("phases_to_run"))

    def test_no_phase_list_means_the_standard_lifecycle(self):
        from benchbox.core.run_service import resolve_lifecycle_phases

        phases = resolve_lifecycle_phases(None)

        assert (phases.generate, phases.load, phases.execute) == (True, True, True)
        assert phases.statistics is False

    def test_an_empty_phase_list_is_treated_as_absent(self):
        from benchbox.core.run_service import resolve_lifecycle_phases

        assert resolve_lifecycle_phases([]) == resolve_lifecycle_phases(None)

    @pytest.mark.parametrize("query_phase", ["warmup", "power", "throughput", "maintenance"])
    def test_any_query_phase_sets_execute(self, query_phase: str):
        from benchbox.core.run_service import resolve_lifecycle_phases

        assert resolve_lifecycle_phases([query_phase]).execute is True

    def test_statistics_stays_opt_in(self):
        from benchbox.core.run_service import resolve_lifecycle_phases

        assert resolve_lifecycle_phases(["load"]).statistics is False
        assert resolve_lifecycle_phases(["load", "statistics"]).statistics is True

    def test_validation_options_default_to_off(self):
        from benchbox.core.run_service import resolve_validation_options

        options = resolve_validation_options(None)

        assert options.enable_preflight_validation is False
        assert options.enable_postgen_manifest_validation is False
        assert options.enable_postload_validation is False

    def test_validation_options_are_read_from_config_options(self):
        from benchbox.core.run_service import resolve_validation_options

        options = resolve_validation_options({"enable_postload_validation": True})

        assert options.enable_postload_validation is True

    def test_execution_mode_is_none_without_a_database(self):
        from benchbox.core.run_service import resolve_execution_mode

        assert resolve_execution_mode(None) is None

    def test_an_explicit_execution_mode_wins(self):
        from benchbox.core.run_service import resolve_execution_mode

        class _Config:
            execution_mode = "dataframe"
            type = "duckdb"

        assert resolve_execution_mode(_Config()) == "dataframe"

    def test_requested_phases_are_stamped_for_combined_mode(self):
        from benchbox.core.run_service import stamp_requested_phases

        config = _config()
        stamp_requested_phases(config, ["power", "throughput"])

        assert config.options["requested_phases"] == ["power", "throughput"]

    def test_stamping_nothing_leaves_options_alone(self):
        from benchbox.core.run_service import stamp_requested_phases

        config = _config(options={"seed": 1})
        stamp_requested_phases(config, None)

        assert "requested_phases" not in (config.options or {})

    def test_the_adapter_factory_receives_the_resolved_phases(self):
        """The injection seam: core asks, the surface builds."""
        from unittest.mock import patch

        from benchbox.core.run_service import execute_run

        seen = {}

        def factory(*, execution_mode, output_root, phases):
            seen["execution_mode"] = execution_mode
            seen["output_root"] = output_root
            seen["phases"] = phases
            return "ADAPTER"

        with (
            patch("benchbox.core.run_service.run_benchmark_lifecycle", return_value="RESULT") as lifecycle,
            patch("benchbox.core.run_service.apply_driver_metadata"),
        ):
            result = execute_run(
                config=_config(),
                benchmark_instance=object(),
                database_config=None,
                system_profile=None,
                platform_config=None,
                output_root="/tmp/out",
                phases_to_run=["load", "power"],
                adapter_factory=factory,
                verbosity=SilentVerbosity(),
            )

        assert result == "RESULT"
        assert seen["execution_mode"] is None
        assert seen["output_root"] == "/tmp/out"
        assert seen["phases"].load is True and seen["phases"].execute is True
        assert lifecycle.call_args.kwargs["platform_adapter"] == "ADAPTER"

    def test_a_factory_returning_none_is_honoured(self):
        """A data-only run has no database to adapt."""
        from unittest.mock import patch

        from benchbox.core.run_service import execute_run

        with (
            patch("benchbox.core.run_service.run_benchmark_lifecycle", return_value="RESULT") as lifecycle,
            patch("benchbox.core.run_service.apply_driver_metadata"),
        ):
            execute_run(
                config=_config(),
                benchmark_instance=object(),
                database_config=None,
                system_profile=None,
                platform_config=None,
                output_root="/tmp/out",
                phases_to_run=["generate"],
                adapter_factory=lambda **_: None,
                verbosity=SilentVerbosity(),
            )

        assert lifecycle.call_args.kwargs["platform_adapter"] is None

    def test_driver_metadata_is_applied_to_every_result(self):
        from unittest.mock import patch

        from benchbox.core.run_service import execute_run

        with (
            patch("benchbox.core.run_service.run_benchmark_lifecycle", return_value="RESULT"),
            patch("benchbox.core.run_service.apply_driver_metadata") as enrich,
        ):
            execute_run(
                config=_config(),
                benchmark_instance=object(),
                database_config=None,
                system_profile=None,
                platform_config=None,
                output_root="/tmp/out",
                phases_to_run=None,
                adapter_factory=lambda **_: "ADAPTER",
                verbosity=SilentVerbosity(),
            )

        enrich.assert_called_once()
        assert enrich.call_args.kwargs["platform_adapter"] == "ADAPTER"


class TestInteractionStaysInTheCli:
    """The anti-pattern: interaction-scoped code must not follow into core."""

    def test_core_emits_no_console_output(self):
        """Structural, not substring: no print calls, no console imports."""
        tree = ast.parse(RUN_SERVICE_SOURCE.read_text(encoding="utf-8"))

        called = {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        attribute_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}

        assert "print" not in called
        assert "print" not in attribute_calls
        assert not any(m.startswith("rich") or m.endswith("printing") for m in modules)

    def test_the_credential_retry_stayed_behind(self):
        """Interactive recovery is CLI-scoped and must not have followed."""
        tree = ast.parse(RUN_SERVICE_SOURCE.read_text(encoding="utf-8"))
        defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

        assert not any("credential" in name.lower() for name in defined)

        cli_source = (REPO_ROOT / "benchbox/cli/orchestrator.py").read_text(encoding="utf-8")
        assert "_offer_and_run_credential_setup" in cli_source

    def test_the_cli_still_owns_the_load_phase_warning(self):
        source = (REPO_ROOT / "benchbox/cli/orchestrator.py").read_text(encoding="utf-8")

        assert "_warn_on_execute_without_load" in source
        assert "assuming data already exists" in source
