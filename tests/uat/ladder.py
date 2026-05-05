"""Per-(platform, benchmark) scale-ladder with early-stop logic.

Mirrors the 2026-05-02 sweep's ladder behaviour
(_project/handoffs/results-explorer-uat-retrospective-20260502.md):
ascend rungs in order; prune subsequent rungs when the previous one
fails or runs longer than `early_stop_after_s` (default 180 s, per
UAT W3 line 196).

Per-rung wall-clock semantics — the threshold is the elapsed time of
the rung that just finished, not a running total. This matches the
bash precedent.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LadderRung:
    """One rung's outcome before deciding whether to advance."""

    scale: float
    elapsed_s: float
    passed: bool


@dataclass(frozen=True)
class LadderDecision:
    """Decision for the next rung. `prune_remaining: True` means stop here."""

    prune_remaining: bool
    reason: str | None


def decide_next(
    rung: LadderRung,
    *,
    early_stop_after_s: float = 180.0,
    early_stop_on_failure: bool = True,
) -> LadderDecision:
    """Decide whether to ascend after observing `rung`."""
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
    """Given a rung order and the observations made so far, return (next_rungs_to_run, pruned_rungs).

    `observations` is in ascending scale order matching the prefix of `rungs`.
    """
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
