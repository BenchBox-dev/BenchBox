"""Cross-surface RunPlan equivalence: CLI and MCP resolve same inputs identically.

W3 for one-engine-mcp-run-service-adoption. The one-engine contract is that
all benchmark business logic lives in benchbox.core below both surfaces;
the two surfaces deliberately expose different subsets but resolve the same
logical inputs through the same core helpers (resolve_lifecycle_phases,
_map_phases_to_execution_type, resolve_run_config). This test pins that.
"""

from __future__ import annotations

import pytest

from benchbox.core.run_service import (
    _map_phases_to_execution_type,
    resolve_lifecycle_phases,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.mark.parametrize(
    "phases, expected_type, expect_execute",
    [
        (["load", "power"], "power", True),
        (["power"], "power", True),
        (["throughput"], "throughput", True),
        (["power", "throughput", "maintenance"], "combined", True),
        (["load"], "load_only", False),
        (["generate"], "data_only", False),
        ([], "standard", False),
        (["warmup"], "standard", False),
    ],
)
def test_runplan_equivalence_phases_map_same_for_cli_and_mcp(phases, expected_type, expect_execute):
    """Same phases list resolves identically via CLI and MCP (both use core)."""
    # MCP previously had _map_phases_to_test_execution_type; now core owns it
    mcp_type = _map_phases_to_execution_type(phases)
    # CLI uses resolve_lifecycle_phases for the same input
    lifecycle = resolve_lifecycle_phases(phases if phases else None)

    assert mcp_type == expected_type
    # Lifecycle and execution_type must agree on whether query execution happens
    if expected_type in ("power", "throughput", "combined", "standard"):
        assert lifecycle.execute is True
    elif expected_type == "load_only":
        assert lifecycle.load is True and lifecycle.execute is False
    elif expected_type == "data_only":
        assert lifecycle.generate is True
    else:
        # standard with no phases defaults to generate+load+execute
        pass


def test_runplan_parity_cli_mcp_run_config_resolution(tmp_path):
    """CLI orchestrator and MCP both delegate RunConfig to core (parity)."""
    from pathlib import Path

    from benchbox.cli.orchestrator import BenchmarkOrchestrator
    from benchbox.core.config import BenchmarkConfig
    from benchbox.core.run_service import SilentVerbosity, resolve_run_config

    cfg = BenchmarkConfig(
        name="tpch", display_name="TPC-H", scale_factor=0.01, queries=["1"], options={"seed": 5, "power_iterations": 2}
    )
    orch = BenchmarkOrchestrator(base_dir=str(tmp_path))

    class _DB:
        type = "duckdb"

    via_cli = orch._prepare_run_config(cfg, _DB())
    via_core = resolve_run_config(
        cfg,
        database_path=orch.directory_manager.get_database_path(
            cfg.name, cfg.scale_factor, "duckdb", tuning_config=None
        ),
        verbosity=SilentVerbosity(),
    )

    # CLI uses its own verbosity (quiet False), MCP uses SilentVerbosity (quiet True) — they differ only in verbosity flags
    # The equivalence is that the non-verbosity fields are identical because both delegate to core
    cli_dump = via_cli.model_dump()
    core_dump = via_core.model_dump()
    for k in ("quiet", "verbose", "verbose_level", "verbose_enabled", "very_verbose"):
        cli_dump.pop(k, None)
        core_dump.pop(k, None)
    assert cli_dump == core_dump
    assert via_core.quiet is True
    assert via_cli.quiet is False


def test_runplan_equivalence_mcp_parity_with_cli_via_core(tmp_path):
    """MCP job worker and CLI orchestrator share the same core RunConfig path."""
    from benchbox.cli.orchestrator import BenchmarkOrchestrator
    from benchbox.core.config import BenchmarkConfig
    from benchbox.core.run_service import SilentVerbosity, resolve_run_config

    cfg = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=1.0, options={"power_iterations": 3})
    orch = BenchmarkOrchestrator(base_dir=str(tmp_path))

    class _DB:
        type = "duckdb"

    # Simulate what MCP would do for the same logical request (via core)
    via_mcp = resolve_run_config(
        cfg,
        database_path=orch.directory_manager.get_database_path("tpch", 1.0, "duckdb", tuning_config=None),
        verbosity=SilentVerbosity(),
    )
    via_cli = orch._prepare_run_config(cfg, _DB())

    # Same config resolves same iterations via core; quiet differs by surface (MCP silent, CLI not)
    assert via_mcp.iterations == via_cli.iterations
    assert via_mcp.quiet is True
    assert via_cli.quiet is False
