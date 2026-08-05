"""Contracts for develop-post-merge push-drop sweep + gap instrumentation.

Pins:

1. develop-post-merge.yml keeps the push trigger and adds an additive schedule
   with a fixed concurrency group that will not cancel SHA-keyed push runs.
2. develop-post-merge-gap-detector.yml exists as a cheap read-only canary.
3. Pure gap-classification logic in scripts/detect_develop_post_merge_gaps.py.
"""

from __future__ import annotations

import importlib.util
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
    """Schedule must not share the SHA-keyed group used by push runs.

    A fixed schedule group with cancel-in-progress false means a sweep cannot
    cancel (or be cancelled by) a concurrent push-triggered run for the tip.
    """
    text = POST_MERGE.read_text(encoding="utf-8")
    assert "develop-post-merge-schedule" in text
    assert "github.event_name == 'schedule'" in text
    assert "cancel-in-progress: false" in text
    # Push path still SHA-keyed (format or legacy literal both acceptable as
    # long as schedule is the fixed branch of the expression).
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
    """Schedule must not silently re-target if the default branch ever moves."""
    text = POST_MERGE.read_text(encoding="utf-8")
    assert "github.event_name == 'schedule' && 'develop' || github.sha" in text


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
