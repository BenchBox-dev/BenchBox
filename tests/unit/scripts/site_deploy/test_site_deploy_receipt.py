from __future__ import annotations

import copy

import pytest

from scripts.site_deploy import receipt as r
from tests.unit.scripts.site_deploy.site_deploy_fakes import SHA_A, make_receipt

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_receipt_records_every_required_field() -> None:
    built = make_receipt(run_id=5, trunk=SHA_A)
    assert r.validate_receipt(built) is built
    assert built["schema"] == "site-deploy-receipt/v1"
    for key in ("deployment_id", "run_id", "routes", "corpus_sha", "parent", "gates", "probes", "artifact"):
        assert key in built
    assert built["artifact"]["sha256"] == "f" * 64
    assert built["gates"]["results"] == {"privacy": "pass"}
    assert len(built["rollback_order"]) == 3


def test_generation_follows_the_parent() -> None:
    parent = {"generation": 6}
    child = make_receipt(run_id=2, trunk=SHA_A, parent=parent)
    assert child["generation"] == 1
    from_builder = r.build_receipt(
        mode="deploy",
        target="github-pages",
        run_id=9,
        deployment_id=1,
        trunk_sha=SHA_A,
        release_tag="v0.4.1",
        release_sha=SHA_A,
        corpus_sha=SHA_A,
        assembly={"routes": [], "tree_sha256": "a" * 64, "total_bytes": 1, "total_files": 1},
        artifact_name="x",
        versions={},
        gates={"ok": True, "results": {}},
        probes={"ok": True},
        parent=parent,
        certifying_run_id=None,
    )
    assert from_builder["generation"] == 7


def test_status_description_round_trips_and_stays_within_the_github_limit() -> None:
    sha = "ab" * 32
    description = r.status_description(sha, 123456789012)
    assert len(description) <= 140
    assert r.parse_status_description(description) == (sha, 123456789012)
    assert r.parse_status_description("legacy deploy") is None
    assert r.parse_status_description(description + " ") is None


def test_canonical_bytes_are_stable_and_hash_matches() -> None:
    built = make_receipt(run_id=5, trunk=SHA_A)
    assert r.canonical_bytes(built) == r.canonical_bytes(copy.deepcopy(built))
    assert len(r.receipt_sha256(r.canonical_bytes(built))) == 64


def test_validation_rejects_every_missing_required_key() -> None:
    for key in r.REQUIRED_KEYS:
        broken = make_receipt(run_id=1, trunk=SHA_A)
        broken.pop(key)
        with pytest.raises(r.ReceiptError):
            r.validate_receipt(broken)


def test_validation_rejects_bad_digest_schema_and_shas() -> None:
    for mutate in (
        lambda d: d.update(schema="other"),
        lambda d: d["artifact"].update(sha256="short"),
        lambda d: d.update(trunk_sha="abc"),
        lambda d: d.update(generation=0),
        lambda d: d["probes"].pop("ok"),
    ):
        broken = make_receipt(run_id=1, trunk=SHA_A)
        mutate(broken)
        with pytest.raises(r.ReceiptError):
            r.validate_receipt(broken)


def test_last_known_good_requires_passing_probes_gates_and_matching_target() -> None:
    good = make_receipt(run_id=1, trunk=SHA_A)
    assert r.is_last_known_good(good)
    assert not r.is_last_known_good(make_receipt(run_id=1, trunk=SHA_A, probes_ok=False))
    assert not r.is_last_known_good(good, target="local-dir")
    bad_gates = make_receipt(run_id=1, trunk=SHA_A)
    bad_gates["gates"]["ok"] = False
    assert not r.is_last_known_good(bad_gates)


def test_receipt_records_the_explorer_digest_apart_from_the_site_artifact() -> None:
    lane = {"/results/:results": "e" * 64}
    routes = [
        {"path": "/", "builder": "landing", "source_sha": SHA_A, "lane_sha256": {"/:.": "1" * 64}},
        {
            "path": "/results/",
            "builder": "explorer",
            "source_sha": SHA_A,
            "corpus": "results-data",
            "lane_sha256": lane,
        },
    ]
    built = r.build_receipt(
        mode="deploy",
        target="github-pages",
        run_id=9,
        deployment_id=1,
        trunk_sha=SHA_A,
        release_tag="v0.4.1",
        release_sha=SHA_A,
        corpus_sha=SHA_A,
        assembly={"routes": routes, "tree_sha256": "a" * 64, "total_bytes": 1, "total_files": 1},
        artifact_name="x",
        versions={},
        gates={"ok": True, "results": {}},
        probes={"ok": True},
        parent=None,
        certifying_run_id=None,
    )
    assert built["explorer"] == {
        "path": "/results/",
        "source_sha": SHA_A,
        "corpus": "results-data",
        "sha256": "e" * 64,
        "lane_sha256": lane,
    }
    assert built["explorer"]["sha256"] != built["artifact"]["sha256"]
    assert r.validate_receipt(built) is built


def test_receipt_without_an_explorer_route_records_none() -> None:
    assert r.explorer_artifact([{"path": "/", "builder": "landing"}]) is None
