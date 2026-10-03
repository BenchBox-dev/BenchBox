from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import check_comment_policy
import pytest
import run_comment_policy as policy_runner
import yaml
from check_comment_policy import allowed, check_ratchet, introduced, load_policy, main, scan_sources, source_paths
from comment_syntax import Finding, javascript_requests, python_findings, scan, sql_comments
from run_comment_policy import TRUSTED_FILES, parser_environment, resolve_base

pytestmark = [pytest.mark.unit, pytest.mark.medium]

ROOT = Path(__file__).resolve().parents[3]
EMPTY_POLICY = {"version": 1, "external": [], "completed": [], "exceptions": []}


def policy(**changes: object) -> dict:
    return {**deepcopy(EMPTY_POLICY), **changes}


@pytest.mark.parametrize(
    "source,kind,symbol",
    [
        ('"module prose"\n', "docstring", ""),
        ('class C:\n    "class prose"\n', "docstring", "C"),
        ('async def f():\n    "function prose"\n', "docstring", "f"),
        ('def f():\n    x = 1\n    "inert prose"\n', "docstring", "f"),
        ('def f():\n    "a" "b"\n', "docstring", "f"),
        ('f.__doc__ = "prose"\n', "runtime-docstring", ""),
        ('__doc__ = "prose"\n', "runtime-docstring", ""),
        ('f.__doc__: str = "prose"\n', "runtime-docstring", ""),
        ('setattr(f, "__doc__", "prose")\n', "runtime-docstring", ""),
        ('f.__dict__["__doc__"] = "prose"\n', "runtime-docstring", ""),
        ("def f():\n    return 1 # explanation\n", "comment", "f"),
    ],
)
def test_python_prohibited_forms(source: str, kind: str, symbol: str) -> None:
    findings = python_findings("a.py", source)
    assert [(f.kind, f.symbol) for f in findings] == [(kind, symbol)]


def test_python_strings_help_and_reads_are_data() -> None:
    assert not python_findings("a.py", 'help = "# useful help"\nx = f.__doc__\n')


def test_runtime_assignment_payload_is_part_of_identity() -> None:
    before = python_findings("a.py", 'f.__doc__ = "before"')
    after = python_findings("a.py", 'f.__doc__ = "after"')
    assert introduced(after, before, []) == after


@pytest.mark.parametrize("source", ["def broken(", '"unterminated', "if True:\n"])
def test_python_syntax_failure_is_visible(source: str) -> None:
    assert scan("a.py", source, "python")[0].kind == "coverage-error"


@pytest.mark.parametrize(
    "source,expected",
    [
        ("SELECT '-- payload', \"-- name\", `#name`, [--name], $$--data$$; -- comment", ["-- comment"]),
        ("SELECT $tag$/*payload*/$tag$; /* outer /* inner */ end */", ["/* outer /* inner */ end */"]),
        ("SELECT 1 # comment", ["# comment"]),
        ("SELECT 'it''s -- data';", []),
    ],
)
def test_sql_literals_and_nested_comments(source: str, expected: list[str]) -> None:
    assert [text for _, text in sql_comments(source, "tsql")] == expected


@pytest.mark.parametrize("source", ["SELECT 'unterminated", "SELECT $$unterminated", "/* unterminated"])
def test_sql_unterminated_constructs_fail(source: str) -> None:
    assert scan("a.sql", source, "sql")[0].kind == "coverage-error"


@pytest.mark.parametrize(
    "lang,source,text",
    [
        ("bash", "cat <<'EOF'\n# payload\nEOF\necho x#data\n# explanation\n", "# explanation"),
        ("yaml", "value: |\n  # payload\n# explanation\n", "# explanation"),
        ("toml", 'value = "# payload"\n# explanation\n', "# explanation"),
        ("css", 'a { content: "/*payload*/"; } /* explanation */', "/* explanation */"),
        ("html", '<p title="<!--payload-->">value</p><!-- explanation -->', "<!-- explanation -->"),
        ("make", "name := value\n# explanation\n", "# explanation"),
        ("docker", "FROM python:3.11\n# explanation\n", "# explanation"),
    ],
)
def test_lexers_preserve_data_and_find_comments(lang: str, source: str, text: str) -> None:
    findings = scan("a", source, lang)
    assert [(f.kind, f.text) for f in findings] == [("comment", text)]


def test_native_request_and_payload_response_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    source = '<script>const x = "// data"; // explanation\n</script>'
    requests = javascript_requests("a.html", source, "html")
    assert len(requests) == 1

    def native_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        assert command[0] == "node"
        assert json.loads(str(kwargs["input"])) == requests
        rows = [
            {"line": 1, "kind": "comment", "text": "// explanation", "symbol": "f"},
            {"line": 1, "kind": "payload", "text": "# executable prose", "symbol": "f", "language": "python"},
        ]
        return subprocess.CompletedProcess(command, 0, json.dumps(dict.fromkeys(requests, rows)))

    monkeypatch.setattr("check_comment_policy.subprocess.run", native_run)
    findings = scan_sources(ROOT, {"a.html": source.encode()}, policy())
    assert [(f.kind, f.text, f.symbol) for f in findings] == [
        ("comment", "// explanation", "script:0:f"),
        ("comment", "# executable prose", "script:0:f:payload:"),
    ]


def test_yaml_run_and_notebook_cells() -> None:
    findings = scan("ci.yml", "run: |\n  echo ok\n  # explanation\n", "yaml")
    assert [(f.kind, f.text) for f in findings] == [("comment", "# explanation")]
    source = json.dumps({"cells": [{"id": "stable", "cell_type": "code", "source": ["# explanation\n"]}]})
    assert scan("a.ipynb", source, "notebook")[0].symbol == "cell:stable:"


