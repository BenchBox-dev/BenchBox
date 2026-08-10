"""Tests for deterministic, fail-closed shadow migration evidence."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
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


def test_comparison_normalizes_generated_import_provenance() -> None:
    legacy = _legacy_snapshot()
    legacy["items"][0]["created_at"] = "2026-07-21T13:19:48Z"
    legacy["items"][0]["deps"] = ["dependency"]
    legacy["items"][0]["deferrals"][0].update({"created_at": "2026-07-21T13:19:48Z", "resolution": "open"})
    legacy["events"] = [
        {"action": "create", "item_id": "sample-item", "detail": {"title": "A sample tracked item"}},
        {"action": "defer", "item_id": "sample-item", "detail": {"deferral_id": 4, "summary": "follow up"}},
    ]
    legacy["meta"] = [{"key": "schema_version", "value": "2"}]
    standalone = _standalone_envelope()
    standalone["tables"]["items"] = [
        {
            key: value
            for key, value in legacy["items"][0].items()
            if key
            not in {"work", "deps", "scope", "verifications", "preserves", "anti_patterns", "prior_art", "deferrals"}
        }
    ]
    standalone["tables"]["items"][0]["created_at"] = "2026-07-21T13:19:54Z"
    standalone["tables"]["deferrals"] = [
        {
            **legacy["items"][0]["deferrals"][0],
            "id": 9,
            "created_at": "2026-07-21T13:19:54Z",
        }
    ]
    standalone["tables"]["anti_patterns"] = [{"item_id": "sample-item", **legacy["items"][0]["anti_patterns"][0]}]
    standalone["tables"]["prior_art"] = [{"item_id": "sample-item", **legacy["items"][0]["prior_art"][0]}]
    standalone["tables"]["item_deps"] = [{"item_id": "sample-item", "needs_item": "dependency"}]
    standalone["events"] = [
        {
            "action": "create",
            "detail": {"item_id": "sample-item", "title": "A sample tracked item"},
        },
        {
            "action": "defer",
            "detail": {"item_id": "sample-item", "deferral_id": 9, "summary": "follow up"},
        },
        {"action": "dependency", "detail": {"item_id": "sample-item", "needs_item": "dependency"}},
    ]
    for table in shadow.TABLE_NAMES:
        if table != "items":
            legacy[table] = list(standalone["tables"][table])

    result = shadow.compare_snapshots(
        legacy,
        standalone,
        import_window=(
            datetime(2026, 7, 21, 13, 19, 40, tzinfo=timezone.utc),
            datetime(2026, 7, 21, 13, 20, 0, tzinfo=timezone.utc),
        ),
    )

    assert result["items"]["field_diffs"] == {}
    assert result["events"]["equal_provenance"] is True
    assert result["events"]["standalone_supplemental_actions"] == {"dependency": 1}
    assert result["events"]["supplemental_provenance_equal"] is True
    assert result["meta"]["equal"] is True
    assert result["passed"] is True


def test_comparison_rejects_dependency_event_detail_drift() -> None:
    legacy = {"items": [], "events": [], "meta": [], "item_deps": [{"item_id": "a", "needs_item": "b"}]}
    standalone = _standalone_envelope()
    standalone["tables"]["item_deps"] = [{"item_id": "a", "needs_item": "b"}]
    standalone["events"] = [{"action": "dependency", "detail": {"item_id": "a", "needs_item": "wrong-target"}}]
    result = shadow.compare_snapshots(legacy, standalone)
    assert result["events"]["supplemental_provenance_equal"] is False
    assert result["passed"] is False


def test_comparison_does_not_hide_durable_timestamp_drift() -> None:
    legacy = _legacy_snapshot()
    standalone = _standalone_envelope()
    standalone["tables"]["items"] = [
        {
            key: value
            for key, value in legacy["items"][0].items()
            if key
            not in {"work", "deps", "scope", "verifications", "preserves", "anti_patterns", "prior_art", "deferrals"}
        }
    ]
    standalone["tables"]["items"][0]["created_at"] = "2025-01-01T00:00:00Z"
    result = shadow.compare_snapshots(legacy, standalone)
    assert "sample-item" in result["items"]["field_diffs"]


def test_malformed_envelope_has_actionable_error() -> None:
    with pytest.raises(shadow.ShadowMigrationError, match="items table"):
        shadow.compare_snapshots({"items": [], "events": [], "meta": []}, {"tables": []})


def test_validate_target_rejects_export_sidecar(tmp_path: Path) -> None:
    target = tmp_path / "shadow.sqlite"
    target.with_suffix(".export.json").write_text("keep", encoding="utf-8")
    with pytest.raises(shadow.ShadowMigrationError, match="export path"):
        shadow.validate_target(target, benchbox_db=tmp_path / "benchbox.sqlite")


def test_validate_target_rejects_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "shadow.sqlite"
    target.write_text("existing", encoding="utf-8")
    with pytest.raises(shadow.ShadowMigrationError, match="must not already exist"):
        shadow.validate_target(target, benchbox_db=tmp_path / "benchbox.sqlite")


@pytest.mark.parametrize("protected_name", ["benchbox.sqlite"])
def test_validate_target_rejects_protected_databases(tmp_path: Path, protected_name: str) -> None:
    protected = tmp_path / protected_name
    with pytest.raises(shadow.ShadowMigrationError, match="protected tracker database"):
        shadow.validate_target(
            protected,
            benchbox_db=tmp_path / "benchbox.sqlite",
        )


def test_canonical_command_uses_only_locked_benchbox_project(tmp_path: Path) -> None:
    scripts_project = tmp_path / "_project" / "scripts"
    scripts_project.mkdir(parents=True)
    (scripts_project / "pyproject.toml").write_text("[project]\nname='scripts'\n", encoding="utf-8")
    (scripts_project / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    command = shadow._canonical_todo_command(tmp_path)

    assert command == ["uv", "run", "--project", str(scripts_project), "--locked", "--", "todo-db"]


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


def test_hosted_snapshot_is_bulk_complete_private_and_no_clobber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queried: list[str] = []

    def fake_rows(connection: object, table: str) -> list[dict]:
        queried.append(table)
        return [{"table": table}]

    monkeypatch.setattr(shadow, "_rows", fake_rows)
    output = tmp_path / "snapshot.json"
    counts = shadow.write_hosted_legacy_snapshot(object(), output)
    expected_tables = [
        "items",
        *[name for name in shadow.TABLE_NAMES if name != "items"],
        *shadow.FINDING_TABLE_NAMES,
        "events",
        "meta",
    ]
    assert queried == expected_tables
    assert counts == dict.fromkeys(expected_tables, 1)
    assert output.stat().st_mode & 0o777 == 0o600
    assert set(json.loads(output.read_text())) == set(expected_tables)
    with pytest.raises(shadow.ShadowMigrationError, match="must not already exist"):
        shadow.write_hosted_legacy_snapshot(object(), output)


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
        )
    assert not target.exists()


def test_failed_import_rolls_back_new_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    todo_dir = tmp_path / "TODO"
    done_dir = tmp_path / "DONE"
    todo_dir.mkdir()
    done_dir.mkdir()
    (todo_dir / "item.yaml").write_text("id: item\n", encoding="utf-8")
    target = tmp_path / "shadow.sqlite"

    monkeypatch.setattr(
        shadow, "legacy_snapshot", lambda connection: {"items": [{"id": "item"}], "events": [], "meta": []}
    )
    monkeypatch.setattr(shadow, "_canonical_todo_command", lambda _: ["uv", "run", "--", "todo-db"])

    def fake_run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        if "todo-db" in command and "init" in command:
            target.touch()
        if "todo-db" in command and "import-yaml" in command:
            raise shadow.ShadowMigrationError("simulated failed import")

    monkeypatch.setattr(shadow, "_run", fake_run)
    with pytest.raises(shadow.ShadowMigrationError, match="simulated failed import"):
        shadow.run_shadow(
            repo_root=tmp_path,
            todo_dir=todo_dir,
            done_dir=done_dir,
            target=target,
            report_path=tmp_path / "report.json",
        )
    assert not target.exists()
