"""Replicated-IMDB prototype: offset math, identity, and oracle scaling."""

from __future__ import annotations

import pytest

from benchbox.core.joinorder_replicated.replicator import (
    DERIVED_IDENTITY,
    KEY_COLUMNS,
    LOOKUP_FK_COLUMNS,
    LOOKUP_TABLES,
    REPLICATED_TABLES,
    REQUIRES_REAPPROVAL,
    SOURCE_IDENTITY,
    ReplicatedManifest,
    expected_row_count,
    expected_table_row_count,
    manifest_hash,
    replica_offset,
    shifted_key,
    validate_scale_factor,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_scale_factor_accepts_integers():
    assert validate_scale_factor(1) == 1
    assert validate_scale_factor(3) == 3


def test_scale_factor_rejects_non_integers_and_zero():
    for bad in (0, -1, 1.5, "2", True, None):
        with pytest.raises(ValueError):
            validate_scale_factor(bad)


def test_replica_zero_is_identity():
    assert replica_offset(0, 1_000_000) == 0
    assert shifted_key(42, replica=0, key_space=1_000_000) == 42


def test_replica_offsets_are_disjoint():
    key_space = 40_000_000
    first = shifted_key(36_244_344, replica=1, key_space=key_space)
    assert first == 36_244_344 + key_space
    assert shifted_key(36_244_344, replica=2, key_space=key_space) == 36_244_344 + 2 * key_space


def test_null_keys_pass_through():
    assert shifted_key(None, replica=1, key_space=100) is None


def test_offset_rejects_bad_inputs():
    with pytest.raises(ValueError):
        replica_offset(-1, 100)
    with pytest.raises(ValueError):
        replica_offset(1, 0)


def test_row_counts_scale_exactly():
    assert expected_row_count(2_528_312, 1) == 2_528_312
    assert expected_row_count(2_528_312, 3) == 2_528_312 * 3


def test_key_columns_cover_all_canonical_tables():
    import tomllib
    from pathlib import Path

    manifest_path = Path(__file__).resolve().parents[4] / "benchbox" / "core" / "joinorder" / "data_manifest.toml"
    tables = {t["name"] for t in tomllib.load(manifest_path.open("rb"))["tables"]}
    keyed = {table for table, _ in KEY_COLUMNS} | set(LOOKUP_TABLES)
    assert keyed == tables, f"uncovered: {tables - keyed}"


def test_key_columns_are_integer_columns_per_committed_manifest():
    import tomllib
    from pathlib import Path

    manifest_path = Path(__file__).resolve().parents[4] / "benchbox" / "core" / "joinorder" / "data_manifest.toml"
    schemas = {t["name"]: t.get("schema", {}) for t in tomllib.load(manifest_path.open("rb"))["tables"]}
    missing = [
        f"{table}.{column}"
        for table, column in KEY_COLUMNS
        if schemas.get(table, {}).get(column, "").upper() != "INTEGER"
    ]
    assert not missing, f"non-integer or missing key columns: {missing}"


def test_lookup_tables_stay_single_copy():
    assert set(LOOKUP_TABLES) == {
        "company_type",
        "comp_cast_type",
        "info_type",
        "kind_type",
        "link_type",
        "role_type",
    }
    assert set(REPLICATED_TABLES).isdisjoint(LOOKUP_TABLES)
    for lookup in LOOKUP_TABLES:
        assert expected_table_row_count(lookup, 4, 3) == 4
    assert expected_table_row_count("title", 2_528_312, 3) == 2_528_312 * 3


def test_lookup_fk_values_never_shift():
    lookup_pairs = {(table, column) for table, column, _ in LOOKUP_FK_COLUMNS}
    keyed_pairs = set(KEY_COLUMNS)
    assert lookup_pairs.isdisjoint(keyed_pairs), f"lookup FKs must not shift: {lookup_pairs & keyed_pairs}"
    for table, _, _ in LOOKUP_FK_COLUMNS:
        assert table in REPLICATED_TABLES
    # Spot-check the contract's headline example: every replica references
    # the same company_type IDs.
    assert ("movie_companies", "company_type_id", "company_type") in LOOKUP_FK_COLUMNS


def test_prototype_stays_deferred_until_reapproval():
    import re
    from pathlib import Path

    assert REQUIRES_REAPPROVAL is True
    repo_root = Path(__file__).resolve().parents[4]
    decision = repo_root / "_project" / "decisions" / "joinorder-track2-scaling-direction-2026-07-04.md"
    assert "must not start unless a future decision re-approves an upward" in decision.read_text(encoding="utf-8")
    registry = repo_root / "benchbox" / "__init__.py"
    assert "joinorder_replicated" not in registry.read_text(encoding="utf-8")
    loader = (repo_root / "benchbox" / "core" / "benchmark_loader.py").read_text(encoding="utf-8")
    assert not re.search(r'"joinorder_replicated"|\'joinorder_replicated\'', loader)


def test_derived_identity_never_claims_canonical():
    manifest = ReplicatedManifest(scale_factor=2)
    body = manifest.to_dict()
    assert body["derived_identity"] == DERIVED_IDENTITY == "replicated_imdb"
    assert body["source_identity"] == SOURCE_IDENTITY == "canonical_imdb"
    assert body["derived_identity"] != "canonical_imdb"


def test_manifest_hash_stable():
    first = ReplicatedManifest(scale_factor=2, source_archive_hash="abc")
    second = ReplicatedManifest(scale_factor=2, source_archive_hash="abc")
    assert manifest_hash(first) == manifest_hash(second)
    other = ReplicatedManifest(scale_factor=3, source_archive_hash="abc")
    assert manifest_hash(first) != manifest_hash(other)


def test_expected_cardinality_scaling_against_oracle():
    import json
    from pathlib import Path

    oracle_path = Path(__file__).resolve().parents[4] / "_project" / "joinorder" / "reference_cardinalities.json"
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    assert len(oracle["queries"]) == 113
    # Replication preserves predicate values, so every query's underlying
    # row count scales by exactly the factor: prove the invariant on the
    # oracle shape.
    for scale in (2, 3):
        for query_id, payload in list(oracle["queries"].items())[:5]:
            count = payload["underlying_row_count"]
            assert expected_row_count(count, scale) == count * scale
