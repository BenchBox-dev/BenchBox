from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LadderRung:
    scale: float
    elapsed_s: float
    passed: bool


@dataclass(frozen=True)
class LadderDecision:
    prune_remaining: bool
    reason: str | None


def decide_next(
    rung: LadderRung,
    *,
    early_stop_after_s: float = 180.0,
    early_stop_on_failure: bool = True,
) -> LadderDecision:
    if early_stop_on_failure and not rung.passed:
        return LadderDecision(
            prune_remaining=True,
            reason=f"previous rung at scale={rung.scale} did not pass",
        )
    if rung.elapsed_s > early_stop_after_s:
        return LadderDecision(
            prune_remaining=True,
            reason=(
                f"previous rung at scale={rung.scale} took {rung.elapsed_s:.1f}s "
                f"> early_stop_after_s={early_stop_after_s:.0f}s"
            ),
        )
    return LadderDecision(prune_remaining=False, reason=None)


def plan_ladder(
    rungs: list[float],
    observations: list[LadderRung],
    *,
    early_stop_after_s: float = 180.0,
    early_stop_on_failure: bool = True,
) -> tuple[list[float], list[float]]:
    if not observations:
        return list(rungs), []
    last = observations[-1]
    decision = decide_next(
        last,
        early_stop_after_s=early_stop_after_s,
        early_stop_on_failure=early_stop_on_failure,
    )
    completed_idx = len(observations)
    if completed_idx >= len(rungs):
        return [], []
    if decision.prune_remaining:
        return [], list(rungs[completed_idx:])
    return list(rungs[completed_idx:]), []