def test_executable_examples_and_unknown_languages() -> None:
    assert scan("docs/a.md", "```python\n# explanation\n```\n", "examples")[0].line == 2
    assert scan("docs/a.md", "```unknown-runtime\ncode\n```\n", "examples")[0].kind == "coverage-error"
    assert not scan("docs/a.md", "```text\n# prose\n```\n", "examples")


def exception(text: str = "# noqa: F401", **changes: str) -> dict:
    return {
        "path": "a.py",
        "symbol": "",
        "text": text,
        "kind": "directive",
        "consumer": "pyproject.toml",
        "necessity": "The import is an intentionally exported compatibility name.",
        "alternative": "Replacing the public export would break callers.",
        "owner": "maintainers",
        "removal": "Remove when the export is retired.",
        "expires": (date.today() + timedelta(days=90)).isoformat(),
        **changes,
    }


@pytest.mark.parametrize("text", ["# noqa: F401 - explanation", "# noqa", "# type: ignore", "# why this is needed"])
def test_directive_grammar_rejects_narrative_and_blanket_suppressions(text: str) -> None:
    with pytest.raises(ValueError):
        load_policy(json.dumps(policy(exceptions=[exception(text)])).encode())


def test_valid_directive_needs_exact_registry_identity() -> None:
    registered = load_policy(json.dumps(policy(exceptions=[exception()])).encode())
    finding = Finding("a.py", 20, "comment", "# noqa: F401")
    assert allowed(finding, registered, "")
    assert not allowed(finding, policy(), "")
    assert not allowed(Finding("other.py", 20, "comment", finding.text), registered, "")
    assert not allowed(Finding("a.py", 20, "comment", finding.text, "different"), registered, "")


def test_expired_or_explanatory_exception_fails() -> None:
    with pytest.raises(ValueError):
        load_policy(json.dumps(policy(exceptions=[exception(expires="2000-01-01")])).encode())
    with pytest.raises(ValueError):
        load_policy(json.dumps(policy(exceptions=[exception(kind="explanation")])).encode())


@pytest.mark.parametrize(
    "line,text,accepted",
    [
        (1, "#!/usr/bin/env python3", True),
        (2, "#!/usr/bin/env python3", False),
        (1, "#!/usr/bin/env python3 # explanation", False),
        (1, "# coding: utf-8", False),
        (1, "# coding: latin-1", True),
        (3, "# coding: latin-1", False),
    ],
)
def test_structural_directive_positions(line: int, text: str, accepted: bool) -> None:
    assert allowed(Finding("a.py", line, "comment", text), policy(), "\n") is accepted


def test_delta_compares_exact_multisets_and_completed_scopes() -> None:
    old = Finding("a.py", 1, "comment", "# old", "f")
    moved = Finding("a.py", 100, "comment", "# old", "f")
    replacement = Finding("a.py", 1, "comment", "# new", "f")
    assert not introduced([moved], [old], [])
    assert introduced([old, old], [old], []) == [old]
    assert introduced([replacement], [old], []) == [replacement]
    assert introduced([moved], [old], ["a.py"]) == [moved]
    assert introduced([Finding("a.py", 1, "comment", "# old", "g")], [old], [])


def test_policy_cannot_weaken_completed_or_external_scopes() -> None:
    with pytest.raises(ValueError):
        check_ratchet(policy(), policy(completed=["a.py"]))
    entry = {"path": "benchbox/", "owner": "fake", "provenance": "a.md"}
    with pytest.raises(ValueError):
        check_ratchet(policy(external=[entry]), policy())


def git_repo(tmp_path: Path, source: str) -> str:
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality/comment-policy.json").write_text(json.dumps(policy()), encoding="utf-8")
    (tmp_path / "a.py").write_text(source, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py", "quality/comment-policy.json"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    return subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()


def test_transition_worktree_and_staged_content(tmp_path: Path) -> None:
    base = git_repo(tmp_path, "# old\nx = 1\n")
    args = ["--root", str(tmp_path), "--mode", "transition", "--base", base]
    assert main(args) == 0
    (tmp_path / "a.py").write_text("# new\nx = 1\n", encoding="utf-8")
    assert main(args) == 1
    assert main([*args, "--staged"]) == 0
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py"], check=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert main([*args, "--staged"]) == 1


def test_enforcement_value_is_validated_and_defaults_to_blocking() -> None:
    assert load_policy(json.dumps(policy()).encode()).get("enforcement", "blocking") == "blocking"
    assert load_policy(json.dumps(policy(enforcement="advisory")).encode())["enforcement"] == "advisory"
    with pytest.raises(ValueError, match="advisory or blocking"):
        load_policy(json.dumps(policy(enforcement="warn")).encode())
    assert load_policy((ROOT / "quality/comment-policy.json").read_bytes())["enforcement"] in {"advisory", "blocking"}
    for malformed in ([], {}, 1, None):
        with pytest.raises(ValueError, match="advisory or blocking"):
            load_policy(json.dumps(policy(enforcement=malformed)).encode())


def test_enforcement_can_be_tightened_but_never_relaxed() -> None:
    check_ratchet(policy(enforcement="blocking"), policy(enforcement="advisory"))
    check_ratchet(policy(enforcement="advisory"), policy(enforcement="advisory"))
    check_ratchet(policy(enforcement="blocking"), policy())
    with pytest.raises(ValueError, match="relaxed"):
        check_ratchet(policy(enforcement="advisory"), policy(enforcement="blocking"))
    with pytest.raises(ValueError, match="relaxed"):
        check_ratchet(policy(enforcement="advisory"), policy())


def test_advisory_enforcement_reports_findings_without_failing_the_comparison(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = git_repo(tmp_path, "x = 1\n")
    args = ["--root", str(tmp_path), "--mode", "transition", "--base", base]
    (tmp_path / "a.py").write_text("# new\nx = 1\n", encoding="utf-8")
    assert main(args) == 1
    (tmp_path / "quality/comment-policy.json").write_text(json.dumps(policy(enforcement="advisory")), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "quality/comment-policy.json"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=F",
            "-c",
            "user.email=f@e.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "advisory",
        ],
        check=True,
    )
    advisory_base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    capsys.readouterr()
    advisory = ["--root", str(tmp_path), "--mode", "transition", "--base", advisory_base]
    assert main(advisory) == 0
    out = capsys.readouterr().out
    assert "a.py:1: CP comment" in out
    assert "enforcement is advisory" in out
    assert main(["--root", str(tmp_path), "--mode", "strict"]) == 1
    assert main(["--root", str(tmp_path), "--mode", "transition", "--base", "f" * 40]) == 2


def test_advisory_annotations_escape_path_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *args, **_: printed.append(" ".join(map(str, args))))
    finding = Finding("dir,x::y%z.py", 7, "comment", "# 100%\r::set-output name=a::b")
    assert check_comment_policy.exit_status("transition", policy(enforcement="advisory"), [finding]) == 0
    annotation = next(line for line in printed if line.startswith("::warning"))
    assert annotation.startswith("::warning file=dir%2Cx%3A%3Ay%25z.py,line=7::")
    assert "\r" not in annotation and "set-output" not in annotation


