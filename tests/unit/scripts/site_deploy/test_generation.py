"""Generation ordering: the serialized writer must never publish something older than what is live."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.site_deploy import generation as g
from tests.unit.scripts.site_deploy.helpers import commit_files, gen, git, sha

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def deployed(generation: g.Generation, **kwargs) -> g.DeployedState:
    return g.DeployedState(generation=generation, receipt_id="site-deploy-1-1", artifact_sha256="1" * 64, **kwargs)


def relate_by_index(candidate: g.Generation, current: g.Generation) -> g.Relations:
    """Ancestry stand-in for a linear history: a lower index is an ancestor."""

    def relation(a: int, b: int) -> g.Relation:
        if a == b:
            return g.Relation.SAME
        return g.Relation.DESCENDANT if a > b else g.Relation.ANCESTOR

    return g.Relations(
        trunk=relation(candidate.trunk_index, current.trunk_index),
        corpus=g.Relation.SAME,
    )


def run_serialized(order: list[g.Generation], start: g.DeployedState | None = None):
    """Apply decisions one after another, as the concurrency group makes them happen."""
    state = start
    outcomes: list[g.Decision] = []
    for candidate in order:
        relations = relate_by_index(candidate, state.generation) if state else None
        decision = g.decide_deploy(candidate, state, relations)
        outcomes.append(decision)
        if decision.allowed:
            state = deployed(
                candidate,
                quarantined_trunk_shas=state.quarantined_trunk_shas if state else frozenset(),
                quarantined_release_tags=state.quarantined_release_tags if state else frozenset(),
            )
    return outcomes, state


A, B, C = gen("a", 10), gen("b", 11), gen("c", 12)


def test_first_deploy_needs_no_ordering() -> None:
    decision = g.decide_deploy(A, None, None)
    assert decision.verdict is g.Verdict.FIRST_DEPLOY and decision.allowed


def test_newer_candidate_deploys() -> None:
    decision = g.decide_deploy(B, deployed(A), relate_by_index(B, A))
    assert decision.verdict is g.Verdict.DEPLOY


def test_older_candidate_is_refused() -> None:
    decision = g.decide_deploy(A, deployed(B), relate_by_index(A, B))
    assert decision.verdict is g.Verdict.REFUSE
    assert "older" in decision.reasons[0]


def test_identical_pins_are_a_noop() -> None:
    decision = g.decide_deploy(A, deployed(A), relate_by_index(A, A))
    assert decision.verdict is g.Verdict.NOOP and not decision.allowed


def test_diverged_trunk_is_refused() -> None:
    relations = g.Relations(trunk=g.Relation.DIVERGED, corpus=g.Relation.SAME)
    assert g.decide_deploy(B, deployed(A), relations).verdict is g.Verdict.REFUSE


def test_older_release_tag_is_refused_even_with_newer_trunk() -> None:
    older_tag = gen("b", 11, tag="v0.4.0")
    decision = g.decide_deploy(older_tag, deployed(gen("a", 10, tag="v0.4.1")), relate_by_index(older_tag, A))
    assert decision.verdict is g.Verdict.REFUSE
    assert "v0.4.0" in decision.reasons[0]


def test_newer_release_tag_with_same_trunk_deploys() -> None:
    newer_tag = gen("a", 10, tag="v0.4.2")
    decision = g.decide_deploy(newer_tag, deployed(A), relate_by_index(newer_tag, A))
    assert decision.verdict is g.Verdict.DEPLOY


@pytest.mark.parametrize("corpus_relation", [g.Relation.ANCESTOR, g.Relation.DIVERGED])
def test_corpus_may_not_move_backwards(corpus_relation: g.Relation) -> None:
    relations = g.Relations(trunk=g.Relation.DESCENDANT, corpus=corpus_relation)
    assert g.decide_deploy(B, deployed(A), relations).verdict is g.Verdict.REFUSE


def test_quarantined_commit_and_tag_are_refused() -> None:
    relations = g.Relations(trunk=g.Relation.DESCENDANT, corpus=g.Relation.SAME)
    blocked_commit = deployed(A, quarantined_trunk_shas=frozenset({B.trunk_sha}))
    assert g.decide_deploy(B, blocked_commit, relations).verdict is g.Verdict.REFUSE
    blocked_tag = deployed(A, quarantined_release_tags=frozenset({"v0.4.1"}))
    newer = gen("b", 11)
    assert g.decide_deploy(newer, blocked_tag, relations).verdict is g.Verdict.REFUSE


def test_relations_are_required_once_something_is_deployed() -> None:
    with pytest.raises(ValueError):
        g.decide_deploy(B, deployed(A), None)


class TestTriggerOrders:
    """Delayed and overlapping runs reach the writer in either order."""

    def test_runs_in_commit_order_both_deploy(self) -> None:
        outcomes, final = run_serialized([A, B])
        assert [o.verdict for o in outcomes] == [g.Verdict.FIRST_DEPLOY, g.Verdict.DEPLOY]
        assert final.generation == B

    def test_delayed_older_run_after_newer_is_refused(self) -> None:
        outcomes, final = run_serialized([B, A])
        assert [o.verdict for o in outcomes] == [g.Verdict.FIRST_DEPLOY, g.Verdict.REFUSE]
        assert final.generation == B

    def test_overlapping_duplicate_runs_deploy_once(self) -> None:
        outcomes, final = run_serialized([B, B, B])
        assert [o.verdict for o in outcomes] == [g.Verdict.FIRST_DEPLOY, g.Verdict.NOOP, g.Verdict.NOOP]
        assert final.generation == B

    @pytest.mark.parametrize(
        "order",
        [[A, B, C], [A, C, B], [B, A, C], [B, C, A], [C, A, B], [C, B, A]],
    )
    def test_every_arrival_order_ends_on_the_newest(self, order: list[g.Generation]) -> None:
        _, final = run_serialized(order)
        assert final.generation == C

    @pytest.mark.parametrize("order", [[A, B, C], [C, B, A], [B, C, A]])
    def test_deployed_generation_never_decreases(self, order: list[g.Generation]) -> None:
        state = None
        indexes: list[int] = []
        for candidate in order:
            _, state = run_serialized([candidate], state)
            indexes.append(state.generation.trunk_index)
        assert indexes == sorted(indexes)

    def test_a_newer_release_does_not_let_older_trunk_back_in(self) -> None:
        released = gen("b", 11, tag="v0.5.0")
        stale_trunk = gen("c", 12, tag="v0.4.1")
        outcomes, final = run_serialized([released, stale_trunk])
        assert outcomes[1].verdict is g.Verdict.REFUSE
        assert final.generation == released


def target(generation: g.Generation, **overrides) -> g.RollbackTarget:
    values = {
        "receipt_id": "site-deploy-9-1",
        "generation": generation,
        "artifact_sha256": "9" * 64,
        "target": "production",
        "status": "live-verified",
        "probes_ok": True,
        "deployment_confirmed": True,
    }
    values.update(overrides)
    return g.RollbackTarget(**values)


class TestRollbackDecision:
    older_relations = g.Relations(trunk=g.Relation.ANCESTOR, corpus=g.Relation.SAME)

    def test_probed_green_older_generation_may_be_restored(self) -> None:
        decision = g.decide_rollback(target(A), deployed(B), self.older_relations)
        assert decision.verdict is g.Verdict.DEPLOY

    @pytest.mark.parametrize(
        "override",
        [
            {"status": "probe-failed"},
            {"status": "candidate"},
            {"probes_ok": False},
            {"deployment_confirmed": False},
            {"target": "preview"},
            {"artifact_sha256": "not-a-digest"},
        ],
    )
    def test_receipts_that_were_not_probed_green_in_production_are_refused(self, override: dict) -> None:
        decision = g.decide_rollback(target(A, **override), deployed(B), self.older_relations)
        assert decision.verdict is g.Verdict.REFUSE

    def test_newer_target_is_not_a_rollback(self) -> None:
        relations = g.Relations(trunk=g.Relation.DESCENDANT, corpus=g.Relation.SAME)
        assert g.decide_rollback(target(C), deployed(B), relations).verdict is g.Verdict.REFUSE

    def test_diverged_target_is_refused(self) -> None:
        relations = g.Relations(trunk=g.Relation.DIVERGED, corpus=g.Relation.SAME)
        assert g.decide_rollback(target(A), deployed(B), relations).verdict is g.Verdict.REFUSE

    def test_target_with_newer_release_tag_is_refused(self) -> None:
        newer_tag = gen("a", 10, tag="v0.5.0")
        assert g.decide_rollback(target(newer_tag), deployed(B), self.older_relations).verdict is g.Verdict.REFUSE

    def test_quarantined_target_is_refused(self) -> None:
        state = deployed(B, quarantined_trunk_shas=frozenset({A.trunk_sha}))
        assert g.decide_rollback(target(A), state, self.older_relations).verdict is g.Verdict.REFUSE

    def test_rolling_back_to_what_is_live_is_a_noop(self) -> None:
        same = g.Relations(trunk=g.Relation.SAME, corpus=g.Relation.SAME)
        live = deployed(A)
        decision = g.decide_rollback(target(A, receipt_id=live.receipt_id), live, same)
        assert decision.verdict is g.Verdict.NOOP

    def test_unconfirmed_live_state_never_short_circuits(self) -> None:
        same = g.Relations(trunk=g.Relation.SAME, corpus=g.Relation.SAME)
        live = deployed(A)
        decision = g.decide_rollback(target(A, receipt_id=live.receipt_id), live, same, live_unconfirmed=True)
        assert decision.verdict is g.Verdict.DEPLOY

    def test_nothing_to_roll_back_from_is_refused(self) -> None:
        assert g.decide_rollback(target(A), None, None).verdict is g.Verdict.REFUSE

    def test_rolled_back_generation_is_quarantined(self) -> None:
        live = deployed(gen("b", 11, tag="v0.5.0"), quarantined_trunk_shas=frozenset({sha("z")}))
        trunk, tags = g.quarantine_after_rollback(live, A)
        assert trunk == {sha("z"), sha("b")}
        assert tags == {"v0.5.0"}

    def test_unchanged_release_tag_is_not_quarantined(self) -> None:
        trunk, tags = g.quarantine_after_rollback(deployed(B), A)
        assert trunk == {B.trunk_sha} and tags == frozenset()


def test_generation_validates_its_pins() -> None:
    with pytest.raises(ValueError):
        g.Generation("short", 1, "v0.4.1", sha("c"))
    with pytest.raises(ValueError):
        g.Generation(sha("a"), 1, "0.4.1", sha("c"))
    with pytest.raises(ValueError):
        g.Generation.from_dict({"trunk_sha": sha("a")})


def test_release_versions_compare_numerically() -> None:
    assert g.release_version("v0.10.0") > g.release_version("v0.9.9")


def test_generation_round_trips_through_a_receipt_mapping() -> None:
    assert g.Generation.from_dict(A.to_dict()) == A


class TestGitFacts:
    def test_relations_follow_real_ancestry(self, repo: Path) -> None:
        first = commit_files(repo, {"f": "1"})
        second = commit_files(repo, {"f": "2"})
        git(repo, "checkout", "-q", "-b", "side", first)
        side = commit_files(repo, {"g": "1"})

        assert g.git_relation(repo, second, second) is g.Relation.SAME
        assert g.git_relation(repo, second, first) is g.Relation.DESCENDANT
        assert g.git_relation(repo, first, second) is g.Relation.ANCESTOR
        assert g.git_relation(repo, side, second) is g.Relation.DIVERGED

    def test_unknown_commit_fails_closed(self, repo: Path) -> None:
        first = commit_files(repo, {"f": "1"})
        assert g.git_relation(repo, sha("f"), first) is g.Relation.DIVERGED

    def test_trunk_index_counts_first_parent_commits(self, repo: Path) -> None:
        first = commit_files(repo, {"f": "1"})
        second = commit_files(repo, {"f": "2"})
        assert g.trunk_index(repo, first) == 1
        assert g.trunk_index(repo, second) == 2
        assert g.first_parent_shas(repo, second, 10) == [second, first]

    def test_trunk_index_rejects_unknown_commits(self, repo: Path) -> None:
        commit_files(repo, {"f": "1"})
        with pytest.raises(ValueError):
            g.trunk_index(repo, sha("f"))
