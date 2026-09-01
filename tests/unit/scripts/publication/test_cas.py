from __future__ import annotations

import pytest

from scripts.publication.cas import CASController
from scripts.publication.manifest import (
    ArtifactEntry,
    BuildClosure,
    CorpusSummary,
    PublicationManifest,
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


def sample_artifacts(db_digest: str = "5" * 64) -> dict[str, ArtifactEntry]:
    return {
        "prose_site": ArtifactEntry(digest="1" * 64, size=1024, path="site/"),
        "api_docs": ArtifactEntry(digest="2" * 64, size=2048, path="docs/"),
        "explorer_app": ArtifactEntry(digest="3" * 64, size=4096, path="explorer/"),
        "publisher_bundle": ArtifactEntry(digest="4" * 64, size=8192, path="bundle/"),
        "corpus_database": ArtifactEntry(
            digest=db_digest,
            size=16384,
            path="data/db.sqlite",
            bundle_count=120,
            inventory_digest="6" * 64,
        ),
        "pages_assembly": ArtifactEntry(digest="7" * 64, size=32768, path="dist/"),
    }


def sample_corpus(count: int = 120) -> CorpusSummary:
    return CorpusSummary(
        bundle_count=count,
        inventory_sha256="8" * 64,
        read_model_sha256="9" * 64,
    )


def test_cas_genesis_transition():
    genesis = PublicationManifest(
        generation=1,
        parent_sha=None,
        parent_generation=None,
        source_commit="f" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(),
    )
    errors = CASController.validate_transition(None, genesis)
    assert errors == []


def test_cas_monotonic_successor():
    current = PublicationManifest(
        generation=1,
        parent_sha=None,
        parent_generation=None,
        source_commit="f" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(120),
    )
    current_head_sha = "a" * 40

    successor = PublicationManifest(
        generation=2,
        parent_sha=current_head_sha,
        parent_generation=1,
        source_commit="e" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(125),
    )

    errors = CASController.validate_transition(current, successor, expected_parent_sha=current_head_sha)
    assert errors == []


def test_cas_stale_parent_sha_rejection():
    current = PublicationManifest(
        generation=2,
        parent_sha="0" * 40,
        parent_generation=1,
        source_commit="f" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(120),
    )
    actual_head_sha = "a" * 40
    stale_parent_sha = "b" * 40

    stale_proposal = PublicationManifest(
        generation=3,
        parent_sha=stale_parent_sha,
        parent_generation=2,
        source_commit="e" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(125),
    )

    errors = CASController.validate_transition(current, stale_proposal, expected_parent_sha=actual_head_sha)
    assert any("parent_sha violation" in e for e in errors)


def test_cas_generation_gap_rejection():
    current = PublicationManifest(
        generation=1,
        parent_sha=None,
        parent_generation=None,
        source_commit="f" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(120),
    )
    head_sha = "a" * 40

    gap_proposal = PublicationManifest(
        generation=5,  # Jump from 1 to 5
        parent_sha=head_sha,
        parent_generation=4,
        source_commit="e" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(125),
    )

    errors = CASController.validate_transition(current, gap_proposal, expected_parent_sha=head_sha)
    assert any("CAS generation violation" in e for e in errors)


def test_is_value_only_diff():
    m1 = PublicationManifest(
        generation=1,
        parent_sha=None,
        parent_generation=None,
        source_commit="f" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts("5" * 64),
        corpus=sample_corpus(120),
    )
    m2 = PublicationManifest(
        generation=2,
        parent_sha="a" * 40,
        parent_generation=1,
        source_commit="e" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts("f" * 64),
        corpus=sample_corpus(125),
    )

    assert CASController.is_value_only_diff(m1, m2, ["publication/manifest.json"]) is True
    assert (
        CASController.is_value_only_diff(m1, m2, ["publication/manifest.json", ".github/workflows/docs.yml"]) is False
    )
    assert CASController.is_value_only_diff(m1, m2, ["scripts/publication/manifest.py"]) is False


def test_regenerate_stale_manifest():
    stale = PublicationManifest(
        generation=2,
        parent_sha="old" + "0" * 37,
        parent_generation=1,
        source_commit="e" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(125),
    )

    current_head = PublicationManifest(
        generation=3,
        parent_sha="mid" + "0" * 37,
        parent_generation=2,
        source_commit="d" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(130),
    )
    new_head_sha = "new" + "0" * 37

    rebound = CASController.regenerate_stale_manifest(stale, current_head, new_head_sha)
    assert rebound.generation == 4
    assert rebound.parent_sha == new_head_sha
    assert rebound.parent_generation == 3


def test_coalesce_corpus_promotions():
    base = PublicationManifest(
        generation=1,
        parent_sha=None,
        parent_generation=None,
        source_commit="f" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts(),
        corpus=sample_corpus(120),
    )
    base_sha = "base" + "0" * 36

    p1 = PublicationManifest(
        generation=2,
        parent_sha=base_sha,
        parent_generation=1,
        source_commit="e" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts("a" * 64),
        corpus=sample_corpus(121),
    )
    p2 = PublicationManifest(
        generation=3,
        parent_sha="p1" + "0" * 38,
        parent_generation=2,
        source_commit="d" * 40,
        source_branch="develop",
        build_closure=sample_closure(),
        artifacts=sample_artifacts("b" * 64),
        corpus=sample_corpus(122),
    )

    coalesced = CASController.coalesce_corpus_promotions(base, base_sha, [p1, p2])
    assert coalesced.generation == 2
    assert coalesced.parent_sha == base_sha
    assert coalesced.parent_generation == 1
    assert coalesced.corpus.bundle_count == 122
    assert coalesced.artifacts["corpus_database"].digest == "b" * 64
