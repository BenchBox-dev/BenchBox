from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from _project.scripts.oracle_reviewers import absence, cli, runner
from _project.scripts.oracle_reviewers.brief import (
    FILE_LIST_DIFF_LINE,
    FULL_DIFF_LINE,
    READ_RULE_PLACEHOLDER,
    READ_RULES,
)
from _project.scripts.oracle_reviewers.commands import Invocation
from _project.scripts.oracle_reviewers.policy import Policy

pytestmark = [pytest.mark.unit, pytest.mark.fast]

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
VERDICT = {
    "status": "complete",
    "incomplete_reason": "",
    "decision": "SHIP",
    "summary": "fine",
    "files_examined": ["a.txt"],
    "defects": [],
    "prior_defects": [],
}


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


def _fake_muse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, name: str = "muse") -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / name
    script.write_text(f"#!{sys.executable}\nimport sys\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")


def _review(
    policy: Policy,
    tmp_path: Path,
    workspace: Path,
    head: str,
    prompt: str = "brief",
    *,
    reviewer: str = "muse",
    brief_mode: str = "inline",
    required: tuple[str, ...] = (),
):
    return runner.review(
        policy.reviewers[reviewer],
        workspace=workspace,
        head_sha=head,
        prompt=prompt,
        scratch=tmp_path / "s",
        now=NOW,
        brief_mode=brief_mode,
        required=required,
    )


def _muse_says(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **over: object) -> None:
    _fake_muse(tmp_path, monkeypatch, f"print({json.dumps(json.dumps({**VERDICT, **over}))})")


def _claude_says(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, turns: int, **over: object) -> None:
    envelope = {"type": "result", "is_error": False, "num_turns": turns, "structured_output": {**VERDICT, **over}}
    _fake_muse(tmp_path, monkeypatch, f"print({json.dumps(json.dumps(envelope))})", name="claude")


def _codex_says(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[dict], **over: object) -> None:
    body = (
        f"open(sys.argv[sys.argv.index('-o') + 1], 'w').write({json.dumps(json.dumps({**VERDICT, **over}))})\n"
        f"for event in {events!r}:\n    print(__import__('json').dumps(event))"
    )
    _fake_muse(tmp_path, monkeypatch, body, name="codex")


def _command(text: str, output: str = "", exit_code: int = 0) -> dict:
    item = {"type": "command_execution", "command": text, "aggregated_output": output, "exit_code": exit_code}
    return {"type": "item.completed", "item": {**item, "status": "completed"}}


DEFECT = {"severity": "High", "file": "a.txt", "line": 1, "end_line": None, "title": "Wrong", "detail": "d"}


