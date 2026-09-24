"""Tests for the hourly sweep early exit on covered tips.

Covers the lookup decision table in scripts/sweep_coverage.py and the
workflow wiring in develop-post-merge.yml: a tip with a success/failure
push run (or a queue certification under ci-dedupe-01's exact rule) lets
the scheduled sweep exit early with a step-summary note, while a
cancelled/missing/running push run, an uncovered tip, or any lookup
error runs the full slim gates. Push and dispatch never exit early, and
mutation jobs stay schedule-excluded exactly as before.
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
GAP_DETECTOR = REPO_ROOT / ".github" / "workflows" / "develop-post-merge-gap-detector.yml"

_SWEEP_SPEC = importlib.util.spec_from_file_location("sweep_coverage", SCRIPTS / "sweep_coverage.py")
assert _SWEEP_SPEC is not None and _SWEEP_SPEC.loader is not None
sweep = importlib.util.module_from_spec(_SWEEP_SPEC)
sys.modules[_SWEEP_SPEC.name] = sweep
_SWEEP_SPEC.loader.exec_module(sweep)

SHA = "c" * 40
REPO = "BenchBox-dev/BenchBox"
TOKEN = "test-token"
COVERED_GUARD = "needs.sweep-coverage.outputs.covered != 'true'"


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


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


def _run_record(
    run_id: int,
    *,
    event: str = "push",
    conclusion: str | None = "success",
    head_sha: str = SHA,
    path: str = ".github/workflows/develop-post-merge.yml",
) -> dict[str, object]:
    return {
        "id": run_id,
        "event": event,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "path": path,
        "created_at": "2026-09-17T12:00:00Z",
    }


def _merge_group_run(run_id: int) -> dict[str, object]:
    return {
        "id": run_id,
        "event": "merge_group",
        "conclusion": "success",
        "head_sha": SHA,
        "path": ".github/workflows/pr.yml",
        "created_at": "2026-09-17T11:00:00Z",
    }


def _routes(
    push_runs: list[dict[str, object]],
    *,
    certify_runs: list[dict[str, object]] | None = None,
    certify_jobs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    routes: dict[str, object] = {
        f"https://api.github.com/repos/{REPO}/actions/workflows/.github%2Fworkflows%2Fdevelop-post-merge.yml/runs": {
            "workflow_runs": push_runs
        },
        f"https://api.github.com/repos/{REPO}/actions/workflows/.github%2Fworkflows%2Fpr.yml/runs": {
            "workflow_runs": certify_runs or []
        },
    }
    if certify_jobs is not None:
        routes[f"https://api.github.com/repos/{REPO}/actions/runs/555/jobs"] = {"jobs": certify_jobs}
    return routes


def _required_job_ok() -> list[dict[str, object]]:
    return [{"name": "ci-required-result", "conclusion": "success"}]


def _cover(*args: object, **kwargs: object) -> dict[str, object]:
    """Call the lookup as a schedule run unless the test says otherwise."""
    kwargs.setdefault("event", "schedule")
    return sweep.find_coverage(*args, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# lookup decision table
# ---------------------------------------------------------------------------


def test_successful_push_run_covers_tip() -> None:
    result = _cover(SHA, REPO, TOKEN, _fake_urlopen(_routes([_run_record(101)])))
    assert result == {
        "covered": True,
        "covering_run_id": 101,
        "reason": "push run 101 of develop-post-merge.yml concluded success on this exact SHA",
    }


def test_failed_push_run_does_not_cover_tip() -> None:
    result = _cover(SHA, REPO, TOKEN, _fake_urlopen(_routes([_run_record(102, conclusion="failure")])))
    assert result["covered"] is False
    assert result["covering_run_id"] is None


def test_cancelled_push_run_is_not_coverage() -> None:
    routes = _routes([_run_record(103, conclusion="cancelled"), _run_record(104, conclusion="startup_failure")])
    result = _cover(SHA, REPO, TOKEN, _fake_urlopen(routes))
    assert result["covered"] is False
    assert result["covering_run_id"] is None


def test_running_push_run_is_not_coverage() -> None:
    routes = _routes([_run_record(105, conclusion=None)])
    result = _cover(SHA, REPO, TOKEN, _fake_urlopen(routes))
    assert result["covered"] is False


def test_dropped_push_runs_full_gates() -> None:
    # Simulated dropped push: no push run exists for the tip and the tip is
    # not queue-certified either, so the sweep must run the full gates.
    routes = _routes([], certify_runs=[])
    result = _cover(SHA, REPO, TOKEN, _fake_urlopen(routes))
    assert result["covered"] is False
    assert result["covering_run_id"] is None


def test_queue_certified_tip_covers_without_push_run() -> None:
    routes = _routes([], certify_runs=[_merge_group_run(555)], certify_jobs=_required_job_ok())
    result = _cover(SHA, REPO, TOKEN, _fake_urlopen(routes))
    assert result["covered"] is True
    assert result["covering_run_id"] == 555


def test_lookup_error_fails_open() -> None:
    routes = _routes([_run_record(101)])
    prefix = f"https://api.github.com/repos/{REPO}/actions/workflows/.github%2Fworkflows%2Fdevelop-post-merge.yml/runs"
    result = _cover(SHA, REPO, TOKEN, _fake_urlopen(routes, failures={prefix}))
    assert result["covered"] is False
    assert "lookup failed open" in str(result["reason"])


def test_non_schedule_event_never_exits_early() -> None:
    def _no_calls(request: object, timeout: object = None) -> _FakeResponse:
        raise AssertionError("no API call expected for a non-schedule event")

    for event in ("push", "workflow_dispatch"):
        result = sweep.find_coverage(SHA, REPO, TOKEN, _no_calls, event=event)
        assert result == {
            "covered": False,
            "covering_run_id": None,
            "reason": f"event {event!r} never exits early; running the full gates",
        }


def test_missing_inputs_fail_open() -> None:
    result = _cover("", REPO, TOKEN, _fake_urlopen({}))
    assert result["covered"] is False


def test_main_exits_zero_and_reports_covering_run(tmp_path: Path) -> None:
    output = tmp_path / "github_output.txt"
    summary = tmp_path / "summary.md"
    routes = _routes([_run_record(101)])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sweep.urllib.request, "urlopen", _fake_urlopen(routes))
        code = sweep.main(
            [
                "--sha",
                SHA,
                "--repo",
                REPO,
                "--token",
                TOKEN,
                "--event",
                "schedule",
                "--github-output",
                str(output),
                "--summary",
                str(summary),
            ]
        )
    assert code == 0
    written = output.read_text(encoding="utf-8")
    assert "covered=true" in written
    assert "covering_run_id=101" in written
    note = summary.read_text(encoding="utf-8")
    assert "101" in note
    assert "early exit" in note


def test_main_exits_zero_on_lookup_error(tmp_path: Path) -> None:
    output = tmp_path / "github_output.txt"
    routes = _routes([_run_record(101)])
    prefix = f"https://api.github.com/repos/{REPO}/actions/workflows/.github%2Fworkflows%2Fdevelop-post-merge.yml/runs"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sweep.urllib.request, "urlopen", _fake_urlopen(routes, failures={prefix}))
        code = sweep.main(
            ["--sha", SHA, "--repo", REPO, "--token", TOKEN, "--event", "schedule", "--github-output", str(output)]
        )
    assert code == 0
    assert "covered=false" in output.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# develop-post-merge.yml wiring
# ---------------------------------------------------------------------------


def _post_merge() -> dict[str, object]:
    return yaml.safe_load(POST_MERGE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_sweep_coverage_job_always_runs_with_actions_read() -> None:
    # The job must not be event-gated: downstream jobs read its outputs on
    # every event, and references to a skipped job's outputs do not
    # evaluate reliably. The script returns covered=false without any API
    # call for non-schedule events (tested at the script level).
    job = _post_merge()["jobs"]["sweep-coverage"]
    assert job.get("if") is None
    assert job["permissions"]["actions"] == "read"
    assert job["outputs"]["covered"] == "${{ steps.coverage.outputs.covered }}"
    assert job["outputs"]["covering_run_id"] == "${{ steps.coverage.outputs.covering_run_id }}"
    lookup = next(step for step in job["steps"] if step.get("id") == "coverage")
    assert "scripts/sweep_coverage.py" in lookup["run"]
    assert lookup["env"]["GH_TOKEN"] == "${{ github.token }}"


def test_slim_gates_skip_only_on_covered_schedule() -> None:
    jobs = _post_merge()["jobs"]
    for name in ("lint", "fast-test", "explorer-tokens"):
        job = jobs[name]
        assert "sweep-coverage" in job["needs"]
        condition = str(job.get("if") or "")
        assert "github.event_name != 'schedule'" in condition
        assert COVERED_GUARD in condition


def test_push_and_dispatch_never_exit_early() -> None:
    # Push runs the gates regardless of coverage; dispatch stays the
    # full-run escape hatch. Only a schedule run on a covered tip skips.
    jobs = _post_merge()["jobs"]
    for name in ("lint", "fast-test", "explorer-tokens"):
        condition = str(jobs[name].get("if") or "")
        assert "github.event_name != 'schedule'" in condition
        if name == "fast-test":
            assert "github.event_name != 'push'" in condition


def test_medium_test_and_mutations_keep_schedule_exclusion() -> None:
    jobs = _post_merge()["jobs"]
    assert "github.event_name != 'schedule'" in str(jobs["medium-test"].get("if") or "")
    for name in ("close-orphaned-prs", "auto-revert-on-failure", "green-run-cleanup"):
        assert "github.event_name != 'schedule'" in str(jobs[name].get("if") or "")


def test_hourly_cadence_unchanged() -> None:
    on = _post_merge()[True]
    crons = [entry["cron"] for entry in on["schedule"]]
    assert crons, "expected the hourly sweep cadence to stay"


def test_gap_detector_untouched_by_sweep_change() -> None:
    text = GAP_DETECTOR.read_text(encoding="utf-8")
    assert "sweep-coverage" not in text
    assert "sweep_coverage" not in text
