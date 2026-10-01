"""Tests for scripts/pr_arm.py: arm the exact head, refuse on any live hold."""

from __future__ import annotations

import importlib.util
import json
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


def _view(**overrides) -> dict:
    view = {
        "number": 7,
        "state": "OPEN",
        "isDraft": False,
        "labels": [],
        "reviewDecision": "",
        "headRefOid": HEAD,
    }
    view.update(overrides)
    return view


class FakeGh:
    """Record every command; answer the PR view with canned state."""

    def __init__(self, view: dict, merge_code: int = 0, view_code: int = 0, view_text: str | None = None) -> None:
        self.view = view
        self.merge_code = merge_code
        self.view_code = view_code
        self.view_text = view_text
        self.calls: list[list[str]] = []

    def __call__(self, cmd: Sequence[str]) -> tuple[int, str]:
        self.calls.append(list(cmd))
        if cmd[:3] == ["gh", "pr", "view"]:
            return self.view_code, self.view_text if self.view_text is not None else json.dumps(self.view)
        if cmd[:3] == ["gh", "pr", "merge"]:
            return self.merge_code, "queued"
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, HEAD + "\n"
        raise AssertionError(f"unexpected command {cmd}")

    def merged(self) -> list[list[str]]:
        return [call for call in self.calls if call[:3] == ["gh", "pr", "merge"]]


def test_arms_the_exact_head_with_squash_and_match_head_commit() -> None:
    gh = FakeGh(_view())
    assert pr_arm.arm("7", HEAD, run=gh) == 0
    assert gh.merged() == [
        ["gh", "pr", "merge", "7", "--repo", pr_arm.REPOSITORY, "--squash", "--match-head-commit", HEAD]
    ]


def test_defaults_to_local_head_and_the_current_branch_pr() -> None:
    gh = FakeGh(_view())
    assert pr_arm.arm(None, None, run=gh) == 0
    view = next(call for call in gh.calls if call[:3] == ["gh", "pr", "view"])
    assert view[3] == "--repo"  # no PR selector: gh resolves the current branch
    assert gh.merged()[0][-1] == HEAD


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"labels": [{"name": "no-auto-merge"}]}, "durable hold label"),
        ({"labels": [{"name": "bug"}, {"name": "no-auto-merge"}]}, "durable hold label"),
        ({"reviewDecision": "CHANGES_REQUESTED"}, "requested changes"),
        ({"isDraft": True}, "draft"),
        ({"state": "CLOSED"}, "not OPEN"),
        ({"state": "MERGED"}, "not OPEN"),
        ({"headRefOid": "b" * 40}, "push first"),
    ],
)
def test_refuses_without_merging_when_the_live_pr_says_not_ready(
    override: dict, expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(_view(**override))
    assert pr_arm.arm("7", HEAD, run=gh) == 2
    assert gh.merged() == []
    assert expected in capsys.readouterr().err


def test_a_hold_label_wins_even_when_everything_else_is_fine() -> None:
    gh = FakeGh(_view(labels=[{"name": "no-auto-merge"}], reviewDecision="APPROVED"))
    assert pr_arm.arm("7", HEAD, run=gh) == 2
    assert gh.merged() == []


def test_reports_every_reason_not_just_the_first(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(_view(isDraft=True, labels=[{"name": "no-auto-merge"}]))
    assert pr_arm.arm("7", HEAD, run=gh) == 2
    err = capsys.readouterr().err
    assert "draft" in err
    assert "durable hold label" in err


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"view_code": 1, "view_text": "gh: not found"}, "cannot read the pull request"),
        ({"view_text": "not json"}, "unreadable pull request state"),
    ],
)
def test_fails_closed_when_the_live_state_cannot_be_read(
    kwargs: dict, expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(_view(), **kwargs)
    assert pr_arm.arm("7", HEAD, run=gh) == 1
    assert gh.merged() == []
    assert expected in capsys.readouterr().err


def test_passes_through_a_failing_merge() -> None:
    gh = FakeGh(_view(), merge_code=1)
    assert pr_arm.arm("7", HEAD, run=gh) == 1
    assert len(gh.merged()) == 1


def test_makefile_exposes_pr_arm_through_the_helper() -> None:
    makefile = (ROOT / "Makefile").read_text()
    assert "\npr-arm:\n" in makefile
    assert "scripts/pr_arm.py" in makefile
