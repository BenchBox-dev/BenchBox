from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import duckdb
import pytest

from scripts.site_deploy import candidate, checksums, cli, generation, receipt
from tests.unit.scripts.site_deploy.site_deploy_fakes import SHA_A, SHA_B, FakeGitHub, make_receipt

pytestmark = [pytest.mark.unit, pytest.mark.fast]

TRUNK_PATH = ".github/workflows/trunk.yml"


def _use(monkeypatch: pytest.MonkeyPatch, api: FakeGitHub) -> None:
    monkeypatch.setattr(cli, "_client", api.client)
    monkeypatch.setattr(cli, "gh_receipt_loader", lambda repo: api.load_receipt)
    monkeypatch.setattr(candidate, "release_tags", lambda repo_dir: ["v0.4.1"])
    monkeypatch.setattr(candidate, "tag_commit", lambda repo_dir, tag: SHA_A)
    monkeypatch.setattr(candidate, "first_parent_shas", lambda repo_dir, ref, limit=50: [SHA_B])
    monkeypatch.setattr(candidate, "is_ancestor", lambda repo_dir, ancestor, descendant: ancestor == SHA_A)


def _green(api: FakeGitHub) -> None:
    api.runs.append(
        {
            "id": 5,
            "head_sha": SHA_B,
            "head_branch": "develop",
            "event": "push",
            "conclusion": "success",
            "path": TRUNK_PATH,
            "created_at": "2026-01-01T00:00:00Z",
        }
    )


def _resolve(tmp_path: Path, *args: str) -> tuple[int, dict[str, Any]]:
    output = tmp_path / "resolved.json"
    code = cli.main(["resolve", "--output", str(output), *args])
    return code, json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}


def _legacy(api: FakeGitHub, deployment_id: int, created: str) -> None:
    api.deployments.append({"id": deployment_id, "created_at": created})
    api.statuses[deployment_id] = [{"state": "success", "description": "legacy", "created_at": created}]


def test_bootstrap_resolve_orders_against_the_newest_receipt_and_records_the_carry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeGitHub()
    _green(api)
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A, generation=4), "2026-01-01T00:00:01Z")
    _legacy(api, 20, "2026-01-01T00:00:02Z")
    _use(monkeypatch, api)
    code, resolved = _resolve(tmp_path, "--mode", "deploy", "--bootstrap")
    assert code == 0
    assert resolved["action"] == "deploy"
    assert resolved["parent"]["generation"] == 4
    assert resolved["parent"]["newer_unreceipted"] is True
    code, _ = _resolve(tmp_path, "--mode", "deploy")
    assert code == 1


def test_current_unknown_rollback_requires_a_recorded_target_and_marks_the_parent_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A, generation=3), "2026-01-01T00:00:01Z")
    _legacy(api, 20, "2026-01-01T00:00:02Z")
    _use(monkeypatch, api)
    strict, _ = _resolve(tmp_path, "--mode", "rollback", "--rollback-run-id", "1")
    assert strict == 1
    code, resolved = _resolve(tmp_path, "--mode", "rollback", "--rollback-run-id", "1", "--current-unknown")
    assert code == 0
    assert resolved["current_unknown"] is True
    assert resolved["newest_deployment_id"] == 20
    assert resolved["parent"]["unknown"] is True
    assert resolved["parent"]["generation"] == 3
    assert resolved["deployed"]["unknown"] is True
    assert resolved["rollback"]["receipt_sha256"] == receipt.receipt_sha256(api.receipts[1])


def test_current_unknown_rollback_refuses_an_unrecorded_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeGitHub()
    _legacy(api, 20, "2026-01-01T00:00:02Z")
    _use(monkeypatch, api)
    code, _ = _resolve(tmp_path, "--mode", "rollback", "--rollback-run-id", "1", "--current-unknown")
    assert code == 1
    assert "no receipt of run 1 is recorded" in capsys.readouterr().err


def test_current_unknown_rollback_supports_only_the_full_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A), "2026-01-01T00:00:01Z")
    _use(monkeypatch, api)
    args = ["--mode", "rollback", "--rollback-run-id", "1", "--current-unknown", "--rollback-phase", "ui-first"]
    code, _ = _resolve(tmp_path, *args)
    assert code == 1
    assert "supports only full" in capsys.readouterr().err


def test_current_unknown_is_rejected_outside_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, FakeGitHub())
    code, _ = _resolve(tmp_path, "--mode", "deploy", "--current-unknown")
    assert code == 1
    assert "only to rollback" in capsys.readouterr().err


