"""The core run service: request/plan types and configuration resolution.

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
    RunPlan,
    RunRequest,
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


class TestRequestAndPlanTypes:
    def test_run_request_carries_a_fully_resolved_description(self):
        request = RunRequest(platform="duckdb", benchmark="tpch", scale_factor=1.0)

        assert request.queries is None
        assert request.phases is None
        assert request.capture_plans is False
        assert dict(request.platform_options) == {}

    def test_run_request_is_immutable(self):
        """The service never renegotiates its inputs."""
        request = RunRequest(platform="duckdb", benchmark="tpch", scale_factor=1.0)

        with pytest.raises(AttributeError):
            request.platform = "sqlite"  # type: ignore[misc]

    def test_two_requests_with_the_same_inputs_are_equal(self):
        first = RunRequest(platform="duckdb", benchmark="tpch", scale_factor=1.0)
        second = RunRequest(platform="duckdb", benchmark="tpch", scale_factor=1.0)

        assert first == second

    def test_run_plan_binds_a_request_to_its_resolved_config(self):
        request = RunRequest(platform="duckdb", benchmark="tpch", scale_factor=1.0)
        config = _config()
        run_config = resolve_run_config(config, database_path="x", verbosity=SilentVerbosity())

        plan = RunPlan(
            request=request,
            benchmark_config=config,
            run_config=run_config,
            execution_type="power",
        )

        assert plan.request is request
        assert plan.run_config is run_config
        assert plan.execution_type == "power"
        assert plan.resolved_mode is None
