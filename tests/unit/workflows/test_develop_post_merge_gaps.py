"""Contracts for develop-post-merge push-drop sweep + gap instrumentation.

Pins:

1. develop-post-merge.yml keeps the push trigger and adds an additive schedule
   with a fixed concurrency group that will not cancel SHA-keyed push runs.
2. Mutation jobs and medium-test are excluded from schedule.
3. Every checkout pins develop on schedule.
4. develop-post-merge-gap-detector.yml exists as a cheap read-only canary.
5. Pure gap-classification + unique-headSha pagination logic in
   scripts/detect_develop_post_merge_gaps.py.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
POST_MERGE = REPO_ROOT / ".github" / "workflows" / "develop-post-merge.yml"
GAP_DETECTOR = REPO_ROOT / ".github" / "workflows" / "develop-post-merge-gap-detector.yml"
SCRIPT = REPO_ROOT / "scripts" / "detect_develop_post_merge_gaps.py"
GAPS_DOC = REPO_ROOT / "docs" / "operations" / "develop-post-merge-gaps.md"
INVENTORY_DOC = REPO_ROOT / "docs" / "operations" / "develop-push-drop-inventory.md"

MUTATION_JOBS = (
    "auto-revert-on-failure",
    "green-run-cleanup",
    "close-orphaned-prs",
)
CHECKOUT_PIN = "github.event_name == 'schedule' && 'develop' || github.sha"
SCHEDULE_EXCLUSION = "github.event_name != 'schedule'"


def _load_script():
    spec = importlib.util.spec_from_file_location("_detect_post_merge_gaps", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_script()


def _load_workflow(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


# ---------------------------------------------------------------------------
# develop-post-merge.yml contracts
# ---------------------------------------------------------------------------
def test_post_merge_keeps_push_and_adds_schedule() -> None:
    workflow = _load_workflow(POST_MERGE)
    # PyYAML 1.1 treats the key `on` as boolean True.
    on = workflow[True]
    assert "push" in on
    assert on["push"]["branches"] == ["develop"]
    assert "schedule" in on
    crons = [entry["cron"] for entry in on["schedule"]]
    assert crons, "expected at least one schedule cron"
    assert "workflow_dispatch" in on


def test_post_merge_schedule_uses_fixed_concurrency_group() -> None:
    """Schedule must not share the SHA-keyed group used by push runs."""
    text = POST_MERGE.read_text(encoding="utf-8")
    assert "develop-post-merge-schedule" in text
    assert "github.event_name == 'schedule'" in text
    # Push path never cancels in progress; schedule may supersede itself.
    assert "cancel-in-progress: ${{ github.event_name == 'schedule' }}" in text
    assert "develop-post-merge-" in text


def test_post_merge_workflow_permissions_stay_contents_read() -> None:
    """No new workflow-level permission classes beyond today's baseline."""
    workflow = _load_workflow(POST_MERGE)
    assert workflow.get("permissions") == {"contents": "read"}


def test_post_merge_gate_jobs_still_present() -> None:
    workflow = _load_workflow(POST_MERGE)
    jobs = workflow["jobs"]
    for name in ("lint", "fast-test", "explorer-tokens", "medium-test"):
        assert name in jobs, f"missing gate job {name}"


def test_post_merge_schedule_checkouts_pin_develop() -> None:
    """Every checkout must pin develop on schedule (count match)."""
    text = POST_MERGE.read_text(encoding="utf-8")
    checkout_count = len(re.findall(r"uses:\s*actions/checkout@v4", text))
    pin_count = text.count(CHECKOUT_PIN)
    assert checkout_count >= 1
    assert pin_count == checkout_count, (
        f"expected every checkout to pin develop on schedule; "
        f"found {checkout_count} checkouts but {pin_count} pin expressions"
    )


def test_mutation_jobs_exclude_schedule() -> None:
    """auto-revert / green-run-cleanup / close-orphaned must not run on schedule."""
    workflow = _load_workflow(POST_MERGE)
    jobs = workflow["jobs"]
    for name in MUTATION_JOBS:
        assert name in jobs, f"missing mutation job {name}"
        job_if = str(jobs[name].get("if", ""))
        assert SCHEDULE_EXCLUSION in job_if, f"{name} must gate on {SCHEDULE_EXCLUSION!r}; got if={job_if!r}"


