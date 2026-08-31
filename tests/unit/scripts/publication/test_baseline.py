from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

SCRIPT = Path(__file__).parents[4] / "scripts/publication/capture_baseline.py"
SPEC = importlib.util.spec_from_file_location("capture_baseline", SCRIPT)
assert SPEC and SPEC.loader
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


def blob(object_id: str, size: int = 12) -> dict:
    return {"mode": "100644", "type": "blob", "object_id": object_id, "size": size}


def valid_baseline() -> dict:
    trees = {
        "develop": {"results-data/bundles/a.json": blob("aaaa")},
        "published-results": {
            "results-data/bundles/a.json": blob("aaaa"),
            "results-data/bundles/archive.json": blob("bbbb", 34),
        },
        "release": {"results-data/bundles/a.json": blob("aaaa")},
    }
    accepted = baseline.accepted_objects(trees)
    return {
        "schema_version": 2,
        "branches": {
            "develop": {"sha": "dev"},
            "published-results": {"sha": "pub"},
            "release": {"sha": "abc"},
        },
        "workflow": {"head_sha": "abc"},
        "pages": {"deployment": {"state": "success"}},
        "corpus": {
            "path_semantics": "set union, never a target count",
            "branch_source_shas": {"develop": "dev", "published-results": "pub", "release": "abc"},
            "branch_objects": trees,
            "develop": {"file_count": 1, "bytes": 12},
            "published_results": {"file_count": 2, "bytes": 46},
            "release": {"file_count": 1, "bytes": 12},
            "accepted_path_union": ["results-data/bundles/a.json", "results-data/bundles/archive.json"],
            "accepted_path_union_count": 2,
            "accepted_objects": accepted,
            "conflicting_paths": [],
            "published_only_paths": ["results-data/bundles/archive.json"],
            "published_only_count": 1,
        },
        "freeze": {
            "destructive_corpus_rewrites": "blocked",
            "mirror_retirement": "blocked",
            "release_deploy_removal": "blocked",
            "incident_owner": "BenchBox maintainers",
        },
    }


def test_tree_objects_preserves_exact_object_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        baseline,
        "run_raw",
        lambda *args: (
            "100644 blob aaaa 12\tresults-data/bundles/a.json\0"
            "100644 blob bbbb 34\tresults-data/bundles/nested/archive.json\0"
        ),
    )

    assert baseline.tree_objects("captured-sha") == {
        "results-data/bundles/a.json": blob("aaaa"),
        "results-data/bundles/nested/archive.json": blob("bbbb", 34),
    }


def test_fetch_branch_sha_uses_fetch_head_not_remote_tracking_ref(monkeypatch) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str) -> str:
        commands.append(args)
        return "captured-sha" if args[:2] == ("git", "rev-parse") else ""

    monkeypatch.setattr(baseline, "run", fake_run)

    assert baseline.fetch_branch_sha("develop") == "captured-sha"
    assert commands == [
        ("git", "fetch", "--no-tags", "origin", "refs/heads/develop"),
        ("git", "rev-parse", "FETCH_HEAD"),
    ]


def test_accepted_objects_preserves_both_variants_for_same_path() -> None:
    trees = {
        "develop": {"results-data/bundles/a.json": blob("aaaa")},
        "published-results": {"results-data/bundles/a.json": blob("bbbb", 13)},
        "release": {},
    }

    assert baseline.accepted_objects(trees) == [
        {
            "path": "results-data/bundles/a.json",
            "variants": [
                {**blob("aaaa"), "branches": ["develop"]},
                {**blob("bbbb", 13), "branches": ["published-results"]},
            ],
        }
    ]


def test_current_deployment_rejects_stale_success_with_newer_inactive_status(monkeypatch) -> None:
    deployments = [
        {"id": 2, "ref": "release", "created_at": "2026-08-31T20:00:00Z"},
        {"id": 1, "ref": "release", "created_at": "2026-08-31T19:00:00Z"},
    ]
    statuses = {
        2: [
            {"state": "inactive", "created_at": "2026-08-31T20:02:00Z"},
            {"state": "success", "created_at": "2026-08-31T20:01:00Z"},
        ],
        1: [{"state": "success", "created_at": "2026-08-31T19:01:00Z"}],
    }
    monkeypatch.setattr(baseline, "gh", lambda path: statuses[int(path.split("/")[4])])

    deployment, status = baseline.current_successful_deployment(deployments)

    assert deployment["id"] == 1
    assert status["state"] == "success"


def test_validation_accepts_exact_set_and_object_identity() -> None:
    assert baseline.validate(valid_baseline()) == []


def test_validation_rejects_legacy_schema() -> None:
    data = valid_baseline()
    data["schema_version"] = 1

    assert "publication baseline schema version must be 2" in baseline.validate(data)


def test_validation_rejects_union_that_is_not_exact() -> None:
    data = valid_baseline()
    data["corpus"]["accepted_path_union"] = ["results-data/bundles/a.json"]
    data["corpus"]["accepted_path_union_count"] = 1

    assert "accepted path union must exactly match develop and published-results branch objects" in baseline.validate(
        data
    )


def test_validation_rejects_branch_inventory_source_sha_drift() -> None:
    data = valid_baseline()
    data["corpus"]["branch_source_shas"]["develop"] = "stale"

    assert "corpus branch inventories must identify their exact captured source SHAs" in baseline.validate(data)


def test_validation_rejects_published_only_difference_drift() -> None:
    data = valid_baseline()
    data["corpus"]["published_only_paths"] = []
    data["corpus"]["published_only_count"] = 0

    assert "published-only paths must exactly match the published-results branch difference" in baseline.validate(data)


def test_validation_rejects_object_inventory_drift() -> None:
    data = valid_baseline()
    data["corpus"]["accepted_objects"][0]["variants"][0]["object_id"] = "wrong"

    assert "accepted object inventory must preserve every branch object identity" in baseline.validate(data)


def test_validation_rejects_count_and_byte_drift() -> None:
    data = valid_baseline()
    data["corpus"]["accepted_path_union_count"] = 3
    data["corpus"]["develop"]["bytes"] = 99

    errors = baseline.validate(data)
    assert "accepted path union count does not match the accepted paths" in errors
    assert "develop byte count does not match its branch objects" in errors


def test_validation_rejects_unsupported_object_mode() -> None:
    data = valid_baseline()
    data["corpus"]["branch_objects"]["develop"]["results-data/bundles/a.json"]["mode"] = "100755"

    assert any("develop object identity is invalid" in error for error in baseline.validate(data))


def test_validation_rejects_count_as_migration_target() -> None:
    data = valid_baseline()
    data["corpus"]["path_semantics"] = "expected count: 2"

    assert "corpus inventory must declare set-union semantics" in baseline.validate(data)


def test_validation_requires_all_destructive_surfaces_frozen() -> None:
    data = valid_baseline()
    data["freeze"]["mirror_retirement"] = "allowed"

    assert "all destructive migration surfaces must remain blocked" in baseline.validate(data)
