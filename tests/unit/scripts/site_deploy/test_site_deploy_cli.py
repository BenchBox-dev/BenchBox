from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from scripts.publication.assembler import compute_tree_digest
from scripts.site_deploy import checksums, cli, publish, receipt
from tests.unit.scripts.site_deploy.site_deploy_fakes import SHA_A, make_receipt

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROUTES = ["/", "/docs/", "/docs/dev/", "/blog/", "/results/"]
FALLBACK = "<script>sessionStorage.setItem('benchbox.results.redirect', 1)</script>"


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _site(root: Path, label: str, snapshot: int = 11) -> Path:
    for relative in ("index.html", "docs/index.html", "docs/dev/index.html", "blog/index.html", "results/index.html"):
        _write(root / relative, f"{label} {relative}")
    _write(root / "results" / "assets" / f"app-{label}.js", f"{label} ui")
    _write(root / "404.html", FALLBACK)
    database = root / "results" / "data" / "results.duckdb"
    database.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE metadata(read_model_version INTEGER)")
        connection.execute("INSERT INTO metadata VALUES (?)", [snapshot])
    return root


def _stored_receipt(tmp_path: Path, tree: Path, run_id: int, ui: int, snapshot: int) -> Path:
    digest, size, files = compute_tree_digest(tree)
    built = make_receipt(run_id=run_id, trunk=SHA_A, ui=ui, snapshot=snapshot)
    built["artifact"].update(sha256=digest, total_bytes=size, total_files=len(files))
    built["routes"] = [{"path": path, "source_sha": SHA_A} for path in ROUTES]
    path = tmp_path / f"receipt-{run_id}.json"
    path.write_bytes(receipt.canonical_bytes(built))
    return path


def _resolved(deployed: dict | None = None, mode: str = "rollback", stored: Path | None = None) -> dict:
    rollback = None
    if stored is not None:
        rollback = {"run_id": 7, "phase": "full", "receipt_sha256": receipt.receipt_sha256(stored.read_bytes())}
    return {
        "mode": mode,
        "trunk_sha": SHA_A,
        "release_tag": "v0.4.1",
        "release_sha": SHA_A,
        "certifying_run_id": None,
        "parent": None,
        "rollback": rollback,
        "deployed": deployed,
    }


def test_rollback_prepare_full_phase_copies_the_restored_tree_and_describes_it(tmp_path: Path) -> None:
    restored = _site(tmp_path / "restored", "old", snapshot=11)
    stored = _stored_receipt(tmp_path, restored, 7, ui=11, snapshot=11)
    resolved = tmp_path / "resolved.json"
    resolved.write_text(json.dumps(_resolved(stored=stored)), encoding="utf-8")
    out = tmp_path / "out"

    code = cli.main(
        [
            "rollback-prepare",
            "--receipt",
            str(stored),
            "--restored-tree",
            str(restored),
            "--resolved",
            str(resolved),
            "--site-dir",
            str(tmp_path / "site-build"),
            "--out-dir",
            str(out),
        ]
    )

    assert code == 0
    assembly = json.loads((out / "route-assembly.json").read_text(encoding="utf-8"))
    assert assembly["tree_sha256"] == compute_tree_digest(tmp_path / "site-build")[0]
    restore = json.loads((out / "restore.json").read_text(encoding="utf-8"))
    assert restore["ui_version"] == 11
    assert restore["phase"] == "full"


