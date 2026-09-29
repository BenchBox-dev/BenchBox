"""Artifact identity, receipts, and the deployment record index."""

from __future__ import annotations

import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from scripts.site_deploy import receipt as r
from tests.unit.scripts.site_deploy.helpers import gen

pytestmark = [pytest.mark.unit, pytest.mark.fast]

MOUNTS = ["/", "/docs/", "/docs/dev/", "/blog/", "/results/"]


def write_site(root: Path) -> Path:
    files = {
        "index.html": "landing",
        "docs/index.html": "docs",
        "docs/guide.html": "guide",
        "docs/dev/index.html": "dev docs",
        "docs/dev/guide.html": "dev guide",
        "blog/index.html": "blog",
        "_static/site.css": "css",
        "results/index.html": "explorer",
        "results/data/results.duckdb": "db-bytes",
        "404.html": "fallback",
        "CNAME": "benchbox.dev",
        ".nojekyll": "",
    }
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


@pytest.fixture
def site(tmp_path: Path) -> Path:
    return write_site(tmp_path / "site")


def candidate_receipt(site: Path, archive: Path, **overrides) -> dict:
    identity = r.tree_identity(site)
    sha = r.write_deterministic_tar(site, archive)
    receipt = r.new_receipt(
        receipt_id="site-deploy-1-1",
        operation="deploy",
        target="production",
        generation=gen(),
        routes=[{"id": "landing", "mount": "/"}],
        identity_evidence={"trunk": {"mode": "ci"}},
        identity=identity,
        archive_sha256=sha,
        explorer={"ui_read_model_version": 11, "snapshot_read_model_version": 11},
        gates=[{"name": "privacy", "ok": True, "detail": ""}],
        checksums=r.build_probe_set(site, identity, MOUNTS),
        quarantine=(set(), set()),
        workflow={"run_id": "1"},
        created_at="2026-09-29T00:00:00Z",
    )
    receipt.update(overrides)
    return receipt


class TestArtifactIdentity:
    def test_tree_identity_is_stable_and_content_sensitive(self, site: Path) -> None:
        first = r.tree_identity(site)
        assert r.tree_identity(site) == first
        (site / "docs" / "guide.html").write_text("changed", encoding="utf-8")
        assert r.tree_identity(site).tree_digest != first.tree_digest

    def test_tar_is_reproducible_across_mtimes(self, site: Path, tmp_path: Path) -> None:
        first = r.write_deterministic_tar(site, tmp_path / "a.tar")
        for path in site.rglob("*"):
            os.utime(path, (1_000_000, 1_000_000))
        assert r.write_deterministic_tar(site, tmp_path / "b.tar") == first

    def test_tar_round_trips_to_the_same_tree(self, site: Path, tmp_path: Path) -> None:
        archive = tmp_path / "a.tar"
        r.write_deterministic_tar(site, archive)
        r.extract_tar_safely(archive, tmp_path / "out")
        assert r.tree_identity(tmp_path / "out") == r.tree_identity(site)

    def test_symlinks_are_refused(self, site: Path) -> None:
        (site / "link").symlink_to(site / "index.html")
        with pytest.raises(r.ReceiptError, match="symlink"):
            r.tree_identity(site)

    @pytest.mark.parametrize("name", ["../escape.txt", "/abs.txt"])
    def test_extraction_refuses_paths_outside_the_destination(self, tmp_path: Path, name: str) -> None:
        archive = tmp_path / "evil.tar"
        with tarfile.open(archive, "w") as tar:
            info = tarfile.TarInfo(name)
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        with pytest.raises(r.ReceiptError):
            r.extract_tar_safely(archive, tmp_path / "out")
        assert not (tmp_path / "escape.txt").exists()

    def test_extraction_refuses_links(self, tmp_path: Path) -> None:
        archive = tmp_path / "evil.tar"
        with tarfile.open(archive, "w") as tar:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        with pytest.raises(r.ReceiptError, match="regular file"):
            r.extract_tar_safely(archive, tmp_path / "out")


