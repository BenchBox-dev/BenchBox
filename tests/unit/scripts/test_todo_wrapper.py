"""Contract tests for the thin TODO wrapper (shim + skill) around todo_db.py.

The wrapper thesis (see _project/specs/todo-db-tracker.md): every rule the old
skill carried as prose must live in the CLI or the DB, so the skill shrinks to
a command contract. These tests pin that contract:

- the `todo` shim is the single entry point and works from any cwd;
- the root skill is genuinely thin (line budget) and carries no schema prose;
- the skill package covers the mandatory workflow verbs and mentions only real commands.

Marked medium (not fast) deliberately: subprocess-driven and the fast lane is
budget-gated.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SHIM_PATH = REPO_ROOT / "_project" / "scripts" / "todo"
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "todo-db" / "SKILL.md"


def _read_skill_package() -> str:
    """Read the routed skill contract: the thin wrapper plus its references."""
    reference_paths = sorted((SKILL_PATH.parent / "references").glob("*.md"))
    return "\n".join(path.read_text(encoding="utf-8") for path in (SKILL_PATH, *reference_paths))


def _declared_standalone_only() -> set[str]:
    """Commands the skill declares as standalone todo-db only (never wrapper)."""
    meta = yaml.safe_load((SKILL_PATH.parent / "skill.yaml").read_text(encoding="utf-8")) or {}
    declared = meta.get("standalone_only_commands") or {}
    assert isinstance(declared, dict), "standalone_only_commands must map command -> minimum version"
    return set(declared)


def _unknown_commands(text: str, declared: set[str]) -> set[str]:
    """Referenced `todo <cmd>` forms that are neither wrapper handlers nor declared."""
    referenced = set(re.findall(r"`todo ([a-z][a-z-]*)", text))
    # `finding` is a real top-level command dispatched via _dispatch's special
    # branch (not _HANDLERS) to keep the todo_db<->todo_findings import cycle
    # load-order-independent -- see _dispatch's comment.
    real = set(todo_db._HANDLERS) | {"finding"}
    return referenced - real - declared


def _load_script():
    name = "todo_db"
    path = REPO_ROOT / "_project" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


todo_db = _load_script()


def _run_shim(args: list[str], db_path: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SHIM_PATH), *args],
        capture_output=True,
        text=True,
        cwd=cwd or REPO_ROOT,
        env={"PATH": os.environ["PATH"], "TODO_DB_PATH": str(db_path), "HOME": str(Path.home())},
        check=False,
        timeout=120,
    )


class TestShim:
    def test_shim_exists_and_is_executable(self):
        assert SHIM_PATH.exists(), "wrapper shim _project/scripts/todo is missing"
        assert SHIM_PATH.stat().st_mode & 0o111, "shim is not executable"
        first_line = SHIM_PATH.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("#!"), "shim needs a shebang"

    def test_shim_execs_todo_db_via_uv(self):
        text = SHIM_PATH.read_text(encoding="utf-8")
        assert "todo_db.py" in text
        assert "uv run --project" in text

    def test_shim_runs_stats_from_repo_subdir(self, tmp_path):
        result = _run_shim(["stats"], tmp_path / "wrapper.sqlite", cwd=REPO_ROOT / "tests")
        assert result.returncode == 0, result.stderr
        stats = json.loads(result.stdout)
        assert stats["items_by_state"] == {}

    def test_shim_propagates_gate_exit_codes(self, tmp_path):
        db = tmp_path / "wrapper.sqlite"
        create = _run_shim(
            [
                "create",
                "gate-item",
                "--title",
                "Gate exit-code item",
                "--worktree",
                "spike",
                "--priority",
                "low",
                "--description",
                "Wrapper contract exit-code check.",
            ],
            db,
        )
        assert create.returncode == 0, create.stderr
        # complete from planning is an illegal transition -> exit 2 through the shim
        complete = _run_shim(["complete", "gate-item"], db)
        assert complete.returncode == 2
        assert "illegal transition" in complete.stderr


class TestSkillThinness:
    def test_skill_exists_with_frontmatter(self):
        assert SKILL_PATH.exists(), "thin skill .claude/skills/todo-db/SKILL.md is missing"
        text = SKILL_PATH.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        frontmatter = text.split("---", 2)[1]
        assert "name: todo-db" in frontmatter
        assert "description:" in frontmatter

    def test_skill_body_is_thin(self):
        text = SKILL_PATH.read_text(encoding="utf-8")
        body = text.split("---", 2)[2]
        nonempty = [line for line in body.splitlines() if line.strip()]
        assert len(nonempty) <= 40, (
            f"thin-wrapper budget exceeded: {len(nonempty)} non-empty body lines > 40 — "
            "rules belong in the CLI/DB, not the skill"
        )

    def test_skill_references_only_real_or_declared_commands(self):
        text = _read_skill_package()
        referenced = set(re.findall(r"`todo ([a-z][a-z-]*)", text))
        assert referenced, "skill package must reference `todo <command>` forms"
        unknown = _unknown_commands(text, _declared_standalone_only())
        assert not unknown, (
            "skill package references commands that are neither wrapper handlers "
            f"nor declared standalone-only: {sorted(unknown)}"
        )

    def test_declared_standalone_commands_are_not_wrapper_handlers(self):
        # Declaring a wrapper-supported verb standalone-only would mask drift
        # in either direction; the sets must stay disjoint.
        overlap = _declared_standalone_only() & set(todo_db._HANDLERS)
        assert not overlap, f"standalone_only_commands overlaps wrapper handlers: {sorted(overlap)}"

    def test_undeclared_unsupported_command_is_flagged(self):
        # Without a declaration the boundary must trip — the declaration is the
        # only sanctioned way to document a wrapper-unsupported verb.
        assert _unknown_commands("run `todo frobnicate` then stop", set()) == {"frobnicate"}
        assert _unknown_commands("`todo update <id>` corrects items", set()) == {"update"}

    def test_standalone_only_commands_never_presented_as_wrapper_invocations(self):
        # A declared verb must never appear as a project-wrapper invocation and
        # every documented use must carry standalone gating language nearby.
        text = _read_skill_package()
        for command in sorted(_declared_standalone_only()):
            assert not re.search(rf"_project/scripts/todo\s+{command}\b", text), (
                f"standalone-only `{command}` shown as a project-wrapper invocation"
            )
            lines = text.splitlines()
            hits = [index for index, line in enumerate(lines) if f"`todo {command}" in line]
            assert hits, f"declared standalone-only `{command}` is never documented"
            for index in hits:
                window = " ".join(lines[max(0, index - 3) : index + 4]).casefold()
                assert "standalone" in window, (
                    f"`todo {command}` reference at package line {index + 1} lacks standalone gating language"
                )

    def test_skill_covers_required_workflow(self):
        text = _read_skill_package()
        for required in (
            "`todo ready`",
            "`todo claim",
            "`todo done",
            "--evidence",
            "`todo defer",
            "`todo promote",
            "`todo dismiss",
            "`todo complete",
            "`todo verify",
            "`todo check-scope",
        ):
            assert required in text, f"skill package workflow is missing {required}"

    def test_skill_carries_no_schema_prose(self):
        body = SKILL_PATH.read_text(encoding="utf-8").split("---", 2)[2].lower()
        for banned in ("schema", "yaml", "reindex", "template", "_indexes"):
            assert banned not in body, (
                f"skill body mentions {banned!r} — schema/validation duties belong to the CLI/DB, not wrapper prose"
            )

    def test_every_cli_subcommand_has_help(self, capsys):
        for command in todo_db._HANDLERS:
            with pytest.raises(SystemExit) as excinfo:
                todo_db.main([command, "--help"])
            assert excinfo.value.code == 0, f"{command} --help failed"
            capsys.readouterr()


class TestWrapperUatLifecycle:
    """UAT: the full agent workflow, end to end, through the shim only.

    Mirrors the skill's numbered workflow — if this passes, the thin skill's
    contract is executable exactly as written.
    """

    def test_full_lifecycle_through_shim(self, tmp_path):
        db = tmp_path / "uat.sqlite"

        def run(*args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
            result = _run_shim(list(args), db)
            assert result.returncode == expect, (
                f"todo {' '.join(args)} -> {result.returncode}\n{result.stdout}\n{result.stderr}"
            )
            return result

        # create an item shaped like a real work order
        run(
            "create",
            "uat-item",
            "--title",
            "UAT lifecycle exercise item",
            "--worktree",
            "spike",
            "--priority",
            "high",
            "--description",
            "End-to-end wrapper acceptance scenario.",
            "--work",
            "w1:implement the thing",
            "--work",
            "w2:verify the thing:needs=w1",
            "--verify",
            "unit gate::true",
            "--only-modify",
            "_project/*",
            "--preserve",
            "existing behavior stays",
        )
        # skill step 1: ready queue shows it
        assert "uat-item" in run("ready").stdout
        # skill step 2: claim prints the work order
        order = run("claim", "uat-item").stdout
        for section in ("scope", "must preserve", "verification ladder", "w1"):
            assert section in order, f"work order missing {section}"
        # unit order is enforced: w2 before w1 refuses
        run("done", "uat-item", "w2", "--evidence", "premature", expect=2)
        # skill step 3: start/done with evidence
        run("start", "uat-item", "w1")
        run("done", "uat-item", "w1", "--evidence", "pytest -q passed")
        run("done", "uat-item", "w2", "--evidence", "verify ladder seq 1 pass")
        # skill step 5: verification ladder runs and records
        assert "pass" in run("verify", "uat-item", "--run", "1").stdout
        # skill step 4: defer mid-flight
        run("defer", "uat-item", "--summary", "follow-up polish", "--reason", "out of scope")
        # skill step 6: complete refuses while the deferral is open
        blocked = _run_shim(["complete", "uat-item", "--pr", "999"], db)
        assert blocked.returncode == 2
        assert "unresolved deferrals" in blocked.stderr
        # resolve by promotion; completion then succeeds
        run("promote", "1", "--to-item", "uat-item-followup")
        run("complete", "uat-item", "--pr", "999")
        # outcomes: parent done, child ready, stats coherent, export stable
        assert "uat-item-followup" in run("ready").stdout
        stats = json.loads(run("stats").stdout)
        assert stats["items_by_state"] == {"done": 1, "planning": 1}
        assert stats["deferrals_by_resolution"] == {"promoted": 1}
        first = run("export", "--out", str(tmp_path / "a")).stdout
        second = run("export", "--out", str(tmp_path / "b")).stdout
        assert first and second
        assert (tmp_path / "a" / "items.jsonl").read_text() == (tmp_path / "b" / "items.jsonl").read_text()
        # a terminal item refuses late deferrals (the buried-deferral guard)
        late = _run_shim(["defer", "uat-item", "--summary", "too late", "--reason", "nope"], db)
        assert late.returncode == 2
        assert "terminal items" in late.stderr
