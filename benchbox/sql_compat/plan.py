from __future__ import annotations

from dataclasses import dataclass, field

from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision


@dataclass(frozen=True)
class PhasedDecision:
    query_id: str | None
    phase: Phase
    decision: CompatibilityDecision


@dataclass
class CompilationPlan:
    platform: str
    benchmark: str
    decisions: dict[tuple[str | None, Phase], CompatibilityDecision] = field(default_factory=dict)

    def get(self, query_id: str | None, phase: Phase) -> CompatibilityDecision | None:
        return self.decisions.get((query_id, phase)) or self.decisions.get((None, phase))