class TestProbeSet:
    def test_every_route_entry_is_probed_as_directory_and_file_url(self, site: Path) -> None:
        checksums = r.build_probe_set(site, r.tree_identity(site), MOUNTS)
        for mount in MOUNTS:
            assert mount in checksums
        assert checksums["/"] == checksums["/index.html"]
        assert checksums["/docs/dev/"] == checksums["/docs/dev/index.html"]
        assert checksums["/docs/"] != checksums["/docs/dev/"]

    def test_snapshot_is_always_probed(self, site: Path) -> None:
        checksums = r.build_probe_set(site, r.tree_identity(site), MOUNTS, sample_per_route=0)
        assert "/results/data/results.duckdb" in checksums

    def test_pages_only_files_and_dotfiles_are_not_probed(self, site: Path) -> None:
        checksums = r.build_probe_set(site, r.tree_identity(site), MOUNTS)
        assert "/CNAME" not in checksums and "/404.html" not in checksums and "/.nojekyll" not in checksums

    def test_nested_route_files_belong_to_the_nested_route(self, site: Path) -> None:
        checksums = r.build_probe_set(site, r.tree_identity(site), MOUNTS, sample_per_route=1)
        # one sample from /docs/ (guide.html) and one from /docs/dev/ (guide.html)
        assert "/docs/guide.html" in checksums and "/docs/dev/guide.html" in checksums

    def test_sample_is_deterministic_and_bounded(self, site: Path) -> None:
        identity = r.tree_identity(site)
        first = r.build_probe_set(site, identity, MOUNTS, sample_per_route=1)
        assert r.build_probe_set(site, identity, MOUNTS, sample_per_route=1) == first

    def test_missing_entry_page_is_an_error(self, site: Path) -> None:
        (site / "blog" / "index.html").unlink()
        with pytest.raises(r.ReceiptError, match="no entry page"):
            r.build_probe_set(site, r.tree_identity(site), MOUNTS)


class TestDeploymentDescription:
    def test_round_trip_and_length(self) -> None:
        text = r.deployment_description(gen(index=12345, tag="v10.20.30"), 12345678901, "f" * 64, verified=True)
        assert len(text) <= 140
        parsed = r.parse_deployment_description(text)
        assert parsed == {
            "st": "ok",
            "index": "12345",
            "rel": "v10.20.30",
            "trunk": "a" * 40,
            "run": "12345678901",
            "art": "f" * 12,
        }

    def test_failed_probes_are_marked(self) -> None:
        text = r.deployment_description(gen(), 7, "f" * 64, verified=False)
        assert r.parse_deployment_description(text)["st"] == "failed"

    @pytest.mark.parametrize("text", [None, "", "deployed by hand", "site-deploy v2 st=ok g=1"])
    def test_foreign_descriptions_do_not_parse(self, text) -> None:
        assert r.parse_deployment_description(text) is None