def test_rollback_prepare_refuses_a_tampered_artifact(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    restored = _site(tmp_path / "restored", "old")
    stored = _stored_receipt(tmp_path, restored, 7, ui=11, snapshot=11)
    (restored / "index.html").write_text("tampered", encoding="utf-8")
    resolved = tmp_path / "resolved.json"
    resolved.write_text(json.dumps(_resolved(stored=stored)), encoding="utf-8")
    code = cli.main(
        [
            "rollback-prepare",
            "--receipt",
            str(stored),
            "--restored-tree",
            str(restored),
            "--resolved",
            str(resolved),
            "--site-dir",
            str(tmp_path / "site-build"),
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 1
    assert "does not match" in capsys.readouterr().err
    assert not (tmp_path / "site-build").exists()


def test_rollback_prepare_ui_first_keeps_the_current_snapshot_and_current_corpus(tmp_path: Path) -> None:
    restored = _site(tmp_path / "restored", "old", snapshot=11)
    current = _site(tmp_path / "current", "new", snapshot=12)
    stored = _stored_receipt(tmp_path, restored, 7, ui=11, snapshot=11)
    resolved = tmp_path / "resolved.json"
    current_digest = compute_tree_digest(current)[0]
    deployed = {"corpus_sha": "9" * 40, "artifact_sha256": current_digest}
    resolved.write_text(json.dumps(_resolved(deployed, stored=stored)), encoding="utf-8")
    out = tmp_path / "out"

    code = cli.main(
        [
            "rollback-prepare",
            "--receipt",
            str(stored),
            "--restored-tree",
            str(restored),
            "--current-tree",
            str(current),
            "--phase",
            "ui-first",
            "--resolved",
            str(resolved),
            "--site-dir",
            str(tmp_path / "site-build"),
            "--out-dir",
            str(out),
        ]
    )

    assert code == 0
    site = tmp_path / "site-build"
    assert (site / "results" / "assets" / "app-old.js").is_file()
    assert not (site / "results" / "assets" / "app-new.js").exists()
    with duckdb.connect(str(site / "results" / "data" / "results.duckdb"), read_only=True) as connection:
        assert connection.execute("SELECT read_model_version FROM metadata").fetchone() == (12,)
    restore = json.loads((out / "restore.json").read_text(encoding="utf-8"))
    assert restore["corpus_sha"] == "9" * 40
    assert (
        json.loads((out / "route-assembly.json").read_text(encoding="utf-8"))["tree_sha256"]
        == compute_tree_digest(site)[0]
    )


def test_finalize_probes_the_target_and_writes_a_receipt_that_the_generation_reader_accepts(tmp_path: Path) -> None:
    site = _site(tmp_path / "site", "b")
    digest, size, files = compute_tree_digest(site)
    out = tmp_path / "out"
    out.mkdir()
    (out / "resolved.json").write_text(json.dumps(_resolved(mode="deploy")), encoding="utf-8")
    (out / "route-assembly.json").write_text(
        json.dumps(
            {
                "routes": [{"path": path, "source_sha": SHA_A} for path in ROUTES],
                "tree_sha256": digest,
                "total_bytes": size,
                "total_files": len(files),
            }
        ),
        encoding="utf-8",
    )
    (out / "gates.json").write_text(
        json.dumps(
            {
                "ok": True,
                "corpus_sha": "1" * 40,
                "results": {"mixed_version": {"status": "pass", "versions": {"ui_expected": 11, "snapshot": 11}}},
            }
        ),
        encoding="utf-8",
    )
    (out / "probe-checksums.json").write_text(json.dumps(checksums.checksum_manifest(site, ROUTES)), encoding="utf-8")

    with publish.running_target(tmp_path / "slot") as target:
        target.publish(site)
        code = cli.main(
            [
                "finalize",
                "--out-dir",
                str(out),
                "--base-url",
                target.base_url,
                "--target",
                "local-dir",
                "--run-id",
                "42",
                "--no-status",
                "--attempts",
                "1",
                "--delay",
                "0",
            ]
        )

    assert code == 0
    built = receipt.validate_receipt(json.loads((out / "receipt" / "receipt.json").read_text(encoding="utf-8")))
    assert built["run_id"] == 42
    assert built["generation"] == 1
    assert built["probes"]["ok"] is True
    assert built["versions"] == {"ui_expected": 11, "snapshot": 11}
    assert built["artifact"]["sha256"] == digest
    assert built["gates"]["gates_sha256"]
    assert receipt.is_last_known_good(built, "local-dir")


def test_finalize_exits_nonzero_but_still_writes_the_receipt_when_probes_fail(tmp_path: Path) -> None:
    site = _site(tmp_path / "site", "b")
    out = tmp_path / "out"
    out.mkdir()
    (out / "resolved.json").write_text(json.dumps(_resolved(mode="deploy")), encoding="utf-8")
    digest, size, files = compute_tree_digest(site)
    (out / "route-assembly.json").write_text(
        json.dumps({"routes": [], "tree_sha256": digest, "total_bytes": size, "total_files": len(files)}),
        encoding="utf-8",
    )
    (out / "gates.json").write_text(
        json.dumps({"ok": True, "corpus_sha": "1" * 40, "results": {"mixed_version": {"status": "pass"}}}),
        encoding="utf-8",
    )
    (out / "probe-checksums.json").write_text(json.dumps({"/": "0" * 64}), encoding="utf-8")
    with publish.running_target(tmp_path / "slot") as target:
        target.publish(site)
        code = cli.main(
            [
                "finalize",
                "--out-dir",
                str(out),
                "--base-url",
                target.base_url,
                "--target",
                "local-dir",
                "--run-id",
                "9",
                "--no-status",
                "--attempts",
                "1",
                "--delay",
                "0",
            ]
        )
    assert code == 1
    built = json.loads((out / "receipt" / "receipt.json").read_text(encoding="utf-8"))
    assert built["probes"]["ok"] is False
    assert not receipt.is_last_known_good(built, "local-dir")


def _prepare(tmp_path: Path, stored: Path, restored: Path, resolved: dict, *extra: str) -> int:
    path = tmp_path / "resolved.json"
    path.write_text(json.dumps(resolved), encoding="utf-8")
    return cli.main(
        [
            "rollback-prepare",
            "--receipt",
            str(stored),
            "--restored-tree",
            str(restored),
            "--resolved",
            str(path),
            "--site-dir",
            str(tmp_path / "site-build"),
            "--out-dir",
            str(tmp_path / "out"),
            *extra,
        ]
    )


def test_rollback_prepare_refuses_a_receipt_that_differs_from_the_resolved_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    restored = _site(tmp_path / "restored", "old")
    stored = _stored_receipt(tmp_path, restored, 7, ui=11, snapshot=11)
    resolved = _resolved(stored=stored)
    resolved["rollback"]["receipt_sha256"] = "0" * 64
    assert _prepare(tmp_path, stored, restored, resolved) == 1
    assert "does not match the resolved" in capsys.readouterr().err
    assert not (tmp_path / "site-build").exists()


def test_rollback_prepare_refuses_a_resolution_without_a_receipt_digest(tmp_path: Path) -> None:
    restored = _site(tmp_path / "restored", "old")
    stored = _stored_receipt(tmp_path, restored, 7, ui=11, snapshot=11)
    assert _prepare(tmp_path, stored, restored, _resolved()) == 1


def test_rollback_prepare_ui_first_refuses_a_current_tree_that_differs_from_the_deployed_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    restored = _site(tmp_path / "restored", "old", snapshot=11)
    current = _site(tmp_path / "current", "new", snapshot=12)
    stored = _stored_receipt(tmp_path, restored, 7, ui=11, snapshot=11)
    deployed = {"corpus_sha": "9" * 40, "artifact_sha256": compute_tree_digest(current)[0]}
    (current / "index.html").write_text("tampered", encoding="utf-8")
    code = _prepare(
        tmp_path,
        stored,
        restored,
        _resolved(deployed, stored=stored),
        "--current-tree",
        str(current),
        "--phase",
        "ui-first",
    )
    assert code == 1
    assert "does not match recorded" in capsys.readouterr().err
    assert not (tmp_path / "site-build").exists()


def test_deployment_lookup_failures_exit_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from tests.unit.scripts.site_deploy.site_deploy_fakes import FakeGitHub

    site = _site(tmp_path / "site", "b")
    digest, size, files = compute_tree_digest(site)
    out = tmp_path / "out"
    out.mkdir()
    (out / "resolved.json").write_text(json.dumps(_resolved(mode="deploy")), encoding="utf-8")
    (out / "route-assembly.json").write_text(
        json.dumps({"routes": [], "tree_sha256": digest, "total_bytes": size, "total_files": len(files)}),
        encoding="utf-8",
    )
    (out / "gates.json").write_text(
        json.dumps({"ok": True, "corpus_sha": "1" * 40, "results": {"mixed_version": {"status": "pass"}}}),
        encoding="utf-8",
    )
    (out / "probe-checksums.json").write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    monkeypatch.setattr(cli, "_client", FakeGitHub().client)
    with publish.running_target(tmp_path / "slot") as target:
        target.publish(site)
        code = cli.main(
            ["finalize", "--out-dir", str(out), "--base-url", target.base_url, "--attempts", "1", "--delay", "0"]
        )
    assert code == 1
    assert "refuse: DeploymentLookupError" in capsys.readouterr().err
