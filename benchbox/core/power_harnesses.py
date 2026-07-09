"""TPC test-phase harness capability registry.

#914 extracted the *power*-test dispatch behind ``resolve_power_harness`` so
``platforms/base/execution.py`` carried no literal TPC benchmark names on that path.
This extends the same capability registry to the remaining phases (throughput,
maintenance) and to the combined runner, so every dispatch method routes by
capability lookup instead of a literal ``benchmark_id == "tpch" / "tpcds"`` branch.
The per-benchmark phase *bodies* still live on the adapter mixin; only the routing
moves here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseHarnessCapability:
    """Adapter capability mapping a benchmark id to one phase's harness method."""

    benchmark_id: str
    adapter_method: str


# Back-compat alias: power was the first phase extracted (#914).
PowerHarnessCapability = PhaseHarnessCapability


@dataclass(frozen=True)
class CombinedHarnessCapability:
    """Adapter capability for the combined runner: a label + the three phase methods."""

    benchmark_id: str
    label: str
    power_method: str
    throughput_method: str
    maintenance_method: str


POWER_HARNESS_CAPABILITIES: tuple[PhaseHarnessCapability, ...] = (
    PhaseHarnessCapability("tpch", "_execute_tpch_power_test"),
    PhaseHarnessCapability("tpcds", "_execute_tpcds_power_test"),
)

THROUGHPUT_HARNESS_CAPABILITIES: tuple[PhaseHarnessCapability, ...] = (
    PhaseHarnessCapability("tpch", "_execute_tpch_throughput_test"),
    PhaseHarnessCapability("tpcds", "_execute_tpcds_throughput_test"),
)

MAINTENANCE_HARNESS_CAPABILITIES: tuple[PhaseHarnessCapability, ...] = (
    PhaseHarnessCapability("tpch", "_execute_tpch_maintenance_test"),
    PhaseHarnessCapability("tpcds", "_execute_tpcds_maintenance_test"),
)

COMBINED_HARNESS_CAPABILITIES: tuple[CombinedHarnessCapability, ...] = (
    CombinedHarnessCapability(
        "tpch", "TPC-H", "_execute_tpch_power_test", "_execute_tpch_throughput_test", "_execute_tpch_maintenance_test"
    ),
    CombinedHarnessCapability(
        "tpcds",
        "TPC-DS",
        "_execute_tpcds_power_test",
        "_execute_tpcds_throughput_test",
        "_execute_tpcds_maintenance_test",
    ),
)

_POWER_HARNESS_BY_ID = {capability.benchmark_id: capability for capability in POWER_HARNESS_CAPABILITIES}
_THROUGHPUT_HARNESS_BY_ID = {capability.benchmark_id: capability for capability in THROUGHPUT_HARNESS_CAPABILITIES}
_MAINTENANCE_HARNESS_BY_ID = {capability.benchmark_id: capability for capability in MAINTENANCE_HARNESS_CAPABILITIES}
_COMBINED_HARNESS_BY_ID = {capability.benchmark_id: capability for capability in COMBINED_HARNESS_CAPABILITIES}


def resolve_power_harness(benchmark_id: str) -> PhaseHarnessCapability | None:
    """Return the registered power-test harness for a canonical benchmark id."""
    return _POWER_HARNESS_BY_ID.get(benchmark_id)


def resolve_throughput_harness(benchmark_id: str) -> PhaseHarnessCapability | None:
    """Return the registered throughput-test harness for a canonical benchmark id."""
    return _THROUGHPUT_HARNESS_BY_ID.get(benchmark_id)


def resolve_maintenance_harness(benchmark_id: str) -> PhaseHarnessCapability | None:
    """Return the registered maintenance-test harness for a canonical benchmark id."""
    return _MAINTENANCE_HARNESS_BY_ID.get(benchmark_id)


def resolve_combined_harness(benchmark_id: str) -> CombinedHarnessCapability | None:
    """Return the registered combined-runner harness for a canonical benchmark id."""
    return _COMBINED_HARNESS_BY_ID.get(benchmark_id)
