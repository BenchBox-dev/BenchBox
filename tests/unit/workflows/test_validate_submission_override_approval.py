"""Override approval separation in validate-submission.yml (review follow-ups).

Covers two review threads on the ``Check override approvals`` step:

* reused override artifacts: a PR that touches a bundle covered by an
  unchanged override must still obtain the approver's review — the gate
  enumerates the override sibling of every changed primary bundle, not
  only override files changed in the PR;
* paginated reviews: the ``gh api --paginate`` output must be slurped and
  flattened before selecting the approver's latest review, so an approval
  on a later page is honored instead of failing the parse.

Also pins the ``*.override.json`` exclusion in the primary-bundle counters
that must agree with the corpus inventory (publication-deploy,
publication-corpus-cutover, seed-corpus).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
VALIDATE_WORKFLOW = ROOT / ".github" / "workflows" / "validate-submission.yml"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "publication-deploy.yml"
CUTOVER_WORKFLOW = ROOT / ".github" / "workflows" / "publication-corpus-cutover.yml"
SEED_WORKFLOW = ROOT / ".github" / "workflows" / "seed-corpus.yml"


def _steps(workflow: Path, job: str) -> list[dict]:
    return yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"][job]["steps"]


def _approval_run() -> str:
    for step in _steps(VALIDATE_WORKFLOW, "validate"):
        if step.get("name") == "Check override approvals":
            return str(step["run"])
    raise AssertionError("Check override approvals step missing from validate-submission.yml")


def _review_program(run: str) -> str:
    candidates = re.findall(r'python3 -c "([^"]+)"', run)
    programs = [c for c in candidates if "all_reviews" in c]
    assert programs, "review-selection python3 -c snippet missing from approval step"
    return programs[0]


def _run_review_program(program: str, payload: object, *, want: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "", "WANT": want},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _review(login: str, state: str) -> dict:
    return {"user": {"login": login}, "state": state}


# ---------------------------------------------------------------------------
# reused overrides (thread 4072122066)
# ---------------------------------------------------------------------------


def test_approval_enumerates_bundle_associated_overrides() -> None:
    run = _approval_run()
    assert "CHANGED_BUNDLES" in run
    assert r"\.(manifest|plans|tuning|applied|override)\.json$" in run
    assert "${bundle%.json}.override.json" in run
    assert 'git cat-file -e "$EFFECTIVE_MERGE:$candidate"' in run
    assert "sort -u" in run


def test_approval_still_covers_directly_changed_overrides() -> None:
    run = _approval_run()
    assert "*.override.json" in run
    assert "--diff-filter=ACMR" in run


def test_no_change_message_covers_associated_case() -> None:
    assert "No override artifacts changed or associated." in _approval_run()


# ---------------------------------------------------------------------------
# paginated reviews (thread 4072122073)
# ---------------------------------------------------------------------------


def test_reviews_are_slurped_before_parsing() -> None:
    run = _approval_run()
    assert "--paginate --slurp" in run
    program = _review_program(run)
    assert "pages" in program
    assert "all_reviews" in program


def test_single_page_approval_recognized() -> None:
    program = _review_program(_approval_run())
    payload = [_review("alice", "COMMENTED"), _review("reviewer2", "APPROVED")]
    assert _run_review_program(program, payload, want="reviewer2") == "yes"


def test_slurped_multi_page_approval_on_later_page_recognized() -> None:
    """The exact reported failure: APPROVED sits on page two of slurped output."""
    program = _review_program(_approval_run())
    payload = [
        [_review("alice", "APPROVED"), _review("reviewer2", "COMMENTED")],
        [_review("reviewer2", "APPROVED")],
    ]
    assert _run_review_program(program, payload, want="reviewer2") == "yes"


def test_latest_decision_wins_across_pages() -> None:
    program = _review_program(_approval_run())
    payload = [
        [_review("reviewer2", "APPROVED")],
        [_review("reviewer2", "CHANGES_REQUESTED")],
    ]
    assert _run_review_program(program, payload, want="reviewer2") == "no"


def test_other_approver_does_not_satisfy() -> None:
    program = _review_program(_approval_run())
    payload = [[_review("alice", "APPROVED")]]
    assert _run_review_program(program, payload, want="reviewer2") == "no"


def test_dismissed_latest_review_does_not_satisfy() -> None:
    program = _review_program(_approval_run())
    payload = [[_review("reviewer2", "APPROVED"), _review("reviewer2", "DISMISSED")]]
    assert _run_review_program(program, payload, want="reviewer2") == "no"


# ---------------------------------------------------------------------------
# primary-bundle counters exclude overrides (thread 4072122058)
# ---------------------------------------------------------------------------


def _all_run_text(workflow: Path) -> str:
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    return "\n".join(str(step.get("run", "")) for job in jobs.values() for step in job.get("steps", []))


def test_deploy_bundle_count_excludes_overrides() -> None:
    run = _all_run_text(DEPLOY_WORKFLOW)
    assert "BUNDLE_COUNT" in run
    assert "! -name '*.override.json'" in run


def test_cutover_count_primary_excludes_overrides() -> None:
    run = _all_run_text(CUTOVER_WORKFLOW)
    assert "count_primary" in run
    assert "! -name '*.override.json'" in run


def test_seed_corpus_locate_excludes_overrides() -> None:
    raw = SEED_WORKFLOW.read_text(encoding="utf-8")
    assert '! -name "*.override.json"' in raw
