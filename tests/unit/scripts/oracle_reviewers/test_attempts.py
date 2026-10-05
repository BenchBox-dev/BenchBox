from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from _project.scripts.oracle_reviewers import attempts, cli, report, selection
from _project.scripts.oracle_reviewers.absence import Absence
from _project.scripts.oracle_reviewers.diff import commentable_lines
from _project.scripts.oracle_reviewers.policy import Policy
from _project.scripts.oracle_reviewers.selection import SelectionInput, excluded_families

pytestmark = [pytest.mark.unit, pytest.mark.fast]

RUN_ID = "4242"
HEAD = "a" * 40
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
DIFF = """diff --git a/benchbox/core/equivalence/checker.py b/benchbox/core/equivalence/checker.py
--- a/benchbox/core/equivalence/checker.py
+++ b/benchbox/core/equivalence/checker.py
@@ -1,1 +1,2 @@
 a = 1
+b = 2
"""


def _plan(policy: Policy, tier: str = "medium-high", labels: tuple[str, ...] = ("author-family:muse",)) -> dict:
    return {
        "schema": 1,
        "mode": "shadow",
        "status_context": policy.status_context,
        "findings_delivery": "comment",
        "repo": "BenchBox-dev/BenchBox",
        "pr": 7,
        "run_id": RUN_ID,
        "base_sha": "b" * 40,
        "head_sha": HEAD,
        "decision": "review",
        "decision_reason": "",
        "tier": tier,
        "tier_reasons": ["changes comparison logic"],
        "blocking": list(policy.tiers[tier].blocking),
        "chain": [reviewer.to_json() for reviewer in policy.chain(tier)],
        "diversity_exempt": list(policy.tiers[tier].diversity_exempt),
        "excluded_families": sorted(excluded_families(labels, policy)),
        "brief_mode": "inline",
        "max_attempts": policy.max_attempts,
        "pool_blocked_until": {},
        "manual": False,
        "previous_state": None,
    }


def _finding(severity: str, line: int = 2) -> dict[str, Any]:
    return {
        "severity": severity,
        "file": "benchbox/core/equivalence/checker.py",
        "line": line,
        "title": f"{severity} issue",
        "detail": "see @someone at https://example.com",
    }


def _write(
    directory: Path,
    slot: int,
    reviewer: str,
    *,
    verdict: dict | None = None,
    missing: Absence | None = None,
    **over: Any,
) -> None:
    artifact = attempts.build_artifact(
        run_id=RUN_ID, pr=7, head_sha=HEAD, slot=slot, reviewer=reviewer, verdict=verdict, missing=missing
    )
    artifact.update(over)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / attempts.artifact_name(slot)).write_text(json.dumps(artifact), encoding="utf-8")


def _decide(policy: Policy, plan: dict, directory: Path):
    loaded = attempts.load(directory, plan, RUN_ID)
    step, errors = attempts.decide(SelectionInput.from_plan(plan, NOW), loaded)
    return loaded, step, errors


def test_absence_then_clean_verdict_passes(policy: Policy, tmp_path: Path) -> None:
    plan = _plan(policy)
    _write(tmp_path, 1, "sonnet", missing=Absence("timeout", "slow"))
    _write(tmp_path, 2, "sol", verdict={"summary": "ok", "findings": [_finding("Medium")]})
    loaded, step, errors = _decide(policy, plan, tmp_path)
    assert errors == []
    assert step.kind == selection.PASS
    final = report.finalize(plan, step, errors, loaded.attempts, loaded.verdicts, {})
    assert final.state == "success"
    assert final.description == "sol: no blocking findings"
    assert "sonnet: absent (timeout)" in final.body


