"""The durable deployment record: Deployment statuses index receipts kept as workflow artifacts."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from scripts.site_deploy import receipt as r, state as s
from tests.unit.scripts.site_deploy.helpers import gen

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO = "o/r"


def description(run: int, *, verified: bool = True, index: int = 10) -> str:
    return r.deployment_description(gen(index=index), run, "a" * 64, verified=verified)


class FakeApi:
    def __init__(self, deployments: list[dict], statuses: dict[int, list[dict]]) -> None:
        self.deployments = deployments
        self.statuses = statuses
        self.calls: list[str] = []

    def __call__(self, path: str):
        self.calls.append(path)
        if "/statuses" in path:
            return self.statuses[int(path.split("/deployments/")[1].split("/")[0])]
        if "/deployments?" in path:
            return self.deployments
        raise AssertionError(path)


def status(state: str, text: str = "") -> dict:
    return {"state": state, "description": text}


class TestFindLiveRecord:
    def test_newest_live_site_deploy_record_wins(self) -> None:
        api = FakeApi(
            [{"id": 3}, {"id": 2}],
            {3: [status("success", description(300))], 2: [status("success", description(200))]},
        )
        record, foreign = s.find_live_record(REPO, api)
        assert record == s.LiveRecord(3, 300, True, description(300))
        assert foreign is False

    def test_status_history_is_read_newest_first(self) -> None:
        api = FakeApi([{"id": 3}], {3: [status("success", description(300)), status("success", "environment status")]})
        record, _ = s.find_live_record(REPO, api)
        assert record is not None and record.run_id == 300

    def test_foreign_writer_newer_than_our_record_is_flagged(self) -> None:
        api = FakeApi(
            [{"id": 4}, {"id": 3}],
            {4: [status("success", "Deployed by legacy workflow")], 3: [status("success", description(300))]},
        )
        record, foreign = s.find_live_record(REPO, api)
        assert record is not None and record.run_id == 300
        assert foreign is True

    def test_failed_pending_and_superseded_deployments_are_not_live(self) -> None:
        api = FakeApi(
            [{"id": 5}, {"id": 4}, {"id": 3}, {"id": 2}],
            {
                5: [status("failure", description(500))],
                4: [status("in_progress")],
                3: [status("inactive", description(300))],
                2: [status("success", description(200))],
            },
        )
        record, foreign = s.find_live_record(REPO, api)
        assert record is not None and record.run_id == 200 and foreign is False

    def test_deployment_that_failed_its_probes_is_still_the_live_record(self) -> None:
        api = FakeApi([{"id": 3}], {3: [status("success", description(300, verified=False))]})
        record, _ = s.find_live_record(REPO, api)
        assert record is not None and record.verified is False

    def test_no_site_deploy_history(self) -> None:
        assert s.find_live_record(REPO, FakeApi([], {})) == (None, False)
        legacy = FakeApi([{"id": 1}], {1: [status("success", "legacy")]})
        assert s.find_live_record(REPO, legacy) == (None, True)


def final_receipt(run_id: int) -> dict:
    return {
        "kind": r.RECEIPT_KIND,
        "schema_version": 1,
        "receipt_id": f"site-deploy-{run_id}-1",
        "operation": "deploy",
        "target": "production",
        "status": "live-verified",
        "generation": gen().to_dict(),
        "artifact": {"sha256": "a" * 64},
        "checksums": {"/": "b" * 64},
        "routes": [{"id": "landing"}],
        "workflow": {"run_id": str(run_id)},
    }


def zipped(data: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("receipt.json", json.dumps(data))
    return buffer.getvalue()


class RunApi:
    def __init__(self, run: dict, artifacts: list[dict]) -> None:
        self.run = run
        self.artifacts = artifacts

    def __call__(self, path: str):
        return {"artifacts": self.artifacts} if path.endswith("/artifacts") else self.run


GOOD_RUN = {"path": ".github/workflows/site-deploy.yml", "conclusion": "success", "head_branch": "develop"}
GOOD_ARTIFACT = {"id": 77, "name": "site-deploy-receipt-300", "expired": False}


class TestFetchReceipt:
    def test_downloads_and_validates_the_receipt_of_a_site_deploy_run(self) -> None:
        got = s.fetch_receipt(
            REPO, 300, RunApi(GOOD_RUN, [GOOD_ARTIFACT]), lambda repo, artifact_id: zipped(final_receipt(300))
        )
        assert got["receipt_id"] == "site-deploy-300-1"

    @pytest.mark.parametrize(
        ("run", "message"),
        [
            ({**GOOD_RUN, "path": ".github/workflows/docs.yml"}, "not a site-deploy run"),
            ({**GOOD_RUN, "conclusion": "failure"}, "did not conclude successfully"),
            ({**GOOD_RUN, "head_branch": "feature/x"}, "did not run from develop"),
        ],
    )
    def test_runs_of_other_workflows_branches_or_outcomes_are_refused(self, run: dict, message: str) -> None:
        with pytest.raises(r.ReceiptError, match=message):
            s.fetch_receipt(REPO, 300, RunApi(run, [GOOD_ARTIFACT]), lambda *_: zipped(final_receipt(300)))

    def test_failed_run_is_accepted_only_when_asked(self) -> None:
        failed = {**GOOD_RUN, "conclusion": "failure"}
        got = s.fetch_receipt(
            REPO, 300, RunApi(failed, [GOOD_ARTIFACT]), lambda *_: zipped(final_receipt(300)), allow_failed_run=True
        )
        assert got["workflow"]["run_id"] == "300"
        cancelled = {**GOOD_RUN, "conclusion": "cancelled"}
        with pytest.raises(r.ReceiptError):
            s.fetch_receipt(REPO, 300, RunApi(cancelled, [GOOD_ARTIFACT]), lambda *_: b"", allow_failed_run=True)

    def test_expired_or_missing_artifact_is_refused(self) -> None:
        with pytest.raises(r.ReceiptError, match="no unexpired artifact"):
            s.fetch_receipt(REPO, 300, RunApi(GOOD_RUN, [{**GOOD_ARTIFACT, "expired": True}]), lambda *_: b"")
        with pytest.raises(r.ReceiptError, match="no unexpired artifact"):
            s.fetch_receipt(REPO, 300, RunApi(GOOD_RUN, []), lambda *_: b"")

    def test_receipt_naming_another_run_is_refused(self) -> None:
        with pytest.raises(r.ReceiptError, match="names run"):
            s.fetch_receipt(REPO, 300, RunApi(GOOD_RUN, [GOOD_ARTIFACT]), lambda *_: zipped(final_receipt(999)))

    def test_invalid_receipt_is_refused(self) -> None:
        with pytest.raises(r.ReceiptError, match="invalid receipt"):
            s.fetch_receipt(REPO, 300, RunApi(GOOD_RUN, [GOOD_ARTIFACT]), lambda *_: zipped({"kind": "x"}))


def test_run_deployment_is_the_newest_created_since_the_run_started() -> None:
    deployments = [
        {"id": 1, "created_at": "2026-09-29T09:00:00Z"},
        {"id": 2, "created_at": "2026-09-29T10:05:00Z"},
        {"id": 3, "created_at": "2026-09-29T10:06:00Z"},
    ]
    assert s.find_run_deployment(REPO, lambda path: deployments, "a" * 40, "2026-09-29T10:00:00Z") == 3
    assert s.find_run_deployment(REPO, lambda path: deployments, "a" * 40, "2026-09-29T11:00:00Z") is None


def test_status_is_posted_with_the_receipt_index(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[tuple[str, dict]] = []
    monkeypatch.setattr(s, "gh_post", lambda path, fields: posted.append((path, fields)))
    s.record_deployment_status(REPO, 42, "site-deploy v1 ...", "https://example.invalid/run")
    assert posted == [
        (
            "repos/o/r/deployments/42/statuses",
            {
                "state": "success",
                "description": "site-deploy v1 ...",
                "log_url": "https://example.invalid/run",
                "environment": "github-pages",
            },
        )
    ]
