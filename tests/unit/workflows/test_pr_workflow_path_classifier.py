"""Guardrails for the develop PR path classifier workflow."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]

# Matches dot and bracket reference forms for every segment of the chain
# independently: needs.ci-paths.outputs.x, needs['ci-paths'].outputs.x,
# needs.ci-paths.outputs['x'], needs['ci-paths']['outputs']['x'] (the fully
# bracketed form GitHub Actions also accepts for hyphenated keys), and any
# dot/bracket mix across the three segments. Shared by the lockstep test and
# its own regex-behavior regression test below so they cannot drift apart.
_CI_PATHS_SEG = r"(?:\.ci-paths|\[['\"]ci-paths['\"]\])"
_OUTPUTS_SEG = r"(?:\.outputs|\[['\"]outputs['\"]\])"
CI_PATHS_OUTPUT_REFERENCE_RE = (
    r"needs" + _CI_PATHS_SEG + _OUTPUTS_SEG + r"(?:\.([A-Za-z0-9_-]+)|\[['\"]([A-Za-z0-9_-]+)['\"]\])"
)


def _load_path_filter_decision():
    """Load scripts/path_filter_decision.py the way the workflow uses it.

    tests/unit/scripts/ has a conftest sys.path shim; here we load by file
    path so the lockstep test derives group names from the same
    `load_rules` + `extra_group_keys` logic the classify step runs (output
    naming additionally mirrors write_github_output's `_`→`-` mapping).
    """
    script = REPO_ROOT / "scripts" / "path_filter_decision.py"
    spec = importlib.util.spec_from_file_location("path_filter_decision_lockstep", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ci_required_result_script() -> str:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["ci-required-result"]["steps"]
    for step in steps:
        if step.get("name") == "Aggregate required result":
            return step["run"]
    raise AssertionError("ci-required-result aggregate step not found")


def _run_ci_required_result(**env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "CI_PATHS_RESULT": "success",
        "CONTENT_RESULT": "skipped",
        "LINT_RESULT": "skipped",
        "TEST_RESULT": "skipped",
        "CORRECTNESS_RESULT": "skipped",
        "PLAN_CAPTURE_RESULT": "skipped",
        "EXPLORER_TOKENS_RESULT": "skipped",
        "AUDIT_SHA_RESULT": "skipped",
        "PACKAGE_SMOKE_RESULT": "skipped",
        "DEPENDENCY_AUDIT_RESULT": "skipped",
        "PARITY_CHECK_RESULT": "skipped",
        "CONTENT_GUARD_NEEDED": "false",
        "NEEDS_CODE_CI": "false",
        "SAFE_CONTENT_ONLY": "true",
        **env_overrides,
    }
    return subprocess.run(
        ["bash", "-c", _ci_required_result_script()],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def test_pr_path_classifier_fetches_base_history_for_merge_base() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8")
    base_fetch = 'git fetch --no-tags origin "${{ github.base_ref }}:refs/remotes/origin/${{ github.base_ref }}"'

    # The classifier uses `git diff origin/develop...HEAD`; a depth-1 base fetch
    # on GitHub's synthetic PR merge ref can leave no merge base available.
    # Three consumers of the full base history today:
    #   - ci-paths (path classifier)
    #   - content-guard (recreates path lists for content validators)
    #   - explorer-tokens (greps the diff for results-explorer/src changes)
    assert '--depth=1 origin "${{ github.base_ref }}:refs/remotes/origin/${{ github.base_ref }}"' not in workflow
    assert workflow.count(base_fetch) == 3


def test_ci_required_result_preserves_content_guard_failure() -> None:
    result = _run_ci_required_result(
        CONTENT_GUARD_NEEDED="true",
        CONTENT_RESULT="failure",
    )

    assert result.returncode == 1
    assert "content-guard=failure" in result.stdout
    assert "Content-only PR; skipped Python code CI." not in result.stdout


def test_ci_required_result_fails_on_explorer_tokens_failure() -> None:
    # When the explorer-tokens job fires (results-explorer/src changed) and
    # fails, the aggregator must fail the required result. Without this
    # branch, the PR could merge despite a token-scan red — silently
    # regressing the blind-spot remediation.
    result = _run_ci_required_result(
        NEEDS_CODE_CI="true",
        SAFE_CONTENT_ONLY="false",
        LINT_RESULT="success",
        TEST_RESULT="success",
        CORRECTNESS_RESULT="success",
        PLAN_CAPTURE_RESULT="success",
        EXPLORER_TOKENS_RESULT="failure",
    )

    assert result.returncode == 1
    assert "explorer-tokens=failure" in result.stdout


def test_ci_required_result_treats_explorer_tokens_skipped_as_success() -> None:
    # Defensive: pin the `|| "skipped"` clause in the aggregator's
    # explorer-tokens check. The (NEEDS_CODE_CI="true",
    # EXPLORER_TOKENS_RESULT="skipped") combination is not produced by any
    # real PR shape today: the explorer-tokens job's `if:` is gated on
    # `needs-code-ci == 'true'`, so when needs-code-ci is true the job runs
    # (its inner detection step skips the scan when no results-explorer/src
    # paths changed, but the *job* still concludes "success", not
    # "skipped"). The only path that yields EXPLORER_TOKENS_RESULT="skipped"
    # is needs-code-ci="false", but the aggregator early-exits at the
    # NEEDS_CODE_CI=false branch before reading EXPLORER_TOKENS_RESULT. The
    # `|| "skipped"` clause is therefore belt-and-braces — this test pins
    # it so a future cleanup that drops the clause is a deliberate choice.
    result = _run_ci_required_result(
        NEEDS_CODE_CI="true",
        SAFE_CONTENT_ONLY="false",
        LINT_RESULT="success",
        TEST_RESULT="success",
        CORRECTNESS_RESULT="success",
        PLAN_CAPTURE_RESULT="success",
        EXPLORER_TOKENS_RESULT="skipped",
    )

    assert result.returncode == 0
    assert "Code/infra PR; lint, fast tests, correctness gate, and plan-capture gate passed." in result.stdout


def test_ci_required_result_passes_on_explorer_tokens_success() -> None:
    # Sanity: when explorer-tokens runs and passes alongside lint+test
    # success, the aggregator returns success.
    result = _run_ci_required_result(
        NEEDS_CODE_CI="true",
        SAFE_CONTENT_ONLY="false",
        LINT_RESULT="success",
        TEST_RESULT="success",
        CORRECTNESS_RESULT="success",
        PLAN_CAPTURE_RESULT="success",
        EXPLORER_TOKENS_RESULT="success",
    )

    assert result.returncode == 0
    assert "Code/infra PR; lint, fast tests, correctness gate, and plan-capture gate passed." in result.stdout


def test_ci_required_result_fails_on_plan_capture_gate_failure() -> None:
    result = _run_ci_required_result(
        NEEDS_CODE_CI="true",
        SAFE_CONTENT_ONLY="false",
        LINT_RESULT="success",
        TEST_RESULT="success",
        CORRECTNESS_RESULT="success",
        PLAN_CAPTURE_RESULT="failure",
        EXPLORER_TOKENS_RESULT="success",
    )

    assert result.returncode == 1
    assert "plan-capture-gate=failure" in result.stdout


def test_ci_required_result_required_jobs_in_needs() -> None:
    # If a future cleanup drops `explorer-tokens` from the
    # `ci-required-result.needs:` list, the aggregator wouldn't observe its
    # status at all (always "" → handled as not-success in the bash logic).
    # Lock the wiring in place.
    workflow_yaml = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8"))
    needs = workflow_yaml["jobs"]["ci-required-result"]["needs"]
    assert "explorer-tokens" in needs
    assert "correctness-gate" in needs
    assert "plan-capture-gate" in needs
    # Path-filtered packaging promotion (pr-gate-package-and-audit-promotion):
    # each must be observed by the aggregator or a skipped-counts-as-pass
    # result silently disappears from the gate.
    assert "package-smoke" in needs
    assert "dependency-audit" in needs


def test_ci_paths_job_outputs_declare_every_path_filter_group() -> None:
    # Incident pin (PR #952 → fixed in PR #955 commit 8652d135): the classify
    # step wrote `packaging-needed`/`viz-needed` to GITHUB_OUTPUT and the
    # gated jobs' `if:` referenced `needs.ci-paths.outputs.<group>-needed`,
    # but the ci-paths JOB `outputs:` block never mapped those step outputs.
    # GitHub Actions only exposes job outputs that are explicitly declared,
    # so every `if:` saw "" and package-smoke / dependency-audit /
    # parity-check silently skipped on EVERY PR — reading green via the
    # aggregator's skip-counts-as-pass rule. path-filters.yml is designed to
    # grow new groups without script changes, so this lockstep must be
    # derived from the rules file, never a hardcoded group list.
    # (Mapping currently lives at pr.yml jobs.ci-paths.outputs, lines ~27-28.)
    pfd = _load_path_filter_decision()
    groups = pfd.extra_group_keys(pfd.load_rules(REPO_ROOT / ".github" / "path-filters.yml"))
    assert groups, "expected at least one extra path-filter group (e.g. packaging, viz)"

    workflow_yaml = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8"))
    declared_outputs = workflow_yaml["jobs"]["ci-paths"]["outputs"]

    # Direction 1 (both ways): the set of `*-needed` outputs declared on the
    # ci-paths job must equal the classify step's `*-needed` emissions —
    # one per extra group (write_github_output normalizes the rules key
    # `_`→`-`) plus the always-emitted core `content-guard-needed`. A
    # missing declaration silently disables a gate (the #952 incident); a
    # stale declaration after a group is removed/renamed feeds "" to the
    # gated job's `if:` — the same silent skip from the other side.
    expected_needed = {f"{group.replace('_', '-')}-needed" for group in groups}
    expected_needed.add("content-guard-needed")
    declared_needed = {key for key in declared_outputs if key.endswith("-needed")}
    assert declared_needed == expected_needed, (
        "jobs.ci-paths.outputs `*-needed` keys must stay in lockstep with "
        "path-filters.yml groups (plus core content-guard-needed). "
        f"Missing declarations: {sorted(expected_needed - declared_needed)}; "
        f"stale declarations (no classify emission behind them): "
        f"{sorted(declared_needed - expected_needed)}. Either way the gated "
        "job's `if:` sees an empty string and silently skips (PR #952)."
    )

    for key in sorted(expected_needed):
        # Whitespace-insensitive: `${{steps.classify.outputs.x}}` and
        # `${{ steps.classify.outputs.x }}` behave identically in Actions.
        actual = re.sub(r"\s+", "", str(declared_outputs[key]))
        assert actual == f"${{{{steps.classify.outputs.{key}}}}}", (
            f"jobs.ci-paths.outputs.{key} must map steps.classify.outputs.{key}"
        )


def test_every_referenced_ci_paths_output_is_declared() -> None:
    # Direction 2 of the lockstep: any `needs.ci-paths.outputs.<key>`
    # reference anywhere in pr.yml (job `if:`, step `if:`, env, run) must
    # name an output the ci-paths job actually declares. Catches a future
    # job referencing a never-declared output even outside the extra-group
    # `<group>-needed` convention.
    # Scanning the raw text (rather than walking parsed YAML) deliberately
    # covers every usage site — job/step `if:`, env, run blocks. Trade-off:
    # a comment naming a dropped output would fail this test too; that is a
    # loud false-fail, preferred over a silent skip.
    workflow_text = (REPO_ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8")
    workflow_yaml = yaml.safe_load(workflow_text)
    declared_outputs = set(workflow_yaml["jobs"]["ci-paths"]["outputs"])

    referenced = {dot or bracket for dot, bracket in re.findall(CI_PATHS_OUTPUT_REFERENCE_RE, workflow_text)}
    assert referenced, "expected pr.yml to reference ci-paths outputs"

    undeclared = referenced - declared_outputs
    assert not undeclared, (
        f"pr.yml references undeclared ci-paths outputs {sorted(undeclared)}; "
        "declare them in jobs.ci-paths.outputs or the referencing `if:` "
        "silently evaluates against an empty string (the PR #952 incident)."
    )


def test_ci_paths_output_reference_regex_matches_fully_bracketed_form() -> None:
    # Regression pin: the regex previously hardcoded a literal `.outputs`, so
    # `needs['ci-paths']['outputs']['new-needed']` (GitHub Actions' fully
    # bracketed index syntax, a common way to reference hyphenated keys) was
    # invisible to Direction 2 -- an undeclared output referenced only in that
    # form would silently bypass this lockstep guard. Exercised against
    # synthetic text so this stays green even if pr.yml itself never happens
    # to use the bracketed form.
    synthetic = "if: ${{ needs['ci-paths']['outputs']['new-needed'] == 'true' }}"
    matches = {dot or bracket for dot, bracket in re.findall(CI_PATHS_OUTPUT_REFERENCE_RE, synthetic)}
    assert matches == {"new-needed"}


def test_parity_check_is_promoted_to_the_required_lane() -> None:
    # parity-check was promoted from non-blocking to required (2026-07-05,
    # parity-check-promotion) once both criteria held: (1) one green run on a
    # real GitHub runner (PR #973), and (2) the 2e-13 geomean_ms drift did NOT
    # reproduce on the runner (a local libm artifact, not a fixture error), so
    # exact comparison is kept. This is the package-smoke pattern: the job
    # keeps its viz path-filter, drops continue-on-error, is in
    # ci-required-result.needs, and the aggregator observes PARITY_CHECK_RESULT
    # with skipped-counts-as-pass.
    workflow_text = (REPO_ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8")
    workflow_yaml = yaml.safe_load(workflow_text)
    parity_job = workflow_yaml["jobs"]["parity-check"]
    aggregator = workflow_yaml["jobs"]["ci-required-result"]
    needs = aggregator["needs"]

    # Promoted shape: blocking, observed, still path-filtered.
    assert parity_job.get("continue-on-error") is None, "continue-on-error must be dropped on promotion"
    assert "viz-needed == 'true'" in parity_job["if"], "path-filtering must stay (non-viz PRs skip)"
    assert "parity-check" in needs, "aggregator must depend on parity-check to observe its result"

    # The aggregator must read PARITY_CHECK_RESULT and apply skipped-counts-as-pass.
    agg_step = next(s for s in aggregator["steps"] if s.get("name") == "Aggregate required result")
    assert agg_step["env"].get("PARITY_CHECK_RESULT") == "${{ needs.parity-check.result }}"
    run = agg_step["run"]
    assert 'PARITY_CHECK_RESULT" != "success"' in run
    assert 'PARITY_CHECK_RESULT" != "skipped"' in run


def test_ci_required_result_fails_on_packaging_job_failure() -> None:
    # Skipped-counts-as-pass only applies when the path-filtered job didn't
    # run at all; a real failure on a packaging PR must still fail the
    # required gate.
    for failing_var in ("PACKAGE_SMOKE_RESULT", "DEPENDENCY_AUDIT_RESULT"):
        result = _run_ci_required_result(
            NEEDS_CODE_CI="true",
            SAFE_CONTENT_ONLY="false",
            LINT_RESULT="success",
            TEST_RESULT="success",
            CORRECTNESS_RESULT="success",
            PLAN_CAPTURE_RESULT="success",
            EXPLORER_TOKENS_RESULT="success",
            **{failing_var: "failure"},
        )
        assert result.returncode == 1, f"{failing_var}=failure should fail ci-required-result"


def test_ci_required_result_passes_when_packaging_jobs_skip() -> None:
    # A PR that touches no packaging paths sees both packaging jobs skipped
    # and must still pass (matches the audit-sha pattern).
    result = _run_ci_required_result(
        NEEDS_CODE_CI="true",
        SAFE_CONTENT_ONLY="false",
        LINT_RESULT="success",
        TEST_RESULT="success",
        CORRECTNESS_RESULT="success",
        PLAN_CAPTURE_RESULT="success",
        EXPLORER_TOKENS_RESULT="success",
    )
    assert result.returncode == 0


def test_ci_required_result_fails_on_parity_check_failure() -> None:
    # Promotion (parity-check-promotion): a viz-touching PR whose parity-check
    # job fails must now fail the required gate (was non-blocking before).
    result = _run_ci_required_result(
        NEEDS_CODE_CI="true",
        SAFE_CONTENT_ONLY="false",
        LINT_RESULT="success",
        TEST_RESULT="success",
        CORRECTNESS_RESULT="success",
        PLAN_CAPTURE_RESULT="success",
        EXPLORER_TOKENS_RESULT="success",
        PARITY_CHECK_RESULT="failure",
    )
    assert result.returncode == 1


def test_ci_required_result_passes_when_parity_check_skips() -> None:
    # A non-viz PR skips parity-check (path-filtered) and must still pass -
    # the skipped-counts-as-pass contract the promotion preserves.
    result = _run_ci_required_result(
        NEEDS_CODE_CI="true",
        SAFE_CONTENT_ONLY="false",
        LINT_RESULT="success",
        TEST_RESULT="success",
        CORRECTNESS_RESULT="success",
        PLAN_CAPTURE_RESULT="success",
        EXPLORER_TOKENS_RESULT="success",
        PARITY_CHECK_RESULT="skipped",
    )
    assert result.returncode == 0
