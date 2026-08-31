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


def valid_baseline() -> dict:
    return {
        "branches": {"release": {"sha": "abc"}},
        "workflow": {"head_sha": "abc"},
        "pages": {"deployment": {"state": "success"}},
        "corpus": {
            "path_semantics": "set union, never a target count",
            "accepted_path_union": ["results-data/bundles/a.json", "results-data/bundles/archive.json"],
            "published_only_paths": ["results-data/bundles/archive.json"],
        },
        "freeze": {
            "destructive_corpus_rewrites": "blocked",
            "mirror_retirement": "blocked",
            "release_deploy_removal": "blocked",
            "incident_owner": "BenchBox maintainers",
        },
    }


def test_tree_paths_preserves_exact_paths_and_sizes(monkeypatch) -> None:
    monkeypatch.setattr(
        baseline,
        "run",
        lambda *args: (
            "100644 blob aaaa 12\tresults-data/bundles/a.json\n"
            "100644 blob bbbb 34\tresults-data/bundles/nested/archive.json"
        ),
    )

    assert baseline.tree_paths("origin/published-results") == {
        "results-data/bundles/a.json": 12,
        "results-data/bundles/nested/archive.json": 34,
    }


def test_validation_accepts_published_only_subset_without_count_target() -> None:
    assert baseline.validate(valid_baseline()) == []


def test_validation_rejects_published_only_path_missing_from_union() -> None:
    data = valid_baseline()
    data["corpus"]["accepted_path_union"] = ["results-data/bundles/a.json"]

    assert "published-only paths must be contained in the accepted union" in baseline.validate(data)


def test_validation_rejects_count_as_migration_target() -> None:
    data = valid_baseline()
    data["corpus"]["path_semantics"] = "expected count: 2"

    assert "corpus inventory must declare set-union semantics" in baseline.validate(data)


def test_validation_requires_all_destructive_surfaces_frozen() -> None:
    data = valid_baseline()
    data["freeze"]["mirror_retirement"] = "allowed"

    assert "all destructive migration surfaces must remain blocked" in baseline.validate(data)
