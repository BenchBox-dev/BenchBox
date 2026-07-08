"""Unit tests for the orphaned-commit detector's pure classification logic.

The git/GitHub-API I/O is exercised by the scheduled workflow itself; here we
pin the allowlist parsing and the new-vs-acknowledged split with no network.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "_project" / "scripts" / "detect_orphaned_commits.py"
_ALLOWLIST = _ROOT / "_project" / "analysis" / "known-stranded-commits.txt"


def _load():
    spec = importlib.util.spec_from_file_location("_detect_orphans", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()

# The four historical, resolved orphans that must be allowlisted.
KNOWN = {
    "43c4f689bf8e739ed633c997153321accfc284fc",  # §2.7  → #986
    "cf394466a1422db63ea93546ef1d870d6d90c28a",  # §2.16 → #996
    "4865a2f24e5aed743d6209956da7b53a3d4d1de1",  # §2.22 → #997
    "3368763728794ed7d9bc54e8f6a6029e6c8d6526",  # §2.22 → #997
}


def test_parse_allowlist_ignores_comments_and_blanks() -> None:
    text = "# a comment\n\nABCDEF0123  # trailing note\n  99AA11  \n"
    assert mod.parse_allowlist(text) == {"abcdef0123", "99aa11"}


def test_the_four_known_orphans_are_allowlisted_in_the_repo_file() -> None:
    allow = mod.parse_allowlist(_ALLOWLIST.read_text(encoding="utf-8"))
    for sha in KNOWN:
        assert mod.is_acknowledged(sha, allow), f"{sha} must be in the shipped allowlist"


def test_is_acknowledged_is_prefix_aware_both_directions() -> None:
    allow = {"cf394466a1422db63ea93546ef1d870d6d90c28a"}
    assert mod.is_acknowledged("cf394466", allow)  # short query vs full allowlist
    assert mod.is_acknowledged("cf394466a1422db63ea93546ef1d870d6d90c28a", allow)
    assert not mod.is_acknowledged("deadbeef", allow)


def test_classify_splits_new_from_acknowledged() -> None:
    allow = set(KNOWN)
    branch_orphans = {
        "remediate-qa-and-browser-test-doc-accuracy": ["cf394466a1422db63ea93546ef1d870d6d90c28a"],
        "some-future-branch": ["0000000000000000000000000000000000000000"],
        "mixed-branch": [
            "43c4f689bf8e739ed633c997153321accfc284fc",  # known
            "1111111111111111111111111111111111111111",  # new
        ],
    }
    new, ack = mod.classify(branch_orphans, allow)
    # The purely-known branch is only in acknowledged, never in new.
    assert "remediate-qa-and-browser-test-doc-accuracy" not in new
    assert "remediate-qa-and-browser-test-doc-accuracy" in ack
    # The purely-new branch fails.
    assert new["some-future-branch"] == ["0000000000000000000000000000000000000000"]
    # A mixed branch reports only its fresh commit under new.
    assert new["mixed-branch"] == ["1111111111111111111111111111111111111111"]
    assert ack["mixed-branch"] == ["43c4f689bf8e739ed633c997153321accfc284fc"]


def test_no_orphans_means_empty_new() -> None:
    new, ack = mod.classify({}, set(KNOWN))
    assert new == {}
    assert ack == {}


@pytest.mark.parametrize(
    "branch,structural",
    [
        ("main", True),
        ("release", True),
        ("published-results", True),
        ("v0.3.1", True),
        ("auto-revert/0ca8b88b", True),
        ("remediate-governance-and-doc-drift", False),
        ("feat/some-feature", False),
        # A "v..." name that is NOT a version tag must not be skipped.
        ("verify-ci-validation-workflow-end-to-end", False),
        ("validate-submission-self-green-guard", False),
        ("v1.2.3", True),
    ],
)
def test_is_structural(branch: str, structural: bool) -> None:
    assert mod.is_structural(branch) is structural


class TestMergedHeadForBranch:
    """#1020 review: use the LATEST PR (by number) as the cutoff, and skip
    the branch entirely when that latest PR closed without merging - an
    older merged PR's head must never be used as the diff cutoff when a
    later PR on the same branch name exists, merged or not."""

    def test_single_merged_pr_returns_its_head(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            mod,
            "_api",
            lambda _url, _token: [
                {"number": 10, "state": "closed", "merged_at": "2026-01-01T00:00:00Z", "head": {"sha": "a" * 40}},
            ],
        )
        assert mod.merged_head_for_branch("o", "r", "b", "tok") == "a" * 40

    def test_open_pr_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            mod,
            "_api",
            lambda _url, _token: [
                {"number": 10, "state": "open", "merged_at": None, "head": {"sha": "a" * 40}},
            ],
        )
        assert mod.merged_head_for_branch("o", "r", "b", "tok") is None

    def test_no_prs_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_api", lambda _url, _token: [])
        assert mod.merged_head_for_branch("o", "r", "b", "tok") is None

    def test_reused_branch_older_merged_then_later_closed_unmerged_skips_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exact false-positive scenario: PR#10 merged the branch long
        ago; the branch name was reused for PR#20, which was closed without
        merging. Commits pushed for PR#20 already had real PR coverage, so
        the branch must be skipped (None), not diffed from PR#10's stale
        head."""
        monkeypatch.setattr(
            mod,
            "_api",
            lambda _url, _token: [
                {"number": 10, "state": "closed", "merged_at": "2026-01-01T00:00:00Z", "head": {"sha": "a" * 40}},
                {"number": 20, "state": "closed", "merged_at": None, "head": {"sha": "b" * 40}},
            ],
        )
        assert mod.merged_head_for_branch("o", "r", "b", "tok") is None

    def test_reused_branch_older_merged_then_later_also_merged_uses_latest_head(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            mod,
            "_api",
            lambda _url, _token: [
                {"number": 10, "state": "closed", "merged_at": "2026-01-01T00:00:00Z", "head": {"sha": "a" * 40}},
                {"number": 20, "state": "closed", "merged_at": "2026-02-01T00:00:00Z", "head": {"sha": "b" * 40}},
            ],
        )
        assert mod.merged_head_for_branch("o", "r", "b", "tok") == "b" * 40
