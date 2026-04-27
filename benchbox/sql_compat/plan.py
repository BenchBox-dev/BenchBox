"""CompilationPlan - cached resolver output for a (platform, benchmark) pair."""

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
    """Cached resolver output for a (platform, benchmark) pair.

    Populated incrementally by CompatibilityResolver.build_plan(). After the
    resolver hands this to the benchmark runner, it must not be mutated - the
    runner enforces this by not retaining a reference to the resolver. The
    dataclass is intentionally not frozen to support incremental population.
    """

    platform: str
    benchmark: str
    decisions: dict[tuple[str | None, Phase], CompatibilityDecision] = field(default_factory=dict)

    def get(self, query_id: str | None, phase: Phase) -> CompatibilityDecision | None:
        """Return the decision for (query_id, phase), falling back to (None, phase)."""
        return self.decisions.get((query_id, phase)) or self.decisions.get((None, phase))
