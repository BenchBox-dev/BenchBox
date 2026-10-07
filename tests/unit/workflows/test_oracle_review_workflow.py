from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "oracle-review.yml"
SCRIPT = "_project/scripts/oracle_review_check.py"
HEAD = "a" * 40
BASE = "b" * 40
REPO = "BenchBox-dev/BenchBox"


def _load() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers() -> dict[str, Any]:
    workflow = _load()
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow has no `on:` block"
    return triggers


def test_job_id_and_name_are_the_required_check_name() -> None:
    workflow = _load()
    assert workflow["name"] == "oracle-review"
    assert list(workflow["jobs"]) == ["oracle-review"]
    assert workflow["jobs"]["oracle-review"]["name"] == "oracle-review"


def test_triggers_cover_pushes_reviews_and_dispatch() -> None:
    triggers = _triggers()
    assert set(triggers) == {"pull_request", "pull_request_review", "workflow_dispatch"}
    assert "merge_group" not in triggers
    assert triggers["pull_request"]["types"] == ["opened", "synchronize", "reopened", "edited", "ready_for_review"]
    assert triggers["pull_request_review"]["types"] == ["submitted", "dismissed"]
    assert triggers["workflow_dispatch"]["inputs"]["pr"]["required"] is True
    assert triggers["workflow_dispatch"]["inputs"]["pr"]["type"] == "string"


def test_permissions_are_read_only() -> None:
    assert _load()["permissions"] == {"actions": "read", "contents": "read", "issues": "read", "pull-requests": "read"}
    assert "permissions" not in _load()["jobs"]["oracle-review"]


def test_concurrency_cancels_superseded_runs_per_pull_request() -> None:
    concurrency = _load()["concurrency"]
    assert concurrency["cancel-in-progress"] is True
    assert "github.event.pull_request.number" in concurrency["group"]
    assert "inputs.pr" in concurrency["group"]
    assert "merge_group" not in concurrency["group"]


def test_job_invokes_the_script_with_the_pull_request_number_and_token() -> None:
    steps = _load()["jobs"]["oracle-review"]["steps"]
    runs = [step for step in steps if SCRIPT in step.get("run", "")]
    assert len(runs) == 1
    step = runs[0]
    assert step["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    assert "github.event.pull_request.number" in step["env"]["PR_NUMBER"]
    assert "inputs.pr" in step["env"]["PR_NUMBER"]
    assert "--pr" in step["run"]
    assert "MERGE_GROUP_REF" not in step["env"]
    assert "MERGE_GROUP_REF" not in step["run"]


def test_required_signal_matches_the_oracle_policy_mode() -> None:
    steps = _load()["jobs"]["oracle-review"]["steps"]
    run = next(step["run"] for step in steps if SCRIPT in step.get("run", ""))
    policy_path = REPO_ROOT / ".github/oracle-reviewers.yml"
    if not policy_path.is_file():
        pytest.skip("the release tree has no oracle reviewer policy")
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    assert f'ORACLE_CONTEXT = "{policy["status_context"]}"' in (REPO_ROOT / SCRIPT).read_text(encoding="utf-8")
    if policy["mode"] == "enforce":
        assert "--signal oracle" in run
        assert policy["findings_delivery"] == "review"
    else:
        assert "--signal" not in run


def test_actions_are_pinned_to_full_commit_shas() -> None:
    steps = _load()["jobs"]["oracle-review"]["steps"]
    for step in steps:
        if "uses" in step:
            ref = step["uses"].split("@", 1)[1]
            assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), step["uses"]


def test_checkout_uses_the_base_checker_and_manifest() -> None:
    steps = _load()["jobs"]["oracle-review"]["steps"]
    checkouts = [step for step in steps if step.get("uses", "").startswith("actions/checkout@")]
    assert len(checkouts) == 1
    ref = checkouts[0]["with"]["ref"]
    assert "github.event.pull_request.base.sha" in ref
    assert "merge_group" not in ref
    assert "steps.dispatch-pr.outputs.base_sha" in ref
    assert "head" not in ref
    assert checkouts[0]["with"]["persist-credentials"] is False
    resolve = next(step for step in steps if step.get("id") == "dispatch-pr")
    assert steps.index(resolve) < steps.index(checkouts[0])
    assert resolve["if"] == "github.event_name == 'workflow_dispatch'"
    assert resolve["env"]["PR_NUMBER"] == "${{ inputs.pr }}"
    assert resolve["env"]["EXPECTED_HEAD"] == "${{ github.sha }}"
    assert resolve["env"]["CURRENT_REF"] == "${{ github.ref }}"
    assert all("${{" not in step.get("run", "") for step in steps)