def commit_policy(tmp_path: Path, enforcement: str) -> str:
    (tmp_path / "quality/comment-policy.json").write_text(json.dumps(policy(enforcement=enforcement)), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A", "quality/comment-policy.json"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=F",
            "-c",
            "user.email=f@e.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            enforcement,
            "--allow-empty",
        ],
        check=True,
    )
    return subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()


def test_advisory_reports_unanalyzable_input_but_still_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git_repo(tmp_path, "x = 1\n")
    base = commit_policy(tmp_path, "advisory")
    (tmp_path / "a.py").write_text("def broken(\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "--mode", "transition", "--base", base]) == 0
    out = capsys.readouterr().out
    assert "CP coverage-error" in out
    assert "(1 are inputs the checker could not analyze)" in out


def test_flipping_to_blocking_does_not_block_itself_but_the_next_change_is(tmp_path: Path) -> None:
    git_repo(tmp_path, "x = 1\n")
    advisory_base = commit_policy(tmp_path, "advisory")
    (tmp_path / "quality/comment-policy.json").write_text(json.dumps(policy(enforcement="blocking")), encoding="utf-8")
    (tmp_path / "a.py").write_text("# new\nx = 1\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "--mode", "transition", "--base", advisory_base]) == 0
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py", "quality/comment-policy.json"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=F",
            "-c",
            "user.email=f@e.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "flip",
        ],
        check=True,
    )
    blocking_base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    (tmp_path / "a.py").write_text("# new\n# another\nx = 1\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "--mode", "transition", "--base", blocking_base]) == 1
    assert main(["--root", str(tmp_path), "--mode", "report"]) == 0


def test_hostile_paths_cannot_start_a_workflow_command_in_the_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    git_repo(tmp_path, "x = 1\n")
    base = commit_policy(tmp_path, "advisory")
    hostile = "::add-mask::secret.py"
    (tmp_path / hostile).write_text("# new\n", encoding="utf-8")
    (tmp_path / "##[stop-commands]hidden.py").write_text("# ##[add-mask]comment-policy\n", encoding="utf-8")
    newline_name = "one.py\n::stop-commands::token\ntwo.py"
    try:
        (tmp_path / newline_name).write_text("# new\n", encoding="utf-8")
    except OSError:
        newline_name = ""
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "--mode", "transition", "--base", base]) == 0
    output = capsys.readouterr().out
    lines = output.splitlines()
    assert "##[" not in output
    assert not [line for line in lines if line.lstrip().startswith("::") and not line.startswith("::warning ")]
    assert not any(line.lstrip().startswith(("::add-mask", "::stop-commands")) for line in lines)
    if newline_name:
        assert not any(line.strip() == "::stop-commands::token" for line in lines)


def test_legacy_command_markers_are_neutralized_in_text_and_annotations() -> None:
    for value in ("# ##[add-mask]comment-policy", "scripts/##[stop-commands]hidden.py"):
        assert "##[" not in check_comment_policy.plain_text(value)
        assert "##[" not in policy_runner.plain_text(value)
        assert "##[" not in check_comment_policy.annotation_text(value)
        assert "##[" not in check_comment_policy.annotation_text(value, property_value=True)
    assert policy_runner.plain_text("::stop-commands::x").startswith("\\::")
    assert policy_runner.plain_text("line one\n::add-mask::x") == "line one\\x0a::add-mask::x"


