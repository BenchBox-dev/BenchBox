"""Contract tests for the thin TODO wrapper and locked package boundary.

The wrapper thesis (see _project/specs/todo-db-tracker.md): every rule the old
skill carried as prose must live in the CLI or the DB, so the skill shrinks to
a command contract. These tests pin that contract:

- the `todo` shim is the single entry point and works from any cwd;
- the root skill is genuinely thin (line budget) and carries no schema prose;
- the skill package separates wrapper commands, standalone CLI commands, and skill-only actions.

Marked medium (not fast) deliberately: subprocess-driven and the fast lane is
budget-gated.
"""

from __future__ import annotations

import hashlib
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
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "todo" / "SKILL.md"
VENDORED_WHEEL = REPO_ROOT / "_project" / "scripts" / "vendor" / "todo_db-0.4.2-py3-none-any.whl"

sys_path = str(REPO_ROOT / "_project" / "scripts")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)
import todo_db_standalone_compat as compat  # noqa: E402


def _read_skill_package() -> str:
    """Read the routed skill contract: the thin wrapper plus its references."""
    reference_paths = sorted((SKILL_PATH.parent / "references").glob("*.md"))
    return "\n".join(path.read_text(encoding="utf-8") for path in (SKILL_PATH, *reference_paths))


def _declared_standalone_cli_commands() -> set[str]:
    """Commands the skill declares as standalone `todo` CLI only (never wrapper)."""
    meta = yaml.safe_load((SKILL_PATH.parent / "skill.yaml").read_text(encoding="utf-8")) or {}
    declared = meta.get("standalone_only_commands") or {}
    assert isinstance(declared, dict), "standalone_only_commands must map command -> minimum version"
    return set(declared)


def _declared_skill_only_actions() -> set[str]:
    """Skill orchestration actions explicitly marked as having no CLI command."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"\| `([a-z][a-z-]*)` — skill-only, no CLI command \|", text))


def _critical_rule_skill_only_actions() -> set[str]:
    """Skill-only actions exempted from the wrapper-help requirement."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    match = re.search(r"Skill-only actions: ([^;]+);", text)
    assert match, "skill package must exempt skill-only actions from the wrapper-help rule"
    return set(re.findall(r"`([a-z][a-z-]*)`", match.group(1)))


def _unknown_cli_commands(text: str, standalone: set[str]) -> set[str]:
    """Referenced `todo <cmd>` forms that are neither wrapper nor standalone CLI commands."""
    referenced = set(re.findall(r"`todo ([a-z][a-z-]*)", text))
    real = set(compat.COMMANDS)
    return referenced - real - standalone


def _run_shim(args: list[str], db_path: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "TODO_DB_PATH": str(db_path), "HOME": str(Path.home())}
    if worker := os.environ.get("PYTEST_XDIST_WORKER"):
        # Keep the CLI's documented xdist self-contention escape visible to the
        # subprocess when this contract test itself runs under a worker.
        env["PYTEST_XDIST_WORKER"] = worker
    return subprocess.run(
        [str(SHIM_PATH), *args],
        capture_output=True,
        text=True,
        cwd=cwd or REPO_ROOT,
        env=env,
        check=False,
        timeout=120,
    )


