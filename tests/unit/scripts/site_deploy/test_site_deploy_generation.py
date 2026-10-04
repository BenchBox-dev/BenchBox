from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field

import pytest

from scripts.site_deploy import generation, receipt as receipt_module
from scripts.site_deploy.generation import DEPLOY, NOOP, REFUSE, Deployed
from tests.unit.scripts.site_deploy.site_deploy_fakes import SHA_A, SHA_B, SHA_C, FakeGitHub, make_receipt

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ORDER = {SHA_A: 1, SHA_B: 2, SHA_C: 3}
SIDE = "d" * 40


def ancestry(ancestor: str, descendant: str) -> bool:
    if SIDE in (ancestor, descendant):
        return ancestor == descendant
    return ORDER[ancestor] < ORDER[descendant]


def deployed(trunk: str = SHA_B, tag: str = "v0.4.1", corpus: str = "1" * 40, generation_number: int = 4) -> Deployed:
    return Deployed(
        generation=generation_number,
        trunk_sha=trunk,
        release_tag=tag,
        corpus_sha=corpus,
        run_id=40,
        receipt_sha256="e" * 64,
        artifact_sha256="f" * 64,
        ui_version=11,
        snapshot_version=11,
    )


def gate(
    trunk: str, tag: str = "v0.4.1", current: Deployed | None = None, mode: str = "deploy", corpus: str | None = None
):
    return generation.generation_gate(
        candidate_trunk=trunk,
        candidate_tag=tag,
        candidate_corpus=corpus,
        deployed=current,
        mode=mode,
        is_ancestor=ancestry,
    )


def test_first_generation_deploys_and_first_rollback_is_refused() -> None:
    assert gate(SHA_A).action == DEPLOY
    assert gate(SHA_A, mode="rollback").action == REFUSE


FORWARD_CASES = [
    (SHA_C, "v0.4.1", DEPLOY),
    (SHA_B, "v0.4.2", DEPLOY),
    (SHA_C, "v0.5.0", DEPLOY),
    (SHA_B, "v0.4.1", NOOP),
    (SHA_A, "v0.4.1", REFUSE),
    (SHA_C, "v0.4.0", REFUSE),
    (SHA_A, "v0.5.0", REFUSE),
    (SIDE, "v0.4.1", REFUSE),
    (SHA_B, "v0.4.0", REFUSE),
    (SHA_B, "v0.10.0", DEPLOY),
    (SHA_B, "v0.3.9", REFUSE),
]


def test_forward_modes_never_regress_trunk_or_release() -> None:
    for trunk, tag, expected in FORWARD_CASES:
        for mode in ("deploy", "preview"):
            assert gate(trunk, tag, deployed(), mode).action == expected


def test_identical_generation_redeploys_when_a_newer_deployment_carries_no_receipt() -> None:
    unreceipted = dataclasses.replace(deployed(), newer_unreceipted=True)
    assert gate(SHA_B, "v0.4.1", unreceipted).action == DEPLOY
    assert gate(SHA_B, "v0.4.1", unreceipted, "rollback").action == DEPLOY
    assert gate(SHA_B, "v0.4.1", deployed()).action == NOOP


def test_rollback_may_move_backwards_and_diverge_but_identical_state_is_noop() -> None:
    assert gate(SHA_A, "v0.3.0", deployed(), "rollback").action == DEPLOY
    assert gate(SIDE, "v0.4.1", deployed(), "rollback").action == DEPLOY
    assert gate(SHA_B, "v0.4.1", deployed(), "rollback").action == NOOP
    same_source_other_tree = generation.generation_gate(
        candidate_trunk=SHA_B,
        candidate_tag="v0.4.1",
        candidate_corpus="1" * 40,
        candidate_artifact="0" * 64,
        deployed=deployed(),
        mode="rollback",
        is_ancestor=ancestry,
    )
    assert same_source_other_tree.action == DEPLOY


def test_rollback_to_same_trunk_with_different_corpus_still_deploys() -> None:
    assert gate(SHA_B, "v0.4.1", deployed(corpus="1" * 40), "rollback", corpus="2" * 40).action == DEPLOY


def test_unknown_ancestry_fails_closed() -> None:
    def broken(ancestor: str, descendant: str) -> bool:
        raise generation.CandidateError("missing object")

    decision = generation.generation_gate(
        candidate_trunk=SHA_C, candidate_tag="v0.4.1", deployed=deployed(), mode="deploy", is_ancestor=broken
    )
    assert decision.action == REFUSE


