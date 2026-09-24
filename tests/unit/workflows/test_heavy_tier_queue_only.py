"""Tests for the heavy-tier queue-only rule (ci-dedupe-06).

The heavy tier (medium-test, correctness-gate, plan-capture-gate,
tpch-binary-framing, integration samples) runs only when
``heavy-needed`` fires: a code-routed tree AND (merge_group event OR
soundness paths touched OR packaging paths touched). Everything else
skips, and the required umbrella models the skip explicitly instead of
trusting it.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr.yml"

_SPEC = importlib.util.spec_from_file_location("heavy_tier_needed", SCRIPTS / "heavy_tier_needed.py")
assert _SPEC is not None and _SPEC.loader is not None
heavy = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = heavy
_SPEC.loader.exec_module(heavy)

HEAVY_JOBS = (
    "medium-test",
    "correctness-gate",
    "plan-capture-gate",
    "tpch-binary-framing",
    "postgres-integration",
    "datafusion-integration",
    "clickhouse-integration",
)
HEAVY_GUARD = "needs.ci-paths.outputs.heavy-needed == 'true'"

SOUNDNESS_PATH = "benchbox/core/equivalence/ordinary.py"
PLAIN_PATH = "benchbox/core/datavault/etl/transformer.py"


def _predicate_source(flag_paths: set[str]) -> str:
    flagged = sorted(flag_paths)
    return (
        f"def any_soundness_path(paths):\n    flagged = {flagged!r}\n    return any(str(p) in flagged for p in paths)\n"
    )


def _decision(*, code: bool = True, packaging: bool = False, paths: list[str] | None = None) -> dict[str, Any]:
    return {
        "needs_code_ci": code,
        "packaging_needed": packaging,
        "changed_paths": paths if paths is not None else [PLAIN_PATH],
    }


def _lookup(decision: dict[str, Any], event: str) -> dict[str, Any]:
    base_reader = lambda _base, _root: _predicate_source({SOUNDNESS_PATH})
    pr_reader = lambda _root: _predicate_source({SOUNDNESS_PATH})
    return heavy.heavy_needed(decision, event, "origin/develop", REPO_ROOT, base_reader, pr_reader)


# ---------------------------------------------------------------------------
# decision table
# ---------------------------------------------------------------------------


def test_code_pr_without_carve_out_skips_heavy() -> None:
    result = _lookup(_decision(), "pull_request")
    assert result == {
        "heavy_needed": False,
        "reason": "no soundness path touched under either predicate copy; pull_request runs skip the heavy tier",
    }


def test_soundness_pr_runs_heavy() -> None:
    result = _lookup(_decision(paths=[SOUNDNESS_PATH]), "pull_request")
    assert result["heavy_needed"] is True
    assert "soundness carve-out" in str(result["reason"])


def test_pr_copy_only_soundness_hit_runs_heavy() -> None:
    # The union covers a PR that narrows the base predicate: the base copy
    # sees nothing, the PR copy flags the path, the tier still runs.
    base_reader = lambda _base, _root: _predicate_source(set())
    pr_reader = lambda _root: _predicate_source({SOUNDNESS_PATH})
    result = heavy.heavy_needed(
        _decision(paths=[SOUNDNESS_PATH]), "pull_request", "origin/develop", REPO_ROOT, base_reader, pr_reader
    )
    assert result["heavy_needed"] is True
    assert "pr" in str(result["reason"])


def test_packaging_pr_runs_heavy() -> None:
    result = _lookup(_decision(packaging=True), "pull_request")
    assert result == {"heavy_needed": True, "reason": "packaging paths touched (packaging carve-out)"}


def test_merge_group_always_runs_heavy_for_code_trees() -> None:
    result = _lookup(_decision(), "merge_group")
    assert result == {
        "heavy_needed": True,
        "reason": "merge_group runs keep the full tier on every code-routed tree",
    }


def test_non_code_merge_group_stays_light() -> None:
    result = _lookup(_decision(code=False), "merge_group")
    assert result["heavy_needed"] is False


def test_lookup_error_fails_closed() -> None:
    def _boom_base(_base: str, _root: Path) -> str:
        raise OSError("git offline")

    result = heavy.heavy_needed(
        _decision(paths=[SOUNDNESS_PATH]),
        "pull_request",
        "origin/develop",
        REPO_ROOT,
        _boom_base,
        lambda _root: _predicate_source(set()),
    )
    assert result["heavy_needed"] is True
    assert "failed closed" in str(result["reason"])


def test_missing_decision_fields_fail_closed() -> None:
    result = _lookup({"needs_code_ci": True}, "pull_request")
    assert result["heavy_needed"] is True


def test_main_check_and_outputs(tmp_path: Path) -> None:
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(_decision()), encoding="utf-8")
    output = tmp_path / "github_output.txt"
    summary = tmp_path / "summary.md"
    base_reader = lambda _base, _root: _predicate_source({SOUNDNESS_PATH})
    pr_reader = lambda _root: _predicate_source({SOUNDNESS_PATH})
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(heavy, "_read_base_copy", base_reader)
        patch.setattr(heavy, "_read_pr_copy", pr_reader)
        code = heavy.main(
            [
                "--decision-in",
                str(decision_path),
                "--event",
                "pull_request",
                "--github-output",
                str(output),
                "--summary",
                str(summary),
            ]
        )
        assert code == 0
        check = heavy.main(["--decision-in", str(decision_path), "--event", "pull_request", "--check"])
        assert check == 1
        check_heavy = heavy.main(["--decision-in", str(decision_path), "--event", "merge_group", "--check"])
        assert check_heavy == 0
    written = output.read_text(encoding="utf-8")
    assert "heavy-needed=false" in written
    assert "Heavy tier needed" in summary.read_text(encoding="utf-8")


def test_main_without_decision_fails_closed() -> None:
    assert heavy.main(["--event", "pull_request"]) == 0


# ---------------------------------------------------------------------------
# pr.yml wiring
# ---------------------------------------------------------------------------


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_heavy_jobs_gate_on_heavy_needed() -> None:
    jobs = _workflow()["jobs"]
    for name in HEAVY_JOBS:
        assert jobs[name]["if"] == "${{ " + HEAVY_GUARD + " }}", name


def test_light_lane_jobs_stay_on_needs_code_ci() -> None:
    jobs = _workflow()["jobs"]
    expected = "${{ needs.ci-paths.outputs.needs-code-ci == 'true' }}"
    for name in ("code-lint", "code-test"):
        assert jobs[name]["if"] == expected, name


def test_ci_paths_emits_heavy_needed() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["ci-paths"]["outputs"]["heavy-needed"] == "${{ steps.heavy.outputs.heavy-needed }}"
    decide = next(step for step in jobs["ci-paths"]["steps"] if step.get("id") == "heavy")
    assert "scripts/heavy_tier_needed.py" in decide["run"]
    assert '--event "${{ github.event_name }}"' in decide["run"]


def test_umbrella_models_heavy_third_state() -> None:
    aggregate = _workflow()["jobs"]["ci-required-result"]
    assert aggregate.get("if") == "always()"
    step = next(step for step in aggregate["steps"] if step.get("name") == "Aggregate required result")
    assert step["env"]["HEAVY_NEEDED"] == "${{ needs.ci-paths.outputs.heavy-needed }}"
    assert "check_heavy" in step["run"]


def test_light_lane_certification_kind_is_not_full() -> None:
    job = _workflow()["jobs"]["certification-identity"]
    record = next(step for step in job["steps"] if step.get("name") == "Record certification identity")
    assert record["env"]["HEAVY_NEEDED"] == "${{ needs.ci-paths.outputs.heavy-needed }}"
    assert 'certification_kind = "fast"' in record["run"]


# ---------------------------------------------------------------------------
# umbrella semantics, executed against the shipped bash
# ---------------------------------------------------------------------------


def _aggregate_script(tmp_path: Path) -> Path:
    step = next(
        step
        for step in _workflow()["jobs"]["ci-required-result"]["steps"]
        if step.get("name") == "Aggregate required result"
    )
    script = tmp_path / "aggregate.sh"
    script.write_text(step["run"], encoding="utf-8")
    return script


def _base_env() -> dict[str, str]:
    return {
        "CI_PATHS_RESULT": "success",
        "TPCH_BINARY_FRAMING_RESULT": "skipped",
        "CONTENT_RESULT": "skipped",
        "SKILL_INTEGRITY_RESULT": "skipped",
        "LINT_RESULT": "success",
        "TEST_RESULT": "success",
        "CORRECTNESS_RESULT": "skipped",
        "PLAN_CAPTURE_RESULT": "skipped",
        "MEDIUM_TEST_RESULT": "skipped",
        "EXPLORER_TOKENS_RESULT": "skipped",
        "SITE_THEME_TOKENS_RESULT": "skipped",
        "EXPLORER_VITEST_RESULT": "skipped",
        "AUDIT_SHA_RESULT": "skipped",
        "PACKAGE_SMOKE_RESULT": "skipped",
        "DEPENDENCY_AUDIT_RESULT": "skipped",
        "PARITY_CHECK_RESULT": "skipped",
        "PUBLICATION_RECONCILIATION_RESULT": "success",
        "CONTENT_GUARD_NEEDED": "false",
        "SKILL_INTEGRITY_NEEDED": "false",
        "NEEDS_CODE_CI": "true",
        "SAFE_CONTENT_ONLY": "false",
        "HEAVY_NEEDED": "false",
    }


def _run_umbrella(tmp_path: Path, **overrides: str) -> int:
    import os

    env = {**os.environ, **_base_env(), **overrides}
    proc = subprocess.run(["bash", str(_aggregate_script(tmp_path))], capture_output=True, text=True, env=env)
    return proc.returncode


def test_light_pr_lane_passes_with_skipped_heavy(tmp_path: Path) -> None:
    assert _run_umbrella(tmp_path) == 0


def test_carve_out_pr_passes_with_successful_heavy(tmp_path: Path) -> None:
    assert (
        _run_umbrella(
            tmp_path,
            HEAVY_NEEDED="true",
            TPCH_BINARY_FRAMING_RESULT="success",
            CORRECTNESS_RESULT="success",
            PLAN_CAPTURE_RESULT="success",
            MEDIUM_TEST_RESULT="success",
        )
        == 0
    )


def test_skipped_heavy_on_required_lane_fails_umbrella(tmp_path: Path) -> None:
    assert _run_umbrella(tmp_path, HEAVY_NEEDED="true") != 0


def test_failed_heavy_on_light_lane_fails_umbrella(tmp_path: Path) -> None:
    assert _run_umbrella(tmp_path, MEDIUM_TEST_RESULT="failure") != 0


def test_unexpected_heavy_success_on_light_lane_fails_umbrella(tmp_path: Path) -> None:
    assert _run_umbrella(tmp_path, MEDIUM_TEST_RESULT="success") != 0


def test_merge_group_lane_passes_with_full_heavy(tmp_path: Path) -> None:
    assert (
        _run_umbrella(
            tmp_path,
            HEAVY_NEEDED="true",
            TPCH_BINARY_FRAMING_RESULT="success",
            CORRECTNESS_RESULT="success",
            PLAN_CAPTURE_RESULT="success",
            MEDIUM_TEST_RESULT="success",
        )
        == 0
    )
