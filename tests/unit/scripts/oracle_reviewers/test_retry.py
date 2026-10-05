from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from _project.scripts.oracle_reviewers.policy import Policy
from _project.scripts.oracle_reviewers.retry import State, decide_rerun, due_for_retry, next_state

pytestmark = [pytest.mark.unit, pytest.mark.fast]

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
HEAD = "a" * 40
OTHER = "b" * 40


def _state(outcome: str, *, head: str = HEAD, age: timedelta = timedelta(hours=2), retries: int = 0) -> State:
    return State(
        7,
        head,
        outcome,
        NOW - age,
        tuple(NOW - timedelta(minutes=10 * (index + 1)) for index in range(retries)),
    )


def _decide(policy: Policy, previous: State | None, *, manual: bool = True, new_diff: bool = False):
    return decide_rerun(manual=manual, new_diff=new_diff, head_sha=HEAD, previous=previous, now=NOW, rules=policy.retry)


def test_rerun_on_the_same_head_needs_every_reviewer_absent(policy: Policy) -> None:
    for outcome in ("success", "failure"):
        decision = _decide(policy, _state(outcome))
        assert not decision.allowed
        assert "already has" in decision.reason
        assert not _decide(policy, _state(outcome), manual=False).allowed
    assert _decide(policy, _state("pending")).allowed


def test_new_head_or_new_diff_reruns(policy: Policy) -> None:
    assert _decide(policy, _state("failure", head=OTHER)).allowed
    assert _decide(policy, _state("failure"), manual=False, new_diff=True).allowed
    assert _decide(policy, None).allowed


def test_pull_request_events_do_not_spend_the_budget(policy: Policy) -> None:
    assert _decide(policy, _state("pending", retries=policy.retry.daily_budget), manual=False).allowed


def test_daily_budget_is_shared_by_comments_and_retries(policy: Policy) -> None:
    decision = _decide(policy, _state("pending", age=timedelta(days=2), retries=policy.retry.daily_budget))
    assert not decision.allowed
    assert "budget" in decision.reason


def test_backoff_starts_at_one_hour_and_doubles(policy: Policy) -> None:
    assert policy.retry.backoff_start_minutes == 60
    assert not _decide(policy, _state("pending", age=timedelta(minutes=59))).allowed
    assert _decide(policy, _state("pending", age=timedelta(minutes=61))).allowed
    assert not _decide(policy, _state("pending", age=timedelta(minutes=90), retries=1)).allowed
    assert _decide(policy, _state("pending", age=timedelta(minutes=121), retries=1)).allowed


def test_next_state_records_manual_retries_in_a_rolling_window(policy: Policy) -> None:
    old = State(7, HEAD, "pending", NOW - timedelta(days=2), (NOW - timedelta(days=2), NOW - timedelta(hours=1)))
    state = next_state(
        previous=old, pr=7, head_sha=HEAD, outcome="pending", manual=True, now=NOW, pool_blocked_until={}
    )
    assert state.retries == (NOW - timedelta(hours=1), NOW)
    assert State.from_json(state.to_json()) == state
    event_state = next_state(
        previous=old, pr=7, head_sha=HEAD, outcome="success", manual=False, now=NOW, pool_blocked_until={}
    )
    assert event_state.retries == (NOW - timedelta(hours=1),)


def test_sweep_retries_only_pending_runs_on_the_current_head(policy: Policy) -> None:
    assert due_for_retry(_state("pending"), HEAD, NOW, policy.retry)
    assert not due_for_retry(_state("pending"), OTHER, NOW, policy.retry)
    assert not due_for_retry(_state("success"), HEAD, NOW, policy.retry)
    assert not due_for_retry(_state("pending", age=timedelta(minutes=5)), HEAD, NOW, policy.retry)