@dataclass
class Pages:
    api: FakeGitHub
    current: dict | None = None
    clock: int = 0
    log: list[str] = field(default_factory=list)

    def read(self) -> Deployed | None:
        return generation.read_deployed(self.api.client(), self.api.load_receipt, allow_bootstrap=True)

    def resolve(self, trunk: str, tag: str = "v0.4.1") -> tuple[str, str | None, generation.Decision]:
        current = self.read()
        decision = gate(trunk, tag, current)
        return trunk, current.receipt_sha256 if current else None, decision

    def deploy(
        self, run_id: int, trunk: str, resolved: tuple[str, str | None, generation.Decision], tag: str = "v0.4.1"
    ) -> bool:
        _, resolved_sha, decision = resolved
        if decision.action != DEPLOY:
            self.log.append(f"run {run_id} {decision.action}")
            return False
        current = self.read()
        recheck = generation.recheck_decision(
            resolved_receipt_sha256=resolved_sha,
            deployed=current,
            candidate_trunk=trunk,
            candidate_tag=tag,
            candidate_corpus=None,
            mode="deploy",
            is_ancestor=ancestry,
        )
        if recheck.action != DEPLOY:
            self.log.append(f"run {run_id} recheck {recheck.action}")
            return False
        parent = None
        number = 1
        if current is not None:
            parent = {"generation": current.generation}
            number = current.generation + 1
        built = make_receipt(run_id=run_id, trunk=trunk, tag=tag, generation=number, parent=parent)
        self.clock += 1
        self.api.record_deployment(run_id * 10, built, f"2026-01-01T00:00:{self.clock:02d}Z")
        self.log.append(f"run {run_id} deployed {trunk[0]}")
        return True


def test_older_then_newer_arrival_deploys_both_in_order() -> None:
    pages = Pages(FakeGitHub())
    pages.deploy(1, SHA_A, pages.resolve(SHA_A))
    pages.deploy(2, SHA_B, pages.resolve(SHA_B))
    assert pages.read().trunk_sha == SHA_B
    assert pages.read().generation == 2
    assert pages.log == ["run 1 deployed a", "run 2 deployed b"]


def test_newer_then_older_arrival_refuses_the_delayed_older_run() -> None:
    pages = Pages(FakeGitHub())
    pages.deploy(2, SHA_B, pages.resolve(SHA_B))
    assert pages.deploy(1, SHA_A, pages.resolve(SHA_A)) is False
    assert pages.read().trunk_sha == SHA_B
    assert pages.log == ["run 2 deployed b", "run 1 refuse"]


def test_overlapping_runs_resolved_together_deploy_only_the_first_to_write() -> None:
    pages = Pages(FakeGitHub())
    resolved_a = pages.resolve(SHA_A)
    resolved_b = pages.resolve(SHA_B)
    assert pages.deploy(2, SHA_B, resolved_b) is True
    assert pages.deploy(1, SHA_A, resolved_a) is False
    assert pages.read().trunk_sha == SHA_B
    assert pages.log[-1] == "run 1 recheck refuse"


def test_overlapping_newer_run_resolved_before_older_wrote_is_rechecked_and_refused() -> None:
    pages = Pages(FakeGitHub())
    resolved_a = pages.resolve(SHA_A)
    resolved_b = pages.resolve(SHA_B)
    assert pages.deploy(1, SHA_A, resolved_a) is True
    assert pages.deploy(2, SHA_B, resolved_b) is False
    assert pages.log[-1] == "run 2 recheck refuse"
    retry = pages.resolve(SHA_B)
    assert pages.deploy(3, SHA_B, retry) is True
    assert pages.read().trunk_sha == SHA_B


def test_delayed_duplicate_of_the_deployed_generation_is_a_noop() -> None:
    pages = Pages(FakeGitHub())
    pages.deploy(1, SHA_B, pages.resolve(SHA_B))
    assert pages.resolve(SHA_B)[2].action == NOOP
    assert pages.deploy(2, SHA_B, pages.resolve(SHA_B)) is False


def test_read_deployed_uses_newest_successful_deployment_with_a_receipt() -> None:
    api = FakeGitHub()
    older = make_receipt(run_id=1, trunk=SHA_A)
    newer = make_receipt(run_id=2, trunk=SHA_B, generation=2)
    api.record_deployment(10, older, "2026-01-01T00:00:01Z")
    api.record_deployment(20, newer, "2026-01-01T00:00:02Z")
    api.deployments.append({"id": 30, "created_at": "2026-01-01T00:00:03Z"})
    api.statuses[30] = [{"state": "failure", "description": "x", "created_at": "2026-01-01T00:00:03Z"}]
    found = generation.read_deployed(api.client(), api.load_receipt)
    assert found is not None
    assert (found.trunk_sha, found.generation, found.run_id) == (SHA_B, 2, 2)


