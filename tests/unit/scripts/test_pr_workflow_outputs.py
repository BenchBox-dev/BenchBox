"""Regression guard for the develop-PR gate's path-filter plumbing.

Every `needs.ci-paths.outputs.<name>` referenced anywhere in
``.github/workflows/pr.yml`` MUST be declared in the ``ci-paths`` job's
``outputs:`` map. GitHub Actions only propagates a step output to
``needs.<job>.outputs.<name>`` when the job re-exports it under ``outputs:``;
an undeclared reference silently evaluates to the empty string, so a job gated
on it (``== 'true'``) is permanently skipped. That exact bug once made
``package-smoke``/``dependency-audit``/``parity-check`` no-ops that
``ci-required-result`` still counted as passing. This test fails closed so it
cannot silently recur.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

PR_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "pr.yml"

_REFERENCE_RE = re.compile(r"needs\.ci-paths\.outputs\.([A-Za-z0-9_-]+)")


def _declared_ci_paths_outputs() -> set[str]:
    data = yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))
    ci_paths = data["jobs"]["ci-paths"]
    return set((ci_paths.get("outputs") or {}).keys())


def _referenced_ci_paths_outputs() -> set[str]:
    return set(_REFERENCE_RE.findall(PR_WORKFLOW.read_text(encoding="utf-8")))


def test_every_referenced_ci_paths_output_is_declared() -> None:
    declared = _declared_ci_paths_outputs()
    referenced = _referenced_ci_paths_outputs()
    undeclared = referenced - declared
    assert not undeclared, (
        "pr.yml references ci-paths outputs that are not declared in the "
        f"ci-paths job's `outputs:` map: {sorted(undeclared)}. Undeclared "
        "outputs resolve to '' at runtime, so any job gated on them is "
        "permanently skipped (and counted as passing). Add each to the "
        "ci-paths `outputs:` map as `<name>: ${{ steps.classify.outputs.<name> }}`."
    )


def test_packaging_and_viz_gates_are_wired() -> None:
    # These three jobs regressed to permanent-skip once; pin them explicitly so
    # a future refactor that drops the declaration is caught by name.
    declared = _declared_ci_paths_outputs()
    for required in ("packaging-needed", "viz-needed"):
        assert required in declared, (
            f"ci-paths must declare `{required}` — package-smoke / "
            "dependency-audit / parity-check gate on it."
        )
