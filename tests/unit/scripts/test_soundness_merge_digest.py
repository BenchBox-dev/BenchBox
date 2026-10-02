"""Tests for the soundness merge digest."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "_project/scripts/soundness_merge_digest.py"

spec = importlib.util.spec_from_file_location("soundness_merge_digest", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
digest = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = digest
spec.loader.exec_module(digest)

HEAD = "a" * 40
OLD = "b" * 40
PUSHED = "2026-10-02T10:00:00Z"
BEFORE = "2026-10-02T09:00:00Z"
AFTER = "2026-10-02T11:00:00Z"
CONNECTOR = "chatgpt-codex-connector[bot]"


def commit(sha, committed_at, merge=False):
    return digest.PullCommit(sha, committed_at, merge)


def evidence(**overrides):
    fields = {"number": 7, "author": "dev", "commits": (commit(OLD, BEFORE), commit(HEAD, PUSHED))}
    fields.update(overrides)
    return digest.PullEvidence(**fields)


def test_connector_review_after_the_last_content_commit_is_a_signal():
    pull = evidence(reviews=(digest.Review(CONNECTOR, AFTER),))
    assert digest.review_signals(pull) == ("connector-review",)


def test_connector_review_before_the_last_content_commit_is_not_a_signal():
    pull = evidence(reviews=(digest.Review(CONNECTOR, BEFORE),))
    assert digest.review_signals(pull) == ()


def test_a_refresh_merge_after_the_review_keeps_the_signal():
    pull = evidence(
        commits=(commit(OLD, BEFORE), commit(HEAD, PUSHED), commit("c" * 40, AFTER, merge=True)),
        reviews=(digest.Review(CONNECTOR, "2026-10-02T10:30:00Z"),),
    )
    assert digest.review_signals(pull) == ("connector-review",)


def test_a_content_commit_after_the_review_drops_the_signal():
    pull = evidence(
        commits=(commit(OLD, BEFORE), commit(HEAD, AFTER)),
        reviews=(digest.Review(CONNECTOR, PUSHED),),
        reactions=(digest.Reaction(CONNECTOR, "+1", PUSHED),),
        comments=(digest.Comment("dev", "Reviewer: codex", PUSHED),),
    )
    assert digest.review_signals(pull) == ()


def test_connector_approval_must_follow_the_final_push():
    stale = evidence(reactions=(digest.Reaction(CONNECTOR, "+1", BEFORE),))
    fresh = evidence(reactions=(digest.Reaction(CONNECTOR, "+1", AFTER),))
    assert digest.review_signals(stale) == ()
    assert digest.review_signals(fresh) == ("connector-approval",)


def test_an_eyes_reaction_alone_is_not_a_signal():
    pull = evidence(reactions=(digest.Reaction(CONNECTOR, "eyes", AFTER),))
    assert digest.review_signals(pull) == ()


def test_a_thumbs_up_from_anyone_else_is_not_a_signal():
    pull = evidence(reactions=(digest.Reaction("dev", "+1", AFTER),))
    assert digest.review_signals(pull) == ()


def test_a_posted_external_review_after_the_final_push_is_a_signal():
    pull = evidence(comments=(digest.Comment("dev", "Reviewer: Agy\n\nNo findings.", AFTER),))
    assert digest.review_signals(pull) == ("external-review:agy",)


@pytest.mark.parametrize(
    "body",
    [
        "**Reviewer:** Codex CLI, read-only",
        "- Reviewer: muse",
        "Soundness review: external agy, plan mode",
        "External reviewer: codex",
    ],
)
def test_common_review_headings_are_recognised(body):
    pull = evidence(comments=(digest.Comment("dev", body, AFTER),))
    assert len(digest.review_signals(pull)) == 1


def test_a_posted_review_from_before_the_final_push_is_not_a_signal():
    pull = evidence(comments=(digest.Comment("dev", "Reviewer: codex", BEFORE),))
    assert digest.review_signals(pull) == ()


def test_a_comment_naming_an_unapproved_reviewer_is_not_a_signal():
    pull = evidence(comments=(digest.Comment("dev", "Reviewer: my own judgement", AFTER),))
    assert digest.review_signals(pull) == ()


def test_a_thread_started_before_a_refresh_merge_is_still_counted():
    threads = (digest.Thread(resolved=True, started_by=CONNECTOR, first_comment_sha=HEAD),)
    pull = evidence(
        commits=(commit(OLD, BEFORE), commit(HEAD, PUSHED), commit("c" * 40, AFTER, merge=True)),
        threads=threads,
    )
    assert digest.unreviewed_thread_count(pull) == 1


def test_a_reviewer_thread_resolved_on_the_final_head_is_counted():
    threads = (
        digest.Thread(resolved=True, started_by=CONNECTOR, first_comment_sha=HEAD),
        digest.Thread(resolved=True, started_by=CONNECTOR, first_comment_sha=OLD),
        digest.Thread(resolved=False, started_by=CONNECTOR, first_comment_sha=HEAD),
        digest.Thread(resolved=True, started_by="dev", first_comment_sha=HEAD),
    )
    assert digest.unreviewed_thread_count(evidence(threads=threads)) == 1


def test_a_commit_with_no_pull_request_needs_attention():
    entry = digest.classify("c" * 40, "direct push", ["AGENTS.md"], None)
    assert entry.needs_attention
    assert entry.reasons == ("no merged pull request",)


def test_a_reviewed_commit_with_no_flagged_thread_needs_none():
    pull = evidence(reviews=(digest.Review(CONNECTOR, AFTER),))
    entry = digest.classify("c" * 40, "change", ["AGENTS.md"], pull)
    assert not entry.needs_attention
    assert entry.reasons == ()


def test_a_reviewed_commit_with_a_flagged_thread_needs_attention():
    pull = evidence(
        reviews=(digest.Review(CONNECTOR, AFTER),),
        threads=(digest.Thread(resolved=True, started_by=CONNECTOR, first_comment_sha=HEAD),),
    )
    entry = digest.classify("c" * 40, "change", ["AGENTS.md"], pull)
    assert entry.needs_attention
    assert "resolved with no later commit" in entry.reasons[0]


def test_render_lists_each_commit_with_its_signal():
    pull = evidence(reviews=(digest.Review(CONNECTOR, AFTER),))
    entries = [
        digest.classify("c" * 40, "reviewed", ["AGENTS.md"], pull),
        digest.classify("d" * 40, "unreviewed", ["AGENTS.md"], evidence(number=8)),
    ]
    text = digest.render(entries, since="1" * 40, until="2" * 40)
    assert "| `ccccccccc` reviewed | #7 | connector-review | - |" in text
    assert "| `ddddddddd` unreviewed | #8 | none | no completed review after the last content commit |" in text


def test_render_reports_an_empty_range():
    assert digest.render([], since="1" * 40, until="2" * 40).endswith("None.")


@pytest.fixture
def stubbed(monkeypatch):
    calls = {"issues": [], "checkpoint": []}
    unreviewed = digest.classify("d" * 40, "unreviewed", ["AGENTS.md"], evidence(number=8))
    monkeypatch.setattr(digest, "run", lambda args, **_: HEAD + "\n")
    monkeypatch.setattr(digest, "read_checkpoint", lambda repo: "1" * 40)
    monkeypatch.setattr(digest, "collect_entries", lambda repo, ref, since: [unreviewed])
    monkeypatch.setattr(digest, "open_gap_issues", lambda repo, entries: calls["issues"].append(entries) or ["d" * 40])
    monkeypatch.setattr(digest, "write_checkpoint", lambda repo, sha, report: calls["checkpoint"].append(sha))
    return calls


def test_apply_opens_issues_and_then_advances_the_checkpoint(stubbed):
    assert digest.main(["--apply"]) == 0
    assert len(stubbed["issues"]) == 1
    assert stubbed["checkpoint"] == [HEAD]


def test_a_dry_run_changes_nothing(stubbed):
    assert digest.main([]) == 0
    assert stubbed["issues"] == []
    assert stubbed["checkpoint"] == []


def test_a_failed_read_does_not_advance_the_checkpoint(stubbed, monkeypatch):
    def broken(repo, ref, since):
        raise digest.ReadError("boom")

    monkeypatch.setattr(digest, "collect_entries", broken)
    assert digest.main(["--apply"]) == 2
    assert stubbed["issues"] == []
    assert stubbed["checkpoint"] == []


def test_a_malformed_response_does_not_advance_the_checkpoint(stubbed, monkeypatch):
    def malformed(repo, ref, since):
        raise KeyError("head")

    monkeypatch.setattr(digest, "collect_entries", malformed)
    assert digest.main(["--apply"]) == 2
    assert stubbed["checkpoint"] == []


def test_a_failure_while_opening_issues_does_not_advance_the_checkpoint(stubbed, monkeypatch):
    def broken(repo, entries):
        raise digest.ReadError("issue create failed")

    monkeypatch.setattr(digest, "open_gap_issues", broken)
    assert digest.main(["--apply"]) == 2
    assert stubbed["checkpoint"] == []


def test_the_first_apply_records_a_checkpoint_without_reporting(stubbed, monkeypatch):
    monkeypatch.setattr(digest, "read_checkpoint", lambda repo: None)
    assert digest.main(["--apply"]) == 0
    assert stubbed["checkpoint"] == [HEAD]
    assert stubbed["issues"] == []


def test_a_dry_run_without_a_checkpoint_asks_for_one(stubbed, monkeypatch):
    monkeypatch.setattr(digest, "read_checkpoint", lambda repo: None)
    assert digest.main([]) == 2
    assert stubbed["checkpoint"] == []


def test_commit_listing_follows_first_parents_in_order(monkeypatch):
    seen = {}

    def fake_run(args, **_):
        seen["args"] = list(args)
        return "x\ny\n"

    monkeypatch.setattr(digest, "run", fake_run)
    assert digest.merged_commits("origin/develop", "abc") == ["x", "y"]
    assert seen["args"][:5] == ["git", "log", "--first-parent", "--reverse", "--format=%H"]
    assert seen["args"][-1] == "abc..origin/develop"


MERGED = "e" * 40


def stub_github(monkeypatch, *, commits, pulls=None):
    pulls = [{"number": 7, "merge_commit_sha": MERGED}] if pulls is None else pulls

    def fake_json(*args):
        endpoint = args[1]
        if endpoint.endswith("/pulls"):
            return pulls
        if "/pulls/7" in endpoint:
            return {"user": {"login": "dev"}}
        raise AssertionError(endpoint)

    def fake_pages(endpoint):
        if endpoint.endswith("/commits"):
            return commits
        if endpoint.endswith("/reviews"):
            return [{"user": {"login": CONNECTOR}, "submitted_at": AFTER}]
        if endpoint.endswith("/reactions"):
            return [{"user": {"login": CONNECTOR}, "content": "+1", "created_at": AFTER}]
        if endpoint.endswith("/comments"):
            return [{"user": {"login": "dev"}, "body": None, "created_at": AFTER}]
        raise AssertionError(endpoint)

    monkeypatch.setattr(digest, "gh_json", fake_json)
    monkeypatch.setattr(digest, "gh_pages", fake_pages)
    monkeypatch.setattr(digest, "collect_threads", lambda repo, number: ())


def api_commit(sha, committed_at, parents):
    return {"sha": sha, "commit": {"committer": {"date": committed_at}}, "parents": [{"sha": "p"}] * parents}


def test_collection_marks_two_parent_commits_as_refresh_merges(monkeypatch):
    commits = [api_commit(OLD, BEFORE, 1), api_commit(HEAD, AFTER, 2)]
    stub_github(monkeypatch, commits=commits)
    pull = digest.collect_pull("o/r", MERGED)
    assert [c.is_merge for c in pull.commits] == [False, True]
    assert pull.content_cutoff == BEFORE
    assert digest.review_signals(pull) == ("connector-review", "connector-approval")


def test_collection_returns_none_without_a_pull_request_for_the_commit(monkeypatch):
    stub_github(monkeypatch, commits=[], pulls=[{"number": 9, "merge_commit_sha": "f" * 40}])
    assert digest.collect_pull("o/r", MERGED) is None


def test_collection_refuses_a_commit_list_at_the_api_limit(monkeypatch):
    commits = [api_commit(f"{i:040x}", BEFORE, 1) for i in range(digest.MAX_PULL_COMMITS)]
    stub_github(monkeypatch, commits=commits)
    with pytest.raises(digest.ReadError):
        digest.collect_pull("o/r", MERGED)