class TestReceipts:
    def test_new_receipt_is_valid_and_binds_the_artifact(self, site: Path, tmp_path: Path) -> None:
        receipt = candidate_receipt(site, tmp_path / "a.tar")
        assert r.validate_receipt(receipt) == []
        assert receipt["artifact"]["sha256"] == r.sha256_file(tmp_path / "a.tar")
        assert receipt["status"] == r.STATUS_CANDIDATE

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda d: d.pop("kind"),
            lambda d: d.update(schema_version=2),
            lambda d: d.update(target="staging"),
            lambda d: d["artifact"].update(sha256="xyz"),
            lambda d: d["generation"].pop("corpus_sha"),
            lambda d: d.update(checksums={}),
        ],
    )
    def test_malformed_receipts_are_rejected(self, site: Path, tmp_path: Path, mutation) -> None:
        receipt = candidate_receipt(site, tmp_path / "a.tar")
        mutation(receipt)
        assert r.validate_receipt(receipt)
        with pytest.raises(r.ReceiptError):
            r.deployed_state_from_receipt(receipt)

    @pytest.mark.parametrize(
        ("target", "probes_ok", "confirmed", "status"),
        [
            ("production", True, True, r.STATUS_LIVE_VERIFIED),
            ("production", True, False, r.STATUS_PROBE_FAILED),
            ("production", False, True, r.STATUS_PROBE_FAILED),
            ("preview", True, False, r.STATUS_PREVIEW_VERIFIED),
            ("preview", False, False, r.STATUS_PROBE_FAILED),
        ],
    )
    def test_finalize_sets_status_from_probes_and_deployment(
        self, site: Path, tmp_path: Path, target: str, probes_ok: bool, confirmed: bool, status: str
    ) -> None:
        receipt = candidate_receipt(site, tmp_path / "a.tar", target=target)
        final = r.finalize_receipt(
            receipt, probes={"ok": probes_ok}, deployment={"confirmed": confirmed}, observed_at="2026-09-29T01:00:00Z"
        )
        assert final["status"] == status
        assert receipt["status"] == r.STATUS_CANDIDATE, "finalize must not mutate the candidate receipt"
        assert final["probes"]["observed_at"] == "2026-09-29T01:00:00Z"

    def test_only_a_live_verified_receipt_becomes_a_rollback_target(self, site: Path, tmp_path: Path) -> None:
        receipt = candidate_receipt(site, tmp_path / "a.tar")
        candidate_target = r.rollback_target_from_receipt(receipt)
        assert candidate_target.status == r.STATUS_CANDIDATE and not candidate_target.probes_ok
        final = r.finalize_receipt(receipt, probes={"ok": True}, deployment={"confirmed": True}, observed_at="t")
        good = r.rollback_target_from_receipt(final)
        assert good.status == r.STATUS_LIVE_VERIFIED and good.probes_ok and good.deployment_confirmed

    def test_deployed_state_carries_quarantine(self, site: Path, tmp_path: Path) -> None:
        receipt = candidate_receipt(site, tmp_path / "a.tar")
        receipt["quarantine"] = {"trunk_shas": ["b" * 40], "release_tags": ["v0.4.0"]}
        state = r.deployed_state_from_receipt(receipt)
        assert state.quarantined_trunk_shas == {"b" * 40} and state.quarantined_release_tags == {"v0.4.0"}

    def test_explorer_versions_are_read_back(self, site: Path, tmp_path: Path) -> None:
        receipt = candidate_receipt(site, tmp_path / "a.tar")
        assert r.explorer_versions_from_receipt(receipt) == (11, 11)
        receipt["explorer"] = {}
        assert r.explorer_versions_from_receipt(receipt) is None

    def test_read_receipt_round_trips_and_validates(self, site: Path, tmp_path: Path) -> None:
        receipt = candidate_receipt(site, tmp_path / "a.tar")
        path = tmp_path / "receipt.json"
        path.write_text(r.dumps(receipt), encoding="utf-8")
        assert r.read_receipt(path) == receipt
        path.write_text(json.dumps({"kind": "other"}), encoding="utf-8")
        with pytest.raises(r.ReceiptError):
            r.read_receipt(path)
        with pytest.raises(r.ReceiptError):
            r.read_receipt(tmp_path / "missing.json")


class TestExactArtifactVerification:
    def test_archive_must_match_the_receipt_digest(self, site: Path, tmp_path: Path) -> None:
        archive = tmp_path / "a.tar"
        receipt = candidate_receipt(site, archive)
        r.verify_archive(archive, receipt)
        archive.write_bytes(archive.read_bytes() + b"\0")
        with pytest.raises(r.ReceiptError, match="does not match receipt"):
            r.verify_archive(archive, receipt)

    def test_extracted_tree_must_match_tree_digest_and_checksums(self, site: Path, tmp_path: Path) -> None:
        archive = tmp_path / "a.tar"
        receipt = candidate_receipt(site, archive)
        r.extract_tar_safely(archive, tmp_path / "out")
        r.verify_extracted_tree(tmp_path / "out", receipt)
        (tmp_path / "out" / "docs" / "index.html").write_text("tampered", encoding="utf-8")
        with pytest.raises(r.ReceiptError, match="tree digest"):
            r.verify_extracted_tree(tmp_path / "out", receipt)

    def test_probe_checksums_are_checked_even_when_the_tree_digest_matches(self, site: Path, tmp_path: Path) -> None:
        archive = tmp_path / "a.tar"
        receipt = candidate_receipt(site, archive)
        receipt["checksums"]["/docs/"] = "0" * 64
        r.extract_tar_safely(archive, tmp_path / "out")
        with pytest.raises(r.ReceiptError, match="checksum"):
            r.verify_extracted_tree(tmp_path / "out", receipt)