@pytest.mark.parametrize("fails", [False, True])
def test_native_test_output_runs_between_stop_and_resume_tokens(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fails: bool, tmp_path: Path
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    seen: list[str] = []

    def native_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        before = capsys.readouterr().out.splitlines()
        assert len(before) == 1 and before[0].startswith("::stop-commands::")
        seen.append(before[0])
        assert kwargs["stderr"] is subprocess.STDOUT
        print("child output")
        if fails:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(policy_runner.subprocess, "run", native_run)
    if fails:
        with pytest.raises(subprocess.CalledProcessError):
            policy_runner.run_native_tests(tmp_path, tmp_path, {})
    else:
        policy_runner.run_native_tests(tmp_path, tmp_path, {})
    after = capsys.readouterr().out.splitlines()
    token = seen[0].removeprefix("::stop-commands::")
    assert len(token) == 32
    assert after == ["child output", f"::{token}::"]


def test_comment_policy_job_sets_up_every_tool_before_the_candidate_checkout() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["comment-policy"]["steps"]
    uses = [str(step.get("uses", "")).split("@")[0] for step in steps]
    checkout = uses.index("actions/checkout")
    for tool in ("actions/setup-python", "astral-sh/setup-uv", "actions/setup-node"):
        assert uses.index(tool) < checkout, f"{tool} must run before the candidate checkout"
    assert checkout == max(index for index, name in enumerate(uses) if name) and steps[checkout + 1]["name"].startswith(
        "Enforce"
    )


def test_comment_policy_job_does_not_let_setup_uv_scan_the_candidate_checkout() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["comment-policy"]["steps"]
    uv = next(step for step in steps if str(step.get("uses", "")).startswith("astral-sh/setup-uv@"))
    assert uv["with"] == {
        "enable-cache": False,
        "working-directory": "${{ runner.temp }}",
        "ignore-empty-workdir": True,
    }


def test_native_test_output_is_not_wrapped_outside_github_actions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(
        policy_runner.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0)
    )
    policy_runner.run_native_tests(tmp_path, tmp_path, {})
    assert capsys.readouterr().out == ""


