"""Track-2 sampled JOB scaling strategy: locked semantics and prototype scope."""

from __future__ import annotations

import pytest

from benchbox.core.joinorder_sampled.sampler import (
    PERSON_CHILD_TABLES,
    TITLE_CHILD_TABLES,
    VERBATIM_TABLES,
    SampledManifest,
    keep_title_id,
    manifest_hash,
    scale_to_fraction,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_scale_factor_semantics_accepts_fractions():
    assert scale_to_fraction(1.0) == 1
    assert scale_to_fraction(0.5) == "1/2" or scale_to_fraction(0.5).numerator == 1
    assert scale_to_fraction(0.1).denominator == 10


def test_scale_factor_semantics_rejects_out_of_range():
    for bad in (0.0, -0.5, 1.5, 2.0):
        with pytest.raises(ValueError):
            scale_to_fraction(bad)


def test_keep_predicate_is_deterministic_and_exact():
    fraction = scale_to_fraction(0.5)
    kept = [i for i in range(1000) if keep_title_id(i, fraction)]
    assert len(kept) == 500
    assert kept == [i for i in range(1000) if keep_title_id(i, fraction)]


def test_keep_predicate_fraction_matches_scale():
    for scale in (0.1, 0.25, 0.5):
        fraction = scale_to_fraction(scale)
        kept = sum(1 for i in range(10000) if keep_title_id(i, fraction))
        assert kept == int(10000 * float(fraction))


def test_join_graph_covers_all_canonical_tables():
    import tomllib
    from pathlib import Path

    manifest_path = Path(__file__).resolve().parents[4] / "benchbox" / "core" / "joinorder" / "data_manifest.toml"
    tables = {t["name"] for t in tomllib.load(manifest_path.open("rb"))["tables"]}
    covered = set(TITLE_CHILD_TABLES) | set(PERSON_CHILD_TABLES) | set(VERBATIM_TABLES) | {"title"}
    assert covered == tables, f"uncovered: {tables - covered}, extra: {covered - tables}"


def test_derived_identity_never_claims_canonical():
    manifest = SampledManifest(scale_factor=0.5, kept_title_ids=1, total_title_ids=2)
    body = manifest.to_dict()
    assert body["derived_identity"] == "joinorder_sampled"
    assert body["derived_identity"] != "canonical_imdb"
    assert body["source_identity"] == "canonical_imdb"


def test_manifest_hash_stable():
    first = SampledManifest(scale_factor=0.5, kept_title_ids=10, total_title_ids=20)
    second = SampledManifest(scale_factor=0.5, kept_title_ids=10, total_title_ids=20)
    assert manifest_hash(first) == manifest_hash(second)
    other = SampledManifest(scale_factor=0.25, kept_title_ids=10, total_title_ids=20)
    assert manifest_hash(first) != manifest_hash(other)