def test_blocking_verdict_fails_and_splits_findings(policy: Policy, tmp_path: Path) -> None:
    plan = _plan(policy)
    findings = [_finding("High", 2), _finding("Low", 40)]
    _write(tmp_path, 1, "sonnet", verdict={"summary": "bad", "findings": findings})
    loaded, step, errors = _decide(policy, plan, tmp_path)
    assert step.kind == selection.FAIL
    final = report.finalize(plan, step, errors, loaded.attempts, loaded.verdicts, commentable_lines(DIFF))
    assert final.state == "failure"
    assert final.description == "sonnet: 1 blocking finding(s)"
    inline, outside = final.body.split("**Findings outside the diff**")
    assert "checker.py:2`" in inline and "checker.py:40`" in outside
    assert "@someone" not in final.body and "https://" not in final.body
    assert "Shadow mode" in final.body


def test_review_delivery_builds_line_threads_only_inside_the_diff(policy: Policy, tmp_path: Path) -> None:
    plan = {**_plan(policy), "findings_delivery": "review"}
    _write(tmp_path, 1, "sonnet", verdict={"summary": "bad", "findings": [_finding("High", 2), _finding("Low", 40)]})
    loaded, step, errors = _decide(policy, plan, tmp_path)
    final = report.finalize(plan, step, errors, loaded.attempts, loaded.verdicts, commentable_lines(DIFF))
    assert final.review is not None
    assert final.review["commit_id"] == HEAD
    assert [(item["path"], item["line"], item["side"]) for item in final.review["comments"]] == [
        ("benchbox/core/equivalence/checker.py", 2, "RIGHT")
    ]
    assert "checker.py:40`" in final.review["body"]


def test_artifact_from_another_run_or_head_is_rejected(policy: Policy, tmp_path: Path) -> None:
    plan = _plan(policy)
    _write(tmp_path, 1, "sonnet", verdict={"summary": "", "findings": []}, run_id="1")
    _, _, errors = _decide(policy, plan, tmp_path)
    assert any("another run" in error for error in errors)
    other = tmp_path / "head"
    _write(other, 1, "sonnet", verdict={"summary": "", "findings": []}, head_sha="c" * 40)
    loaded, step, errors = _decide(policy, plan, other)
    assert any("another head" in error for error in errors)
    final = report.finalize(plan, step, errors, loaded.attempts, loaded.verdicts, {})
    assert final.state == "pending"


def test_out_of_order_reviewer_fails_the_replay(policy: Policy, tmp_path: Path) -> None:
    plan = _plan(policy)
    _write(tmp_path, 1, "luna", verdict={"summary": "", "findings": []})
    loaded, step, errors = _decide(policy, plan, tmp_path)
    assert errors == ["slot 1 ran luna, but the policy selects sonnet"]
    assert report.finalize(plan, step, errors, loaded.attempts, loaded.verdicts, {}).state == "pending"


def test_reviewer_outside_the_chain_is_rejected(policy: Policy, tmp_path: Path) -> None:
    plan = _plan(policy, tier="very-high", labels=())
    _write(tmp_path, 1, "sonnet", verdict={"summary": "", "findings": []})
    _, _, errors = _decide(policy, plan, tmp_path)
    assert any("outside the tier chain" in error for error in errors)


def test_invalid_verdict_counts_as_absent(policy: Policy, tmp_path: Path) -> None:
    plan = _plan(policy)
    _write(tmp_path, 1, "sonnet", verdict={"summary": "", "findings": [{"severity": "Severe"}]})
    loaded, step, errors = _decide(policy, plan, tmp_path)
    assert errors == []
    assert loaded.attempts[0].absence == "invalid"
    assert step.reviewer is not None and step.reviewer.name == "sol"


def test_all_absent_is_pending_and_names_every_reviewer(policy: Policy, tmp_path: Path) -> None:
    plan = _plan(policy, tier="very-high", labels=())
    _write(tmp_path, 1, "opus", missing=Absence("quota", "limit"))
    _write(tmp_path, 2, "sol", missing=Absence("auth", "bad key"))
    loaded, step, errors = _decide(policy, plan, tmp_path)
    final = report.finalize(plan, step, errors, loaded.attempts, loaded.verdicts, {})
    assert final.state == "pending"
    assert final.description.startswith("pending: opus: absent (quota")
    assert len(final.description) <= 140
    assert "opus: absent (quota)" in final.body and "sol: absent (auth)" in final.body