def test_run_name_records_the_event_action_the_script_uses_to_find_head_moves() -> None:
    assert _load()["run-name"] == "oracle-review (${{ github.event.action || github.event_name }})"


def _pull(**changes: Any) -> dict[str, Any]:
    return {
        "number": 7,
        "state": "OPEN",
        "baseRefName": "develop",
        "baseRefOid": BASE,
        "headRefName": "fix/example",
        "headRefOid": HEAD,
        "isCrossRepository": False,
        **changes,
    }


def _environment(tmp_path: Path, pulls: list[Any], checker_exit: int, checker_message: str) -> dict[str, str]:
    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "counter = Path(os.environ['FAKE_GH_COUNTER'])\n"
        "index = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(index + 1))\n"
        "with open(os.environ['FAKE_GH_CALLS'], 'a') as calls:\n"
        "    calls.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "assert sys.argv[1:6] == ['pr', 'view', '7', '--repo', 'BenchBox-dev/BenchBox']\n"
        "pull = json.loads(os.environ['FAKE_PULLS'])[index]\n"
        "if isinstance(pull, dict) and pull.get('api_error'):\n"
        "    sys.exit(1)\n"
        "if isinstance(pull, dict):\n"
        "    pull = {field: pull[field] for field in sys.argv[7].split(',') if field in pull}\n"
        "print(json.dumps(pull))\n"
    )
    gh.chmod(0o755)
    checker = tmp_path / "python"
    checker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['FAKE_CHECKER_CALL']).write_text(json.dumps(sys.argv[1:]))\n"
        "print(os.environ['FAKE_CHECKER_MESSAGE'])\n"
        "sys.exit(int(os.environ['FAKE_CHECKER_EXIT']))\n"
    )
    checker.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "FAKE_GH_COUNTER": str(tmp_path / "gh-count"),
        "FAKE_GH_CALLS": str(tmp_path / "gh-calls"),
        "FAKE_PULLS": json.dumps(pulls),
        "FAKE_CHECKER_CALL": str(tmp_path / "checker-call"),
        "FAKE_CHECKER_EXIT": str(checker_exit),
        "FAKE_CHECKER_MESSAGE": checker_message,
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        "GH_TOKEN": "fixture-token",
        "GITHUB_TOKEN": "fixture-token",
        "EVENT_NAME": "workflow_dispatch",
        "PR_NUMBER": "7",
        "REPO": REPO,
        "EXPECTED_HEAD": HEAD,
        "CURRENT_REF": "refs/heads/fix/example",
        "PR_SNAPSHOT": "",
    }


def _run_step(tmp_path: Path, step: dict[str, Any], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "workflow-step.sh"
    script.write_text(step["run"], encoding="utf-8")
    return subprocess.run(["bash", str(script)], env=env, text=True, capture_output=True, timeout=10)


def _dispatch(
    tmp_path: Path,
    pulls: list[Any],
    *,
    checker_exit: int = 0,
    checker_message: str = "oracle-review: not a soundness path change",
    **env_changes: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    env = _environment(tmp_path, pulls, checker_exit, checker_message)
    env.update(env_changes)
    steps = _load()["jobs"]["oracle-review"]["steps"]
    resolve = next(step for step in steps if step.get("id") == "dispatch-pr")
    check = next(step for step in steps if SCRIPT in step.get("run", ""))
    result = _run_step(tmp_path, resolve, env)
    if result.returncode:
        return result, {}
    outputs = dict(line.split("=", 1) for line in (tmp_path / "outputs").read_text().splitlines())
    env["PR_SNAPSHOT"] = outputs["snapshot"]
    return _run_step(tmp_path, check, env), outputs


@pytest.mark.parametrize(
    "message",
    ["oracle-review: not a soundness path change", f"oracle-review: pass (Codex connector review of {HEAD})"],
)
def test_dispatch_checks_current_head_around_every_checker_success(tmp_path: Path, message: str) -> None:
    result, outputs = _dispatch(tmp_path, [_pull(), _pull(), _pull()], checker_message=message)
    assert result.returncode == 0, result.stderr
    assert outputs["base_sha"] == BASE
    assert json.loads(outputs["snapshot"])["headRefOid"] == HEAD
    assert (tmp_path / "gh-count").read_text() == "3"
    assert json.loads((tmp_path / "checker-call").read_text()) == [SCRIPT, "--repo", REPO, "--pr", "7"]
    assert message in result.stdout


@pytest.mark.parametrize("pr", ["", "0", "-7", "7.5", " 7", "7\n8", "$(touch injected)"])
def test_dispatch_rejects_malformed_pr_before_any_api_or_checkout(tmp_path: Path, pr: str) -> None:
    result, outputs = _dispatch(tmp_path, [], PR_NUMBER=pr)
    assert result.returncode != 0
    assert outputs == {}
    assert not (tmp_path / "gh-count").exists()
    assert not (tmp_path / "checker-call").exists()


@pytest.mark.parametrize("head", ["", "a" * 39, "z" * 40])
def test_dispatch_rejects_malformed_captured_commit(tmp_path: Path, head: str) -> None:
    result, outputs = _dispatch(tmp_path, [], EXPECTED_HEAD=head)
    assert result.returncode != 0
    assert outputs == {}
    assert not (tmp_path / "gh-count").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"number": 8},
        {"state": "CLOSED"},
        {"baseRefName": "release"},
        {"isCrossRepository": True},
        {"headRefName": "fix/another"},
        {"headRefOid": "c" * 40},
        {"baseRefOid": None},
        {"baseRefOid": "not-a-sha"},
    ],
)
def test_dispatch_rejects_wrong_pr_or_untrusted_checkout(tmp_path: Path, changes: dict[str, Any]) -> None:
    result, outputs = _dispatch(tmp_path, [_pull(**changes)])
    assert result.returncode != 0
    assert outputs == {}
    assert not (tmp_path / "outputs").exists()
    assert not (tmp_path / "checker-call").exists()