def test_mutation_jobs_preserve_push_path_conditions() -> None:
    """Push-path behavior must not be weakened when adding schedule exclusion."""
    workflow = _load_workflow(POST_MERGE)
    jobs = workflow["jobs"]

    auto = str(jobs["auto-revert-on-failure"]["if"])
    assert "always()" in auto
    assert "needs.lint.result == 'failure'" in auto
    assert "needs.medium-test.result == 'failure'" in auto
    # event_name leads so always() cannot re-enable the job on schedule.
    assert auto.index(SCHEDULE_EXCLUSION) < auto.index("always()")

    green = str(jobs["green-run-cleanup"]["if"])
    assert "always()" in green
    assert "needs.lint.result == 'success'" in green
    assert "needs.medium-test.result == 'success'" in green
    assert green.index(SCHEDULE_EXCLUSION) < green.index("always()")

    # close-orphaned had no prior if; exclusion alone is the gate.
    close = str(jobs["close-orphaned-prs"]["if"])
    assert SCHEDULE_EXCLUSION in close


def test_medium_test_is_slim_schedule_omitted() -> None:
    """Cost decision: medium-test runs on push/dispatch only, not schedule."""
    workflow = _load_workflow(POST_MERGE)
    medium_if = str(workflow["jobs"]["medium-test"].get("if", ""))
    assert SCHEDULE_EXCLUSION in medium_if
    # Slim gates remain unconditional (no schedule exclusion).
    for name in ("lint", "fast-test", "explorer-tokens"):
        job_if = workflow["jobs"][name].get("if")
        assert job_if is None or SCHEDULE_EXCLUSION not in str(job_if)


# ---------------------------------------------------------------------------
# gap detector workflow contracts
# ---------------------------------------------------------------------------
def test_gap_detector_workflow_is_read_only_scheduled_canary() -> None:
    workflow = _load_workflow(GAP_DETECTOR)
    # PyYAML 1.1 treats the key `on` as boolean True.
    on = workflow[True]
    assert "schedule" in on
    assert "workflow_dispatch" in on
    assert "push" not in on  # instrumentation, not another push-spam path

    perms = workflow.get("permissions") or {}
    assert perms.get("contents") == "read"
    assert perms.get("actions") == "read"
    # No write surfaces.
    for key in ("pull-requests", "issues", "contents"):
        if key == "contents":
            assert perms[key] == "read"
        else:
            assert key not in perms or perms[key] == "read"

    jobs = workflow["jobs"]
    assert len(jobs) == 1
    detect = next(iter(jobs.values()))
    steps_text = yaml.dump(detect.get("steps") or [])
    assert "detect_develop_post_merge_gaps.py" in steps_text


def test_gap_detector_concurrency_does_not_cancel_in_progress() -> None:
    workflow = _load_workflow(GAP_DETECTOR)
    concurrency = workflow.get("concurrency") or {}
    assert concurrency.get("cancel-in-progress") is False
    assert concurrency.get("group") == "develop-post-merge-gap-detector"


# ---------------------------------------------------------------------------
# Ops inventory for the broader develop-push class
# ---------------------------------------------------------------------------
def test_gaps_doc_links_push_drop_inventory() -> None:
    """Incident doc must point maintainers at the full develop-push inventory."""
    text = GAPS_DOC.read_text(encoding="utf-8")
    assert "develop-push-drop-inventory" in text
    assert "push-drop" in text or "schedule" in text


def test_push_drop_inventory_names_develop_push_subjects() -> None:
    """Inventory must name the post-merge backstop and the other develop-push subjects."""
    assert INVENTORY_DOC.is_file(), f"missing inventory doc at {INVENTORY_DOC}"
    text = INVENTORY_DOC.read_text(encoding="utf-8")
    for needle in (
        "develop-post-merge",
        "orphaned-commit-detector",
        "submission-validator-drift-check",
        "sync-results-data-to-published",
        "results-explorer-browser",
        "corpus-drift-check",
        "push-drop",
        "schedule",
    ):
        assert needle in text, f"inventory missing {needle!r}"


def test_push_drop_inventory_subject_set_matches_workflows() -> None:
    """Table subject set must stay aligned with workflows that push to develop."""
    subjects: list[str] = []
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = _load_workflow(path)
        on = workflow.get(True) or workflow.get("on")
        if not isinstance(on, dict) or "push" not in on:
            continue
        push = on["push"]
        hits_develop = False
        if push is None:
            hits_develop = True
        elif isinstance(push, dict):
            if "tags" in push and "branches" not in push:
                hits_develop = False
            else:
                branches = push.get("branches")
                if branches is None and "branches-ignore" not in push:
                    hits_develop = "tags" not in push
                else:
                    hits_develop = branches is not None and "develop" in list(branches)
        if hits_develop:
            subjects.append(path.name)

    expected = {
        "develop-post-merge.yml",
        "docs.yml",
        "orphaned-commit-detector.yml",
        "publication-lane-docs.yml",
        "publication-lane-explorer.yml",
        "results-explorer-browser.yml",
        "submission-validator-drift-check.yml",
        "sync-results-data-to-published.yml",
    }
    assert set(subjects) == expected, f"develop-push subject set drifted: {subjects}"

    inventory = INVENTORY_DOC.read_text(encoding="utf-8")
    for name in expected:
        assert name in inventory, f"inventory does not list {name}"
    assert "| `docs.yml` | `develop`, all paths |" in inventory


