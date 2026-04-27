"""CompatibilityResolver - builds CompilationPlan from the registry.

Called once per (platform, benchmark) at run start. The resulting
CompilationPlan is cached in the benchmark execution context so
warmup/power/throughput phases do not re-query the registry.
"""

from __future__ import annotations

from typing import Literal

from benchbox.sql_compat.context import CompatibilityContext, Phase
from benchbox.sql_compat.plan import CompilationPlan
from benchbox.sql_compat.registry import CompatibilityRegistry


class CompatibilityResolver:
    def __init__(self, registry: CompatibilityRegistry) -> None:
        self._registry = registry

    def build_plan(
        self,
        platform: str,
        benchmark: str,
        query_ids: list[str],
        platform_version: str | None = None,
        mode: Literal["sql", "dataframe"] = "sql",
    ) -> CompilationPlan:
        """Pre-compute decisions for all (query_id, phase) combinations.

        Args:
            platform: Platform key (e.g. "starrocks").
            benchmark: Benchmark name (e.g. "h2odb").
            query_ids: All query IDs that will run (e.g. ["Q1", "Q2", ...]).
                       An empty list still resolves platform- and benchmark-wide
                       rules (query_id=None tier).
            platform_version: Semver string or None.
            mode: "sql" or "dataframe".

        Returns:
            CompilationPlan with decisions keyed by (query_id | None, Phase).
        """
        plan = CompilationPlan(platform=platform, benchmark=benchmark)

        phases = list(Phase)

        # Resolve benchmark-wide rules (query_id=None)
        for phase in phases:
            ctx = CompatibilityContext(
                platform=platform,
                platform_version=platform_version,
                benchmark=benchmark,
                query_id=None,
                phase=phase,
                mode=mode,
                dialect=None,
            )
            decision = self._registry.resolve(ctx)
            if decision is not None:
                plan.decisions[(None, phase)] = decision

        # Resolve per-query rules (override benchmark-wide where more specific)
        for query_id in query_ids:
            for phase in phases:
                ctx = CompatibilityContext(
                    platform=platform,
                    platform_version=platform_version,
                    benchmark=benchmark,
                    query_id=query_id,
                    phase=phase,
                    mode=mode,
                    dialect=None,
                )
                decision = self._registry.resolve(ctx)
                if decision is not None:
                    plan.decisions[(query_id, phase)] = decision

        return plan
