"""Composable UAT phases plus shared phase-result contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class PhaseResult:
    """Common phase result contract used by the UAT orchestrator."""

    phase: str
    aborted: bool = False
    abort_reason: str | None = None

    def exit_code(self) -> int:
        return 2 if self.aborted else 0
