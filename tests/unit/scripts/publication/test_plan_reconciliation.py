from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

SCRIPT = Path(__file__).parents[4] / "scripts/publication/check_plan_reconciliation.py"
SPEC = importlib.util.spec_from_file_location("check_plan_reconciliation", SCRIPT)
assert SPEC and SPEC.loader
reconciliation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reconciliation)

PREFIX = "independent-publication-"
LIVE_A0_A11 = [
    "independent-publication-a0-baseline-and-freeze",
    "independent-publication-a1-authority-and-threat-contract",
    "independent-publication-a2-corpus-trust-isolation",
    "independent-publication-a3-control-plane-and-artifact-contract",
    "independent-publication-a4-hermetic-build-and-shadow-assembly",
    "independent-publication-a5-noop-deploy-and-automatic-rollback",
    "independent-publication-a6-site-and-api-docs-lane",
    "independent-publication-a7-explorer-application-lane",
    "independent-publication-a8-published-results-gate-and-shadow-promotion",
    "independent-publication-a9-corpus-production-cutover",
    "independent-publication-a10-release-and-mirror-retirement",
    "independent-publication-a11-operations-canaries-and-closeout",
]


def test_all_controlling_surfaces_and_gates_are_named() -> None:
    text = reconciliation.DECISION.read_text()

    assert all(surface in text for surface in reconciliation.REQUIRED_SURFACES)
    assert all(gate in text for gate in reconciliation.REQUIRED_GATES)


def test_planned_tracker_ids_filters_requested_prefix() -> None:
    text = "`independent-publication-a1-later` then `independent-publication-a0-first` and `unrelated`"

    assert reconciliation.planned_tracker_ids(text, PREFIX) == [
        "independent-publication-a1-later",
        "independent-publication-a0-first",
    ]


def test_live_tracker_ids_orders_by_a_phase_not_hardcoded_order() -> None:
    payload = [
        {"id": "independent-publication-a11-operations-canaries-and-closeout"},
        {"id": "independent-publication-a3-control-plane-and-artifact-contract"},
        {"id": "unrelated-item"},
        {"id": "independent-publication-a0-baseline-and-freeze"},
        {"id": "independent-publication-a10-release-and-mirror-retirement"},
    ]

    assert reconciliation.live_tracker_ids(payload, PREFIX) == [
        "independent-publication-a0-baseline-and-freeze",
        "independent-publication-a3-control-plane-and-artifact-contract",
        "independent-publication-a10-release-and-mirror-retirement",
        "independent-publication-a11-operations-canaries-and-closeout",
    ]


def test_live_tracker_ids_ignores_items_outside_prefix() -> None:
    payload = [
        {"id": "independent-publication-a0-baseline-and-freeze"},
        {"id": "some-other-item"},
    ]

    assert reconciliation.live_tracker_ids(payload, PREFIX) == ["independent-publication-a0-baseline-and-freeze"]


def test_live_tracker_ids_excludes_dropped_items() -> None:
    payload = [
        {"id": "independent-publication-a0-baseline-and-freeze", "state": "done"},
        {"id": "independent-publication-a1-authority-and-threat-contract", "state": "active"},
        {"id": "independent-publication-a2-corpus-trust-isolation", "state": "dropped"},
    ]

    assert reconciliation.live_tracker_ids(payload, PREFIX) == [
        "independent-publication-a0-baseline-and-freeze",
        "independent-publication-a1-authority-and-threat-contract",
    ]


def test_decision_names_exact_live_ordered_tracker_sequence() -> None:
    text = reconciliation.DECISION.read_text()
    payload = [{"id": item_id} for item_id in reversed(LIVE_A0_A11)]

    assert reconciliation.planned_tracker_ids(text, PREFIX) == reconciliation.live_tracker_ids(payload, PREFIX)
    assert reconciliation.planned_tracker_ids(text, PREFIX) == LIVE_A0_A11


def test_authority_is_not_a_hardcoded_tracker_list() -> None:
    assert not hasattr(reconciliation, "REQUIRED_TRACKER_IDS")


def test_load_live_items_returns_none_when_todo_cmd_fails() -> None:
    import sys

    assert reconciliation.load_live_items([sys.executable, "-c", "raise SystemExit(1)"]) is None


def test_load_live_items_parses_json_list() -> None:
    import json
    import sys

    payload = [{"id": "independent-publication-a0-baseline-and-freeze"}]
    cmd = [sys.executable, "-c", f"import json,sys; print(json.dumps({json.dumps(payload)}))"]

    assert reconciliation.load_live_items(cmd) == payload


def test_load_live_items_returns_none_on_non_list_json() -> None:
    import sys

    cmd = [sys.executable, "-c", "print('{}')"]

    assert reconciliation.load_live_items(cmd) is None


def test_load_live_items_returns_none_on_invalid_json() -> None:
    import sys

    cmd = [sys.executable, "-c", "print('not json')"]

    assert reconciliation.load_live_items(cmd) is None


def test_main_fails_closed_when_live_tracker_unavailable(monkeypatch) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["check_plan_reconciliation", "--todo-prefix", "independent-publication-"])
    monkeypatch.setattr(reconciliation, "load_live_items", lambda: None)

    assert reconciliation.main() == 1


def test_main_fails_when_live_sequence_does_not_match(monkeypatch) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["check_plan_reconciliation", "--todo-prefix", "independent-publication-"])
    live_items = [
        {"id": "independent-publication-a0-baseline-and-freeze"},
        {"id": "independent-publication-a1-authority-and-threat-contract"},
    ]
    monkeypatch.setattr(reconciliation, "load_live_items", lambda: live_items)

    assert reconciliation.main() == 1


def test_main_succeeds_when_live_sequence_matches_decision(monkeypatch) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["check_plan_reconciliation", "--todo-prefix", "independent-publication-"])
    live_items = [{"id": item_id} for item_id in LIVE_A0_A11]
    monkeypatch.setattr(reconciliation, "load_live_items", lambda: live_items)

    assert reconciliation.main() == 0
