from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .policy import RetryRules

SUCCESS = "success"
FAILURE = "failure"
PENDING = "pending"
DECISIVE = (SUCCESS, FAILURE)
WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class State:
    pr: int
    head_sha: str
    outcome: str
    updated_at: datetime
    retries: tuple[datetime, ...] = ()
    pool_blocked_until: Mapping[str, datetime] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "pr": self.pr,
            "head_sha": self.head_sha,
            "outcome": self.outcome,
            "updated_at": self.updated_at.isoformat(),
            "retries": [moment.isoformat() for moment in self.retries],
            "pool_blocked_until": {pool: moment.isoformat() for pool, moment in self.pool_blocked_until.items()},
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> State:
        return cls(
            pr=int(data["pr"]),
            head_sha=str(data["head_sha"]),
            outcome=str(data["outcome"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            retries=tuple(datetime.fromisoformat(item) for item in data.get("retries", [])),
            pool_blocked_until={
                pool: datetime.fromisoformat(value) for pool, value in data.get("pool_blocked_until", {}).items()
            },
        )


@dataclass(frozen=True)
class RerunDecision:
    allowed: bool
    reason: str


def recent_retries(state: State | None, now: datetime) -> tuple[datetime, ...]:
    if state is None:
        return ()
    return tuple(moment for moment in state.retries if now - moment < WINDOW)


def decide_rerun(
    *,
    manual: bool,
    new_diff: bool,
    head_sha: str,
    previous: State | None,
    now: datetime,
    rules: RetryRules,
) -> RerunDecision:
    same_head = previous is not None and previous.head_sha == head_sha
    if same_head and previous is not None and previous.outcome in DECISIVE and not new_diff:
        return RerunDecision(False, f"head {head_sha} already has a {previous.outcome} result")
    if not manual:
        return RerunDecision(True, "pull request event")
    retries = recent_retries(previous, now)
    if len(retries) >= rules.daily_budget:
        return RerunDecision(False, f"the daily retry budget of {rules.daily_budget} is used")
    if same_head and previous is not None:
        wait = timedelta(minutes=rules.backoff_start_minutes * 2 ** len(retries))
        ready_at = previous.updated_at + wait
        if now < ready_at:
            return RerunDecision(False, f"backoff: the next retry is allowed after {ready_at.isoformat()}")
    return RerunDecision(True, "retry within budget")


def next_state(
    *,
    previous: State | None,
    pr: int,
    head_sha: str,
    outcome: str,
    manual: bool,
    now: datetime,
    pool_blocked_until: Mapping[str, datetime],
) -> State:
    retries = recent_retries(previous, now) + ((now,) if manual else ())
    return State(pr, head_sha, outcome, now, retries, dict(pool_blocked_until))


def due_for_retry(state: State, current_head: str, now: datetime, rules: RetryRules) -> bool:
    if state.outcome != PENDING or state.head_sha != current_head:
        return False
    return decide_rerun(
        manual=True, new_diff=False, head_sha=current_head, previous=state, now=now, rules=rules
    ).allowed
