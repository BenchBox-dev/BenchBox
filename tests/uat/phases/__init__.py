from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class PhaseResult:
    phase: str
    aborted: bool = False
    abort_reason: str | None = None

    def exit_code(self) -> int:
        return 2 if self.aborted else 0