def test_selected_reviewer_that_never_reported_is_pending(policy: Policy, tmp_path: Path) -> None:
    plan = _plan(policy)
    loaded, step, errors = _decide(policy, plan, tmp_path)
    assert step.kind == selection.REVIEW
    final = report.finalize(plan, step, errors, loaded.attempts, loaded.verdicts, {})
    assert final.state == "pending"
    assert "selected but did not report" in final.body


def _run_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *argv: str) -> dict[str, str]:
    output = tmp_path / "github-output.txt"
    output.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_RUN_ID", RUN_ID)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert cli.main(list(argv)) == 0
    return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())


def test_cli_select_finalize_and_ensure_attempt(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "plan.json").write_text(json.dumps(_plan(policy)), encoding="utf-8")
    (plan_dir / "diff.patch").write_text(DIFF, encoding="utf-8")
    attempts_dir = tmp_path / "attempts"
    attempts_dir.mkdir()
    plan_path = str(plan_dir / "plan.json")
    out = _run_cli(
        monkeypatch, tmp_path, "select", "--plan", plan_path, "--attempts-dir", str(attempts_dir), "--slot", "1"
    )
    assert out == {"reviewer": "sonnet", "harness": "claude"}
    _run_cli(
        monkeypatch,
        tmp_path,
        "ensure-attempt",
        "--plan",
        plan_path,
        "--slot",
        "1",
        "--reviewer",
        "sonnet",
        "--out-dir",
        str(attempts_dir),
    )
    out = _run_cli(
        monkeypatch, tmp_path, "select", "--plan", plan_path, "--attempts-dir", str(attempts_dir), "--slot", "2"
    )
    assert out == {"reviewer": "sol", "harness": "codex"}
    stale = _run_cli(
        monkeypatch, tmp_path, "select", "--plan", plan_path, "--attempts-dir", str(attempts_dir), "--slot", "3"
    )
    assert stale == {"reviewer": "", "harness": ""}
    _write(attempts_dir, 2, "sol", verdict={"summary": "", "findings": [_finding("Critical")]})
    final_dir = tmp_path / "final"
    out = _run_cli(
        monkeypatch,
        tmp_path,
        "finalize",
        "--plan",
        plan_path,
        "--attempts-dir",
        str(attempts_dir),
        "--out-dir",
        str(final_dir),
    )
    assert out == {"state": "failure", "comment": "true", "review": "false", "has_state": "true"}
    status = json.loads((final_dir / "status.json").read_text(encoding="utf-8"))
    assert status["context"] == "oracle-review-shadow"
    assert status["state"] == "failure"
    assert status["target_url"].endswith(f"/actions/runs/{RUN_ID}")
    state = json.loads((final_dir / "state" / "state.json").read_text(encoding="utf-8"))
    assert state["head_sha"] == HEAD and state["outcome"] == "failure"
    comment = json.loads((final_dir / "comment.json").read_text(encoding="utf-8"))
    assert "Findings on diff lines" in comment["body"]


def test_cli_finalize_refuses_a_plan_from_another_run(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({**_plan(policy), "run_id": "1"}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_RUN_ID", RUN_ID)
    with pytest.raises(SystemExit, match="another run"):
        cli.main(
            ["finalize", "--plan", str(plan_path), "--attempts-dir", str(tmp_path), "--out-dir", str(tmp_path / "o")]
        )


@pytest.mark.parametrize(("decision", "state"), [("success", "success"), ("fork", "pending")])
def test_cli_finalize_fixed_decisions(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision: str, state: str
) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({**_plan(policy), "decision": decision}), encoding="utf-8")
    out = _run_cli(
        monkeypatch,
        tmp_path,
        "finalize",
        "--plan",
        str(plan_path),
        "--attempts-dir",
        str(tmp_path),
        "--out-dir",
        str(tmp_path / "o"),
    )
    assert out["state"] == state and out["has_state"] == "false" and out["comment"] == "false"
    status = json.loads((tmp_path / "o" / "status.json").read_text(encoding="utf-8"))
    assert status["description"] == ("no soundness path changed" if decision == "success" else "fork: owner review")
