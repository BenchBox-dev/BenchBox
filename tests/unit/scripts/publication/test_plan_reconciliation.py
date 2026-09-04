from __future__ import annotations

import importlib.util
import json
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

REAL_DEPS = {
    "independent-publication-a0-baseline-and-freeze": [],
    "independent-publication-a1-authority-and-threat-contract": ["independent-publication-a0-baseline-and-freeze"],
    "independent-publication-a2-corpus-trust-isolation": ["independent-publication-a1-authority-and-threat-contract"],
    "independent-publication-a3-control-plane-and-artifact-contract": [
        "independent-publication-a1-authority-and-threat-contract",
        "independent-publication-a2-corpus-trust-isolation",
    ],
    "independent-publication-a4-hermetic-build-and-shadow-assembly": [
        "independent-publication-a3-control-plane-and-artifact-contract"
    ],
    "independent-publication-a5-noop-deploy-and-automatic-rollback": [
        "independent-publication-a4-hermetic-build-and-shadow-assembly"
    ],
    "independent-publication-a6-site-and-api-docs-lane": [
        "independent-publication-a5-noop-deploy-and-automatic-rollback"
    ],
    "independent-publication-a7-explorer-application-lane": [
        "independent-publication-a5-noop-deploy-and-automatic-rollback"
    ],
    "independent-publication-a8-published-results-gate-and-shadow-promotion": [
        "independent-publication-a2-corpus-trust-isolation",
        "independent-publication-a4-hermetic-build-and-shadow-assembly",
        "independent-publication-a7-explorer-application-lane",
    ],
    "independent-publication-a9-corpus-production-cutover": [
        "independent-publication-a6-site-and-api-docs-lane",
        "independent-publication-a7-explorer-application-lane",
        "independent-publication-a8-published-results-gate-and-shadow-promotion",
    ],
    "independent-publication-a10-release-and-mirror-retirement": [
        "independent-publication-a9-corpus-production-cutover"
    ],
    "independent-publication-a11-operations-canaries-and-closeout": [
        "independent-publication-a10-release-and-mirror-retirement"
    ],
}


def _snapshot(states: dict[str, str] | None = None, deps: dict[str, list[str]] | None = None) -> dict:
    if states is None:
        states = dict.fromkeys(LIVE_A0_A11, "active")
    if deps is None:
        deps = {item_id: list(REAL_DEPS.get(item_id, [])) for item_id in states}
    return {"states": states, "deps": deps}


def _envelope(items: list[dict], item_deps: list[dict]) -> str:
    return json.dumps({"tables": {"items": items, "item_deps": item_deps}})


def _prefixed_argv(monkeypatch) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["check_plan_reconciliation", "--todo-prefix", PREFIX])


# --- planned/live ordering helpers (unchanged surface) -----------------------


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


# --- export envelope parsing ------------------------------------------------


def test_parse_envelope_builds_state_and_dep_maps() -> None:
    raw = _envelope(
        items=[
            {"id": "independent-publication-a0-baseline-and-freeze", "state": "done"},
            {"id": "independent-publication-a1-authority-and-threat-contract", "state": "active"},
        ],
        item_deps=[
            {
                "item_id": "independent-publication-a1-authority-and-threat-contract",
                "needs_item": "independent-publication-a0-baseline-and-freeze",
            },
        ],
    )

    snapshot = reconciliation.parse_envelope(raw)

    assert snapshot == {
        "states": {
            "independent-publication-a0-baseline-and-freeze": "done",
            "independent-publication-a1-authority-and-threat-contract": "active",
        },
        "deps": {
            "independent-publication-a0-baseline-and-freeze": [],
            "independent-publication-a1-authority-and-threat-contract": [
                "independent-publication-a0-baseline-and-freeze"
            ],
        },
    }


def test_parse_envelope_returns_none_on_malformed_json() -> None:
    assert reconciliation.parse_envelope("not json") is None