def test_candidate_cannot_relax_blocking_enforcement_in_a_comparison(tmp_path: Path) -> None:
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality/comment-policy.json").write_text(json.dumps(policy(enforcement="blocking")), encoding="utf-8")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py", "quality/comment-policy.json"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=F",
            "-c",
            "user.email=f@e.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "blocking",
        ],
        check=True,
    )
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    (tmp_path / "quality/comment-policy.json").write_text(json.dumps(policy(enforcement="advisory")), encoding="utf-8")
    (tmp_path / "a.py").write_text("# new\nx = 1\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "--mode", "transition", "--base", base]) == 2


def test_new_exception_cannot_self_authorize_source(tmp_path: Path) -> None:
    base = git_repo(tmp_path, "x = 1\n")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "quality/comment-policy.json").write_text(
        json.dumps(policy(exceptions=[exception()])), encoding="utf-8"
    )
    (tmp_path / "a.py").write_text("x = 1 # noqa: F401\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "--mode", "transition", "--base", base]) == 1


def test_missing_base_and_unpinned_bootstrap_fail(tmp_path: Path) -> None:
    base = git_repo(tmp_path, "x = 1\n")
    assert main(["--root", str(tmp_path), "--mode", "transition"]) == 2
    assert main(["--root", str(tmp_path), "--mode", "transition", "--base", "f" * 40]) == 2
    assert main(["--root", str(tmp_path), "--mode", "transition", "--base", base, "--bootstrap"]) == 2


def test_bootstrap_base_is_refused_when_a_policy_registry_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin = plain_repo(tmp_path, "x = 1\n")
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality/comment-policy.json").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "quality/comment-policy.json"], check=True)
    with_registry = commit_change(tmp_path, "x = 2\n")
    monkeypatch.setattr("check_comment_policy.BOOTSTRAP_BASE", pin)
    monkeypatch.setattr("run_comment_policy.BOOTSTRAP_BASE", pin)
    assert not check_comment_policy.bootstrap_base_allowed(tmp_path, with_registry)
    assert not policy_runner.bootstrap_base_allowed(tmp_path, with_registry)


def git_run(root: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def merge_commit_repo(tmp_path: Path) -> tuple[str, str, str]:
    event_base = plain_repo(tmp_path, "x = 1\n")
    git_run(tmp_path, "checkout", "-q", "-b", "pr")
    (tmp_path / "pr.py").write_text("y = 1\n", encoding="utf-8")
    git_run(tmp_path, "add", "pr.py")
    git_run(tmp_path, "commit", "-qm", "pr")
    pr_head = git_run(tmp_path, "rev-parse", "HEAD")
    git_run(tmp_path, "checkout", "-q", "-B", "target", event_base)
    (tmp_path / "target.py").write_text("z = 1\n", encoding="utf-8")
    git_run(tmp_path, "add", "target.py")
    git_run(tmp_path, "commit", "-qm", "target moved on")
    target_tip = git_run(tmp_path, "rev-parse", "HEAD")
    git_run(tmp_path, "checkout", "-q", "--detach", target_tip)
    git_run(tmp_path, "merge", "--no-ff", "-qm", "merge ref", pr_head)
    return event_base, target_tip, pr_head


def test_ci_comparison_base_is_the_merge_target_not_the_stale_event_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_base, target_tip, pr_head = merge_commit_repo(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")
    assert policy_runner.comparison_base(tmp_path, event_base) == event_base
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert policy_runner.comparison_base(tmp_path, event_base) == target_tip
    with pytest.raises(ValueError, match="not an ancestor"):
        policy_runner.comparison_base(tmp_path, pr_head)
    git_run(tmp_path, "checkout", "-q", "--detach", target_tip)
    assert policy_runner.comparison_base(tmp_path, event_base) == event_base


def test_local_runs_keep_the_requested_base_even_on_a_merge_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_base, _target_tip, _pr_head = merge_commit_repo(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert policy_runner.comparison_base(tmp_path, event_base) == event_base


def test_checker_command_compares_against_the_given_base(tmp_path: Path) -> None:
    command = policy_runner.checker_command(Path("python"), tmp_path, tmp_path, "c" * 40, bootstrap=True, staged=False)
    assert command[command.index("--base") + 1] == "c" * 40
    assert "--bootstrap" in command
    assert "--staged" not in command


def test_local_default_base_is_the_branch_point_when_develop_moved_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    branch_point = git_repo(tmp_path, "x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "branch", "-q", "develop-tip"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "-q", "develop-tip"], check=True)
    develop_tip = commit_change(tmp_path, "x = 2\n")
    subprocess.run(["git", "-C", str(tmp_path), "update-ref", "refs/remotes/origin/develop", develop_tip], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "-q", "-B", "feature", branch_point], check=True)
    feature_head = commit_change(tmp_path, "x = 3\n")
    assert resolve_base(tmp_path, None) == branch_point
    assert resolve_base(tmp_path, feature_head) == feature_head
    with pytest.raises(subprocess.CalledProcessError):
        resolve_base(tmp_path, develop_tip)


def commit_change(tmp_path: Path, source: str) -> str:
    (tmp_path / "a.py").write_text(source, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "next",
        ],
        check=True,
    )
    return subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()


def plain_repo(tmp_path: Path, source: str) -> str:
    (tmp_path / "a.py").write_text(source, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return commit_change(tmp_path, source)


def test_bootstrap_base_allows_only_descendants_of_the_initial_rollout_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin = plain_repo(tmp_path, "x = 1\n")
    descendant = commit_change(tmp_path, "x = 2\n")
    monkeypatch.setattr("check_comment_policy.BOOTSTRAP_BASE", pin)
    monkeypatch.setattr("run_comment_policy.BOOTSTRAP_BASE", pin)
    assert check_comment_policy.bootstrap_base_allowed(tmp_path, pin)
    assert check_comment_policy.bootstrap_base_allowed(tmp_path, descendant)
    assert policy_runner.bootstrap_base_allowed(tmp_path, descendant)
    assert not check_comment_policy.bootstrap_base_allowed(tmp_path, "f" * 40)
    assert not policy_runner.bootstrap_base_allowed(tmp_path, "f" * 40)
    monkeypatch.setattr("check_comment_policy.BOOTSTRAP_BASE", descendant)
    assert not check_comment_policy.bootstrap_base_allowed(tmp_path, pin)


def test_bootstrap_base_is_refused_once_the_trusted_launcher_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin = plain_repo(tmp_path, "x = 1\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/run_comment_policy.py").write_text("", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "scripts/run_comment_policy.py"], check=True)
    with_launcher = commit_change(tmp_path, "x = 2\n")
    monkeypatch.setattr("check_comment_policy.BOOTSTRAP_BASE", pin)
    monkeypatch.setattr("run_comment_policy.BOOTSTRAP_BASE", pin)
    assert check_comment_policy.bootstrap_base_allowed(tmp_path, pin)
    assert not check_comment_policy.bootstrap_base_allowed(tmp_path, with_launcher)
    assert not policy_runner.bootstrap_base_allowed(tmp_path, with_launcher)


@pytest.mark.parametrize(
    "event_name,event",
    [
        ("pull_request", {"pull_request": {"base": {"sha": "a" * 40}}}),
        ("merge_group", {"merge_group": {"base_sha": "a" * 40}}),
    ],
)
def test_ci_event_rejects_base_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event_name: str, event: dict
) -> None:
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    with pytest.raises(ValueError, match="platform event"):
        resolve_base(tmp_path, "b" * 40)


def test_ci_policy_is_always_required_and_has_local_equivalent() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["comment-policy"]
    assert "if" not in job
    step = next(step for step in job["steps"] if step.get("name") == "Enforce comment and docstring policy")
    assert 'git show "${BASE_REF}:scripts/run_comment_policy.py"' in step["run"]
    assert 'python -I "$RUNNER_TEMP/comment-policy-runner.py" --native-tests' in step["run"]
    assert ': "${BASE_REF:?' in step["run"]
    listing = step["run"].split('installed="$(git ls-tree -r --name-only "$BASE_REF" --', 1)[1].split(')"', 1)[0]
    assert set(listing.replace("\\", " ").split()) == {*TRUSTED_FILES, "quality/comment-policy.json"}
    assert step["run"].index('installed="$(') < step["run"].index("git cat-file -e")
    assert 'elif [ -z "$installed" ] && git merge-base --is-ancestor' in step["run"]
    assert "git merge-base --is-ancestor ed5c263c513ba65499f4918d3a7de607f280c65b" in step["run"]
    assert "pull_request.base.sha" in step["env"]["BASE_REF"]
    assert "merge_group.base_sha" in step["env"]["BASE_REF"]
    tooling = workflow["jobs"]["tooling"]
    assert "comment-policy" in tooling["needs"]
    assert any("--always comment-policy" in step.get("run", "") for step in tooling["steps"])
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert 'failed="$$failed comment-policy"' in makefile


@pytest.mark.parametrize(
    "source,expected",
    [
        ("SELECT ARRAY[1 /* explanation */];", ["/* explanation */"]),
        ("SELECT payload #>> '{a}' FROM t;", []),
        ("SELECT * FROM #temporary_table;", []),
    ],
)
def test_sql_array_and_operator_contexts(source: str, expected: list[str]) -> None:
    assert [text for _, text in sql_comments(source)] == expected


@pytest.mark.parametrize("source", ['sql = "VALUES (1) -- explanation"', 'sql = f"SELECT {column} -- explanation"'])
def test_sql_literals_and_fstrings_in_python(source: str) -> None:
    assert [f.text for f in python_findings("a.py", source)] == ["-- explanation"]


def test_changed_unsupported_source_cannot_cancel_coverage_failure() -> None:
    finding = Finding("a.tpl", 1, "coverage-error", "unsupported")
    assert introduced([finding], [finding], []) == [finding]


@pytest.mark.parametrize(
    "path",
    [".gitignore", ".gitattributes", ".dockerignore", ".importlinter", "skill-sync.conf", "scripts/a.zsh", "scripts/a"],
)
def test_extensionless_and_config_source_are_included(path: str) -> None:
    assert scan_sources(ROOT, {path: b"# explanation\n"}, policy())


def test_executable_python_heredoc() -> None:
    source = "python3 - <<'PY'\n# explanation\nPY\n"
    findings = scan("ci.sh", source, "bash")
    assert [(f.kind, f.text) for f in findings] == [("comment", "# explanation")]


def test_jsonc_and_json_script_are_data() -> None:
    assert not scan_sources(ROOT, {"a.jsonc": b'{"enabled":true}'}, policy())
    assert not scan_sources(ROOT, {"a.html": b'<script type="application/json">{"enabled":true}</script>'}, policy())


def test_removing_exception_revokes_permission(tmp_path: Path) -> None:
    base = git_repo(tmp_path, "x = 1 # noqa: F401\n")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    registry = tmp_path / "quality/comment-policy.json"
    registry.write_text(json.dumps(policy(exceptions=[exception()])), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "quality/comment-policy.json", "pyproject.toml"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "fixture permission",
        ],
        check=True,
    )
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    registry.write_text(json.dumps(policy()), encoding="utf-8")
    assert main(["--root", str(tmp_path), "--mode", "transition", "--base", base]) == 1


@pytest.mark.parametrize("source", ['__doc__: str = "prose"', '__doc__ += "prose"', 'f"inert {value}"'])
def test_other_python_prose_forms(source: str) -> None:
    assert python_findings("a.py", source)


def test_python_sql_context_avoids_docstrings_and_fstring_fragments() -> None:
    assert [f.kind for f in python_findings("a.py", '"Show plan evolution -- details"')] == ["docstring"]
    assert not python_findings("a.py", "sql = f\"SELECT * FROM t WHERE x = '{value}'\"")
    assert [f.text for f in python_findings("a.py", 'conn.execute("PRAGMA foreign_keys=ON; -- explanation")')] == [
        "-- explanation"
    ]


@pytest.mark.parametrize(
    "source", ["SELECT [1 /* explanation */, 2];", "SELECT 1 FROM t WHERE x = 1 AND [--flag] = 1;"]
)
def test_ambiguous_sql_brackets_require_dialect(source: str) -> None:
    assert scan("a.sql", source, "sql")[0].kind == "coverage-error"
    assert [text for _, text in sql_comments(source, "duckdb")] or not sql_comments(source, "tsql")


@pytest.mark.parametrize(
    "path",
    [
        "results-explorer/a.mts",
        "docker/a.java",
        "benchbox/a.properties",
        ".github/CODEOWNERS",
        "scripts/a.zsh",
        "scripts/new-format.xyz",
    ],
)
def test_closed_inventory_discovers_maintained_sources(tmp_path: Path, path: str) -> None:
    git_repo(tmp_path, "x=1")
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# explanation", encoding="utf-8")
    assert path in source_paths(tmp_path, False)
    subprocess.run(["git", "-C", str(tmp_path), "add", path], check=True)
    assert path in source_paths(tmp_path, True)


def test_zsh_shebang_is_minimum_directive() -> None:
    assert [f.kind for f in scan("a.zsh", "#!/bin/zsh\n# explanation\n", "bash")] == ["comment", "comment"]


@pytest.mark.parametrize(
    "source", ["printf python <<'EOF'\necho ok\nEOF\n", "python script.py <<'EOF'\n# input data\nEOF\n"]
)
def test_heredoc_arguments_and_script_input_are_data(source: str) -> None:
    assert not scan("a.sh", source, "bash")


def test_multiple_heredocs_and_continued_header() -> None:
    source = "python - \\\n <<'A' <<'B'\n# unused input\nA\n# explanation\nB\n"
    assert [f.text for f in scan("a.sh", source, "bash")] == ["# explanation"]


def test_piped_heredoc_is_executable() -> None:
    source = "cat <<'JS' | node\n// explanation\nJS\n"
    assert javascript_requests("a.sh", source, "bash")


@pytest.mark.parametrize(
    "source",
    [
        "write_sql: 'SELECT 1 -- explanation'",
        "cleanup_sql: 'DELETE FROM t -- explanation'",
        "platform_overrides:\n  duckdb: 'SELECT 1 -- explanation'",
    ],
)
def test_repository_sql_carriers_are_routed(source: str) -> None:
    assert [f.text for f in scan("a.yaml", source, "yaml")] == ["-- explanation"]


def test_github_script_routes_native_request() -> None:
    source = "steps:\n- uses: actions/github-script@sha\n  with:\n    script: |\n      // explanation\n"
    assert list(javascript_requests("ci.yaml", source, "yaml").values()) == ["// explanation\n"]


def test_myst_metadata_and_nested_examples() -> None:
    source = "```{tags}\npython\n```\n```{toctree}\nindex\n```\n````{note}\n```python\n# explanation\n```\n````\n"
    assert [(f.line, f.text) for f in scan("docs/a.md", source, "examples")] == [(9, "# explanation")]
    source = "  ```python\n  # explanation\n  ```\n"
    assert [(f.line, f.text) for f in scan("docs/a.md", source, "examples")] == [(2, "# explanation")]


def test_rst_nested_code_is_dedented() -> None:
    source = "   .. code-block:: python\n      :linenos:\n\n      # explanation\n      x=1\n"
    assert [(f.line, f.text) for f in scan("docs/a.rst", source, "examples")] == [(4, "# explanation")]


def test_exception_budget_and_completed_external_overlap() -> None:
    registered = load_policy(json.dumps(policy(exceptions=[exception()])).encode())
    assert len(scan_sources(ROOT, {"a.py": b"x=1 # noqa: F401\ny=2 # noqa: F401\n"}, registered)) == 1
    with pytest.raises(ValueError, match="overlap"):
        load_policy(
            json.dumps(
                policy(
                    completed=["vendor/"],
                    external=[{"path": "vendor/a.py", "owner": "upstream", "provenance": "README.md"}],
                )
            ).encode()
        )


def test_fixture_exception_binds_payload_kind_text_and_count() -> None:
    entry = exception("-- explanation", kind="fixture", payload="SELECT 1 -- explanation", finding_kind="comment")
    registered = load_policy(json.dumps(policy(exceptions=[entry])).encode())
    finding = Finding("a.py", 1, "comment", "-- explanation", payload="SELECT 1 -- explanation")
    assert allowed(finding, registered, "")
    assert not allowed(
        Finding("a.py", 1, "comment", "-- explanation", payload="SELECT 2 -- explanation"), registered, ""
    )


def test_report_handles_provenance_excluded_vendor_binary(tmp_path: Path) -> None:
    git_repo(tmp_path, "# legacy\n")
    path = "_project/scripts/vendor/package.whl"
    binary = tmp_path / path
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"PK\x03\x04\xff")
    (tmp_path / "quality/comment-policy.json").write_text(
        json.dumps(policy(external=[{"path": path, "owner": "upstream", "provenance": "a.py"}])), encoding="utf-8"
    )
    assert path in source_paths(tmp_path, False)
    assert main(["--root", str(tmp_path), "--mode", "report"]) == 0