class TestShim:
    def test_shim_exists_and_is_executable(self):
        assert SHIM_PATH.exists(), "wrapper shim _project/scripts/todo is missing"
        assert SHIM_PATH.stat().st_mode & 0o111, "shim is not executable"
        first_line = SHIM_PATH.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("#!"), "shim needs a shebang"

    def test_shim_execs_locked_package_adapter_via_uv(self):
        text = SHIM_PATH.read_text(encoding="utf-8")
        assert "# todo-db-wrapper: v2" in text
        assert "TODO_DB_AUTH_CONTRACT=v2" in text
        assert "todo_db_standalone_compat.py" in text
        assert "todo_db.py" not in text
        assert "uv run --project" in text
        assert "turso db tokens create" not in text

    def test_scripts_project_uses_verified_vendored_todo_db_release(self):
        assert VENDORED_WHEEL.is_file()
        assert hashlib.sha256(VENDORED_WHEEL.read_bytes()).hexdigest() == (
            "c9f1b97f04f1bc9bd92647abbeb1b2ef1ef8665d6b0db8dc1dfda9f1a06731b7"
        )
        project = (REPO_ROOT / "_project" / "scripts" / "pyproject.toml").read_text(encoding="utf-8")
        assert 'todo-db = { path = "vendor/todo_db-0.4.2-py3-none-any.whl" }' in project
        assert "github.com/joeharris76/todo-db" not in project

    @pytest.mark.parametrize("subcommand", ["create", "candidates"])
    def test_offline_finding_commands_do_not_mint_hosted_credentials(self, tmp_path: Path, subcommand: str):
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        (fake_bin / "uv").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fake_bin / "turso").write_text("#!/bin/sh\nexit 91\n", encoding="utf-8")
        (fake_bin / "uv").chmod(0o755)
        (fake_bin / "turso").chmod(0o755)

        result = subprocess.run(
            [str(SHIM_PATH), "--actor", "reviewer", "finding", subcommand],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}", "HOME": str(Path.home())},
            check=False,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize(
        "args",
        [
            ["--help"],
            ["--version"],
            ["--db", "local.sqlite", "stats"],
            ["--db=local.sqlite", "stats"],
        ],
    )
    def test_metadata_and_explicit_local_paths_do_not_mint_hosted_credentials(
        self, tmp_path: Path, args: list[str]
    ) -> None:
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        marker = tmp_path / "turso-called"
        (fake_bin / "uv").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fake_bin / "turso").write_text(f"#!/bin/sh\ntouch {marker}\nexit 91\n", encoding="utf-8")
        (fake_bin / "uv").chmod(0o755)
        (fake_bin / "turso").chmod(0o755)

        result = subprocess.run(
            [str(SHIM_PATH), *args],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}", "HOME": str(Path.home())},
            check=False,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        assert not marker.exists()

    def test_v2_auth_exit_contract_is_negotiated_without_endpoint_disclosure(self) -> None:
        endpoint = "libsql://auth-contract.invalid"
        result = subprocess.run(
            [str(SHIM_PATH), "--db", endpoint, "list"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PATH": os.environ["PATH"], "HOME": str(Path.home())},
            check=False,
            timeout=120,
        )

        assert result.returncode == 4
        assert endpoint not in result.stdout + result.stderr
        assert "bounded credential" in result.stderr

    def test_shim_runs_stats_from_repo_subdir(self, tmp_path):
        result = _run_shim(["stats"], tmp_path / "wrapper.sqlite", cwd=REPO_ROOT / "tests")
        assert result.returncode == 0, result.stderr
        stats = json.loads(result.stdout)
        assert stats["items_by_state"] == {}

    def test_explicit_local_read_initializes_missing_database(self, tmp_path: Path) -> None:
        db = tmp_path / "explicit.sqlite"
        result = subprocess.run(
            [str(SHIM_PATH), "--db", str(db), "stats"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PATH": os.environ["PATH"], "HOME": str(Path.home())},
            check=False,
            timeout=120,
        )

        assert result.returncode == 0, result.stderr
        assert db.is_file()
        assert json.loads(result.stdout)["items_by_state"] == {}

    def test_legacy_compatibility_commands_remain_available(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy-commands.sqlite"
        create = _run_shim(
            [
                "create",
                "compat-item",
                "--title",
                "Compatibility command item",
                "--worktree",
                "compat",
                "--priority",
                "low",
                "--description",
                "Exercise the retained compatibility commands.",
            ],
            db,
        )
        assert create.returncode == 0, create.stderr

        scope = _run_shim(
            ["scope-update", "compat-item", "--add-only-modify", "tests/**", "--reason", "test boundary"], db
        )
        assert scope.returncode == 0, scope.stderr
        assert _run_shim(["claim", "compat-item"], db).returncode == 0
        renewed = _run_shim(["renew", "compat-item"], db)
        assert renewed.returncode == 0, renewed.stderr
        status = _run_shim(["freeze", "--status"], db)
        assert status.returncode == 0, status.stderr
        assert status.stdout.strip() == "no live freeze"
        frozen = _run_shim(["--actor", "alice", "freeze", "--reason", "compatibility test"], db)
        assert frozen.returncode == 0, frozen.stderr
        blocked = _run_shim(
            [
                "--actor",
                "bob",
                "create",
                "blocked-item",
                "--title",
                "Blocked during freeze",
                "--worktree",
                "compat",
                "--priority",
                "low",
                "--description",
                "This write must not pass a foreign freeze.",
            ],
            db,
        )
        assert blocked.returncode == 2
        assert "tracker is frozen for maintenance by alice" in blocked.stderr
        released = _run_shim(["--actor", "alice", "freeze", "--release"], db)
        assert released.returncode == 0, released.stderr

    def test_shim_resolves_code_from_own_location_not_cwd_git_root(self, tmp_path):
        # Absolute path to THIS tree's shim must win even when cwd is another
        # git root with a decoy package adapter (the lagging-primary
        # / wrong-clone failure mode).
        assert SHIM_PATH.is_absolute()
        decoy = tmp_path / "other-clone"
        scripts = decoy / "_project" / "scripts"
        scripts.mkdir(parents=True)
        (decoy / ".git").mkdir()
        decoy_marker = "DECOY_TODO_DB_MARKER_NOT_FROM_REAL_TREE"
        (scripts / "todo_db_standalone_compat.py").write_text(
            f"import sys\nprint({decoy_marker!r})\nsys.exit(97)\n",
            encoding="utf-8",
        )
        (scripts / "pyproject.toml").write_text(
            '[project]\nname = "decoy"\nversion = "0"\nrequires-python = ">=3.10"\n',
            encoding="utf-8",
        )
        # Foreign non-git cwd smoke
        result = subprocess.run(
            [str(SHIM_PATH), "update", "--help"],
            capture_output=True,
            text=True,
            cwd="/tmp",
            env={"PATH": os.environ["PATH"], "HOME": str(Path.home())},
            check=False,
            timeout=120,
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "update" in combined
        assert decoy_marker not in combined
        # Foreign git root with decoy scripts must not execute the decoy
        result2 = subprocess.run(
            [str(SHIM_PATH), "update", "--help"],
            capture_output=True,
            text=True,
            cwd=str(decoy),
            env={"PATH": os.environ["PATH"], "HOME": str(Path.home())},
            check=False,
            timeout=120,
        )
        combined2 = result2.stdout + result2.stderr
        assert result2.returncode == 0, combined2
        assert "update" in combined2
        assert decoy_marker not in combined2
        assert result2.returncode != 97

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
        assert SKILL_PATH.exists(), "thin skill .claude/skills/todo/SKILL.md is missing"
        text = SKILL_PATH.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        frontmatter = text.split("---", 2)[1]
        assert "name: todo" in frontmatter
        assert "description:" in frontmatter

    def test_skill_body_is_thin(self):
        text = SKILL_PATH.read_text(encoding="utf-8")
        body = text.split("---", 2)[2]
        nonempty = [line for line in body.splitlines() if line.strip()]
        assert len(nonempty) <= 40, (
            f"thin-wrapper budget exceeded: {len(nonempty)} non-empty body lines > 40 — "
            "rules belong in the CLI/DB, not the skill"
        )

    def test_skill_references_only_real_or_declared_cli_commands(self):
        text = _read_skill_package()
        referenced = set(re.findall(r"`todo ([a-z][a-z-]*)", text))
        assert referenced, "skill package must reference `todo <command>` forms"
        unknown = _unknown_cli_commands(text, _declared_standalone_cli_commands())
        assert not unknown, (
            "skill package presents actions as CLI commands that are neither wrapper handlers "
            f"nor declared standalone CLI commands: {sorted(unknown)}"
        )

    def test_action_capability_classes_are_disjoint(self):
        wrapper_commands = set(compat.COMMANDS)
        standalone_commands = _declared_standalone_cli_commands()
        skill_actions = _declared_skill_only_actions()
        assert skill_actions, "skill package must declare its skill-only actions"
        assert not (wrapper_commands & standalone_commands), "standalone CLI commands overlap wrapper handlers"
        assert not (wrapper_commands & skill_actions), "skill-only actions overlap wrapper handlers"
        assert not (standalone_commands & skill_actions), "skill-only actions overlap standalone CLI commands"

    def test_skill_only_actions_are_exempted_from_wrapper_help(self):
        assert _critical_rule_skill_only_actions() == _declared_skill_only_actions()

    def test_undeclared_unsupported_command_is_flagged(self):
        # Without a declaration the boundary must trip — the declaration is the
        # only sanctioned way to document a wrapper-unsupported CLI verb.
        assert _unknown_cli_commands("run `todo frobnicate` then stop", set()) == {"frobnicate"}
        # update is a real wrapper handler; it must not be flagged as unknown
        # when the declared standalone set is empty.
        assert _unknown_cli_commands("`todo update <id>` corrects items", set()) == set()

    def test_skill_only_action_presented_as_cli_command_is_flagged(self):
        assert "batch" in _declared_skill_only_actions()
        assert _unknown_cli_commands("run `todo batch`", set()) == {"batch"}

    def test_standalone_cli_commands_never_presented_as_wrapper_invocations(self):
        # A declared verb must never appear as a project-wrapper invocation and
        # every documented use must carry standalone gating language nearby.
        text = _read_skill_package()
        for command in sorted(_declared_standalone_cli_commands()):
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

    def test_skill_only_actions_never_presented_as_cli_commands(self):
        text = _read_skill_package()
        for action in sorted(_declared_skill_only_actions()):
            assert not re.search(rf"\btodo\s+{action}\b", text), (
                f"skill-only action `{action}` is presented as a CLI command"
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
        del capsys
        for command in sorted(compat.COMMANDS):
            result = subprocess.run(
                [str(SHIM_PATH), command, "--help"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            assert result.returncode == 0, f"{command} --help failed: {result.stderr}"


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
