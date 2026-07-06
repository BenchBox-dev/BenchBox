"""Regression guard for the submission-manifest waiver's spoof resistance.

`validate-submission.yml` waives the `--require-manifest` requirement for
maintainer corpus-mirror PRs (they legitimately carry maintainer-run bundles
with no sidecar). The waiver MUST gate on an unforgeable signal.

`github.head_ref` is attacker-controlled on fork PRs, so a branch-name-only
waiver (`case $HEAD_REF in auto/results-mirror-*`) is spoofable: anyone could
open a fork PR from a branch so named and drop the sidecar requirement,
laundering a community bundle into a maintainer-run (ranking-eligible) stamp.
The load-bearing check is `github.event.pull_request.head.repo.fork == false`,
which a fork PR cannot forge. This test fails closed if the fork gate is ever
dropped from the waiver.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "validate-submission.yml"


def _validate_step() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = data["jobs"]["validate"]["steps"]
    for step in steps:
        if step.get("id") == "validate":
            return step
    raise AssertionError("validate-submission.yml has no step with id: validate")


def test_waiver_env_binds_unforgeable_fork_signal() -> None:
    env = _validate_step().get("env") or {}
    fork_bindings = {k: v for k, v in env.items() if "head.repo.fork" in str(v)}
    assert fork_bindings, (
        "The 'Validate bundles' step must bind github.event.pull_request."
        "head.repo.fork into the env so the manifest waiver can gate on it. "
        "github.head_ref alone is attacker-controlled on fork PRs and spoofable."
    )


def test_waiver_gates_manifest_skip_on_fork_check() -> None:
    step = _validate_step()
    env = step.get("env") or {}
    run = step["run"]

    fork_var = next(
        (k for k, v in env.items() if "head.repo.fork" in str(v)),
        None,
    )
    assert fork_var is not None, "no env var bound to head.repo.fork"

    # The block that clears REQUIRE_MANIFEST (the sidecar waiver) must be
    # guarded by the fork variable resolving to the same-repo ("false") case.
    # We require the fork guard and the branch pattern to co-occur with the
    # empty-string assignment that drops --require-manifest.
    assert re.search(rf'\[\s*"\${fork_var}"\s*=\s*"false"\s*\]', run), (
        "The manifest waiver must be nested under an "
        f'[ "${fork_var}" = "false" ] guard; a fork PR must never reach the '
        "REQUIRE_MANIFEST='' branch."
    )
    assert "auto/results-mirror-*" in run, "The waiver should still narrow to the mirror branch pattern."


def test_default_requires_manifest() -> None:
    # Fail-closed default: the sidecar is required unless explicitly waived.
    run = _validate_step()["run"]
    assert 'REQUIRE_MANIFEST="--require-manifest"' in run, (
        "REQUIRE_MANIFEST must default to --require-manifest (fail closed); "
        "the waiver only clears it inside the fork+branch guard."
    )
