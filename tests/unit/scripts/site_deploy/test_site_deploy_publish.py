from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from scripts.publication.assembler import compute_tree_digest
from scripts.site_deploy import artifacts, checksums, deployments, parity, probe, publish, receipt, rollback
from tests.unit.scripts.site_deploy.site_deploy_fakes import SHA_A, FakeGitHub, make_receipt

pytestmark = [pytest.mark.unit, pytest.mark.medium]

ROUTES = ["/", "/docs/", "/docs/dev/", "/blog/", "/results/"]
FALLBACK = "<script>window.sessionStorage.setItem('benchbox.results.redirect', 1)</script>"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _site(root: Path, label: str, *, dev: bool) -> Path:
    _write(root / "index.html", f"{label} landing")
    _write(root / "docs" / "index.html", f"{label} docs")
    _write(root / "docs" / "guide.html", f"{label} guide")
    _write(root / "blog" / "index.html", f"{label} blog")
    _write(root / "results" / "index.html", f"{label} explorer")
    _write(root / "results" / "data" / "results.duckdb", f"{label} snapshot")
    _write(root / "404.html", FALLBACK)
    _write(root / ".nojekyll", "")
    if dev:
        _write(root / "docs" / "dev" / "index.html", f"{label} dev docs")
    return root


def _fetch(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_checksum_manifest_maps_served_urls_to_file_hashes(tmp_path: Path) -> None:
    site = _site(tmp_path / "site", "b", dev=True)
    manifest = checksums.checksum_manifest(site, ROUTES)
    _, _, files = compute_tree_digest(site)
    assert manifest["/"] == files["index.html"]
    assert manifest["/docs/dev/"] == files["docs/dev/index.html"]
    assert manifest["/results/data/results.duckdb"] == files["results/data/results.duckdb"]
    assert "/docs/guide.html" in manifest


def test_checksum_manifest_fails_when_a_route_is_not_served(tmp_path: Path) -> None:
    site = _site(tmp_path / "site", "a", dev=False)
    with pytest.raises(ValueError, match="/docs/dev/"):
        checksums.checksum_manifest(site, ROUTES)


def test_local_target_emulates_pages_index_redirect_and_404_fallback(tmp_path: Path) -> None:
    site = _site(tmp_path / "site", "b", dev=True)
    with publish.running_target(tmp_path / "slot") as target:
        target.publish(site)
        assert _fetch(target.base_url + "/") == (200, b"b landing")
        assert _fetch(target.base_url + "/docs/") == (200, b"b docs")
        assert _fetch(target.base_url + "/docs/guide") == (200, b"b guide")
        status, body = _fetch(target.base_url + "/results/deep/link")
        assert status == 404
        assert b"benchbox.results.redirect" in body
        assert _fetch(target.base_url + "/../../etc/passwd")[0] == 404


def test_probe_matches_served_bytes_and_flags_a_changed_route(tmp_path: Path) -> None:
    site = _site(tmp_path / "site", "b", dev=True)
    manifest = checksums.checksum_manifest(site, ROUTES)
    with publish.running_target(tmp_path / "slot") as target:
        target.publish(site)
        good = probe.probe(target.base_url, manifest, tmp_path / "probe", attempts=1, delay=0)
        assert good["ok"] is True
        assert good["matched"] == len(manifest)
        assert good["deep_link"]["ok"] is True
        (target.slot_dir / "docs" / "index.html").write_text("tampered", encoding="utf-8")
        bad = probe.probe(target.base_url, manifest, tmp_path / "probe2", attempts=2, delay=0, sleep=lambda _: None)
        assert bad["ok"] is False
        assert "/docs/" in bad["mismatched"]
        assert bad["attempts"] == 2


def test_probe_fails_when_the_target_is_unreachable(tmp_path: Path) -> None:
    result = probe.probe("http://127.0.0.1:9", {"/": "a" * 64}, tmp_path, attempts=1, delay=0, timeout=1)
    assert result["ok"] is False


def _drill(tmp_path: Path) -> dict:
    legacy = _site(tmp_path / "legacy", "a", dev=False)
    routes = _site(tmp_path / "routes", "b", dev=True)
    digest, size, manifest = compute_tree_digest(routes)
    assembly = {
        "routes": [{"path": path, "source_sha": SHA_A} for path in ROUTES],
        "tree_sha256": digest,
        "total_bytes": size,
        "total_files": len(manifest),
    }
    return publish.run_drill(
        legacy_tree=legacy,
        routes_tree=routes,
        route_paths=ROUTES,
        trunk_sha=SHA_A,
        release_tag="v0.4.1",
        release_sha=SHA_A,
        corpus_sha="1" * 40,
        routes_assembly=assembly,
        versions={"ui_expected": 11, "snapshot": 11},
        gates={"ok": True, "results": {"privacy": {"status": "pass"}}},
        work_dir=tmp_path / "work",
        receipts_dir=tmp_path / "receipts",
    )


def test_rollback_drill_restores_the_exact_first_generation(tmp_path: Path) -> None:
    drill = _drill(tmp_path)
    assert drill["ok"] is True
    assert drill["restored_digest_equals_a"] is True
    assert [step["step"] for step in drill["steps"]] == [
        "publish A (legacy single-ref assembly)",
        "publish B (route build)",
        "rollback to A by receipt",
    ]
    assert drill["steps"][0]["tree_sha256"] == drill["steps"][2]["tree_sha256"] != drill["steps"][1]["tree_sha256"]
    names = sorted(path.name for path in (tmp_path / "receipts").iterdir())
    assert names == ["receipt-a.json", "receipt-b.json", "receipt-rollback.json"]
    rollback_receipt = json.loads((tmp_path / "receipts" / "receipt-rollback.json").read_text(encoding="utf-8"))
    assert rollback_receipt["mode"] == "rollback"
    assert rollback_receipt["parent"]["generation"] == 2
    assert rollback_receipt["rollback"]["phase"] == "full"
    b_receipt = json.loads((tmp_path / "receipts" / "receipt-b.json").read_text(encoding="utf-8"))
    assert b_receipt["parent"]["run_id"] == 1


def test_load_restore_verifies_the_artifact_against_the_receipt(tmp_path: Path) -> None:
    site = _site(tmp_path / "site", "a", dev=False)
    digest, _, _ = compute_tree_digest(site)
    built = make_receipt(run_id=3, trunk=SHA_A)
    built["artifact"]["sha256"] = digest
    built["target"] = "local-dir"
    path = tmp_path / "receipt.json"
    path.write_bytes(receipt.canonical_bytes(built))
    restored = rollback.load_restore(path, site, target="local-dir")
    assert restored.receipt["run_id"] == 3
    (site / "docs" / "index.html").write_text("changed", encoding="utf-8")
    with pytest.raises(rollback.RollbackError, match="does not match"):
        rollback.load_restore(path, site, target="local-dir")


def test_load_restore_refuses_receipts_that_were_not_last_known_good(tmp_path: Path) -> None:
    site = _site(tmp_path / "site", "a", dev=False)
    digest, _, _ = compute_tree_digest(site)
    built = make_receipt(run_id=3, trunk=SHA_A, probes_ok=False)
    built["artifact"]["sha256"] = digest
    path = tmp_path / "receipt.json"
    path.write_bytes(receipt.canonical_bytes(built))
    with pytest.raises(rollback.RollbackError, match="last-known-good"):
        rollback.load_restore(path, site)
    with pytest.raises(rollback.RollbackError, match="missing"):
        rollback.load_restore(tmp_path / "none.json", site)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(rollback.RollbackError, match="invalid"):
        rollback.load_restore(path, site)


def test_receipt_must_be_recorded_on_a_successful_deployment_status() -> None:
    api = FakeGitHub()
    built = make_receipt(run_id=3, trunk=SHA_A)
    sha = api.record_deployment(30, built, "2026-01-01T00:00:01Z")
    restore = rollback.Restore(receipt=built, receipt_sha256=sha, tree=Path("."))
    assert rollback.recorded_in_deployments([api.statuses[30]], restore) is True
    forged = rollback.Restore(receipt=built, receipt_sha256="0" * 64, tree=Path("."))
    assert rollback.recorded_in_deployments([api.statuses[30]], forged) is False


def test_verify_recorded_scans_deployment_history() -> None:
    api = FakeGitHub()
    built = make_receipt(run_id=3, trunk=SHA_A)
    sha = api.record_deployment(30, built, "2026-01-01T00:00:01Z")
    rollback.verify_recorded(api.client(), sha, 3)
    with pytest.raises(rollback.RollbackError, match="not recorded"):
        rollback.verify_recorded(api.client(), "0" * 64, 3)
    with pytest.raises(rollback.RollbackError, match="unreadable"):
        rollback.verify_recorded(FakeGitHub(fail=True).client(), sha, 3)


def test_ui_first_artifact_keeps_the_current_snapshot_and_restores_the_ui(tmp_path: Path) -> None:
    current = _site(tmp_path / "current", "new", dev=True)
    _write(current / "results" / "assets" / "app-new.js", "new ui")
    restored = _site(tmp_path / "restored", "old", dev=False)
    _write(restored / "results" / "assets" / "app-old.js", "old ui")
    _write(restored / "404.html", "old fallback")
    out = tmp_path / "composed"
    digest = artifacts.compose_ui_first(current, restored, out)
    assert (out / "404.html").read_text(encoding="utf-8") == "old fallback"
    assert (out / "results" / "index.html").read_text(encoding="utf-8") == "old explorer"
    assert (out / "results" / "assets" / "app-old.js").is_file()
    assert not (out / "results" / "assets" / "app-new.js").exists()
    assert (out / "results" / "data" / "results.duckdb").read_text(encoding="utf-8") == "new snapshot"
    assert (out / "docs" / "dev" / "index.html").read_text(encoding="utf-8") == "new dev docs"
    assert digest == compute_tree_digest(out)[0]


def test_ui_first_refuses_a_restored_artifact_without_the_fallback(tmp_path: Path) -> None:
    current = _site(tmp_path / "current", "new", dev=True)
    restored = _site(tmp_path / "restored", "old", dev=False)
    (restored / "404.html").unlink()
    with pytest.raises(artifacts.ArtifactError, match="deep-link fallback"):
        artifacts.compose_ui_first(current, restored, tmp_path / "composed")


def test_verify_tree_rejects_a_digest_mismatch(tmp_path: Path) -> None:
    site = _site(tmp_path / "site", "a", dev=False)
    with pytest.raises(artifacts.ArtifactError):
        artifacts.verify_tree(site, "0" * 64)
    with pytest.raises(artifacts.ArtifactError):
        artifacts.verify_tree(tmp_path / "missing", "0" * 64)


def test_parity_report_explains_added_changed_and_removed_files_per_route(tmp_path: Path) -> None:
    legacy = _site(tmp_path / "legacy", "a", dev=False)
    routes = _site(tmp_path / "routes", "b", dev=True)
    (legacy / "extra.txt").write_text("gone", encoding="utf-8")
    report = parity.classify(legacy, routes)
    assert report["added"] == 1
    assert report["removed"] == 1
    assert report["by_route"]["/docs/dev/"]["added"] == 1
    assert "new route" in report["by_route"]["/docs/dev/"]["explanation"]
    assert report["by_route"]["/docs/"]["changed"] == 2
    assert report["identical_files"] == 2


def _linked_deployment(api: FakeGitHub, deployment_id: int, created: str, link: str | None) -> None:
    api.deployments.append({"id": deployment_id, "created_at": created})
    api.statuses[deployment_id] = [{"state": "success", "log_url": link, "created_at": created}]


def test_deployment_lookup_binds_to_the_run_link_not_the_clock() -> None:
    api = FakeGitHub()
    _linked_deployment(api, 1, "2026-01-01T00:00:00Z", "https://github.com/owner/repo/actions/runs/77/job/1")
    _linked_deployment(api, 2, "2026-01-02T00:00:00Z", "https://github.com/owner/repo/actions/runs/770")
    _linked_deployment(api, 3, "2026-01-03T00:00:00Z", None)
    assert deployments.find_run_deployment_id(api.client(), 77) == 1
    assert deployments.find_run_deployment_id(api.client(), 770) == 2
    with pytest.raises(deployments.DeploymentLookupError, match="links to run 7"):
        deployments.find_run_deployment_id(api.client(), 7)


def test_deployment_lookup_survives_a_rerun_of_the_failed_jobs() -> None:
    api = FakeGitHub()
    _linked_deployment(api, 1, "2026-01-01T00:00:00Z", "https://github.com/owner/repo/actions/runs/77")
    _linked_deployment(api, 2, "2030-01-01T00:00:00Z", "https://github.com/owner/repo/actions/runs/88")
    assert deployments.find_run_deployment_id(api.client(), 77) == 1


def test_deployment_lookup_fails_closed_on_api_errors() -> None:
    with pytest.raises(deployments.DeploymentLookupError, match="unreadable"):
        deployments.find_run_deployment_id(FakeGitHub(fail=True).client(), 77)


def test_newest_deployment_id() -> None:
    api = FakeGitHub()
    assert deployments.newest_deployment_id(api.client()) is None
    _linked_deployment(api, 1, "2026-01-01T00:00:00Z", None)
    _linked_deployment(api, 2, "2026-01-02T00:00:00Z", None)
    assert deployments.newest_deployment_id(api.client()) == 2


def test_post_receipt_status_records_a_non_inactivating_success() -> None:
    api = FakeGitHub()
    api.deployments = [{"id": 2, "created_at": "2026-01-02T00:00:00Z"}]
    deployments.post_receipt_status(api.client(), 2, "a" * 64, 77, "https://log", "https://site")
    posted = api.statuses[2][-1]
    assert posted["state"] == "success"
    assert posted["description"] == receipt.status_description("a" * 64, 77)
    assert posted["auto_inactive"] is False
    with pytest.raises(deployments.DeploymentLookupError, match="not recorded"):
        deployments.post_receipt_status(FakeGitHub(fail=True).client(), 2, "a" * 64, 77, "l", "u")


def test_recorded_shas_lists_newest_first_for_the_run() -> None:
    api = FakeGitHub()
    first = api.record_deployment(30, make_receipt(run_id=3, trunk=SHA_A), "2026-01-01T00:00:01Z")
    api.statuses[30].append(
        {
            "state": "success",
            "description": receipt.status_description("b" * 64, 3),
            "created_at": "2026-01-01T00:00:09Z",
        }
    )
    assert rollback.recorded_shas(api.client(), 3) == ["b" * 64, first]
    assert rollback.recorded_shas(api.client(), 4) == []