@pytest.mark.parametrize("ref", ["refs/heads/develop", "refs/tags/fix/example", "refs/heads/fix/another"])
def test_dispatch_rejects_default_branch_tags_and_other_branches(tmp_path: Path, ref: str) -> None:
    result, outputs = _dispatch(tmp_path, [_pull()], CURRENT_REF=ref)
    assert result.returncode != 0
    assert outputs == {}
    assert not (tmp_path / "checker-call").exists()


@pytest.mark.parametrize("changed_read", [1, 2])
def test_dispatch_rejects_head_moving_before_or_during_checker(tmp_path: Path, changed_read: int) -> None:
    pulls = [_pull(), _pull(), _pull()]
    pulls[changed_read] = _pull(headRefOid="c" * 40)
    result, _ = _dispatch(tmp_path, pulls)
    assert result.returncode != 0
    assert "identity or head changed" in result.stderr
    assert (tmp_path / "checker-call").exists() is (changed_read == 2)


@pytest.mark.parametrize("changes", [{"state": "CLOSED"}, {"baseRefName": "release"}, {"isCrossRepository": True}])
def test_dispatch_rejects_identity_change_after_checker(tmp_path: Path, changes: dict[str, Any]) -> None:
    result, _ = _dispatch(tmp_path, [_pull(), _pull(), _pull(**changes)])
    assert result.returncode != 0
    assert "identity or head changed" in result.stderr
    assert (tmp_path / "checker-call").exists()


@pytest.mark.parametrize("failed_read", [0, 1, 2])
def test_dispatch_api_failure_never_passes(tmp_path: Path, failed_read: int) -> None:
    pulls = [_pull(), _pull(), _pull()]
    pulls[failed_read] = {"api_error": True}
    result, _ = _dispatch(tmp_path, pulls)
    assert result.returncode != 0
    assert (tmp_path / "checker-call").exists() is (failed_read == 2)


@pytest.mark.parametrize("pull", [None, {}, "malformed"])
def test_dispatch_malformed_metadata_never_reaches_checkout(tmp_path: Path, pull: Any) -> None:
    result, outputs = _dispatch(tmp_path, [pull])
    assert result.returncode != 0
    assert outputs == {}
    assert not (tmp_path / "checker-call").exists()


@pytest.mark.parametrize("checker_exit", [1, 2])
def test_dispatch_waiting_and_error_remain_failed(tmp_path: Path, checker_exit: int) -> None:
    result, _ = _dispatch(tmp_path, [_pull(), _pull()], checker_exit=checker_exit)
    assert result.returncode == checker_exit
    assert (tmp_path / "gh-count").read_text() == "2"


def test_dispatch_does_not_require_develop_to_stop_advancing(tmp_path: Path) -> None:
    result, outputs = _dispatch(tmp_path, [_pull(), _pull(baseRefOid="c" * 40), _pull(baseRefOid="d" * 40)])
    assert result.returncode == 0, result.stderr
    assert outputs["base_sha"] == BASE


def test_pull_request_events_do_not_use_dispatch_guards(tmp_path: Path) -> None:
    env = _environment(tmp_path, [], 0, "oracle-review: not a soundness path change")
    env.update(EVENT_NAME="pull_request", PR_NUMBER="7")
    check = next(step for step in _load()["jobs"]["oracle-review"]["steps"] if SCRIPT in step.get("run", ""))
    result = _run_step(tmp_path, check, env)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "gh-count").exists()
    assert json.loads((tmp_path / "checker-call").read_text()) == [SCRIPT, "--repo", REPO, "--pr", "7"]
