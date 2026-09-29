"""Rollback redeploys the exact artifact of a prior probed-green receipt."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.site_deploy import generation as g, receipt as r, rollback as rb
from scripts.site_deploy.pipeline import PipelineError
from tests.unit.scripts.site_deploy.helpers import commit_files, gen, git
from tests.unit.scripts.site_deploy.test_receipt import candidate_receipt, write_site

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def live_verified(site: Path, archive: Path, **overrides) -> dict:
    base = candidate_receipt(site, archive, **overrides)
    return r.finalize_receipt(base, probes={"ok": True}, deployment={"confirmed": True}, observed_at="t")


@pytest.fixture
def good(tmp_path: Path) -> tuple[dict, Path]:
    site = write_site(tmp_path / "good-site")
    archive = tmp_path / "good.tar"
    return live_verified(site, archive, receipt_id="site-deploy-100-1"), archive


def deployed_receipt(tmp_path: Path, versions: tuple[int, int] = (11, 11), **kwargs) -> dict:
    site = write_site(tmp_path / "live-site")
    (site / "docs" / "index.html").write_text("newer docs", encoding="utf-8")
    receipt = live_verified(site, tmp_path / "live.tar", receipt_id="site-deploy-200-1", **kwargs)
    receipt["explorer"] = {"ui_read_model_version": versions[0], "snapshot_read_model_version": versions[1]}
    return receipt


class TestStage:
    def test_verified_archive_is_staged_and_rollback_receipt_records_lineage(self, good, tmp_path: Path) -> None:
        target, archive = good
        live = deployed_receipt(tmp_path, generation=gen("b", 11).to_dict())
        rolled = rb.stage_rollback(
            target_receipt=target,
            deployed_receipt=live,
            archive=archive,
            out_dir=tmp_path / "out",
            target="production",
            workflow={"run_id": "300", "run_attempt": "1"},
        )
        assert (tmp_path / "out" / "site" / "docs" / "index.html").read_text() == "docs"
        assert rolled["operation"] == "rollback" and rolled["status"] == r.STATUS_CANDIDATE
        assert rolled["artifact"]["sha256"] == target["artifact"]["sha256"]
        assert rolled["checksums"] == target["checksums"]
        assert rolled["rollback"] == {
            "restored_receipt_id": "site-deploy-100-1",
            "restored_run_id": "1",
            "replaced_receipt_id": "site-deploy-200-1",
        }
        assert rolled["quarantine"]["trunk_shas"] == ["b" * 40]
        assert (tmp_path / "out" / "receipt.json").is_file()

    def test_tampered_archive_is_refused_before_extraction(self, good, tmp_path: Path) -> None:
        target, archive = good
        archive.write_bytes(archive.read_bytes() + b"\0")
        with pytest.raises(r.ReceiptError, match="does not match receipt"):
            rb.stage_rollback(
                target_receipt=target,
                deployed_receipt=deployed_receipt(tmp_path),
                archive=archive,
                out_dir=tmp_path / "out",
                target="production",
            )
        assert not (tmp_path / "out" / "site").exists()

    def test_snapshot_rollback_with_the_ui_is_refused(self, good, tmp_path: Path) -> None:
        target, archive = good
        target["explorer"] = {"ui_read_model_version": 11, "snapshot_read_model_version": 11}
        live = deployed_receipt(tmp_path, versions=(12, 12))
        with pytest.raises(PipelineError, match="Roll the UI back before"):
            rb.stage_rollback(
                target_receipt=target,
                deployed_receipt=live,
                archive=archive,
                out_dir=tmp_path / "out",
                target="production",
            )

    def test_ui_first_rollback_is_accepted_and_waiver_covers_the_single_step(self, good, tmp_path: Path) -> None:
        target, archive = good
        target["explorer"] = {"ui_read_model_version": 11, "snapshot_read_model_version": 12}
        live = deployed_receipt(tmp_path, versions=(12, 12))
        rb.stage_rollback(
            target_receipt=target,
            deployed_receipt=live,
            archive=archive,
            out_dir=tmp_path / "ui-first",
            target="production",
        )

        target["explorer"] = {"ui_read_model_version": 11, "snapshot_read_model_version": 11}
        rb.stage_rollback(
            target_receipt=target,
            deployed_receipt=live,
            archive=archive,
            out_dir=tmp_path / "waived",
            target="production",
            waive_cache_window=True,
        )

    def test_staging_never_overwrites_an_existing_tree(self, good, tmp_path: Path) -> None:
        target, archive = good
        (tmp_path / "out" / "site").mkdir(parents=True)
        with pytest.raises(PipelineError, match="existing directory"):
            rb.stage_rollback(
                target_receipt=target,
                deployed_receipt=deployed_receipt(tmp_path),
                archive=archive,
                out_dir=tmp_path / "out",
                target="production",
            )


class TestPlan:
    def test_repository_history_decides_the_rollback(self, repo: Path, good, tmp_path: Path) -> None:
        old = commit_files(repo, {"f": "1"})
        new = commit_files(repo, {"f": "2"})
        target, _ = good
        target["generation"] = {**gen().to_dict(), "trunk_sha": old, "corpus_sha": old}
        live = deployed_receipt(tmp_path, generation={**gen().to_dict(), "trunk_sha": new, "corpus_sha": new})

        decision, restored, deployed = rb.plan_rollback(repo_root=repo, target_receipt=target, deployed_receipt=live)
        assert decision.verdict is g.Verdict.DEPLOY
        assert restored.generation.trunk_sha == old and deployed.generation.trunk_sha == new

        # The same receipts in the other direction is a forward move, not a rollback.
        decision, _, _ = rb.plan_rollback(repo_root=repo, target_receipt=live, deployed_receipt=target)
        assert decision.verdict is g.Verdict.REFUSE

    def test_a_receipt_that_failed_its_probes_cannot_be_restored(self, repo: Path, tmp_path: Path) -> None:
        sha = commit_files(repo, {"f": "1"})
        site = write_site(tmp_path / "s")
        bad = r.finalize_receipt(
            candidate_receipt(
                site, tmp_path / "a.tar", generation={**gen().to_dict(), "trunk_sha": sha, "corpus_sha": sha}
            ),
            probes={"ok": False},
            deployment={"confirmed": True},
            observed_at="t",
        )
        decision, _, _ = rb.plan_rollback(repo_root=repo, target_receipt=bad, deployed_receipt=None)
        assert decision.verdict is g.Verdict.REFUSE
        assert any("probe" in reason or "live-verified" in reason for reason in decision.reasons)