def _legacy_deployment(api: FakeGitHub, deployment_id: int, created: str) -> None:
    api.deployments.append({"id": deployment_id, "created_at": created})
    api.statuses[deployment_id] = [{"state": "success", "description": "legacy deploy", "created_at": created}]


def test_receiptless_newest_deployment_fails_closed_without_bootstrap() -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A), "2026-01-01T00:00:01Z")
    _legacy_deployment(api, 20, "2026-01-01T00:00:02Z")
    with pytest.raises(generation.GenerationAuthorityError, match="bootstrap"):
        generation.read_deployed(api.client(), api.load_receipt)


def test_bootstrap_narrows_the_guard_to_the_newest_receipt_bearing_generation() -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_B, generation=4), "2026-01-01T00:00:01Z")
    api.record_deployment(11, make_receipt(run_id=2, trunk=SHA_A, generation=3), "2026-01-01T00:00:00Z")
    _legacy_deployment(api, 20, "2026-01-01T00:00:02Z")
    found = generation.read_deployed(api.client(), api.load_receipt, allow_bootstrap=True)
    assert found is not None
    assert (found.trunk_sha, found.generation, found.newer_unreceipted) == (SHA_B, 4, True)
    assert gate(SHA_A, current=found).action == REFUSE
    assert gate(SHA_C, current=found).action == DEPLOY


def test_bootstrap_with_a_clean_history_does_not_flag_unreceipted_deployments() -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A), "2026-01-01T00:00:01Z")
    found = generation.read_deployed(api.client(), api.load_receipt, allow_bootstrap=True)
    assert found is not None and found.newer_unreceipted is False


def test_only_a_history_without_any_receipt_is_a_first_deploy() -> None:
    api = FakeGitHub()
    _legacy_deployment(api, 20, "2026-01-01T00:00:02Z")
    with pytest.raises(generation.GenerationAuthorityError):
        generation.read_deployed(api.client(), api.load_receipt)
    assert generation.read_deployed(api.client(), api.load_receipt, allow_bootstrap=True) is None


def test_empty_history_needs_bootstrap() -> None:
    api = FakeGitHub()
    with pytest.raises(generation.GenerationAuthorityError):
        generation.read_deployed(api.client(), api.load_receipt)
    assert generation.read_deployed(api.client(), api.load_receipt, allow_bootstrap=True) is None


def test_link_baseline_is_read_from_the_receipt() -> None:
    api = FakeGitHub()
    built = make_receipt(run_id=1, trunk=SHA_A)
    built["link_baseline"] = {"release_tag": "v0.4.1", "broken": 1, "links": [["/a", "/b", "missing path"]]}
    api.record_deployment(10, built, "2026-01-01T00:00:01Z")
    found = generation.read_deployed(api.client(), api.load_receipt)
    assert found is not None and found.link_baseline == {"v0.4.1": [["/a", "/b", "missing path"]]}


def test_receipt_that_does_not_match_its_recorded_digest_is_rejected() -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A), "2026-01-01T00:00:01Z")
    forged = json.loads(api.receipts[1])
    forged["trunk_sha"] = SHA_C
    api.receipts[1] = receipt_module.canonical_bytes(forged)
    with pytest.raises(generation.GenerationAuthorityError, match="does not match"):
        generation.read_deployed(api.client(), api.load_receipt)


def test_missing_receipt_artifact_fails_closed() -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A), "2026-01-01T00:00:01Z")

    def missing(run_id: int, expected_sha256: str | None = None) -> bytes:
        raise OSError("expired")

    with pytest.raises(generation.GenerationAuthorityError, match="unavailable"):
        generation.read_deployed(api.client(), missing)


def test_receipt_with_failed_probes_blocks_deploys_but_not_rollbacks() -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A, probes_ok=False), "2026-01-01T00:00:01Z")
    with pytest.raises(generation.GenerationAuthorityError, match="last-known-good"):
        generation.read_deployed(api.client(), api.load_receipt)
    found = generation.read_deployed(api.client(), api.load_receipt, require_good=False)
    assert found is not None and found.trunk_sha == SHA_A


def test_api_failure_reading_deployments_fails_closed() -> None:
    api = FakeGitHub(fail=True)
    with pytest.raises(generation.GenerationAuthorityError):
        generation.read_deployed(api.client(), api.load_receipt, allow_bootstrap=True)
