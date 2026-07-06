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
    assert re.search(rf'\[\s*"\${fork_var}"\s*=\s*"false"\s*\]', run), (
        "The manifest waiver must be nested under an "
        f'[ "${fork_var}" = "false" ] guard; a fork PR must never reach the '
        "REQUIRE_MANIFEST='' branch."
    )
    assert "auto/results-mirror-*" in run, "The waiver should still narrow to the mirror branch pattern."

    # Presence alone doesn't prove NESTING: a future edit could leave the fork
    # check in the step but move the mirror-branch waiver back outside it,
    # reintroducing the fork-branch spoofing bypass while both substrings
    # above still individually appear somewhere in `run`. Extract the actual
    # `then ... fi` body guarded by the fork check and require BOTH the
    # branch pattern and the empty-REQUIRE_MANIFEST assignment to be inside
    # it, not just present anywhere in the step.
    guard_match = re.search(
        rf'\[\s*"\${fork_var}"\s*=\s*"false"\s*\]\s*;\s*then\n(.*?)\nfi\b',
        run,
        re.DOTALL,
    )
    assert guard_match is not None, (
        f'Could not find a `if [ "${fork_var}" = "false" ]; then ... fi` block to inspect - '
        "the fork guard must wrap a then/fi body, not just appear in a condition."
    )
    guarded_body = guard_match.group(1)
    assert "auto/results-mirror-*" in guarded_body, (
        "The mirror branch pattern check must be NESTED inside the "
        f'[ "${fork_var}" = "false" ] guard body, not merely present elsewhere in the step - '
        "otherwise a same-named branch on a fork PR could still reach the waiver."
    )
    assert re.search(r'REQUIRE_MANIFEST\s*=\s*""', guarded_body), (
        'The REQUIRE_MANIFEST="" assignment (the actual waiver) must be NESTED inside the '
        f'[ "${fork_var}" = "false" ] guard body, not merely present elsewhere in the step - '
        "otherwise a fork PR could reach the waiver regardless of the fork check's outcome."
    )


def test_default_requires_manifest() -> None:
    # Fail-closed default: the sidecar is required unless explicitly waived.
    run = _validate_step()["run"]
    assert 'REQUIRE_MANIFEST="--require-manifest"' in run, (
        "REQUIRE_MANIFEST must default to --require-manifest (fail closed); "
        "the waiver only clears it inside the fork+branch guard."
    )
