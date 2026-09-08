from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.publication.assembler import compute_tree_digest
from scripts.publication.candidate import (
    CandidateValidationError,
    create_candidate_metadata,
    extract_candidate_archive,
    manifest_digest,
    validate_candidate_directory,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _manifest(site: Path) -> dict:
    tree_digest, size, _ = compute_tree_digest(site)
    checksums = {
        "/": hashlib.sha256((site / "index.html").read_bytes()).hexdigest(),
        "/docs/": hashlib.sha256((site / "docs/index.html").read_bytes()).hexdigest(),
        "/docs/api.html": hashlib.sha256((site / "docs/api.html").read_bytes()).hexdigest(),
        "/results/": hashlib.sha256((site / "results/index.html").read_bytes()).hexdigest(),
        "/results/data/results.duckdb": hashlib.sha256((site / "results/data/results.duckdb").read_bytes()).hexdigest(),
    }
    sha40 = "a" * 40
    sha64 = "b" * 64
    data = {
        "schema_version": 2,
        "target": "benchbox.dev",
        "generation": 1,
        "parent_sha": None,
        "parent_generation": None,
        "source_commit": sha40,
        "source_branch": "develop",
        "develop_sha": sha40,
        "published_results_sha": "c" * 40,
        "created_at": "2026-09-08T00:00:00Z",
        "build_closure": {
            "os_image": "ubuntu",
            "python_version": "3.12",
            "node_version": "20",
            "uv_version": "0.8",
            "lockfile_sha256": sha64,
            "workflow_sha": sha40,
            "action_shas": {"checkout": sha40},
            "read_model_version": "test",
        },
        "artifacts": {
            name: {"digest": sha64, "size": size, "path": path}
            for name, path in (
                ("prose_site", "/"),
                ("api_docs", "/docs/api.html"),
                ("explorer_app", "/results/"),
                ("publisher_bundle", "/"),
                ("corpus_database", "/results/data/results.duckdb"),
                ("pages_assembly", "/"),
            )
        },
        "corpus": {"bundle_count": 1, "inventory_sha256": sha64, "read_model_sha256": sha64},
        "checksums": checksums,
    }
    data["artifacts"]["pages_assembly"]["digest"] = tree_digest
    data["manifest_digest"] = manifest_digest(data)
    return data


def _bundle(tmp_path: Path) -> tuple[Path, dict, dict, dict]:
    site = tmp_path / "site"
    for relative, content in {
        "index.html": b"home",
        "docs/index.html": b"docs",
        "docs/api.html": b"api",
        "results/index.html": b"results",
        "results/data/results.duckdb": b"duckdb",
    }.items():
        path = site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = _manifest(site)
    manifest_path = tmp_path / "desired-manifest.json"
    assembly_path = tmp_path / "assembly-receipt.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assembly_path.write_text(
        json.dumps({"candidate_mode": "candidate-only", "artifact_run_id": "123"}), encoding="utf-8"
    )
    candidate = tmp_path / "candidate.json"
    create_candidate_metadata(
        manifest_path,
        assembly_path,
        site,
        artifact_id=None,
        producer_run_id="123",
        output=candidate,
    )
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "site").symlink_to(site, target_is_directory=True)
    # The validator reads an extracted archive, so package real files.
    (root / "site").unlink()
    import shutil

    shutil.copytree(site, root / "site")
    for name, source in (
        ("candidate.json", candidate),
        ("desired-manifest.json", manifest_path),
        ("assembly-receipt.json", assembly_path),
    ):
        (root / name).write_bytes(source.read_bytes())
    artifact_metadata = {"id": 456, "expired": False, "workflow_run": {"id": 123}}
    run_metadata = {
        "id": 123,
        "status": "completed",
        "conclusion": "success",
        "event": "workflow_dispatch",
        "head_branch": "develop",
        "head_sha": "a" * 40,
        "name": "Publication Control Plane Deployment",
        "path": ".github/workflows/publication-deploy.yml",
    }
    return root, artifact_metadata, run_metadata, manifest


def test_candidate_provenance_and_complete_routes_are_validated(tmp_path: Path) -> None:
    root, artifact_metadata, run_metadata, manifest = _bundle(tmp_path)
    summary = validate_candidate_directory(
        root,
        artifact_id=456,
        artifact_metadata=artifact_metadata,
        run_metadata=run_metadata,
        expected_develop_sha=manifest["develop_sha"],
        expected_published_results_sha=manifest["published_results_sha"],
    )
    assert summary.site_tree_sha256 == manifest["artifacts"]["pages_assembly"]["digest"]
    assert set(summary.route_checksums) >= {
        "/",
        "/docs/",
        "/docs/api.html",
        "/results/",
        "/results/data/results.duckdb",
    }


@pytest.mark.parametrize(
    "mutation",
    ["missing_route", "wrong_producer", "expired", "stale_source"],
)
def test_candidate_rejects_untrusted_or_incomplete_selection(tmp_path: Path, mutation: str) -> None:
    root, artifact_metadata, run_metadata, manifest = _bundle(tmp_path)
    if mutation == "missing_route":
        manifest["checksums"].pop("/results/")
        (root / "desired-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    elif mutation == "wrong_producer":
        run_metadata["name"] = "Other workflow"
    elif mutation == "expired":
        artifact_metadata["expired"] = True
    else:
        manifest["develop_sha"] = "d" * 40
        (root / "desired-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CandidateValidationError):
        validate_candidate_directory(
            root,
            artifact_id=456,
            artifact_metadata=artifact_metadata,
            run_metadata=run_metadata,
            expected_develop_sha="a" * 40,
            expected_published_results_sha="c" * 40,
        )


def test_candidate_archive_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape", "bad")
    with pytest.raises(CandidateValidationError, match="unsafe path"):
        extract_candidate_archive(archive, tmp_path / "out")


def test_candidate_rejects_missing_producer_head(tmp_path: Path) -> None:
    root, artifact_metadata, run_metadata, manifest = _bundle(tmp_path)
    run_metadata.pop("head_sha")

    with pytest.raises(CandidateValidationError, match="producer head SHA"):
        validate_candidate_directory(
            root,
            artifact_id=456,
            artifact_metadata=artifact_metadata,
            run_metadata=run_metadata,
            expected_develop_sha=manifest["develop_sha"],
        )


def test_candidate_rejects_route_metadata_substitution(tmp_path: Path) -> None:
    root, artifact_metadata, run_metadata, manifest = _bundle(tmp_path)
    metadata = json.loads((root / "candidate.json").read_text(encoding="utf-8"))
    metadata["route_checksums"]["/"] = "0" * 64
    (root / "candidate.json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(CandidateValidationError, match="route checksums"):
        validate_candidate_directory(
            root,
            artifact_id=456,
            artifact_metadata=artifact_metadata,
            run_metadata=run_metadata,
            expected_develop_sha=manifest["develop_sha"],
        )
