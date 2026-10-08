from __future__ import annotations

from dataclasses import dataclass

from .verdict import COMPLETE, DO_NOT_SHIP, SHIP, SHIP_WITH_FIXES, Finding, Verdict

DO_NOT_SHIP_SUMMARY = 1500
LABELS = {SHIP: "SHIP", SHIP_WITH_FIXES: "SHIP WITH FIXES", DO_NOT_SHIP: "DO NOT SHIP"}


@dataclass(frozen=True)
class Judgement:
    decision: str
    defects: tuple[Finding, ...]
    summary: str

    @property
    def label(self) -> str:
        return LABELS[self.decision]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def judge(verdict: Verdict, max_defects: int) -> Judgement:
    if verdict.status != COMPLETE:
        raise ValueError("only a complete review can be judged")
    over = verdict.listed > max_defects
    if verdict.decision == DO_NOT_SHIP or over:
        note = f" The reviewer listed {verdict.listed} defects, more than the {max_defects} allowed." if over else ""
        return Judgement(DO_NOT_SHIP, (), _clip(verdict.summary, DO_NOT_SHIP_SUMMARY - len(note)) + note)
    if verdict.defects:
        return Judgement(SHIP_WITH_FIXES, verdict.defects, verdict.summary)
    return Judgement(SHIP, (), verdict.summary)
