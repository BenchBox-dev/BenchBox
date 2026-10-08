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
        plan = CompilationPlan(platform=platform, benchmark=benchmark)

        phases = list(Phase)

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
