"""Guard that UAT follow-up work does not change the public BenchBox CLI surface."""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.fast

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_INTERNAL_CLI_FILES = {
    "benchbox/cli/benchmarks.py",
    "benchbox/cli/commands/calculate_qphh.py",
    "benchbox/cli/commands/compare_dataframes.py",
    "benchbox/cli/commands/compare_plans.py",
    "benchbox/cli/commands/convert.py",
    "benchbox/cli/commands/df_tuning.py",
    "benchbox/cli/commands/run.py",
    "benchbox/cli/commands/run_official.py",
    "benchbox/cli/commands/submit.py",
    "benchbox/cli/commands/tuning.py",
    "benchbox/cli/commands/visualize.py",
    "benchbox/cli/help.py",
    "benchbox/cli/orchestrator.py",
}
ALLOWED_HIDDEN_COMPAT_CLI_FILES = {
    "benchbox/cli/commands/calculate_qphh.py",
    "benchbox/cli/commands/compare_dataframes.py",
    "benchbox/cli/commands/compare_plans.py",
    "benchbox/cli/commands/df_tuning.py",
    "benchbox/cli/commands/run_official.py",
    "benchbox/cli/commands/tuning.py",
}
FORBIDDEN_CLI_SURFACE_DECORATORS = {"argument", "command", "group", "option"}
FORBIDDEN_CLI_SURFACE_FUNCTIONS = {
    "benchbox/cli/commands/convert.py": "convert",
    "benchbox/cli/commands/run.py": "run",
    "benchbox/cli/commands/submit.py": "submit",
    "benchbox/cli/commands/visualize.py": "visualize",
}


def test_uat_did_not_modify_benchbox_cli_surface():
    base = _verified_base_ref()
    changed = set(_git("diff", "--name-only", base, "--", "benchbox/cli/").stdout.splitlines())
    unexpected = changed - ALLOWED_INTERNAL_CLI_FILES

    assert not unexpected, f"Unexpected benchbox CLI file changes: {sorted(unexpected)}"

    forbidden = []
    for path in sorted(ALLOWED_INTERNAL_CLI_FILES):
        if path in ALLOWED_HIDDEN_COMPAT_CLI_FILES:
            continue
        if _cli_surface_changed(
            path,
            base_source=_source_at_ref(base, path),
            current_source=_source_at_worktree(path),
        ):
            forbidden.append(path)
    assert not forbidden, f"Unexpected CLI surface changes: {forbidden}"


def test_cli_surface_guard_detects_click_argument_changes():
    base_source = """import click

@click.command("submit")
@click.argument("result_file", required=False)
def submit(
    ctx,
):
    pass
"""
    current_source = """import click

@click.command("submit")
@click.argument("extra_result_file")
@click.argument("result_file", required=False)
def submit(
    ctx,
):
    pass
"""
    assert _cli_surface_changed(
        "benchbox/cli/commands/submit.py",
        base_source=base_source,
        current_source=current_source,
    )


def test_cli_surface_guard_detects_signature_continuation_changes():
    base_source = """import click

@click.command("submit")
def submit(
    ctx,
):
    pass
"""
    current_source = """import click

@click.command("submit")
def submit(
    ctx,
    result_file,
):
    pass
"""
    assert _cli_surface_changed(
        "benchbox/cli/commands/submit.py",
        base_source=base_source,
        current_source=current_source,
    )


def test_cli_surface_guard_allows_submit_body_changes():
    base_source = """import click

@click.command("submit")
def submit(
    ctx,
):
    return "old"
"""
    current_source = """import click

@click.command("submit")
def submit(
    ctx,
):
    return "new"
"""
    assert not _cli_surface_changed(
        "benchbox/cli/commands/submit.py",
        base_source=base_source,
        current_source=current_source,
    )


def test_cli_surface_guard_skips_when_base_ref_is_missing(monkeypatch: pytest.MonkeyPatch):
    missing_base = "refs/heads/__benchbox_missing_base__"
    monkeypatch.setenv("BENCHBOX_BASE_REF", missing_base)

    with pytest.raises(pytest.skip.Exception, match=f"base ref {missing_base!r} is not available"):
        _verified_base_ref()


def _verified_base_ref() -> str:
    inside = _git("rev-parse", "--is-inside-work-tree", check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        pytest.skip("CLI surface drift guard requires a git worktree")

    base = os.environ.get("BENCHBOX_BASE_REF", "origin/develop")
    verified = _git("rev-parse", "--verify", f"{base}^{{commit}}", check=False)
    if verified.returncode != 0:
        pytest.skip(f"CLI surface drift guard base ref {base!r} is not available")
    return base


def _source_at_ref(ref: str, path: str) -> str:
    source = _git("show", f"{ref}:{path}", check=False)
    if source.returncode != 0:
        return ""
    return source.stdout


def _source_at_worktree(path: str) -> str:
    try:
        return (REPO_ROOT / path).read_text()
    except FileNotFoundError:
        return ""


def _cli_surface_changed(
    path: str,
    *,
    base_source: str,
    current_source: str,
) -> bool:
    return _cli_surface_snapshot(base_source, path) != _cli_surface_snapshot(current_source, path)


def _cli_surface_snapshot(source: str, path: str) -> tuple[str, ...]:
    if not source:
        return ()

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise AssertionError(f"Could not parse {path} while checking CLI surface drift: {exc}") from exc

    lines = source.splitlines()
    surface = []
    function_name = FORBIDDEN_CLI_SURFACE_FUNCTIONS.get(path)
    functions = sorted(
        (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)),
        key=lambda node: node.lineno,
    )
    for node in functions:
        for decorator in node.decorator_list:
            if _click_surface_decorator_name(decorator) in FORBIDDEN_CLI_SURFACE_DECORATORS:
                end_lineno = decorator.end_lineno or decorator.lineno
                surface.extend(lines[decorator.lineno - 1 : end_lineno])
        if function_name is not None and node.name == function_name and node.body:
            surface.extend(lines[node.lineno - 1 : node.body[0].lineno - 1])
    return tuple(surface)


def _click_surface_decorator_name(decorator: ast.expr) -> str | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "click":
        return target.attr
    return None


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed with {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result
