from __future__ import annotations

import pytest

from scripts.publication.manifest import (
    ArtifactEntry,
    BuildClosure,
    CorpusSummary,
    PublicationManifest,
    deserialize_manifest,
    serialize_manifest,
    validate_manifest_dict,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def sample_closure() -> BuildClosure:
    return BuildClosure(
        os_image="ubuntu-24.04",
        python_version="3.12.13",
        node_version="20.18.0",
        uv_version="0.4.10",
        lockfile_sha256="a" * 64,
        workflow_sha="b" * 40,
        action_shas={"actions/checkout": "c" * 40},
        read_model_version="1.0.0",
    )


def sample_artifacts() -> dict[str, ArtifactEntry]:
    return {
        "prose_site": ArtifactEntry(digest="1" * 64, size=1024, path="site/"),
        "api_docs": ArtifactEntry(digest="2" * 64, size=2048, path="docs/"),
        "explorer_app": ArtifactEntry(digest="3" * 64, size=4096, path="explorer/"),
        "publisher_bundle": ArtifactEntry(digest="4" * 64, size=8192, path="bundle/"),
        "corpus_database": ArtifactEntry(
            digest="5" * 64,
            size=16384,
            path="data/db.sqlite",
            bundle_count=120,
            inventory_digest="6" * 64,
        ),
        "pages_assembly": ArtifactEntry(digest="7" * 64, size=32768, path="dist/"),
    }


def sample_corpus() -> CorpusSummary:
    return CorpusSummary(
        bundle_count=120,
        inventory_sha256="8" * 64,
        read_model_sha256="9" * 64,
    )


def test_valid_genesis_manifest():
    manifest = PublicationManifest(
        generation=1,
        parent_sha=None,
        parent_generation=None,
        source_commit="f" * 40,
        source_branch="develop",
        develop_sha="d" * 40,
        published_results_sha="c" * 40,
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(),
    )
    raw = manifest.to_dict()
    errors = validate_manifest_dict(raw)
    assert errors == []

    serialized = serialize_manifest(manifest)
    deserialized = deserialize_manifest(serialized)
    assert deserialized.generation == 1
    assert deserialized.parent_sha is None
    assert deserialized.source_commit == "f" * 40
    assert deserialized.develop_sha == "d" * 40
    assert deserialized.published_results_sha == "c" * 40
    assert deserialized.build_closure.python_version == "3.12.13"
    assert deserialized.artifacts["corpus_database"].bundle_count == 120


def test_valid_successor_manifest():
    manifest = PublicationManifest(
        generation=2,
        parent_sha="0" * 40,
        parent_generation=1,
        source_commit="e" * 40,
        source_branch="develop",
        develop_sha="d" * 40,
        published_results_sha="c" * 40,
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(),
    )
    errors = validate_manifest_dict(manifest.to_dict())
    assert errors == []
    digest = manifest.compute_digest()
    assert len(digest) == 64


def test_reject_invalid_generation_and_parent():
    # Generation 0 invalid
    m0 = PublicationManifest(
        generation=0,
        parent_sha=None,
        parent_generation=None,
        source_commit="f" * 40,
        source_branch="develop",
        develop_sha="d" * 40,
        published_results_sha="c" * 40,
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(),
    )
    errors = validate_manifest_dict(m0.to_dict())
    assert any("generation must be a positive integer" in e for e in errors)

    # Generation 2 with parent_sha None invalid
    m2_no_parent = PublicationManifest(
        generation=2,
        parent_sha=None,
        parent_generation=1,
        source_commit="f" * 40,
        source_branch="develop",
        develop_sha="d" * 40,
        published_results_sha="c" * 40,
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(),
    )
    errors = validate_manifest_dict(m2_no_parent.to_dict())
    assert any("parent_sha must be a 40-char hex string" in e for e in errors)

    # Generation 2 with mismatched parent_generation
    m2_bad_parent_gen = PublicationManifest(
        generation=2,
        parent_sha="0" * 40,
        parent_generation=0,
        source_commit="f" * 40,
        source_branch="develop",
        develop_sha="d" * 40,
        published_results_sha="c" * 40,
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(),
    )
    errors = validate_manifest_dict(m2_bad_parent_gen.to_dict())
    assert any("parent_generation must be 1" in e for e in errors)


def test_reject_incomplete_build_closure():
    raw = PublicationManifest(
        generation=1,
        parent_sha=None,
        parent_generation=None,
        source_commit="f" * 40,
        source_branch="develop",
        develop_sha="d" * 40,
        published_results_sha="c" * 40,
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(),
    ).to_dict()

    del raw["build_closure"]["lockfile_sha256"]
    errors = validate_manifest_dict(raw)
    assert any("missing required field: 'lockfile_sha256'" in e for e in errors)


def test_reject_missing_artifacts():
    raw = PublicationManifest(
        generation=1,
        parent_sha=None,
        parent_generation=None,
        source_commit="f" * 40,
        source_branch="develop",
        develop_sha="d" * 40,
        published_results_sha="c" * 40,
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(),
    ).to_dict()

    del raw["artifacts"]["corpus_database"]
    errors = validate_manifest_dict(raw)
    assert any("missing required entry: 'corpus_database'" in e for e in errors)


def test_reject_malformed_digests():
    raw = PublicationManifest(
        generation=1,
        parent_sha=None,
        parent_generation=None,
        source_commit="f" * 40,
        source_branch="develop",
        develop_sha="d" * 40,
        published_results_sha="c" * 40,
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(),
    ).to_dict()

    raw["artifacts"]["prose_site"]["digest"] = "invalid_digest"
    errors = validate_manifest_dict(raw)
    assert any("invalid digest" in e for e in errors)


def test_reject_manifest_with_only_source_commit():
    raw = PublicationManifest(
        generation=1,
        parent_sha=None,
        parent_generation=None,
        source_commit="f" * 40,
        source_branch="develop",
        develop_sha="d" * 40,
        published_results_sha="c" * 40,
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(),
    ).to_dict()
    del raw["published_results_sha"]
    del raw["develop_sha"]
    errors = validate_manifest_dict(raw)
    assert any("published_results_sha must be a 40-char hex string" in e for e in errors)
    assert any("develop_sha must be a 40-char hex string" in e for e in errors)
