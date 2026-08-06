"""Explicit auto-merge holds must survive push and nightly re-arm paths.

Defect (auto-merge-explicit-hold-is-not-durable): ``gh pr merge --disable-auto``
was not a durable product signal while re-arm paths could silently re-enable
auto-merge (historically: synchronize re-enable; nightly --apply if it ever
armed). Draft was the only durable hold. This suite pins the durable-hold
contract across workflow + sweep layers:

1. Synchronize never re-enables auto-merge (only revokes).
2. Label ``no-auto-merge`` blocks enable and triggers disable.
3. Draft remains a job-level hold.
4. Nightly green-unmerged ``--apply`` never enables auto-merge and does not
   classify an explicit hold as stranded.
5. Soundness disable unions base-ref + PR-copy predicates (enable still needs
   both false so a PR cannot weaken its own gate).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTO_MERGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "auto-merge-on-open.yml"
NIGHTLY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly.yml"
SWEEP_SCRIPT = REPO_ROOT / "_project" / "scripts" / "green_unmerged_sweep.py"
PR_TRIAGE_DOC = REPO_ROOT / "docs" / "operations" / "pr-triage.md"

HOLD_LABEL = "no-auto-merge"
ARM_COMMAND = "gh pr merge --auto --squash"
DISABLE_COMMAND = "gh pr merge --disable-auto"

# Exact enable/disable `if:` pins (collapsed form). Keep lockstep with
# tests/unit/workflows/test_auto_merge_enablement_point.py.
ENABLE_IF = (
    "steps.soundness.outputs.soundness_path != 'true' "
    "&& steps.hold.outputs.held != 'true' "
    "&& github.event.action == 'ready_for_review'"
)
SOUNDNESS_DISABLE_IF = "steps.soundness.outputs.soundness_path == 'true'"
HOLD_DISABLE_IF = "steps.hold.outputs.held == 'true'"


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow has no `on:` block"
    return triggers


def _steps_by_name(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    named: dict[str, dict[str, Any]] = {}
    for step in job.get("steps") or []:
        name = step.get("name")
        if name:
            named[str(name)] = step
    return named


def _collapsed_if(step: dict[str, Any]) -> str:
    raw = str(step.get("if") or "").strip()
    return re.sub(r"\s+", " ", raw)


def _enable_job() -> dict[str, Any]:
    workflow = _load_yaml(AUTO_MERGE_WORKFLOW)
    jobs = workflow.get("jobs") or {}
    assert "enable" in jobs
    return jobs["enable"]


def _load_sweep():
    spec = importlib.util.spec_from_file_location("_green_unmerged_sweep_hold", SWEEP_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Workflow: never re-arm on synchronize; hold label + draft are durable
# ---------------------------------------------------------------------------


def test_workflow_never_enables_on_synchronize() -> None:
    """Push must not re-arm auto-merge (historical defect class)."""
    steps = _steps_by_name(_enable_job())
    enable = steps["Enable squash auto-merge"]
    condition = _collapsed_if(enable)
    assert condition == ENABLE_IF
    assert "synchronize" not in condition
    assert ARM_COMMAND in str(enable.get("run") or "")


def test_workflow_enable_requires_absence_of_hold_label() -> None:
    """ready_for_review must not arm while no-auto-merge is present."""
    steps = _steps_by_name(_enable_job())
    enable = steps["Enable squash auto-merge"]
    assert _collapsed_if(enable) == ENABLE_IF
    assert "steps.hold.outputs.held != 'true'" in _collapsed_if(enable)


def test_workflow_hold_step_matches_exact_label() -> None:
    """Hold detection must be exact-name (grep -qxF), shared constant name."""
    text = AUTO_MERGE_WORKFLOW.read_text(encoding="utf-8")
    steps = _steps_by_name(_enable_job())
    hold = steps.get("Check explicit hold label")
    assert hold is not None, "hold check step missing"
    assert hold.get("id") == "hold"
    run = str(hold.get("run") or "")
    assert f"grep -qxF '{HOLD_LABEL}'" in run or f'grep -qxF "{HOLD_LABEL}"' in run
    assert "held=$held" in run or "held=" in run
    # Label constant appears in both layers for lockstep.
    assert HOLD_LABEL in text


def test_workflow_disables_on_explicit_hold() -> None:
    """Applying the hold label must revoke any enabled auto-merge."""
    steps = _steps_by_name(_enable_job())
    disable = steps.get("Disable auto-merge for explicit hold")
    assert disable is not None, "explicit-hold disable step missing"
    assert _collapsed_if(disable) == HOLD_DISABLE_IF
    assert DISABLE_COMMAND in str(disable.get("run") or "")


def test_workflow_disables_on_soundness() -> None:
    """Soundness revocation must remain independent of the hold path."""
    steps = _steps_by_name(_enable_job())
    disable = steps.get("Disable auto-merge for soundness PR")
    assert disable is not None
    assert _collapsed_if(disable) == SOUNDNESS_DISABLE_IF
    assert DISABLE_COMMAND in str(disable.get("run") or "")


def test_workflow_listens_for_labeled_to_make_hold_durable() -> None:
    """Without `labeled`, applying no-auto-merge would not revoke until a push."""
    types = _triggers(_load_yaml(AUTO_MERGE_WORKFLOW))["pull_request"]["types"]
    assert "labeled" in types
    for required in ("opened", "reopened", "ready_for_review", "synchronize"):
        assert required in types


def test_workflow_skips_drafts_at_job_level() -> None:
    job = _enable_job()
    assert "draft" in str(job.get("if") or "")
    assert "false" in str(job.get("if") or "")


def test_soundness_unions_base_ref_and_pr_copy_predicates() -> None:
    """Disable uses base OR PR-copy; enable still requires soundness_path != true.

    Base-ref alone cannot see a gate widened in the same PR. PR-copy alone
    would let a PR narrow the surface. Union + enable-on-not-true preserves
    both properties.
    """
    text = AUTO_MERGE_WORKFLOW.read_text(encoding="utf-8")
    assert "predicate_base.py" in text
    assert 'git show "origin/${{ github.base_ref }}:_project/scripts/auto_merge_soundness_paths.py"' in text
    # PR checkout copy is evaluated for the union (widening).
    assert "python3 _project/scripts/auto_merge_soundness_paths.py --stdin --format github-output" in text
    # Union is OR of both results.
    assert '[ "$base_result" = "soundness_path=true" ] || [ "$pr_result" = "soundness_path=true" ]' in text
    # Self-touch override remains.
    assert 'grep -qxF "_project/scripts/auto_merge_soundness_paths.py"' in text
    assert 'grep -qxF ".github/workflows/auto-merge-on-open.yml"' in text


# ---------------------------------------------------------------------------
# Sweep: never re-arm; honour the same hold label
# ---------------------------------------------------------------------------


def test_sweep_hold_label_constant_matches_workflow() -> None:
    sweep = _load_sweep()
    assert sweep.AUTO_MERGE_HOLD_LABEL == HOLD_LABEL
    assert HOLD_LABEL in AUTO_MERGE_WORKFLOW.read_text(encoding="utf-8")


def test_sweep_has_auto_merge_hold_label_is_exact() -> None:
    sweep = _load_sweep()
    assert sweep.has_auto_merge_hold_label([HOLD_LABEL]) is True
    assert sweep.has_auto_merge_hold_label(["no-auto-merge-except"]) is False
    assert sweep.has_auto_merge_hold_label(["enhancement", HOLD_LABEL]) is True
    assert sweep.has_auto_merge_hold_label([]) is False
    assert sweep.has_auto_merge_hold_label(None) is False


def test_sweep_explicit_hold_is_not_stranded() -> None:
    sweep = _load_sweep()
    assert (
        sweep.is_stranded(
            draft=False,
            required_green=True,
            auto_merge_enabled=False,
            soundness_gated=False,
            age_hours=10.0,
            grace_hours=2.0,
            explicit_hold=True,
        )
        is False
    )
    # Control: same row without hold is stranded.
    assert (
        sweep.is_stranded(
            draft=False,
            required_green=True,
            auto_merge_enabled=False,
            soundness_gated=False,
            age_hours=10.0,
            grace_hours=2.0,
            explicit_hold=False,
        )
        is True
    )


def test_sweep_classify_pr_reads_hold_label() -> None:
    import datetime as dt

    sweep = _load_sweep()
    now = dt.datetime(2026, 7, 23, 12, 0, tzinfo=dt.timezone.utc)
    pr = {
        "number": 99,
        "title": "held",
        "html_url": "https://example.invalid/99",
        "draft": False,
        "updated_at": "2026-07-23T08:00:00Z",
        "head_pushed_at": "2026-07-23T08:00:00Z",
        "auto_merge": None,
        "labels": [HOLD_LABEL],
        "changed_files": ["benchbox/platforms/duckdb/adapter.py"],
        "check_runs": [
            {
                "name": "ci-required-result",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-07-23T08:10:00Z",
            }
        ],
    }
    classified = sweep.classify_pr(pr, now)
    assert classified.explicit_hold is True
    assert classified.stranded is False


def test_sweep_apply_never_enables_auto_merge() -> None:
    """`--apply` must not call gh pr merge --auto / REST merge enablement.

    This is the nightly re-arm pin: the job runs with --apply, so any arming
    call in the script would re-arm holds the sweep did not set.
    """
    import ast

    text = SWEEP_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(text)
    # Walk Call nodes: no gh pr merge / merge-enable REST helpers.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # subprocess.run([...]) or similar list/tuple first arg with "gh" "pr" "merge"
        if not node.args:
            continue
        first = node.args[0]
        elts: list[ast.AST] = []
        if isinstance(first, (ast.List, ast.Tuple)):
            elts = list(first.elts)
        words: list[str] = []
        for elt in elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                words.append(elt.value)
        if len(words) >= 3 and words[0] == "gh" and words[1] == "pr" and words[2] == "merge":
            raise AssertionError(f"sweep must not invoke gh pr merge (found {words!r})")
        # Direct string call forms
    assert "never enables auto-merge" in text
    assert "/merges" not in text
    assert "put_auto_merge" not in text
    assert "enable_auto_merge" not in text
    # Apply path only mutates the digest issue, never a PR merge endpoint.
    apply_src = ast.get_source_segment(
        text, next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    )
    assert apply_src is not None
    assert "upsert_pinned_issue" in apply_src
    assert "gh pr merge" not in apply_src
    assert "auto_merge" in text  # still reads the field for classification


def test_nightly_invokes_sweep_apply_without_arming_flags() -> None:
    text = NIGHTLY_WORKFLOW.read_text(encoding="utf-8")
    assert "green_unmerged_sweep.py --apply" in text
    # Nightly must not pass any arm/enable flag if one is ever added.
    apply_lines = [
        line for line in text.splitlines() if "green_unmerged_sweep.py" in line and not line.lstrip().startswith("#")
    ]
    assert apply_lines, "nightly has no executable green_unmerged_sweep.py invocation"
    for apply_line in apply_lines:
        assert "--apply" in apply_line
        assert "--enable" not in apply_line
        assert "--arm" not in apply_line


def test_ops_docs_document_durable_hold() -> None:
    doc = PR_TRIAGE_DOC.read_text(encoding="utf-8")
    assert "Durable auto-merge holds" in doc
    assert HOLD_LABEL in doc
    assert "never" in doc.lower() and "enables auto-merge" in doc.lower()