def test_clean_verdict_is_recorded(policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, head = _workspace(tmp_path)
    _fake_muse(tmp_path, monkeypatch, f"print({json.dumps(json.dumps(VERDICT))})")
    outcome = _review(policy, tmp_path, workspace, head)
    assert outcome.missing is None
    assert outcome.verdict == {**VERDICT, "defect_count": 0}


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


def _status(workspace: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(workspace), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_staged_diff_is_readable_in_the_workspace_and_leaves_it_clean(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)
    source = tmp_path / "diff.patch"
    source.write_text("diff --git a/a.txt b/a.txt\n+changed\n", encoding="utf-8")
    staged = runner.stage_pull_request_diff(source, workspace)
    assert staged == workspace / runner.STAGED_DIFF_NAME
    assert staged.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert staged.resolve().is_relative_to(workspace.resolve())
    assert _status(workspace) == ""


@pytest.mark.parametrize("content", [None, "", "  \n"])
def test_nothing_is_staged_without_a_diff(tmp_path: Path, content: str | None) -> None:
    workspace, _ = _workspace(tmp_path)
    source = tmp_path / "diff.patch"
    if content is not None:
        source.write_text(content, encoding="utf-8")
    assert runner.stage_pull_request_diff(source, workspace) is None
    assert not (workspace / runner.STAGED_DIFF_NAME).exists()


def test_a_pull_request_file_with_the_staging_name_is_never_overwritten(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)
    (workspace / runner.STAGED_DIFF_NAME).write_text("from the pull request\n", encoding="utf-8")
    source = tmp_path / "diff.patch"
    source.write_text("+x\n", encoding="utf-8")
    assert runner.stage_pull_request_diff(source, workspace) is None
    assert (workspace / runner.STAGED_DIFF_NAME).read_text(encoding="utf-8") == "from the pull request\n"


def test_a_symlink_with_the_staging_name_is_never_followed(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)
    outside = tmp_path / "outside.txt"
    (workspace / runner.STAGED_DIFF_NAME).symlink_to(outside)
    source = tmp_path / "diff.patch"
    source.write_text("+x\n", encoding="utf-8")
    assert runner.stage_pull_request_diff(source, workspace) is None
    assert not outside.exists()


def test_a_directory_that_is_not_a_repository_stages_nothing(tmp_path: Path) -> None:
    source = tmp_path / "diff.patch"
    source.write_text("+x\n", encoding="utf-8")
    plain = tmp_path / "plain"
    plain.mkdir()
    assert runner.stage_pull_request_diff(source, plain) is None


def _plan_dir(policy: Policy, tmp_path: Path, head: str, scope: str, brief: str, diff: str | None) -> Path:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    plan = {
        "pr": 7,
        "head_sha": head,
        "brief_mode": "inline",
        "scope": scope,
        "chain": [policy.reviewers["muse"].to_json()],
    }
    (plan_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (plan_dir / "brief.md").write_text(brief, encoding="utf-8")
    if diff is not None:
        (plan_dir / "diff.patch").write_text(diff, encoding="utf-8")
    return plan_dir / "plan.json"


def _run_review(
    plan_path: Path,
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    monkeypatch.setenv("GITHUB_RUN_ID", "99")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))
    cli.main(
        [
            "review",
            "--plan",
            str(plan_path),
            "--slot",
            "1",
            "--reviewer",
            "muse",
            "--harness",
            "muse",
            "--workspace",
            str(workspace),
            "--scratch",
            str(tmp_path / "scratch"),
            "--out-dir",
            str(tmp_path / "attempt"),
        ]
    )
    return json.loads((tmp_path / "attempt" / "attempt-1.json").read_text(encoding="utf-8"))


def _capture_prompt_body(tmp_path: Path) -> str:
    return f"open('{tmp_path}/prompt.txt', 'w').write(sys.argv[-1])\nprint({json.dumps(json.dumps(VERDICT))})"


def test_a_scoped_review_gives_the_reviewer_a_readable_full_diff(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    brief = f"Intro.\n{FULL_DIFF_LINE}Files changed.\n"
    plan_path = _plan_dir(policy, tmp_path, head, "changed", brief, "diff --git a/a.txt b/a.txt\n+whole\n")
    _fake_muse(tmp_path, monkeypatch, _capture_prompt_body(tmp_path))
    artifact = _run_review(plan_path, workspace, tmp_path, monkeypatch)
    prompt = (tmp_path / "prompt.txt").read_text(encoding="utf-8")
    staged = workspace / runner.STAGED_DIFF_NAME
    assert f"The whole pull request diff is at {staged};" in prompt
    assert "+whole" in staged.read_text(encoding="utf-8")
    assert artifact["outcome"] == "verdict" and artifact["absence"] is None
    assert artifact["verdict"]["summary"] == VERDICT["summary"]


def test_a_full_review_stages_no_diff(policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, head = _workspace(tmp_path)
    plan_path = _plan_dir(policy, tmp_path, head, "full", "Intro.\n", "diff --git a/a.txt b/a.txt\n+whole\n")
    _fake_muse(tmp_path, monkeypatch, _capture_prompt_body(tmp_path))
    _run_review(plan_path, workspace, tmp_path, monkeypatch)
    assert not (workspace / runner.STAGED_DIFF_NAME).exists()
    assert (tmp_path / "prompt.txt").read_text(encoding="utf-8") == "Intro.\n"


def test_a_scoped_review_without_a_diff_drops_the_diff_line(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    plan_path = _plan_dir(policy, tmp_path, head, "changed", f"Intro.\n{FULL_DIFF_LINE}Files.\n", None)
    _fake_muse(tmp_path, monkeypatch, _capture_prompt_body(tmp_path))
    _run_review(plan_path, workspace, tmp_path, monkeypatch)
    assert (tmp_path / "prompt.txt").read_text(encoding="utf-8") == "Intro.\nFiles.\n"


def test_a_reviewer_that_reports_incomplete_is_absent_with_its_reason(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    _muse_says(tmp_path, monkeypatch, status="incomplete", decision="NONE", incomplete_reason="could not read a.txt")
    outcome = _review(policy, tmp_path, workspace, head)
    assert outcome.verdict is None
    assert outcome.missing == absence.Absence(absence.INCOMPLETE, "could not read a.txt")


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ({"file": "invented.py"}, "a defect cites invented.py, which is not a file in the head commit"),
        ({"line": 2}, "a defect cites a.txt:2, past its last line (1)"),
        ({"end_line": 9}, "a defect cites a.txt:9, past its last line (1)"),
        ({"file": "../outside.txt"}, "file must be a repository-relative path"),
    ],
)
def test_a_defect_citing_a_line_the_head_lacks_makes_the_review_incomplete(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: dict, message: str
) -> None:
    workspace, head = _workspace(tmp_path)
    (tmp_path / "outside.txt").write_text("x\n" * 50, encoding="utf-8")
    _muse_says(tmp_path, monkeypatch, decision="SHIP_WITH_FIXES", defects=[{**DEFECT, **defect}])
    outcome = _review(policy, tmp_path, workspace, head)
    assert outcome.verdict is None and outcome.missing is not None
    assert outcome.missing.kind in (absence.INCOMPLETE, absence.INVALID)
    assert outcome.missing.detail == message


def test_a_defect_citing_a_real_line_is_recorded(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    _muse_says(tmp_path, monkeypatch, decision="SHIP_WITH_FIXES", defects=[DEFECT])
    outcome = _review(policy, tmp_path, workspace, head)
    assert outcome.missing is None and outcome.verdict is not None
    assert [item["file"] for item in outcome.verdict["defects"]] == ["a.txt"]


def test_a_file_list_ship_must_examine_every_required_file(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    (workspace / "b.txt").write_text("b\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(workspace), "add", "b.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "b"],
        check=True,
    )
    head = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    _muse_says(tmp_path, monkeypatch, files_examined=["a.txt"])
    short = _review(policy, tmp_path, workspace, head, brief_mode="file-list", required=("a.txt", "b.txt"))
    assert short.missing == absence.Absence(
        absence.INCOMPLETE, "the reviewer found no defects but did not examine b.txt"
    )
    inline = _review(policy, tmp_path, workspace, head, brief_mode="inline", required=("a.txt", "b.txt"))
    assert inline.missing is None


def test_absolute_examined_paths_inside_the_workspace_count(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    _muse_says(tmp_path, monkeypatch, files_examined=[str(workspace.resolve() / "a.txt")])
    outcome = _review(policy, tmp_path, workspace, head, brief_mode="file-list", required=("a.txt",))
    assert outcome.missing is None


@pytest.mark.parametrize(
    ("turns", "brief_mode", "accepted"), [(1, "file-list", False), (3, "file-list", True), (1, "inline", True)]
)
def test_claude_must_take_a_reading_turn_on_a_file_list_brief(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, turns: int, brief_mode: str, accepted: bool
) -> None:
    workspace, head = _workspace(tmp_path)
    _claude_says(tmp_path, monkeypatch, turns)
    outcome = _review(policy, tmp_path, workspace, head, reviewer="sonnet", brief_mode=brief_mode, required=("a.txt",))
    if accepted:
        assert outcome.missing is None and outcome.verdict is not None
    else:
        assert outcome.verdict is None
        assert outcome.missing == absence.Absence(
            absence.INCOMPLETE, "the reviewer read no files: it answered a file-list brief in a single turn"
        )


def test_a_codex_ship_without_any_read_command_is_a_hollow_review(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    hollow = {"summary": "I could not review the files because I may not run commands.", "files_examined": ["a.txt"]}
    _codex_says(tmp_path, monkeypatch, [{"type": "turn.completed"}], **hollow)
    outcome = _review(policy, tmp_path, workspace, head, reviewer="sol", brief_mode="file-list", required=("a.txt",))
    assert outcome.verdict is None
    assert outcome.missing is not None and outcome.missing.kind == absence.INCOMPLETE
    assert "command trace shows no successful read" in outcome.missing.detail


@pytest.mark.parametrize(
    ("event", "accepted"),
    [
        (_command("/bin/zsh -lc 'cat -n a.txt'", "1 a"), True),
        (_command("/bin/zsh -lc 'rg -n x .'", "./a.txt:1:a"), True),
        (_command("/bin/zsh -lc 'cat -n a.txt'", "", exit_code=1), False),
        (_command("/bin/zsh -lc 'ls'", "README"), False),
    ],
)
def test_a_codex_file_list_review_needs_a_successful_read_of_a_required_file(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: dict, accepted: bool
) -> None:
    workspace, head = _workspace(tmp_path)
    _codex_says(tmp_path, monkeypatch, [event])
    outcome = _review(policy, tmp_path, workspace, head, reviewer="sol", brief_mode="file-list", required=("a.txt",))
    assert (outcome.missing is None) is accepted


def test_codex_quota_reported_in_the_event_stream_is_quota(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    error = {"type": "turn.failed", "error": {"message": "You've hit your usage limit. Resets in 2h"}}
    body = f"print(__import__('json').dumps({error!r}))\nraise SystemExit(1)"
    _fake_muse(tmp_path, monkeypatch, body, name="codex")
    outcome = _review(policy, tmp_path, workspace, head, reviewer="sol")
    assert outcome.missing is not None and outcome.missing.kind == absence.QUOTA
    assert outcome.missing.reset_at == NOW + timedelta(hours=2)


def test_the_review_fills_the_read_rule_for_the_reviewers_harness(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    plan_path = _plan_dir(policy, tmp_path, head, "full", f"Rules: {READ_RULE_PLACEHOLDER}\n", None)
    _fake_muse(tmp_path, monkeypatch, _capture_prompt_body(tmp_path))
    _run_review(plan_path, workspace, tmp_path, monkeypatch)
    assert (tmp_path / "prompt.txt").read_text(encoding="utf-8") == f"Rules: {READ_RULES['muse']}\n"


def test_a_file_list_review_stages_the_whole_diff(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, head = _workspace(tmp_path)
    plan_path = _plan_dir(
        policy, tmp_path, head, "full", f"Intro. {FILE_LIST_DIFF_LINE}Read.\n", "diff --git a/a.txt b/a.txt\n+whole\n"
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_path.write_text(json.dumps({**plan, "brief_mode": "file-list", "evidence_files": ["a.txt"]}), "utf-8")
    _fake_muse(tmp_path, monkeypatch, _capture_prompt_body(tmp_path))
    artifact = _run_review(plan_path, workspace, tmp_path, monkeypatch)
    staged = workspace / runner.STAGED_DIFF_NAME
    assert (tmp_path / "prompt.txt").read_text(encoding="utf-8") == (
        f"Intro. The whole pull request diff is at {staged}; read it with the changed files. Read.\n"
    )
    assert "+whole" in staged.read_text(encoding="utf-8")
    assert artifact["outcome"] == "verdict"
