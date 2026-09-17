"""Tests for queue-certified post-merge skips (fast/medium tests + browser suite).

Covers the lookup decision table in scripts/queue_certification.py, the
certified third-state signature, and the workflow wiring in
develop-post-merge.yml and results-explorer-browser.yml: certified SHAs skip
the re-runs, every other path runs the full gates, lint and its fast-lane
cache always run, auto-revert can never fire from a certified skip, and the
certifying run ID reaches the step summary and metrics.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

POST_MERGE = REPO_ROOT / ".github" / "workflows" / "develop-post-merge.yml"
BROWSER = REPO_ROOT / ".github" / "workflows" / "results-explorer-browser.yml"

_QCERT_SPEC = importlib.util.spec_from_file_location("queue_certification", SCRIPTS / "queue_certification.py")
assert _QCERT_SPEC is not None and _QCERT_SPEC.loader is not None
qcert = importlib.util.module_from_spec(_QCERT_SPEC)
sys.modules[_QCERT_SPEC.name] = qcert
_QCERT_SPEC.loader.exec_module(qcert)

_SIG_SPEC = importlib.util.spec_from_file_location("post_merge_signature", SCRIPTS / "post_merge_signature.py")
assert _SIG_SPEC is not None and _SIG_SPEC.loader is not None
sig = importlib.util.module_from_spec(_SIG_SPEC)
sys.modules[_SIG_SPEC.name] = sig
_SIG_SPEC.loader.exec_module(sig)

_BROWSER_GATE_SPEC = importlib.util.spec_from_file_location(
    "browser_gate_aggregate", REPO_ROOT / "_project" / "scripts" / "browser_gate_aggregate.py"
)
assert _BROWSER_GATE_SPEC is not None and _BROWSER_GATE_SPEC.loader is not None
gate_mod = importlib.util.module_from_spec(_BROWSER_GATE_SPEC)
sys.modules[_BROWSER_GATE_SPEC.name] = gate_mod
_BROWSER_GATE_SPEC.loader.exec_module(gate_mod)

SHA = "a" * 40


def _certify(*args: object, **kwargs: object) -> dict[str, object]:
    """Call the lookup as a push to develop unless the test says otherwise."""
    kwargs.setdefault("event", "push")
    kwargs.setdefault("ref", "refs/heads/develop")
    return qcert.find_certifying_run(*args, **kwargs)  # type: ignore[arg-type]


OTHER_SHA = "b" * 40
REPO = "BenchBox-dev/BenchBox"
TOKEN = "test-token"
CERTIFIED_GUARD = "needs.queue-certification.outputs.certified != 'true'"


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _run_record(
    run_id: int,
    *,
    event: str = "merge_group",
    conclusion: str = "success",
    head_sha: str = SHA,
    path: str = ".github/workflows/pr.yml",
) -> dict[str, object]:
    return {
        "id": run_id,
        "event": event,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "path": path,
        "created_at": "2026-09-16T12:00:00Z",
    }


def _job(name: str, conclusion: str | None = "success") -> dict[str, object]:
    return {
        "name": name,
        "conclusion": conclusion,
        "started_at": "2026-09-16T12:00:00Z",
        "completed_at": "2026-09-16T12:01:00Z",
    }


def _fake_urlopen(routes: dict[str, object], failures: set[str] | None = None):
    failures = failures or set()

    def _open(request: object, timeout: object = None) -> _FakeResponse:
        url = request.full_url if hasattr(request, "full_url") else str(request)  # type: ignore[union-attr]
        for prefix, payload in routes.items():
            if url.startswith(prefix):
                if prefix in failures:
                    raise OSError(f"boom for {prefix}")
                return _FakeResponse(payload)
        raise AssertionError(f"unexpected API call: {url}")

    return _open


def _pr_routes(
    runs: list[dict[str, object]],
    jobs_by_run: dict[int, list[dict[str, object]]],
    browser_runs: list[dict[str, object]] | None = None,
    browser_jobs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    routes: dict[str, object] = {
        f"https://api.github.com/repos/{REPO}/actions/workflows/.github/workflows/pr.yml/runs": {"workflow_runs": runs},
    }
    for run_id, jobs in jobs_by_run.items():
        routes[f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/jobs"] = {"jobs": jobs}
    routes[
        f"https://api.github.com/repos/{REPO}/actions/workflows/.github/workflows/results-explorer-browser.yml/runs"
    ] = {"workflow_runs": browser_runs or []}
    if browser_jobs is not None:
        routes[f"https://api.github.com/repos/{REPO}/actions/runs/777/jobs"] = {"jobs": browser_jobs}
    return routes


# ---------------------------------------------------------------------------
# Lookup decision table
# ---------------------------------------------------------------------------


def test_certified_sha_with_successful_queue_run_and_required_result() -> None:
    routes = _pr_routes(
        [_run_record(101)],
        {101: [_job("ci-required-result"), _job("medium-test")]},
    )
    result = _certify(SHA, REPO, TOKEN, urlopen=_fake_urlopen(routes))
    assert result == {
        "certified": True,
        "run_id": 101,
        "reason": f"merge_group run 101 passed {qcert.PR_WORKFLOW_FILE} on this exact SHA",
    }


def test_uncertified_sha_without_matching_run_runs_full_gates() -> None:
    routes = _pr_routes([_run_record(101, head_sha=OTHER_SHA)], {101: [_job("ci-required-result")]})
    result = _certify(SHA, REPO, TOKEN, urlopen=_fake_urlopen(routes))
    assert result["certified"] is False
    assert result["run_id"] is None


def test_non_success_queue_run_does_not_certify() -> None:
    routes = _pr_routes(
        [_run_record(101, conclusion="failure")],
        {101: [_job("ci-required-result", "failure")]},
    )
    assert _certify(SHA, REPO, TOKEN, urlopen=_fake_urlopen(routes))["certified"] is False


def test_pull_request_event_run_does_not_certify() -> None:
    routes = _pr_routes(
        [_run_record(101, event="pull_request")],
        {101: [_job("ci-required-result")]},
    )
    assert _certify(SHA, REPO, TOKEN, urlopen=_fake_urlopen(routes))["certified"] is False


def test_wrong_workflow_path_does_not_certify() -> None:
    routes = _pr_routes(
        [_run_record(101, path=".github/workflows/other.yml")],
        {101: [_job("ci-required-result")]},
    )
    assert _certify(SHA, REPO, TOKEN, urlopen=_fake_urlopen(routes))["certified"] is False


def test_required_result_not_success_does_not_certify() -> None:
    for conclusion in ("failure", "cancelled", "skipped", None):
        routes = _pr_routes(
            [_run_record(101)],
            {101: [_job("ci-required-result", conclusion), _job("medium-test")]},
        )
        result = _certify(SHA, REPO, TOKEN, urlopen=_fake_urlopen(routes))
        assert result["certified"] is False, conclusion


def test_missing_required_result_job_does_not_certify() -> None:
    routes = _pr_routes([_run_record(101)], {101: [_job("medium-test")]})
    assert _certify(SHA, REPO, TOKEN, urlopen=_fake_urlopen(routes))["certified"] is False


def test_api_failure_fails_open() -> None:
    routes = _pr_routes([_run_record(101)], {101: [_job("ci-required-result")]})
    opener = _fake_urlopen(routes, failures={f"https://api.github.com/repos/{REPO}/actions/runs/101/jobs"})
    result = _certify(SHA, REPO, TOKEN, urlopen=opener)
    assert result["certified"] is False
    assert "lookup failed open" in str(result["reason"])


def test_missing_credentials_fail_open() -> None:
    result = _certify(SHA, REPO, "")
    assert result["certified"] is False


def test_ineligible_events_make_no_api_calls() -> None:
    def _forbidden(request: object, timeout: object = None) -> object:
        raise AssertionError("no API call may happen for ineligible events")

    for event in ("schedule", "workflow_dispatch", "pull_request", "merge_group", ""):
        result = qcert.find_certifying_run(SHA, REPO, TOKEN, urlopen=_forbidden, event=event, ref="refs/heads/develop")
        assert result["certified"] is False
        assert "never queue-certified" in str(result["reason"])


def test_ineligible_refs_make_no_api_calls() -> None:
    def _forbidden(request: object, timeout: object = None) -> object:
        raise AssertionError("no API call may happen for ineligible refs")

    for ref in ("refs/heads/release", "refs/pull/1/merge", ""):
        result = qcert.find_certifying_run(SHA, REPO, TOKEN, urlopen=_forbidden, event="push", ref=ref)
        assert result["certified"] is False
        assert "never queue-certified" in str(result["reason"])


def test_newest_successful_run_wins_over_older_failure() -> None:
    older = dict(_run_record(100), created_at="2026-09-15T12:00:00Z", conclusion="failure")
    newer = dict(_run_record(101), created_at="2026-09-16T12:00:00Z")
    routes = _pr_routes(
        [older, newer],
        {
            100: [_job("ci-required-result", "failure")],
            101: [_job("ci-required-result")],
        },
    )
    result = _certify(SHA, REPO, TOKEN, urlopen=_fake_urlopen(routes))
    assert result["certified"] is True
    assert result["run_id"] == 101


def test_browser_gate_required_for_browser_certification() -> None:
    browser_run = dict(
        _run_record(777, path=".github/workflows/results-explorer-browser.yml"),
    )
    routes = _pr_routes(
        [_run_record(101)],
        {101: [_job("ci-required-result")]},
        browser_runs=[browser_run],
        browser_jobs=[_job("Results Explorer browser gate")],
    )
    result = _certify(SHA, REPO, TOKEN, require_browser_gate=True, urlopen=_fake_urlopen(routes))
    assert result["certified"] is True


def test_browser_gate_failure_blocks_browser_certification() -> None:
    browser_run = dict(
        _run_record(777, path=".github/workflows/results-explorer-browser.yml"),
    )
    routes = _pr_routes(
        [_run_record(101)],
        {101: [_job("ci-required-result")]},
        browser_runs=[browser_run],
        browser_jobs=[_job("Results Explorer browser gate", "failure")],
    )
    result = _certify(SHA, REPO, TOKEN, require_browser_gate=True, urlopen=_fake_urlopen(routes))
    assert result["certified"] is False


def test_cli_writes_outputs_and_always_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(request: object, timeout: object = None) -> object:
        raise OSError("network down")

    monkeypatch.setattr(qcert.urllib.request, "urlopen", _boom)
    out = tmp_path / "github_output.txt"
    summary = tmp_path / "summary.md"
    assert (
        qcert.main(
            ["--sha", SHA, "--repo", REPO, "--token", TOKEN, "--github-output", str(out), "--summary", str(summary)]
        )
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert "certified=false" in text
    assert "certifying_run_id=" in text
    assert "full gates" in summary.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Certified third-state signature
# ---------------------------------------------------------------------------


def test_certified_signature_carries_no_failure_ids(tmp_path: Path) -> None:
    out = tmp_path / "signature.json"
    assert sig.main(["build", "--job", "fast-test", "--certified-by", "424242", "--out", str(out)]) == 0
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["job"] == "fast-test"
    assert record["kind"] == "certified"
    assert record["failure_ids"] == []
    assert record["certified_by_run"] == 424242


def test_certified_build_rejects_mixed_inputs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "signature.json"
    assert (
        sig.main(["build", "--job", "fast-test", "--certified-by", "1", "--failed-step", "x", "--out", str(out)]) == 1
    )
    assert "mutually exclusive" in capsys.readouterr().err


def test_certified_current_run_never_fires_auto_revert(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    previous = tmp_path / "previous.json"
    assert sig.main(["build", "--job", "medium-test", "--certified-by", "424242", "--out", str(current)]) == 0
    previous.write_text(
        json.dumps({"job": "medium-test", "kind": "junit", "failure_ids": ["tests/unit/a.py::test_x"]}),
        encoding="utf-8",
    )
    diff_out = tmp_path / "diff.json"
    assert sig.main(["diff", "--previous", str(previous), "--current", str(current), "--out", str(diff_out)]) == 0
    assert json.loads(diff_out.read_text(encoding="utf-8"))["new_failure_ids"] == []


def test_certified_baseline_does_not_mask_real_failures(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    previous = tmp_path / "previous.json"
    assert sig.main(["build", "--job", "medium-test", "--certified-by", "424242", "--out", str(previous)]) == 0
    current.write_text(
        json.dumps({"job": "medium-test", "kind": "junit", "failure_ids": ["tests/unit/a.py::test_x"]}),
        encoding="utf-8",
    )
    diff_out = tmp_path / "diff.json"
    assert sig.main(["diff", "--previous", str(previous), "--current", str(current), "--out", str(diff_out)]) == 0
    assert json.loads(diff_out.read_text(encoding="utf-8"))["new_failure_ids"] == ["tests/unit/a.py::test_x"]


# ---------------------------------------------------------------------------
# develop-post-merge.yml wiring
# ---------------------------------------------------------------------------


def _post_merge() -> dict[str, object]:
    return yaml.safe_load(POST_MERGE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _jobs(name: str) -> dict[str, object]:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    return workflow["jobs"]  # type: ignore[no-any-return]


def test_certification_job_always_runs_with_actions_read() -> None:
    # The job must not be event-gated: downstream jobs read its outputs on
    # every event, and references to a skipped job's outputs do not
    # evaluate reliably. The script returns certified=false without any API
    # call for ineligible events (tested at the script level).
    job = _post_merge()["jobs"]["queue-certification"]
    assert job.get("if") is None
    assert job["permissions"]["actions"] == "read"
    assert job["outputs"]["certified"] == "${{ steps.certify.outputs.certified }}"
    assert job["outputs"]["certifying_run_id"] == "${{ steps.certify.outputs.certifying_run_id }}"
    lookup = next(step for step in job["steps"] if step.get("id") == "certify")
    assert "scripts/queue_certification.py" in lookup["run"]
    assert lookup["env"]["GH_TOKEN"] == "${{ github.token }}"


def test_certification_job_uploads_expected_signature_artifacts() -> None:
    job = _post_merge()["jobs"]["queue-certification"]
    names = [
        step.get("with", {}).get("name") for step in job["steps"] if "upload-artifact" in str(step.get("uses", ""))
    ]
    assert "signature-fast-test" in names
    assert "signature-medium-test" in names


def test_fast_test_skips_only_on_certified_push() -> None:
    job = _post_merge()["jobs"]["fast-test"]
    assert "queue-certification" in job["needs"]
    condition = str(job.get("if") or "")
    assert "github.event_name != 'push'" in condition
    assert CERTIFIED_GUARD in condition


def test_medium_test_keeps_schedule_exclusion_and_skips_on_certified_push() -> None:
    job = _post_merge()["jobs"]["medium-test"]
    assert "queue-certification" in job["needs"]
    condition = str(job.get("if") or "")
    assert "github.event_name != 'schedule'" in condition
    assert CERTIFIED_GUARD in condition


def test_lint_and_fast_lane_cache_run_on_every_push() -> None:
    job = _post_merge()["jobs"]["lint"]
    assert "needs" not in job
    assert job.get("if") is None
    steps = job["steps"]
    assert any("fast-lane-count" in str(step.get("run", "")) for step in steps)
    cache = next(step for step in steps if str(step.get("name", "")).startswith("Cache fast-lane count"))
    assert "fast-lane-count-develop-" in str(cache["with"]["key"])


def test_schedule_and_dispatch_never_skip() -> None:
    # The certify job always runs, but the script reports certified=false
    # for schedule/dispatch (no API calls), so the gate conditions below
    # stay true and the full gates run.
    jobs = _post_merge()["jobs"]
    assert jobs["queue-certification"].get("if") is None
    for name in ("fast-test", "medium-test"):
        condition = str(jobs[name].get("if") or "")
        assert "github.event_name != 'push'" in condition or name == "medium-test"


def test_auto_revert_cannot_trigger_from_certified_skip() -> None:
    job = _post_merge()["jobs"]["auto-revert-on-failure"]
    assert "queue-certification" in job["needs"]
    trigger = str(job.get("if") or "")
    assert CERTIFIED_GUARD in trigger
    # Simulate the trigger: a certified skip reports skipped gates, which must
    # not satisfy any failure disjunct, while a real failure still fires.
    assert (
        _trigger_fires(trigger, certified="true", lint="success", fast="skipped", tokens="success", medium="skipped")
        is False
    )
    assert (
        _trigger_fires(trigger, certified="", lint="success", fast="failure", tokens="success", medium="success")
        is True
    )
    assert (
        _trigger_fires(trigger, certified="", lint="success", fast="success", tokens="success", medium="success")
        is False
    )


def _trigger_fires(trigger: str, *, certified: str, lint: str, fast: str, tokens: str, medium: str) -> bool:
    """Evaluate the auto-revert trigger shape against one needs-result row."""
    assert "github.event_name != 'schedule'" in trigger
    assert CERTIFIED_GUARD in trigger
    if certified == "true":
        return False
    results = {
        "needs.lint.result": lint,
        "needs.fast-test.result": fast,
        "needs.explorer-tokens.result": tokens,
        "needs.medium-test.result": medium,
    }
    return any(results[key] == "failure" for key in results)


def test_green_run_cleanup_cannot_clear_incidents_from_certified_skip() -> None:
    job = _post_merge()["jobs"]["green-run-cleanup"]
    condition = str(job.get("if") or "")
    for gate in (
        "needs.lint.result",
        "needs.fast-test.result",
        "needs.explorer-tokens.result",
        "needs.medium-test.result",
    ):
        assert f"{gate} == 'success'" in condition
    # Certified skips report 'skipped', so the all-success conjunction is false.


def test_metrics_records_certifying_run_id() -> None:
    job = _post_merge()["jobs"]["metrics"]
    assert "queue-certification" in job["needs"]
    assert job["env"]["CERTIFYING_RUN_ID"] == "${{ needs.queue-certification.outputs.certifying_run_id }}"
    step = next(step for step in job["steps"] if "dev-loop-metrics" in str(step.get("run", "")))
    assert "queue_certified_by_run_id" in step["run"]


def test_baseline_selection_walks_back_past_certified_runs() -> None:
    text = POST_MERGE.read_text(encoding="utf-8")
    assert 'any(.kind == "certified")' in text or '.kind == "certified"' in text
    assert "walking back" in text


# ---------------------------------------------------------------------------
# results-explorer-browser.yml wiring
# ---------------------------------------------------------------------------


def test_browser_certification_requires_browser_gate() -> None:
    # Always runs (see above); the script limits certification to pushes to
    # develop and additionally requires the queue run's browser gate here.
    job = _jobs("results-explorer-browser.yml")["queue-certification"]
    assert job.get("if") is None
    assert job["permissions"]["actions"] == "read"
    lookup = next(step for step in job["steps"] if step.get("id") == "certify")
    assert "--require-browser-gate" in lookup["run"]


def test_browser_suite_skips_only_on_certified_develop_push() -> None:
    jobs = _jobs("results-explorer-browser.yml")
    for name in ("chromium", "firefox-smoke", "webkit-smoke"):
        job = jobs[name]
        assert "queue-certification" in job["needs"]
        condition = str(job.get("if") or "")
        assert "needs.explorer-changes.outputs.needed == 'true'" in condition
        assert CERTIFIED_GUARD in condition


def test_browser_gate_passes_certified_skip_with_run_id() -> None:
    evaluate = gate_mod.evaluate_gate
    passes, message = evaluate("success", "skipped", "true", "true", "424242")
    assert passes is True
    assert "424242" in message
    passes, _ = evaluate("success", "skipped", "true", "", "")
    assert passes is False
    passes, _ = evaluate("failure", "skipped", "true", "true", "424242")
    assert passes is False
    passes, _ = evaluate("success", "success", "true", "true", "424242")
    assert passes is True


def test_browser_gate_aggregate_step_receives_certification_env() -> None:
    gate = _jobs("results-explorer-browser.yml")["browser-required-result"]
    assert "queue-certification" in gate["needs"]
    step = next(step for step in gate["steps"] if "browser_gate_aggregate" in str(step.get("run", "")))
    assert step["env"]["CERTIFIED"] == "${{ needs.queue-certification.outputs.certified }}"
    assert step["env"]["CERTIFYING_RUN_ID"] == "${{ needs.queue-certification.outputs.certifying_run_id }}"


def test_queue_certification_script_is_stdlib_only() -> None:
    text = (SCRIPTS / "queue_certification.py").read_text(encoding="utf-8")
    assert "import requests" not in text
    assert "subprocess" not in text
