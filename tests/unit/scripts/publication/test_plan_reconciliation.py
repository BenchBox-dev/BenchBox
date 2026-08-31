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


def test_all_controlling_surfaces_and_gates_are_named() -> None:
    text = reconciliation.DECISION.read_text()

    assert all(surface in text for surface in reconciliation.REQUIRED_SURFACES)
    assert all(gate in text for gate in reconciliation.REQUIRED_GATES)


def test_planned_tracker_ids_filters_requested_prefix() -> None:
    text = "`independent-publication-a0-baseline` and `unrelated`"

    assert reconciliation.planned_tracker_ids(text, "independent-publication-") == [
        "independent-publication-a0-baseline"
    ]
