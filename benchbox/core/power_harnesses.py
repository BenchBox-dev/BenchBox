"""Power-test harness capability registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PowerHarnessCapability:
    """Adapter capability for a benchmark-specific power-test harness."""

    benchmark_id: str
    adapter_method: str


POWER_HARNESS_CAPABILITIES: tuple[PowerHarnessCapability, ...] = (
    PowerHarnessCapability("tpch", "_execute_tpch_power_test"),
    PowerHarnessCapability("tpcds", "_execute_tpcds_power_test"),
)

_POWER_HARNESS_BY_ID = {capability.benchmark_id: capability for capability in POWER_HARNESS_CAPABILITIES}


def resolve_power_harness(benchmark_id: str) -> PowerHarnessCapability | None:
    """Return the registered power-test harness for a canonical benchmark id."""
    return _POWER_HARNESS_BY_ID.get(benchmark_id)