def test_parser_environment_installs_only_trusted_material(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("comment-policy-package.json", "comment-policy-package-lock.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    commands = []
    monkeypatch.setenv("PYTHONPATH", "candidate")
    monkeypatch.setenv("NODE_OPTIONS", "--require=candidate")
    monkeypatch.setenv("COMMENT_POLICY_TYPESCRIPT", "candidate")

    def install(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("run_comment_policy.subprocess.run", install)
    python, env = parser_environment(tmp_path)
    assert str(python).startswith(str(tmp_path))
    assert "PYTHONPATH" not in env and "NODE_OPTIONS" not in env
    assert env["COMMENT_POLICY_TYPESCRIPT"] == str(tmp_path / "node_modules/typescript")
    assert "--require-hashes" in commands[1][0]
    assert "--ignore-scripts" in commands[2][0]
    assert str(tmp_path / "comment-policy-requirements.txt") in commands[1][0]
    assert commands[2][1]["cwd"] == tmp_path


def test_comment_policy_trust_roots_require_soundness_review() -> None:
    routes = (ROOT / ".github/soundness-paths.txt").read_text().splitlines()
    owners = (ROOT / ".github/CODEOWNERS").read_text().splitlines()
    for path in (*TRUSTED_FILES, "scripts/run_comment_policy.py", "quality/comment-policy.json"):
        assert "file\t" + path in routes
        assert path + " @joeharris76" in owners


@pytest.mark.parametrize("prose,native_failure", [(True, False), (True, True), (False, False), (False, True)])
def test_candidate_native_execution_cannot_replace_checker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prose: bool, native_failure: bool
) -> None:
    git_repo(tmp_path, "x = 1\n")
    for name in TRUSTED_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    (tmp_path / "scripts/comment_policy_entry.py").write_bytes((ROOT / "scripts/comment_policy_entry.py").read_bytes())
    (tmp_path / "scripts/check_comment_policy.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "root = Path(sys.argv[sys.argv.index('--root') + 1])\n"
        "raise SystemExit(int('# explanation' in (root / 'scripts/bad.py').read_text()))\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "scripts", "quality"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Checker fixture",
        ],
        check=True,
    )
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    (tmp_path / "scripts/bad.py").write_text("# explanation\n" if prose else "x = 1\n", encoding="utf-8")
    order = []
    real_run = subprocess.run

    def execute(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if command[0] == "node":
            order.append("native")
            directory = kwargs["cwd"]
            assert isinstance(directory, Path)
            (directory / "check_comment_policy.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
            if native_failure:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0)
        if command[0] == sys.executable and any(str(value).endswith("comment_policy_entry.py") for value in command):
            order.append("checker")
        return real_run(command, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.setattr(policy_runner, "parser_environment", lambda trusted: (Path(sys.executable), dict(os.environ)))
    monkeypatch.setattr(policy_runner.subprocess, "run", execute)
    assert policy_runner.main(["--base", base, "--native-tests"]) == (1 if prose else 2 if native_failure else 0)
    assert order == (["checker"] if prose else ["checker", "native"])
    assert (tmp_path / "scripts/bad.py").read_text() == ("# explanation\n" if prose else "x = 1\n")


def test_new_files_do_not_inherit_vendor_directory_exclusion() -> None:
    registered = policy(external=[{"path": "vendor/", "owner": "upstream", "provenance": "README.md"}])
    registered["external_members"] = {"vendor/old.py"}
    findings = scan_sources(ROOT, {"vendor/old.py": b"# upstream\n", "vendor/new.py": b"# explanation\n"}, registered)
    assert [(f.path, f.text) for f in findings] == [("vendor/new.py", "# explanation")]


def test_invalid_source_encoding_is_inventory_debt_in_report(tmp_path: Path) -> None:
    git_repo(tmp_path, "x=1")
    (tmp_path / "a.py").write_bytes(b"\xff")
    assert main(["--root", str(tmp_path), "--mode", "report"]) == 0
    assert main(["--root", str(tmp_path), "--mode", "strict"]) == 1


@pytest.mark.parametrize(
    "source",
    [
        'exec("# explanation")',
        'eval("1 # explanation")',
        'compile("# explanation", "generated", "exec")',
        'code = "# explanation"\nexec(code)',
        'code = "# " + "explanation"\nexec(code)',
        'import builtins as bi\nbi.exec("# explanation")',
        'from builtins import exec as run\nrun("# explanation")',
        'exec(compile("# explanation", "generated", "exec"))',
        'import subprocess\nsubprocess.run(["python3", "-c", "# explanation"])',
        'import subprocess, sys\nsubprocess.run([sys.executable, "-c", "# explanation"])',
        "import subprocess\nsubprocess.run(\"python3 -c '# explanation'\", shell=True)",
        'import subprocess\nsubprocess.run(args=["python3", "-c", "# explanation"])',
        'import subprocess\nsubprocess.run(args="echo ok # explanation", shell=True)',
    ],
)
def test_python_executable_strings_reach_scanner(source: str) -> None:
    assert [f.text for f in python_findings("a.py", source)] == ["# explanation"]


@pytest.mark.parametrize(
    "source", ["exec(source)", 'code = code + "text"\nexec(code)', 'code = "before"\ncode = "after"\nexec(code)']
)
def test_python_unresolved_execution_fails_visibly(source: str) -> None:
    assert python_findings("a.py", source)[0].kind == "payload-error"


@pytest.mark.parametrize(
    "source",
    [
        'def exec(value):\n    return value\nexec("# data")',
        'def f(exec):\n    return exec("# data")',
        'text = "# data"',
    ],
)
def test_local_execution_names_and_ordinary_strings_are_data(source: str) -> None:
    assert not python_findings("a.py", source)


@pytest.mark.parametrize(
    "source", ['python3 -c "# explanation"', "eval 'echo ok # explanation'", "bash -lc 'echo ok # explanation'"]
)
def test_shell_executable_arguments_are_routed(source: str) -> None:
    assert [f.text for f in scan("a.sh", source, "bash")] == ["# explanation"]


@pytest.mark.parametrize("source", ["# explanation", "echo ok # explanation", "echo ok # explanation\n"])
def test_shell_comments_at_end_of_input(source: str) -> None:
    findings = scan("a.sh", source, "bash")
    assert [(finding.line, finding.text) for finding in findings] == [(1, "# explanation")]
    assert not scan("a.sh", 'printf "%s" "# data"', "bash")


def test_shell_dynamic_execution_requires_adapter() -> None:
    assert scan("a.sh", 'python -c "$code"', "bash")[0].kind == "coverage-error"
    assert not scan("a.sh", 'printf "%s" "eval # input data"', "bash")


@pytest.mark.parametrize("module_name", ["check_deps", "scan_imports"])
def test_markdown_parser_dependency_is_backed_by_import_sites(module_name: str, tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        module_name, ROOT / "_project/scripts/dependency_audit" / f"{module_name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    collect = getattr(module, "_collect_python_imports", None) or module.collect_python_imports
    uses = getattr(module, "_package_uses", None) or module.package_uses
    script = tmp_path / "consumer.py"
    script.write_text("from markdown_it import MarkdownIt\n", encoding="utf-8")
    assert uses("markdown-it-py", collect(tmp_path, ["consumer.py"])) == ["consumer.py:1"]
    script.write_text('data = "from markdown_it import MarkdownIt"\n', encoding="utf-8")
    assert not uses("markdown-it-py", collect(tmp_path, ["consumer.py"]))
    assert not uses("markdown-it-py", {})


def test_opaque_fixture_permission_changes_with_contributing_consumer_code() -> None:
    source = "code = input()\nexec(code)"
    finding = python_findings("a.py", source)[0]
    registered = policy(
        exceptions=[exception(finding.text, kind="fixture", payload=finding.payload, finding_kind="payload-error")]
    )
    assert allowed(finding, registered, source)
    changed = python_findings("a.py", source + '\ncode_input = "# new explanation"')[0]
    assert changed.text == finding.text
    assert changed.payload != finding.payload
    assert not allowed(changed, registered, source)


def test_native_payload_batches_include_nested_shell_javascript(monkeypatch: pytest.MonkeyPatch) -> None:
    source = 'import {execSync} from "node:child_process"; execSync("node -e \'// explanation\'");'
    batches = []

    def native_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        requests = json.loads(str(kwargs["input"]))
        batches.append(requests)
        row = (
            {"kind": "payload", "language": "bash", "line": 1, "symbol": "", "text": "node -e '// explanation'"}
            if len(batches) == 1
            else {"kind": "comment", "line": 1, "text": "// explanation", "symbol": ""}
        )
        return subprocess.CompletedProcess(command, 0, json.dumps({key: [row] for key in requests}))

    monkeypatch.setattr("check_comment_policy.subprocess.run", native_run)
    findings = scan_sources(ROOT, {"a.ts": source.encode()}, policy())
    assert [(f.kind, f.text) for f in findings] == [("comment", "// explanation")]
    assert len(batches) == 2
    assert list(batches[1].values()) == ["// explanation"]


@pytest.mark.parametrize("node_type", [ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef])
def test_consumer_digest_ignores_absent_empty_type_parameters(node_type: type[ast.AST]) -> None:
    from comment_syntax import python_consumer_digest

    node: Any = node_type()
    vars(node)["_fields"] = tuple(name for name in node_type._fields if name != "type_params")
    tree = ast.Module(body=[node], type_ignores=[])
    before = python_consumer_digest(tree)
    vars(node)["_fields"] = (*node._fields, "type_params")
    node.type_params = []
    assert python_consumer_digest(tree) == before
    node.type_params = [ast.Name(id="T", ctx=ast.Load())]
    assert python_consumer_digest(tree) != before


def test_consumer_digest_has_stable_python_version_encoding() -> None:
    from comment_syntax import python_consumer_digest

    tree = ast.parse("def consume(value):\n    return value + 1\n")
    assert python_consumer_digest(tree) == "sha256:c6aaea25c78f8f6fdbf83d97c11fe1be21e859156b678d34cfbcc79f8c261c69"
