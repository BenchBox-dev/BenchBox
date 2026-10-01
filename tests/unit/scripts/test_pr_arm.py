"""Tests for scripts/pr_arm.py: arm the exact head, refuse on any live hold."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
HEAD = "a" * 40


def _load():
    spec = importlib.util.spec_from_file_location("pr_arm", ROOT / "scripts/pr_arm.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pr_arm = _load()
LandingError = pr_arm.pr_landing.LandingError


def _view(**overrides) -> dict:
    view = {
        "number": 7,
        "state": "OPEN",
        "isDraft": False,
        "labels": [],
        "reviewDecision": "",
        "headRefOid": HEAD,
        "baseRefName": "develop",
    }
    view.update(overrides)
    return view


class FakeGh:
    """Record every command and answer like the real `git` and `gh` would, including their refusals."""

    def __init__(self, view: dict | str | None = None, listed: list[int] | str | None = None, **kwargs) -> None:
        self.view = _view() if view is None else view
        self.listed = [7] if listed is None else listed
        self.merge_code = kwargs.get("merge_code", 0)
        self.view_code = kwargs.get("view_code", 0)
        self.local_head = kwargs.get("local_head", HEAD)
        self.calls: list[list[str]] = []

    def __call__(self, cmd: Sequence[str]) -> tuple[int, str]:
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd == ["git", "rev-parse", "HEAD"]:
            return 0, self.local_head + "\n"
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return 0, "fix/thing\n"
        if cmd[:3] == ["gh", "pr", "list"]:
            body = self.listed if isinstance(self.listed, str) else json.dumps([{"number": n} for n in self.listed])
            return 0, body
        if cmd[:3] == ["gh", "pr", "view"]:
            # Real gh rejects --repo with no PR argument ("argument required when using the --repo flag").
            assert len(cmd) > 3 and not cmd[3].startswith("-"), f"gh pr view needs a selector: {cmd}"
            body = self.view if isinstance(self.view, str) else json.dumps(self.view)
            return self.view_code, body
        if cmd[:3] == ["gh", "pr", "merge"]:
            return self.merge_code, "queued"
        raise AssertionError(f"unexpected command {cmd}")

    def merged(self) -> list[list[str]]:
        return [call for call in self.calls if call[:3] == ["gh", "pr", "merge"]]


def _arm(gh: FakeGh, pr: str | None = "7", head: str | None = None, *, unpublished=(), threads=False) -> int:
    return pr_arm.arm(
        pr,
        head,
        run=gh,
        unpublished=lambda _checkout: list(unpublished),
        threads=lambda _run, _repo, _number: threads,
    )


def test_arms_the_exact_head_with_squash_and_match_head_commit() -> None:
    gh = FakeGh()
    assert _arm(gh) == 0
    assert gh.merged() == [
        ["gh", "pr", "merge", "7", "--repo", pr_arm.REPOSITORY, "--squash", "--match-head-commit", HEAD]
    ]


def test_default_resolves_the_current_branch_pr_before_viewing_it() -> None:
    gh = FakeGh(listed=[7])
    assert _arm(gh, pr=None) == 0
    listing = next(call for call in gh.calls if call[:3] == ["gh", "pr", "list"])
    assert listing[listing.index("--head") + 1] == "fix/thing"
    assert listing[listing.index("--base") + 1] == "develop"
    view = next(call for call in gh.calls if call[:3] == ["gh", "pr", "view"])
    assert view[3] == "7"  # an explicit selector, never a bare `gh pr view --repo`


@pytest.mark.parametrize("listed", [[], [7, 8]])
def test_default_refuses_when_the_branch_does_not_name_exactly_one_pr(
    listed: list[int], capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(listed=listed)
    assert _arm(gh, pr=None) == 1
    assert gh.merged() == []
    assert "expected exactly one open PR" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("view", "extra", "expected"),
    [
        (_view(labels=[{"name": "no-auto-merge"}]), {}, "durable hold label"),
        (_view(labels=[{"name": "bug"}, {"name": "no-auto-merge"}]), {}, "durable hold label"),
        (_view(reviewDecision="CHANGES_REQUESTED"), {}, "requested changes"),
        (_view(isDraft=True), {}, "draft"),
        (_view(state="CLOSED"), {}, "not OPEN"),
        (_view(state="MERGED"), {}, "not OPEN"),
        (_view(baseRefName="feature/x"), {}, "arms only PRs into 'develop'"),
        (_view(baseRefName="release"), {}, "arms only PRs into 'develop'"),
        (_view(headRefOid="b" * 40), {}, "push first"),
        (_view(), {"threads": True}, "unresolved, non-outdated review thread"),
        (_view(), {"unpublished": ["uncommitted working-tree changes"]}, "unpublished work"),
        (_view(), {"unpublished": ["2 local commit(s) not pushed to upstream"]}, "not pushed"),
    ],
)
def test_refuses_without_merging_when_the_live_pr_says_not_ready(
    view: dict, extra: dict, expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(view=view)
    assert _arm(gh, **extra) == 2
    assert gh.merged() == []
    assert expected in capsys.readouterr().err


def test_an_expected_head_that_is_not_local_head_is_refused_before_any_gh_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # PR head A is pushed, but local HEAD holds an unpushed correction B: HEAD=A must not arm A.
    gh = FakeGh(view=_view(headRefOid="a" * 40), local_head="b" * 40)
    assert _arm(gh, head="a" * 40) == 2
    assert gh.merged() == []
    assert not any(call[:2] == ["gh", "pr"] for call in gh.calls)
    assert "is not local HEAD" in capsys.readouterr().err


def test_a_matching_expected_head_is_accepted() -> None:
    gh = FakeGh()
    assert _arm(gh, head=HEAD) == 0
    assert gh.merged()[0][-1] == HEAD


def test_reports_every_reason_not_just_the_first(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(view=_view(isDraft=True, labels=[{"name": "no-auto-merge"}], baseRefName="release"))
    assert _arm(gh, threads=True) == 2
    err = capsys.readouterr().err
    for expected in ("draft", "durable hold label", "arms only PRs into", "review thread"):
        assert expected in err


@pytest.mark.parametrize(
    ("gh", "expected"),
    [
        (FakeGh(view="gh: not found", view_code=1), "cannot read the pull request"),
        (FakeGh(view="not json"), "live state could not be verified"),
        (FakeGh(view="[]"), "live state could not be verified"),  # valid JSON of the wrong shape
        (FakeGh(view="{}"), "live state could not be verified"),
        (FakeGh(listed="not json"), "live state could not be verified"),
    ],
)
def test_fails_closed_when_the_live_state_cannot_be_read(
    gh: FakeGh, expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _arm(gh, pr=None if gh.listed == "not json" else "7") == 1
    assert gh.merged() == []
    assert expected in capsys.readouterr().err


def test_fails_closed_when_the_review_thread_check_cannot_run(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh()

    def broken(*_args) -> bool:
        raise LandingError("live review-thread verification failed for PR #7")

    code = pr_arm.arm("7", None, run=gh, unpublished=lambda _c: [], threads=broken)
    assert code == 1
    assert gh.merged() == []
    assert "live state could not be verified" in capsys.readouterr().err


def test_fails_closed_when_a_command_cannot_be_executed(capsys: pytest.CaptureFixture[str]) -> None:
    def missing(_cmd: Sequence[str]) -> tuple[int, str]:
        raise FileNotFoundError("gh")

    assert pr_arm.arm("7", None, run=missing, unpublished=lambda _c: [], threads=lambda *_a: False) == 1
    assert "live state could not be verified" in capsys.readouterr().err


def test_a_hold_label_wins_even_when_everything_else_is_fine() -> None:
    gh = FakeGh(view=_view(labels=[{"name": "no-auto-merge"}], reviewDecision="APPROVED"))
    assert _arm(gh) == 2
    assert gh.merged() == []


def test_passes_through_a_failing_merge() -> None:
    gh = FakeGh(merge_code=1)
    assert _arm(gh) == 1
    assert len(gh.merged()) == 1


def test_makefile_exposes_pr_arm_through_the_helper_and_declares_it_phony() -> None:
    makefile = (ROOT / "Makefile").read_text()
    assert "\npr-arm:\n" in makefile
    assert "scripts/pr_arm.py" in makefile
    phony = next(line for line in makefile.splitlines() if line.startswith(".PHONY: pr-arm "))
    assert re.search(r"(?<![\w-])pr-arm(?![\w-])", phony)
