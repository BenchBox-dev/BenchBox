from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from _project.scripts.oracle_reviewers import absence, runner
from _project.scripts.oracle_reviewers.commands import Invocation
from _project.scripts.oracle_reviewers.policy import Policy

pytestmark = [pytest.mark.unit, pytest.mark.fast]

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
VERDICT = {"summary": "fine", "findings": []}


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("a\n", encoding="utf-8")
    for args in (
        ("init", "-q"),
        ("add", "a.txt"),
        ("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init"),
    ):
        subprocess.run(["git", "-C", str(workspace), *args], check=True)
    head = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return workspace, head


def _fake_muse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "muse"
    script.write_text(f"#!{sys.executable}\nimport sys\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")


def _review(policy: Policy, tmp_path: Path, workspace: Path, head: str, prompt: str = "brief"):
    return runner.review(
        policy.reviewers["muse"], workspace=workspace, head_sha=head, prompt=prompt, scratch=tmp_path / "s", now=NOW
    )


def test_clean_verdict_is_recorded(policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, head = _workspace(tmp_path)
    _fake_muse(tmp_path, monkeypatch, f"print({json.dumps(json.dumps(VERDICT))})")
    outcome = _review(policy, tmp_path, workspace, head)
    assert outcome.missing is None
    assert outcome.verdict == VERDICT


def test_workspace_change_makes_the_reviewer_absent(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    body = f"open('{workspace}/b.txt', 'w').write('x')\nprint({json.dumps(json.dumps(VERDICT))})"
    _fake_muse(tmp_path, monkeypatch, body)
    outcome = _review(policy, tmp_path, workspace, head)
    assert outcome.missing is not None and outcome.missing.kind == absence.INVALID
    assert "changed the workspace" in outcome.missing.detail


def test_wrong_head_is_refused_before_running(policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, _ = _workspace(tmp_path)
    _fake_muse(tmp_path, monkeypatch, "raise SystemExit('must not run')")
    outcome = _review(policy, tmp_path, workspace, "f" * 40)
    assert outcome.missing is not None and "not at the reviewed head" in outcome.missing.detail


def test_truncated_or_empty_brief_is_absent(policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, head = _workspace(tmp_path)
    _fake_muse(tmp_path, monkeypatch, "raise SystemExit('must not run')")
    outcome = _review(policy, tmp_path, workspace, head, prompt="")
    assert outcome.missing is not None and outcome.missing.kind == absence.INVALID


def test_missing_cli_is_an_error_absence(policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, head = _workspace(tmp_path)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    outcome = _review(policy, tmp_path, workspace, head)
    assert outcome.missing is not None and outcome.missing.kind == absence.ERROR


def test_prose_output_is_invalid(policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, head = _workspace(tmp_path)
    _fake_muse(tmp_path, monkeypatch, "print('Looks good to me!')")
    outcome = _review(policy, tmp_path, workspace, head)
    assert outcome.missing is not None and outcome.missing.kind == absence.INVALID


def test_diagnostic_is_sanitized(policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, head = _workspace(tmp_path)
    _fake_muse(tmp_path, monkeypatch, "sys.stderr.write('token sk-ant-oat01-' + 'A' * 40 + '\\n')\nsys.exit(3)")
    outcome = _review(policy, tmp_path, workspace, head)
    assert outcome.missing is not None and outcome.missing.detail == "exit code 3"
    assert "AAAAAAAAAA" not in outcome.diagnostic and "[redacted]" in outcome.diagnostic


def test_diagnostic_is_an_excerpt_not_the_raw_output(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    body = "print('model said private things')\nsys.stderr.write('trace 1\\ntrace 2\\nfatal: quota\\n')\nsys.exit(1)"
    _fake_muse(tmp_path, monkeypatch, body)
    monkeypatch.setenv("META_API_KEY", "should-not-appear")
    outcome = _review(policy, tmp_path, workspace, head)
    assert outcome.diagnostic == "fatal: quota"


def test_execute_kills_on_timeout(tmp_path: Path) -> None:
    invocation = Invocation((sys.executable, "-c", "import time; time.sleep(30)"), tmp_path, None)
    result = runner.execute(invocation, 1)
    assert result.timed_out is True
