"""Tests for the receipt-bound medium-tier preflight stage (ci-dedupe-05).

`make pr-preflight-medium-tests` runs the exact CI medium selection
(`make test-medium`, no local-only subset) through local_validation's
medium-tier gate when the path classifier says the diff needs code CI,
and skips otherwise. Failure propagates: the stage fails pr-preflight
and leaves no receipt behind.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
CLASSIFIER = [sys.executable, str(ROOT / "scripts" / "path_filter_decision.py")]
LOCAL_VALIDATION = [sys.executable, str(ROOT / "scripts" / "local_validation.py")]

GATE = "medium-tier"


def _decision(tmp_path: Path, *, code: bool, skill_only: bool = False) -> Path:
    payload = {
        "skill_integrity_needed": skill_only,
        "content_guard_needed": not code and not skill_only,
        "skill_integrity_only": skill_only,
        "needs_code_ci": code,
    }
    path = tmp_path / f"decision-{code}-{skill_only}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _check(decision: Path) -> int:
    return subprocess.run(
        [*CLASSIFIER, "--json-in", str(decision), "--check", "needs-code-ci"],
        capture_output=True,
        text=True,
    ).returncode


def test_code_routed_diff_needs_medium_tier(tmp_path: Path) -> None:
    assert _check(_decision(tmp_path, code=True)) == 0


def test_content_only_diff_skips_medium_tier(tmp_path: Path) -> None:
    assert _check(_decision(tmp_path, code=False)) == 1


def test_skill_only_diff_skips_medium_tier(tmp_path: Path) -> None:
    assert _check(_decision(tmp_path, code=False, skill_only=True)) == 1


def _makefile_target_body(target_name: str) -> str:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.split(":", 1)[0] == target_name),
        None,
    )
    assert start is not None, f"Makefile target not found: {target_name}"
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith(("\t", " ")):
            break
        body.append(line)
    return "".join(body)


def test_medium_stage_uses_classifier_and_receipt_bound_ci_selection() -> None:
    body = _makefile_target_body("pr-preflight-medium-tests")
    assert "scripts/path_filter_decision.py" in body
    assert "--check needs-code-ci" in body
    assert "local-validation GATE=medium-tier" in body
    # Same marker selection as CI: the target must invoke make test-medium,
    # never its own pytest subset.
    assert 'CMD="make test-medium"' in body
    assert "pytest -m" not in body


def test_medium_stage_scrubs_control_vars_from_gate_env() -> None:
    # GNU make exports command-line variables to recipe environments and
    # smuggles their assignments inside MAKEFLAGS. A leaked PATH_DECISION
    # makes test-spawned makes take the caller-supplied branch with no
    # lists dir ("PATH_LISTS is required"); a leaked SKIP_FAST_TESTS flips
    # the route into its skip branch inside the suite.
    body = _makefile_target_body("pr-preflight-medium-tests")
    assert "env -u PATH_DECISION" in body
    assert "-u PATH_LISTS" in body
    assert "-u SKIP_FAST_TESTS" in body
    assert "MAKEFLAGS=" in body


def test_medium_stage_failure_is_not_swallowed() -> None:
    body = _makefile_target_body("pr-preflight-medium-tests")
    assert "set -eu" in body
    for mask in ("|| true", "|| exit 0", "|| true;"):
        assert mask not in body
    assert "\n\t-" not in body


def test_required_preflight_runs_medium_stage() -> None:
    body = _makefile_target_body("pr-preflight-uncached")
    assert "pr-preflight-medium-tests" in body


def test_failing_gate_command_fails_and_leaves_no_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipts = tmp_path / "receipts"
    monkeypatch.setenv("BENCHBOX_VALIDATION_RECEIPTS_DIR", str(receipts))
    gate = "probe-failing-medium-tier"
    proc = subprocess.run(
        [*LOCAL_VALIDATION, "run", "--gate", gate, "--", sys.executable, "-c", "raise SystemExit(3)"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert proc.returncode != 0
    stored = list(receipts.rglob("*")) if receipts.exists() else []
    assert [path for path in stored if path.is_file() and gate in path.name] == []


def test_skip_paths_exit_zero_without_running_tests(tmp_path: Path) -> None:
    for name, decision in (
        ("content", _decision(tmp_path, code=False)),
        ("skill", _decision(tmp_path, code=False, skill_only=True)),
    ):
        proc = subprocess.run(
            ["make", "-s", "pr-preflight-medium-tests", f"PATH_DECISION={decision}"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        assert proc.returncode == 0, f"{name} skip path failed: {proc.stderr[-2000:]}"
        assert "skipping medium tier" in proc.stdout
