"""Track-2 sampled JOB scaling strategy: locked semantics and prototype scope."""

from __future__ import annotations

from fractions import Fraction

import pytest

from benchbox.core.joinorder_sampled.sampler import (
    MOVIE_LINK_ENDPOINTS,
    MOVIE_LINK_TABLE,
    PERSON_CHILD_TABLES,
    TITLE_CHILD_TABLES,
    VERBATIM_TABLES,
    SampledManifest,
    close_title_set_over_episode_parents,
    keep_movie_link_row,
    keep_title_child_row,
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


def test_scale_factor_rejects_values_rounded_into_range():
    with pytest.raises(ValueError):
        scale_to_fraction(1.0001)
    with pytest.raises(ValueError):
        scale_to_fraction(0.0001)
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            scale_to_fraction(bad)


def test_scale_factor_accepts_exact_fraction_input():
    assert scale_to_fraction(Fraction(1, 4)) == Fraction(1, 4)


def test_movie_link_requires_both_endpoints():
    assert MOVIE_LINK_TABLE == "movie_link"
    assert MOVIE_LINK_ENDPOINTS == ("movie_id", "linked_movie_id")
    assert MOVIE_LINK_TABLE not in TITLE_CHILD_TABLES
    kept = {1, 2}
    assert keep_movie_link_row({"movie_id": 1, "linked_movie_id": 2}, kept)
    assert not keep_movie_link_row({"movie_id": 1, "linked_movie_id": 3}, kept)
    assert not keep_movie_link_row({"movie_id": 3, "linked_movie_id": 2}, kept)
    assert not keep_movie_link_row({"movie_id": 1, "linked_movie_id": None}, kept)


def test_single_key_child_row_survives_on_movie_id():
    assert keep_title_child_row({"movie_id": 1}, {1, 2}, TITLE_CHILD_TABLES["cast_info"])
    assert not keep_title_child_row({"movie_id": 3}, {1, 2}, TITLE_CHILD_TABLES["cast_info"])


def test_episode_parent_closure_retains_series_title():
    kept = close_title_set_over_episode_parents({10}, {10: 1, 11: 2})
    assert kept == {10, 1}
    assert close_title_set_over_episode_parents({10}, {10: None}) == {10}


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
    covered = set(TITLE_CHILD_TABLES) | {MOVIE_LINK_TABLE} | set(PERSON_CHILD_TABLES) | set(VERBATIM_TABLES) | {"title"}
    assert covered == tables, f"uncovered: {tables - covered}, extra: {covered - tables}"


def test_derived_identity_never_claims_canonical():
    manifest = SampledManifest(scale_factor=0.5, kept_title_ids=1, total_title_ids=2)
    body = manifest.to_dict()
    assert body["derived_identity"] == "joinorder_sampled"
    assert body["derived_identity"] != "canonical_imdb"
    assert body["source_identity"] == "canonical_imdb"


def test_manifest_binds_exact_source_archive():
    manifest = SampledManifest(
        scale_factor=0.5,
        kept_title_ids=10,
        total_title_ids=20,
        source_dataset_version="joinorder-imdb-2013-v1",
        source_manifest_hash="abc123",
        source_data_archive_hash="def456",
    )
    body = manifest.to_dict()
    assert body["source_dataset_version"] == "joinorder-imdb-2013-v1"
    assert body["source_manifest_hash"] == "abc123"
    assert body["source_data_archive_hash"] == "def456"
    rebound = SampledManifest(scale_factor=0.5, kept_title_ids=10, total_title_ids=20)
    assert manifest_hash(manifest) != manifest_hash(rebound)


def test_manifest_hash_stable():
    first = SampledManifest(scale_factor=0.5, kept_title_ids=10, total_title_ids=20)
    second = SampledManifest(scale_factor=0.5, kept_title_ids=10, total_title_ids=20)
    assert manifest_hash(first) == manifest_hash(second)
    other = SampledManifest(scale_factor=0.25, kept_title_ids=10, total_title_ids=20)
    assert manifest_hash(first) != manifest_hash(other)