def test_parse_envelope_returns_none_on_truncated_envelope() -> None:
    raw = _envelope(items=[{"id": "x", "state": "active"}], item_deps=[])
    assert reconciliation.parse_envelope(raw[: len(raw) // 2]) is None


def test_parse_envelope_returns_none_on_missing_tables() -> None:
    assert reconciliation.parse_envelope(json.dumps({"events": []})) is None
    assert reconciliation.parse_envelope(json.dumps({"tables": {"items": []}})) is None


def test_parse_envelope_returns_none_when_item_row_lacks_id() -> None:
    assert (
        reconciliation.parse_envelope(json.dumps({"tables": {"items": [{"state": "active"}], "item_deps": []}})) is None
    )


def test_load_tracker_snapshot_returns_none_when_export_fails(monkeypatch) -> None:
    monkeypatch.setattr(reconciliation, "_run_export", lambda output_path: False)

    assert reconciliation.load_tracker_snapshot() is None


def test_load_tracker_snapshot_parses_written_envelope(monkeypatch) -> None:
    raw = _envelope(items=[{"id": "x", "state": "active"}], item_deps=[{"item_id": "x", "needs_item": "y"}])

    def fake_run_export(output_path: Path) -> bool:
        output_path.write_text(raw, encoding="utf-8")
        return True

    monkeypatch.setattr(reconciliation, "_run_export", fake_run_export)

    assert reconciliation.load_tracker_snapshot() == {
        "states": {"x": "active"},
        "deps": {"x": ["y"]},
    }


# --- main() fail-closed / success behaviour --------------------------------


def test_main_fails_closed_when_snapshot_unavailable(monkeypatch) -> None:
    _prefixed_argv(monkeypatch)
    monkeypatch.setattr(reconciliation, "load_tracker_snapshot", lambda: None)

    assert reconciliation.main() == 1


def test_main_fails_closed_when_dependency_row_absent(monkeypatch) -> None:
    _prefixed_argv(monkeypatch)
    states = dict.fromkeys(LIVE_A0_A11, "active")
    deps = {item_id: list(REAL_DEPS.get(item_id, [])) for item_id in LIVE_A0_A11}
    deps.pop("independent-publication-a5-noop-deploy-and-automatic-rollback")
    monkeypatch.setattr(reconciliation, "load_tracker_snapshot", lambda: _snapshot(states, deps))

    assert reconciliation.main() == 1


def test_main_succeeds_when_live_sequence_matches_decision(monkeypatch) -> None:
    _prefixed_argv(monkeypatch)
    monkeypatch.setattr(reconciliation, "load_tracker_snapshot", lambda: _snapshot())

    assert reconciliation.main() == 0


def test_main_fails_when_live_sequence_does_not_match(monkeypatch) -> None:
    _prefixed_argv(monkeypatch)
    states = {
        "independent-publication-a0-baseline-and-freeze": "active",
        "independent-publication-a1-authority-and-threat-contract": "active",
    }
    monkeypatch.setattr(reconciliation, "load_tracker_snapshot", lambda: _snapshot(states))

    assert reconciliation.main() == 1


def test_main_fails_on_dependency_edge_drift(monkeypatch) -> None:
    _prefixed_argv(monkeypatch)
    deps = {item_id: list(REAL_DEPS.get(item_id, [])) for item_id in LIVE_A0_A11}
    deps["independent-publication-a1-authority-and-threat-contract"] = []
    monkeypatch.setattr(reconciliation, "load_tracker_snapshot", lambda: _snapshot(deps=deps))

    assert reconciliation.main() == 1


def test_main_fails_on_partial_edge_removal(monkeypatch) -> None:
    _prefixed_argv(monkeypatch)
    deps = {item_id: list(REAL_DEPS.get(item_id, [])) for item_id in LIVE_A0_A11}
    deps["independent-publication-a8-published-results-gate-and-shadow-promotion"] = [
        "independent-publication-a2-corpus-trust-isolation",
        "independent-publication-a4-hermetic-build-and-shadow-assembly",
    ]
    monkeypatch.setattr(reconciliation, "load_tracker_snapshot", lambda: _snapshot(deps=deps))

    assert reconciliation.main() == 1


def test_main_fails_when_required_phase_is_dropped(monkeypatch) -> None:
    _prefixed_argv(monkeypatch)
    states = dict.fromkeys(LIVE_A0_A11, "done")
    states["independent-publication-a5-noop-deploy-and-automatic-rollback"] = "dropped"
    monkeypatch.setattr(reconciliation, "load_tracker_snapshot", lambda: _snapshot(states))

    assert reconciliation.main() == 1


def test_main_fails_when_dropped_phase_omitted_from_decision(monkeypatch) -> None:
    _prefixed_argv(monkeypatch)
    states = dict.fromkeys(LIVE_A0_A11, "done")
    states["independent-publication-a5-noop-deploy-and-automatic-rollback"] = "dropped"
    omitted = [item_id for item_id in LIVE_A0_A11 if item_id != LIVE_A0_A11[5]]
    monkeypatch.setattr(reconciliation, "load_tracker_snapshot", lambda: _snapshot(states))
    monkeypatch.setattr(reconciliation, "planned_tracker_ids", lambda text, prefix: omitted)

    assert reconciliation.main() == 1


def test_main_fails_when_pinned_phase_missing_from_plan(monkeypatch) -> None:
    _prefixed_argv(monkeypatch)
    omitted = LIVE_A0_A11[:-1]
    monkeypatch.setattr(reconciliation, "load_tracker_snapshot", lambda: _snapshot())
    monkeypatch.setattr(reconciliation, "planned_tracker_ids", lambda text, prefix: omitted)

    assert reconciliation.main() == 1


def test_main_fails_when_pinned_phase_missing_from_live(monkeypatch) -> None:
    _prefixed_argv(monkeypatch)
    states = dict.fromkeys(LIVE_A0_A11[:-1], "done")
    monkeypatch.setattr(reconciliation, "load_tracker_snapshot", lambda: _snapshot(states))

    assert reconciliation.main() == 1


# --- dependency_violations (pure) ------------------------------------------


def test_dependency_violations_passes_for_real_dag() -> None:
    assert reconciliation.dependency_violations(LIVE_A0_A11, REAL_DEPS) == []


def test_dependency_violations_fails_on_removed_chain() -> None:
    drifted = dict(REAL_DEPS)
    drifted["independent-publication-a1-authority-and-threat-contract"] = []

    violations = reconciliation.dependency_violations(LIVE_A0_A11, drifted)

    assert any("has no prior dependency" in v and "a1-authority" in v for v in violations)


def test_dependency_violations_fails_on_backward_edge() -> None:
    drifted = dict(REAL_DEPS)
    drifted["independent-publication-a1-authority-and-threat-contract"] = [
        "independent-publication-a2-corpus-trust-isolation"
    ]

    violations = reconciliation.dependency_violations(LIVE_A0_A11, drifted)

    assert any("depends on" in v and "which the plan orders after it" in v for v in violations)


def test_dependency_violations_surfaces_cycle_as_backward_edge() -> None:
    drifted = dict(REAL_DEPS)
    drifted["independent-publication-a0-baseline-and-freeze"] = [
        "independent-publication-a1-authority-and-threat-contract"
    ]

    violations = reconciliation.dependency_violations(LIVE_A0_A11, drifted)

    assert any("depends on" in v for v in violations)


def test_dependency_violations_fails_on_partial_edge_removal() -> None:
    drifted = dict(REAL_DEPS)
    drifted["independent-publication-a8-published-results-gate-and-shadow-promotion"] = [
        "independent-publication-a2-corpus-trust-isolation",
        "independent-publication-a4-hermetic-build-and-shadow-assembly",
    ]

    violations = reconciliation.dependency_violations(LIVE_A0_A11, drifted)

    assert any("is missing expected dependency" in v and "a8-published" in v and "a7-explorer" in v for v in violations)


def test_dependency_violations_fails_on_unexpected_edge() -> None:
    drifted = dict(REAL_DEPS)
    drifted["independent-publication-a3-control-plane-and-artifact-contract"] = [
        "independent-publication-a1-authority-and-threat-contract",
        "independent-publication-a2-corpus-trust-isolation",
        "independent-publication-a0-baseline-and-freeze",
    ]

    violations = reconciliation.dependency_violations(LIVE_A0_A11, drifted)

    assert any("has unexpected dependency" in v and "a3-control" in v for v in violations)


def test_dependency_violations_fails_on_external_dependency() -> None:
    drifted = dict(REAL_DEPS)
    drifted["independent-publication-a3-control-plane-and-artifact-contract"] = [
        "independent-publication-a1-authority-and-threat-contract",
        "independent-publication-a2-corpus-trust-isolation",
        "external-tracker-item",
    ]

    violations = reconciliation.dependency_violations(LIVE_A0_A11, drifted)

    assert any("has unexpected external dependency" in v and "external-tracker-item" in v for v in violations)


def test_dependency_violations_fails_on_unpinned_phase() -> None:
    plan = LIVE_A0_A11 + ["independent-publication-a12-new-phase"]
    drifted = dict(REAL_DEPS)
    drifted["independent-publication-a12-new-phase"] = ["independent-publication-a11-operations-canaries-and-closeout"]

    violations = reconciliation.dependency_violations(plan, drifted)

    assert any("is not pinned in EXPECTED_DEPS" in v and "a12-new-phase" in v for v in violations)


def test_expected_deps_matches_real_deps() -> None:
    assert reconciliation.EXPECTED_DEPS == REAL_DEPS
