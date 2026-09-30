from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from check_comment_policy import allowed, check_ratchet, introduced, load_policy, main, scan_sources
from comment_syntax import Finding, javascript_requests, python_findings, scan, sql_comments
from run_comment_policy import resolve_base

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
    assert [text for _, text in sql_comments(source)] == expected


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


@pytest.mark.parametrize(
    "path,source,text",
    [
        ("a.ts", 'const x = /https?:\\/\\//; const y = "// data"; // explanation', "// explanation"),
        ("a.ts", "const x = `// data ${1 /* explanation */}`;", "/* explanation */"),
        ("a.tsx", "const x = <div>https://host # data{/* explanation */}</div>;", "/* explanation */"),
        ("a.tsx", "const x = <div>\n// data\n<span /></div>; // explanation", "// explanation"),
        ("a.ts", "const x = 1; /* explanation */", "/* explanation */"),
    ],
)
def test_typescript_contexts(path: str, source: str, text: str) -> None:
    findings = scan_sources(ROOT, {path: source.encode()}, policy())
    assert [(f.kind, f.text) for f in findings] == [("comment", text)]


def test_nested_javascript_requests_and_html() -> None:
    source = '<script>const x = "// data"; // explanation\n</script>'
    assert len(javascript_requests("a.html", source, "html")) == 1
    assert [f.text for f in scan_sources(ROOT, {"a.html": source.encode()}, policy())] == ["// explanation"]


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
    assert 'uv run -- python "$RUNNER_TEMP/comment-policy-runner.py"' in step["run"]
    assert "8fbad03469746539959af14e865a19c53fab68f5" in step["run"]
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
