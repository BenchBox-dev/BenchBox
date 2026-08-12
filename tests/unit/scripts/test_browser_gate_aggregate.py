"""Contract tests for the fail-closed browser gate aggregation policy."""

import pytest

from _project.scripts.browser_gate_aggregate import evaluate_gate

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.mark.parametrize(
    ("changes_result", "chromium_result", "needed", "expected"),
    [
        ("failure", "success", "true", False),
        ("cancelled", "success", "true", False),
        ("skipped", "skipped", "false", False),
        ("success", "success", "true", True),
        ("success", "success", "false", True),
        ("success", "skipped", "false", True),
        ("success", "skipped", "true", False),
        ("success", "skipped", "", False),
        ("success", "failure", "true", False),
        ("success", "cancelled", "true", False),
        ("success", "neutral", "false", False),
    ],
)
def test_browser_gate_aggregate_matrix(changes_result: str, chromium_result: str, needed: str, expected: bool) -> None:
    passes, _message = evaluate_gate(changes_result, chromium_result, needed)

    assert passes is expected


def test_browser_gate_rejects_unknown_skip_state() -> None:
    passes, message = evaluate_gate("success", "skipped", "TRUE")

    assert not passes
    assert "invalid needed" in message
