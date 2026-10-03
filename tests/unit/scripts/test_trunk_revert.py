from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
OID = "b" * 40
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def _load():
    spec = importlib.util.spec_from_file_location("trunk_revert", ROOT / "scripts/trunk_revert.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


trunk_revert = _load()


class FakeRun:
    def __init__(self, *, pr_view: dict | None = None, dirty: str = "", fail: dict[str, int] | None = None):
        self.pr_view = pr_view
        self.dirty = dirty
        self.fail = fail or {}
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> tuple[int, str]:
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "view"]:
            return 0, json.dumps(self.pr_view)
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return 0, self.dirty
        if cmd[:2] == ["gh", "pr"] and cmd[2] == "create":
            return 0, "https://github.com/BenchBox-dev/BenchBox/pull/99\n"
        for prefix, code in self.fail.items():
            if " ".join(cmd).startswith(prefix):
                return code, "boom"
        return 0, ""


def _merged(title: str = "fix(x): thing") -> dict:
    return {"state": "MERGED", "mergeCommit": {"oid": OID}, "title": title}


def test_refuses_a_pr_that_is_not_merged(capsys: pytest.CaptureFixture[str]) -> None:
    run = FakeRun(pr_view={"state": "OPEN", "mergeCommit": None, "title": "t"})
    assert trunk_revert.revert(12, run=run) == 1
    assert "not MERGED" in capsys.readouterr().err
    assert not any(call[:2] == ["git", "revert"] or call[:2] == ["git", "switch"] for call in run.calls)


def test_refuses_a_dirty_worktree(capsys: pytest.CaptureFixture[str]) -> None:
    run = FakeRun(pr_view=_merged(), dirty=" M scripts/x.py\n")
    assert trunk_revert.revert(12, run=run) == 1
    assert "uncommitted or untracked" in capsys.readouterr().err
    assert not any(call[:2] == ["git", "switch"] for call in run.calls)


def test_builds_the_expected_revert_and_pr_commands(capsys: pytest.CaptureFixture[str]) -> None:
    run = FakeRun(pr_view=_merged("fix(x): thing"))
    assert trunk_revert.revert(12, run=run) == 0
    assert run.calls == [
        ["gh", "pr", "view", "12", "--repo", trunk_revert.REPOSITORY, "--json", "state,mergeCommit,title"],
        ["git", "status", "--porcelain"],
        ["git", "fetch", "origin", "develop", "--quiet"],
        ["git", "merge-base", "--is-ancestor", OID, "origin/develop"],
        ["git", "switch", "--no-track", "-c", "fix/revert-12", "origin/develop"],
        ["git", "revert", "--no-edit", OID],
        ["git", "commit", "--amend", "-m", 'Revert "fix(x): thing" (#12)', "-m", f"This reverts commit {OID}."],
        ["git", "push", "-u", "origin", "fix/revert-12"],
        [
            "gh",
            "pr",
            "create",
            "--repo",
            trunk_revert.REPOSITORY,
            "--base",
            "develop",
            "--head",
            "fix/revert-12",
            "--fill",
        ],
    ]
    assert "pull/99" in capsys.readouterr().out


def test_title_with_quotes_and_command_substitution_stays_one_argument() -> None:
    title = 'fix: "quoted" $(touch /tmp/pwned) `id` ; rm -rf /'
    run = FakeRun(pr_view=_merged(title))
    assert trunk_revert.revert(5, run=run) == 0
    amend = next(call for call in run.calls if call[:3] == ["git", "commit", "--amend"])
    assert amend[3] == "-m"
    assert amend[4] == f'Revert "{title}" (#5)'
    assert all(isinstance(part, str) for call in run.calls for part in call)
    assert not any(call[0] == "sh" or "-c" in call[:2] for call in run.calls)


def test_aborts_the_revert_when_it_conflicts(capsys: pytest.CaptureFixture[str]) -> None:
    run = FakeRun(pr_view=_merged(), fail={"git revert --no-edit": 1})
    assert trunk_revert.revert(12, run=run) == 1
    assert ["git", "revert", "--abort"] in run.calls
    assert not any(call[:2] == ["git", "push"] for call in run.calls)
    assert "git revert failed" in capsys.readouterr().err


def test_refuses_a_merge_commit_that_is_not_on_develop() -> None:
    run = FakeRun(pr_view=_merged(), fail={"git merge-base": 1})
    assert trunk_revert.revert(12, run=run) == 1
    assert not any(call[:2] == ["git", "switch"] for call in run.calls)


def _runs(*items: tuple[str, str | None, timedelta]) -> list[dict]:
    return [
        {"status": status, "conclusion": conclusion, "updatedAt": (NOW - age).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for status, conclusion, age in items
    ]


def _gate(runs: list[dict] | None, branch: str = "fix/thing", *, code: int = 0, out: str | None = None):
    payload = json.dumps(runs) if out is None else out

    def run(cmd: list[str]) -> tuple[int, str]:
        assert cmd[:3] == ["gh", "run", "list"]
        assert cmd[cmd.index("--workflow") :][:6] == ["--workflow", "trunk.yml", "--branch", "develop", "--limit", "5"]
        assert cmd[-2:] == ["--json", "conclusion,status,updatedAt"]
        return code, payload

    return trunk_revert.trunk_gate(branch, run=run, now=NOW)


def test_gate_allows_when_there_are_no_runs(capsys: pytest.CaptureFixture[str]) -> None:
    assert _gate([]) is None
    assert capsys.readouterr().err.count("warning") == 1


def test_gate_allows_when_gh_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert _gate(None, code=1, out="HTTP 404: workflow trunk.yml not found") is None
    assert capsys.readouterr().err.count("warning") == 1


def test_gate_allows_when_the_newest_run_is_green() -> None:
    assert (
        _gate(_runs(("completed", "success", timedelta(minutes=5)), ("completed", "failure", timedelta(hours=3))))
        is None
    )


def test_gate_allows_a_red_run_under_thirty_minutes() -> None:
    assert _gate(_runs(("completed", "failure", timedelta(minutes=29)))) is None


def test_gate_refuses_a_red_run_over_thirty_minutes() -> None:
    refusal = _gate(_runs(("completed", "failure", timedelta(minutes=31))))
    assert refusal is not None
    assert "red for 31 minutes" in refusal
    assert "make trunk-revert" in refusal


def test_gate_allows_red_then_green() -> None:
    runs = _runs(
        ("completed", "failure", timedelta(hours=2)),
        ("completed", "success", timedelta(hours=1)),
    )
    assert _gate(runs) is None


def test_gate_ignores_a_run_still_in_progress() -> None:
    runs = _runs(
        ("in_progress", None, timedelta(minutes=1)),
        ("completed", "failure", timedelta(hours=1)),
    )
    assert _gate(runs) is not None


def test_gate_exempts_revert_branches() -> None:
    assert _gate(_runs(("completed", "failure", timedelta(hours=5))), branch="fix/revert-12") is None


def test_main_gate_exits_nonzero_on_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(trunk_revert, "trunk_gate", lambda branch, run=None, repo="": "develop is red")
    assert trunk_revert.main(["gate", "--branch", "fix/x"]) == 1
    assert "Refusing to open PR: develop is red" in capsys.readouterr().err


def test_main_rejects_a_malformed_repo(capsys: pytest.CaptureFixture[str]) -> None:
    assert trunk_revert.main(["revert", "--pr", "3", "--repo", "not a repo"]) == 2