# ---------------------------------------------------------------------------
# Pure script logic
# ---------------------------------------------------------------------------
def test_parse_sha_lines_ignores_comments_and_messages() -> None:
    text = """
    # header
    abcdef0123456789 deadbeef comment ignored as message
    \t
    1111111111111111
    """
    assert mod.parse_sha_lines(text) == [
        "abcdef0123456789",
        "1111111111111111",
    ]


def test_find_uncovered_reports_missing_in_order() -> None:
    commits = ["aaa", "bbb", "ccc", "ddd"]
    runs = {"aaa", "ccc"}
    assert mod.find_uncovered(commits, runs) == ["bbb", "ddd"]


def test_find_uncovered_is_prefix_aware() -> None:
    full = "abcdef0123456789abcdef0123456789abcdef01"
    assert mod.find_uncovered([full], {"abcdef01"}) == []
    assert mod.find_uncovered(["abcdef01"], {full}) == []
    assert mod.find_uncovered([full], {"deadbeef"}) == [full]


def test_find_uncovered_empty_when_fully_covered() -> None:
    commits = ["a" * 40, "b" * 40]
    assert mod.find_uncovered(commits, set(commits)) == []


def test_format_report_mentions_uncovered_shas() -> None:
    report = mod.format_report(["a", "b"], ["b"], commit_limit=2, run_count=1)
    assert "uncovered: 1" in report
    assert "b" in report
    assert "develop-post-merge" in report


def test_accumulate_unique_head_shas_stops_at_min_unique() -> None:
    pages = [
        [{"headSha": "aaa", "databaseId": 1}, {"headSha": "aaa", "databaseId": 2}],
        [{"headSha": "bbb", "databaseId": 3}],
        [{"headSha": "ccc", "databaseId": 4}],  # should not be needed
    ]
    got = mod.accumulate_unique_head_shas(pages, min_unique=2)
    assert got == {"aaa", "bbb"}


def test_live_run_head_shas_paginates_past_tip_flood() -> None:
    """100 schedule runs for tip must not hide older push-covered SHAs."""
    tip = "t" * 40
    older = [f"{i:040x}" for i in range(1, 6)]  # five distinct older SHAs

    # First 100 rows are all tip (schedule self-poisoning shape).
    # Deeper rows carry the older push headShas.
    def list_runs(limit: int) -> list[dict]:
        rows: list[dict] = []
        for i in range(100):
            rows.append({"headSha": tip, "databaseId": i + 1, "event": "schedule"})
        for i, sha in enumerate(older):
            rows.append({"headSha": sha, "databaseId": 200 + i, "event": "push"})
        return rows[:limit]

    unique = mod.live_run_head_shas(
        min_unique=1 + len(older),  # tip + all older
        page_size=100,
        max_rows=200,
        list_runs=list_runs,
    )
    assert tip in unique
    for sha in older:
        assert sha in unique, f"older push SHA {sha} must survive tip flood"
    # And find_uncovered must not false-gap those older commits.
    commits = [tip, *older]
    assert mod.find_uncovered(commits, unique) == []


def test_live_run_head_shas_still_reports_true_gaps() -> None:
    tip = "a" * 40
    covered = "b" * 40
    missing = "c" * 40

    def list_runs(limit: int) -> list[dict]:
        rows = [
            {"headSha": tip, "databaseId": 1},
            {"headSha": covered, "databaseId": 2},
        ]
        return rows[:limit]

    unique = mod.live_run_head_shas(
        min_unique=20,
        page_size=10,
        max_rows=50,
        list_runs=list_runs,
    )
    assert mod.find_uncovered([tip, covered, missing], unique) == [missing]


def test_cli_exits_one_on_gap(tmp_path: Path) -> None:
    commits = tmp_path / "commits.txt"
    runs = tmp_path / "runs.txt"
    commits.write_text("aaa\nbbb\n", encoding="utf-8")
    runs.write_text("aaa\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--commits-file", str(commits), "--runs-file", str(runs)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "bbb" in completed.stderr


def test_cli_exits_zero_when_covered(tmp_path: Path) -> None:
    commits = tmp_path / "commits.txt"
    runs = tmp_path / "runs.txt"
    commits.write_text("aaa\nbbb\n", encoding="utf-8")
    runs.write_text("aaa\nbbb\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--commits-file", str(commits), "--runs-file", str(runs), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert '"ok": true' in completed.stdout
