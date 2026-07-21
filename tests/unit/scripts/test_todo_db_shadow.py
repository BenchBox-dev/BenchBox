"""Tests for deterministic, fail-closed shadow migration evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]


def _load_shadow() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "_project" / "scripts" / "todo_db_shadow.py"
    spec = importlib.util.spec_from_file_location("todo_db_shadow_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shadow = _load_shadow()


def _legacy_snapshot() -> dict:
    return {
        "items": [
            {
                "id": "sample-item",
                "title": "A sample tracked item",
                "worktree": "benchbox",
                "priority": "high",
                "state": "planning",
                "blocked_reason": None,
                "category": "Core",
                "description": "A description longer than ten characters.",
                "approach": "Keep the adapter thin.",
                "claimed_by": None,
                "claimed_at": None,
                "created_at": "2026-07-20T00:00:00Z",
                "completed_at": None,
                "completed_pr": None,
                "work": [],
                "deps": [],
                "scope": [],
                "verifications": [],
                "preserves": [],
                "anti_patterns": [{"dont": "drop data", "why": "loss", "instead": "compare"}],
                "prior_art": [{"path": "README.md", "concept": "bridge", "decision": "extend"}],
                "deferrals": [{"id": 1, "from_item": "sample-item", "summary": "follow up", "reason": "later"}],
            }
        ],
        "events": [{"action": "create", "item_id": "sample-item", "detail": {"title": "A sample tracked item"}}],
        "meta": [],
    }


def _standalone_envelope() -> dict:
    return {
        "events": [{"action": "create", "detail": {"title": "A sample tracked item", "item_id": "sample-item"}}],
        "tables": {
            "items": [],
            "work_units": [],
            "work_needs": [],
            "item_deps": [],
            "scope_rules": [],
            "verifications": [],
            "preserves": [],
            "anti_patterns": [],
            "prior_art": [],
            "deferrals": [],
        },
    }


def test_comparison_is_deterministic_and_reports_semantic_loss() -> None:
    legacy = _legacy_snapshot()
    first = shadow.compare_snapshots(legacy, _standalone_envelope())
    second = shadow.compare_snapshots(legacy, _standalone_envelope())
    assert first == second
    assert first["passed"] is False
    assert first["items"]["legacy_count"] == 1
    assert first["items"]["standalone_count"] == 0
    assert first["events"]["equal_provenance"] is True
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_equivalent_snapshot_passes_all_semantic_gates() -> None:
    legacy = _legacy_snapshot()
    item = legacy["items"][0]
    row = {
        key: value
        for key, value in item.items()
        if key not in {"work", "deps", "scope", "verifications", "preserves", "anti_patterns", "prior_art", "deferrals"}
    }
    tables = {
        "items": [row],
        "work_units": [],
        "work_needs": [],
        "item_deps": [],
        "scope_rules": [],
        "verifications": [],
        "preserves": [],
        "anti_patterns": [{"item_id": "sample-item", **item["anti_patterns"][0]}],
        "prior_art": [{"item_id": "sample-item", **item["prior_art"][0]}],
        "deferrals": item["deferrals"],
    }
    for table in shadow.TABLE_NAMES:
        if table != "items":
            legacy[table] = list(tables[table])
    result = shadow.compare_snapshots(
        legacy,
        {
            "events": [{"action": "create", "detail": {"title": "A sample tracked item", "item_id": "sample-item"}}],
            "tables": tables,
        },
    )
    assert not result["items"]["missing"], result
    assert not result["items"]["unexpected"], result
    assert not result["items"]["field_diffs"], json.dumps(result["items"]["field_diffs"], sort_keys=True)
    assert result["events"]["equal_provenance"], result["events"]
    assert all(counts["legacy"] == counts["standalone"] for counts in result["table_counts"].values()), result[
        "table_counts"
    ]
    assert result["passed"] is True
    assert not result["items"]["field_diffs"]
    assert all(counts["legacy"] == counts["standalone"] for counts in result["table_counts"].values())


def test_comparison_includes_meta_and_normalizes_event_order() -> None:
    legacy = {
        "items": [],
        "events": [
            {"action": "done", "item_id": "b", "detail": {"wid": "w1"}},
            {"action": "create", "item_id": "a", "detail": {}},
        ],
        "meta": [{"key": "lint.require_scope_rules", "value": "on"}],
    }
    standalone = {
        "events": [
            {"action": "create", "detail": {"item_id": "a"}},
            {"action": "done", "detail": {"item_id": "b", "wid": "w1"}},
        ],
        "metadata": {"lint.require_scope_rules": "on"},
        "tables": {name: [] for name in shadow.TABLE_NAMES},
    }
    result = shadow.compare_snapshots(legacy, standalone)
    assert result["meta"]["equal"] is True
    assert result["events"]["equal_provenance"] is True


def test_malformed_envelope_has_actionable_error() -> None:
    with pytest.raises(shadow.ShadowMigrationError, match="items table"):
        shadow.compare_snapshots({"items": [], "events": [], "meta": []}, {"tables": []})


def test_validate_target_rejects_export_sidecar(tmp_path: Path) -> None:
    target = tmp_path / "shadow.sqlite"
    target.with_suffix(".export.json").write_text("keep", encoding="utf-8")
    with pytest.raises(shadow.ShadowMigrationError, match="export path"):
        shadow.validate_target(target, benchbox_db=tmp_path / "benchbox.sqlite", standalone_db=tmp_path / "plan.sqlite")


def test_run_captures_success_output() -> None:
    result = shadow._run(["sh", "-c", "printf imported; printf warning >&2"], cwd=Path.cwd(), env={})
    assert result == {"stdout": "imported", "stderr": "warning", "returncode": 0}


def test_run_redacts_success_output() -> None:
    result = shadow._run(
        ["sh", "-c", "printf secret; printf secret >&2"],
        cwd=Path.cwd(),
        env={"TODO_DB_RO_AUTH_TOKEN": "secret"},
    )
    assert result == {"stdout": "[REDACTED]", "stderr": "[REDACTED]", "returncode": 0}


def test_empty_source_is_rejected_before_any_target_creation(tmp_path: Path) -> None:
    todo_dir = tmp_path / "TODO"
    done_dir = tmp_path / "DONE"
    todo_dir.mkdir()
    done_dir.mkdir()
    target = tmp_path / "shadow.sqlite"

    with pytest.raises(shadow.ShadowMigrationError, match="no YAML tracker records"):
        shadow.run_shadow(
            repo_root=tmp_path,
            todo_dir=todo_dir,
            done_dir=done_dir,
            target=target,
            report_path=tmp_path / "report.json",
            standalone_project=tmp_path / "standalone",
        )
    assert not target.exists()


def test_zero_item_import_is_rejected_instead_of_passing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    todo_dir = tmp_path / "TODO"
    done_dir = tmp_path / "DONE"
    todo_dir.mkdir()
    done_dir.mkdir()
    (todo_dir / "item.yaml").write_text("id: item\n", encoding="utf-8")
    target = tmp_path / "shadow.sqlite"

    monkeypatch.setattr(shadow, "legacy_snapshot", lambda connection: {"items": [], "events": [], "meta": []})
    monkeypatch.setattr(shadow, "_run", lambda command, *, cwd, env: None)

    with pytest.raises(shadow.ShadowMigrationError, match="legacy import produced zero items"):
        shadow.run_shadow(
            repo_root=tmp_path,
            todo_dir=todo_dir,
            done_dir=done_dir,
            target=target,
            report_path=tmp_path / "report.json",
            standalone_project=tmp_path / "standalone",
        )
    assert not target.exists()


def test_failed_import_rolls_back_new_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    todo_dir = tmp_path / "TODO"
    done_dir = tmp_path / "DONE"
    todo_dir.mkdir()
    done_dir.mkdir()
    (todo_dir / "item.yaml").write_text("id: item\n", encoding="utf-8")
    target = tmp_path / "shadow.sqlite"
    standalone_project = tmp_path / "standalone"

    monkeypatch.setattr(
        shadow, "legacy_snapshot", lambda connection: {"items": [{"id": "item"}], "events": [], "meta": []}
    )

    def fake_run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        if str(standalone_project) in command and "init" in command:
            target.touch()
        if str(standalone_project) in command and "import-yaml" in command:
            raise shadow.ShadowMigrationError("simulated failed import")

    monkeypatch.setattr(shadow, "_run", fake_run)
    with pytest.raises(shadow.ShadowMigrationError, match="simulated failed import"):
        shadow.run_shadow(
            repo_root=tmp_path,
            todo_dir=todo_dir,
            done_dir=done_dir,
            target=target,
            report_path=tmp_path / "report.json",
            standalone_project=standalone_project,
        )
    assert not target.exists()