def test_recheck_of_an_unknown_current_rollback_compares_the_newest_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeGitHub()
    _legacy(api, 20, "2026-01-01T00:00:02Z")
    _use(monkeypatch, api)
    resolved = tmp_path / "resolved.json"
    resolved.write_text(
        json.dumps({"mode": "rollback", "bootstrap": False, "current_unknown": True, "newest_deployment_id": 20}),
        encoding="utf-8",
    )
    assert cli.main(["recheck", "--resolved", str(resolved)]) == 0
    _legacy(api, 21, "2026-01-01T00:00:03Z")
    assert cli.main(["recheck", "--resolved", str(resolved)]) == 1


def _snapshot(path: Path, version: int) -> Path:
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE TABLE metadata(read_model_version INTEGER)")
        connection.execute("INSERT INTO metadata VALUES (?)", [version])
    return path


def test_gates_derive_unknown_current_versions_from_the_live_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.site_deploy import gates as gates_module

    captured: dict[str, Any] = {}

    def fake_run(inputs: Any) -> dict[str, Any]:
        captured["deployed"] = inputs.deployed
        captured["tag"] = inputs.release_tag
        return {"ok": True, "results": {}, "corpus_sha": inputs.corpus_sha}

    monkeypatch.setattr(gates_module, "run_gates", fake_run)
    resolved = tmp_path / "resolved.json"
    resolved.write_text(
        json.dumps(
            {
                "mode": "rollback",
                "trunk_sha": SHA_A,
                "release_tag": "v0.4.1",
                "rollback": {"phase": "full"},
                "deployed": {"unknown": True, "ui_version": None, "snapshot_version": None},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "assembly.json"
    assembly.write_text(json.dumps({"routes": []}), encoding="utf-8")
    site = tmp_path / "site"
    (site / "results" / "data").mkdir(parents=True)
    _snapshot(site / "results" / "data" / "results.duckdb", 12)
    out = tmp_path / "out"
    live = _snapshot(tmp_path / "live.duckdb", 12)
    base = [
        "gates",
        "--repo-root",
        str(tmp_path),
        "--site-dir",
        str(site),
        "--resolved",
        str(resolved),
        "--assembly",
        str(assembly),
        "--out-dir",
        str(out),
        "--corpus-sha",
        "1" * 40,
    ]
    assert cli.main([*base, "--deployed-snapshot", str(live)]) == 0
    assert captured["deployed"]["ui_version"] == 12
    assert captured["deployed"]["snapshot_version"] == 12
    assert captured["tag"] == "v0.4.1"
    written = json.loads((out / "gates.json").read_text(encoding="utf-8"))
    assert written["live_versions"] == {"ui_upper_bound": 12, "snapshot": 12}
    assert cli.main(base) == 1


def test_finalize_binds_the_deployment_to_the_run_and_record_posts_after_the_receipt_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.publication.assembler import compute_tree_digest
    from scripts.site_deploy import publish

    api = FakeGitHub()
    api.deployments = [{"id": 1, "created_at": "2026-01-01T00:00:00Z"}, {"id": 2, "created_at": "2030-01-01T00:00:00Z"}]
    api.statuses[1] = [
        {
            "state": "success",
            "log_url": "https://github.com/owner/repo/actions/runs/77",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]
    api.statuses[2] = [
        {
            "state": "success",
            "log_url": "https://github.com/owner/repo/actions/runs/88",
            "created_at": "2030-01-01T00:00:00Z",
        }
    ]
    monkeypatch.setattr(cli, "_client", api.client)
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    site = tmp_path / "site"
    (site / "index.html").parent.mkdir(parents=True)
    (site / "index.html").write_text("x", encoding="utf-8")
    (site / "results" / "data").mkdir(parents=True)
    (site / "404.html").write_text(
        "<script>sessionStorage.setItem('benchbox.results.redirect', 1)</script>", encoding="utf-8"
    )
    _snapshot(site / "results" / "data" / "results.duckdb", 11)
    digest, size, files = compute_tree_digest(site)
    out = tmp_path / "out"
    out.mkdir()
    (out / "resolved.json").write_text(
        json.dumps(
            {
                "mode": "deploy",
                "trunk_sha": SHA_A,
                "release_tag": "v0.4.1",
                "release_sha": SHA_A,
                "certifying_run_id": 5,
                "parent": {"unknown": True, "generation": 3},
                "rollback": None,
                "deployed": None,
            }
        ),
        encoding="utf-8",
    )
    (out / "route-assembly.json").write_text(
        json.dumps({"routes": [], "tree_sha256": digest, "total_bytes": size, "total_files": len(files)}),
        encoding="utf-8",
    )
    (out / "gates.json").write_text(
        json.dumps(
            {
                "ok": True,
                "corpus_sha": "1" * 40,
                "live_versions": {"ui_upper_bound": 12, "snapshot": 12},
                "results": {"mixed_version": {"status": "pass"}},
            }
        ),
        encoding="utf-8",
    )
    (out / "probe-checksums.json").write_text(json.dumps(checksums.checksum_manifest(site, ["/"])), encoding="utf-8")
    with publish.running_target(tmp_path / "slot") as target:
        target.publish(site)
        code = cli.main(
            [
                "finalize",
                "--out-dir",
                str(out),
                "--base-url",
                target.base_url,
                "--artifact-name",
                "site-deploy-artifact-77-2",
                "--attempts",
                "1",
                "--delay",
                "0",
            ]
        )
        assert code == 0
        assert api.statuses[1][-1].get("description") is None
        built = receipt.validate_receipt(json.loads((out / "receipt" / "receipt.json").read_text(encoding="utf-8")))
        assert built["deployment_id"] == 1
        assert built["artifact"]["name"] == "site-deploy-artifact-77-2"
        assert built["generation"] == 4
        assert built["parent"]["live_versions"] == {"ui_upper_bound": 12, "snapshot": 12}
        assert cli.main(["record", "--out-dir", str(out), "--base-url", target.base_url]) == 0
    posted = api.statuses[1][-1]
    raw = (out / "receipt" / "receipt.json").read_bytes()
    assert posted["description"] == receipt.status_description(receipt.receipt_sha256(raw), 77)
    assert 2 not in {key for key, rows in api.statuses.items() if rows and rows[-1].get("description")}


def test_record_refuses_a_receipt_without_a_deployment_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    built = make_receipt(run_id=77, trunk=SHA_A)
    built["deployment_id"] = None
    (tmp_path / "receipt").mkdir()
    (tmp_path / "receipt" / "receipt.json").write_bytes(receipt.canonical_bytes(built))
    assert cli.main(["record", "--out-dir", str(tmp_path)]) == 1
    assert "no deployment id" in capsys.readouterr().err


def test_receipt_artifact_names_pick_the_run_and_order_attempts_newest_first() -> None:
    names = [
        "site-deploy-receipt-9-1",
        "site-deploy-receipt-9-3",
        "site-deploy-receipt-9-2",
        "site-deploy-receipt-99-9",
        "site-deploy-receipt-9",
        "site-deploy-artifact-9-1",
    ]
    assert cli.receipt_artifact_names(names, 9) == [
        "site-deploy-receipt-9-3",
        "site-deploy-receipt-9-2",
        "site-deploy-receipt-9-1",
    ]


def test_receipt_loader_returns_the_attempt_whose_digest_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    first = receipt.canonical_bytes(make_receipt(run_id=9, trunk=SHA_A))
    second = receipt.canonical_bytes(make_receipt(run_id=9, trunk=SHA_B))
    by_name = {"site-deploy-receipt-9-1": first, "site-deploy-receipt-9-2": second}
    monkeypatch.setattr(cli, "_gh", lambda *args: "\n".join(by_name) + "\n")

    def download(repo: str, run_id: int, name: str, destination: Path) -> None:
        (destination / cli.RECEIPT_FILE).write_bytes(by_name[name])

    monkeypatch.setattr(cli, "gh_download", download)
    load = cli.gh_receipt_loader("owner/repo")
    assert load(9) == second
    assert load(9, receipt.receipt_sha256(first)) == first
    with pytest.raises(OSError, match="matches the recorded digest"):
        load(9, "0" * 64)


def test_gh_failures_surface_as_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.CalledProcessError(1, "gh", stderr="no")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(OSError, match="gh api"):
        cli.gh_receipt_loader("owner/repo")(9)


def test_unreadable_receipt_authority_is_a_clean_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A), "2026-01-01T00:00:01Z")

    def gone(run_id: int, expected_sha256: str | None = None) -> bytes:
        raise OSError("expired")

    with pytest.raises(generation.GenerationAuthorityError, match="unavailable"):
        generation.read_deployed(api.client(), gone)


def test_recheck_ignores_the_run_s_own_waiting_deployment_but_refuses_a_foreign_newer_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeGitHub()
    _legacy(api, 20, "2026-01-01T00:00:02Z")
    _use(monkeypatch, api)
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    resolved = tmp_path / "resolved.json"
    resolved.write_text(
        json.dumps({"mode": "rollback", "bootstrap": False, "current_unknown": True, "newest_deployment_id": 20}),
        encoding="utf-8",
    )
    api.deployments.append({"id": 30, "created_at": "2026-01-01T00:00:09Z"})
    api.statuses[30] = [
        {
            "state": "waiting",
            "log_url": "https://github.com/owner/repo/actions/runs/77/job/5",
            "created_at": "2026-01-01T00:00:09Z",
        }
    ]
    assert cli.main(["recheck", "--resolved", str(resolved)]) == 0
    api.deployments.append({"id": 31, "created_at": "2026-01-01T00:00:10Z"})
    api.statuses[31] = [
        {
            "state": "success",
            "log_url": "https://github.com/owner/repo/actions/runs/78",
            "created_at": "2026-01-01T00:00:10Z",
        }
    ]
    assert cli.main(["recheck", "--resolved", str(resolved)]) == 1
