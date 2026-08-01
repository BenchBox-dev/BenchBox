"""Tests for the tracker v2 improvements driven by the head-to-head eval.

Covers (see _project/specs/todo-db-tracker.md, post-eval improvements):
- shared database across git worktrees (resolve via the common git dir);
- `check-scope` exempts the tracker's own state directory;
- `start`/`done` record the worktree and branch so another agent can
  resume or recover partial work, surfaced in the work order;
- schema v1 -> v2 migration path (`todo migrate`);
- `create --from -` JSON payload creation.

Marked medium (not fast): the fast lane is budget-gated and several tests
shell out to git.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    name = "todo_db_v2_under_test"
    path = REPO_ROOT / "_project" / "scripts" / "todo_db.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


todo_db = _load_script()


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture()
def git_repo(tmp_path):
    """A real git repo with one linked worktree on its own branch."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "trunk")
    _git(main, "commit", "--allow-empty", "-q", "-m", "root")
    _git(main, "worktree", "add", "-q", "-b", "feat-resume", str(tmp_path / "wt"))
    return {"main": main, "worktree": tmp_path / "wt"}


@pytest.fixture()
def conn(tmp_path):
    connection = todo_db.connect(tmp_path / "todo.sqlite")
    yield connection
    connection.close()


def _mk(conn, item_id="resume-item", **overrides):
    kwargs = {
        "item_id": item_id,
        "title": "A resumable tracked item",
        "worktree": "spike",
        "priority": "medium",
        "description": "A description longer than ten characters.",
        "work": [{"id": "w1", "summary": "first unit"}],
    }
    kwargs.update(overrides)
    todo_db.create_item(conn, "tester", **kwargs)
    return item_id


class TestSharedDbAcrossWorktrees:
    def test_worktree_resolves_to_main_repo_db(self, git_repo, monkeypatch):
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        expected = git_repo["main"] / ".todo-db" / "todo.sqlite"
        monkeypatch.chdir(git_repo["worktree"])
        assert todo_db.resolve_db_path(None).resolve() == expected.resolve()
        monkeypatch.chdir(git_repo["main"])
        assert todo_db.resolve_db_path(None).resolve() == expected.resolve()

    def test_env_override_still_wins(self, git_repo, monkeypatch):
        monkeypatch.setenv("TODO_DB_PATH", "/elsewhere/todo.sqlite")
        monkeypatch.chdir(git_repo["worktree"])
        assert todo_db.resolve_db_path(None) == Path("/elsewhere/todo.sqlite")


class TestScopeSelfExemption:
    def test_trailing_slash_scope_is_recursive_without_matching_siblings(self):
        rules = [{"kind": "only_modify", "path_glob": "tests/"}]
        violations = todo_db.check_paths(
            ["tests/unit/scripts/test_todo_db.py", "tests-other/not_allowed.py"],
            rules,
        )
        assert violations == ["tests-other/not_allowed.py: outside only_modify allowlist"]

    def test_trailing_slash_deny_scope_is_recursive(self):
        rules = [{"kind": "do_not_modify", "path_glob": "_project/scripts/"}]
        assert todo_db.check_paths(["_project/scripts/todo_db.py"], rules) == [
            "_project/scripts/todo_db.py: matches do_not_modify"
        ]

    def test_tracker_state_never_violates_scope(self):
        rules = [{"kind": "only_modify", "path_glob": "src/*"}]
        violations = todo_db.check_paths(
            [".todo-db/todo.sqlite", ".todo-db/export/items.jsonl", "docs/x.md"],
            rules,
        )
        assert violations == ["docs/x.md: outside only_modify allowlist"]

    def test_tracker_state_ignored_even_under_do_not_modify(self):
        rules = [{"kind": "do_not_modify", "path_glob": ".todo-db/*"}]
        assert todo_db.check_paths([".todo-db/todo.sqlite"], rules) == []


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (SimpleNamespace(command="init"), False),
        (SimpleNamespace(command="stats"), False),
        (SimpleNamespace(command="claim"), True),
        (SimpleNamespace(command="future-write-command"), True),
        (SimpleNamespace(command="import-yaml", dry_run=True), False),
        (SimpleNamespace(command="import-yaml", dry_run=False), True),
        (SimpleNamespace(command="verify", run=None), False),
        (SimpleNamespace(command="verify", run=1), True),
        (SimpleNamespace(command="config", value=None), False),
        (SimpleNamespace(command="config", value="on"), True),
    ],
)
def test_implicit_fallback_write_classification(args, expected):
    assert todo_db._command_mutates_tracker(args) is expected


class TestResumeLocation:
    def test_start_records_worktree_and_branch(self, conn, git_repo, monkeypatch):
        monkeypatch.chdir(git_repo["worktree"])
        _mk(conn)
        todo_db.claim_item(conn, "alice", "resume-item")
        todo_db.start_unit(conn, "alice", "resume-item", "w1")
        unit = todo_db.get_item(conn, "resume-item")["work"][0]
        assert unit["status"] == "in_progress"
        assert unit["started_at"]
        assert Path(unit["started_worktree"]).resolve() == git_repo["worktree"].resolve()
        assert unit["started_branch"] == "feat-resume"

    def test_done_without_start_stamps_location_implicitly(self, conn, git_repo, monkeypatch):
        monkeypatch.chdir(git_repo["main"])
        _mk(conn)
        todo_db.claim_item(conn, "alice", "resume-item")
        todo_db.done_unit(conn, "alice", "resume-item", "w1", "ran the checks")
        unit = todo_db.get_item(conn, "resume-item")["work"][0]
        assert unit["status"] == "done"
        assert Path(unit["started_worktree"]).resolve() == git_repo["main"].resolve()
        assert unit["started_branch"] == "trunk"

    def test_done_after_start_keeps_original_location(self, conn, git_repo, monkeypatch):
        monkeypatch.chdir(git_repo["worktree"])
        _mk(conn)
        todo_db.claim_item(conn, "alice", "resume-item")
        todo_db.start_unit(conn, "alice", "resume-item", "w1")
        monkeypatch.chdir(git_repo["main"])
        todo_db.done_unit(conn, "bob", "resume-item", "w1", "finished elsewhere")
        unit = todo_db.get_item(conn, "resume-item")["work"][0]
        assert unit["started_branch"] == "feat-resume"

    def test_work_order_surfaces_resume_info(self, conn, git_repo, monkeypatch, capsys):
        monkeypatch.chdir(git_repo["worktree"])
        _mk(conn)
        todo_db.claim_item(conn, "alice", "resume-item")
        todo_db.start_unit(conn, "alice", "resume-item", "w1")
        order = todo_db.work_order(conn, "resume-item")
        in_progress = [u for u in order["ready_units"] if u["status"] == "in_progress"]
        assert in_progress and in_progress[0]["started_branch"] == "feat-resume"
        todo_db._print_work_order(order)
        printed = capsys.readouterr().out
        assert "resumable" in printed
        assert "feat-resume" in printed


class TestSchemaMigration:
    def _make_v1_db(self, tmp_path):
        """Reconstruct a v1 database: the CORE (pre-findings) schema minus the
        v2 columns. Uses _CORE_SCHEMA_SQL, not SCHEMA_SQL: a real v1/v2 DB never
        had findings tables, and MIGRATIONS[3] recreates them on upgrade -- so
        seeding from the full current schema would collide ('table findings
        already exists')."""
        import sqlite3

        v1_sql = "\n".join(
            line
            for line in todo_db._CORE_SCHEMA_SQL.splitlines()
            if "started_at" not in line and "started_worktree" not in line and "started_branch" not in line
        )
        db_path = tmp_path / "v1.sqlite"
        raw = sqlite3.connect(db_path)
        raw.executescript(v1_sql)
        raw.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
        raw.commit()
        raw.close()
        return db_path

    def test_connect_refuses_old_schema_with_migrate_hint(self, tmp_path):
        db_path = self._make_v1_db(tmp_path)
        with pytest.raises(todo_db.TodoError, match="migrate"):
            todo_db.connect(db_path)

    def test_migrate_upgrades_v1_to_current(self, tmp_path):
        db_path = self._make_v1_db(tmp_path)
        applied = todo_db.migrate_db(db_path)
        assert applied  # at least one migration ran
        assert todo_db.SCHEMA_VERSION in applied  # ... reaching the current version
        conn = todo_db.connect(db_path)  # no longer refuses
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(work_units)")}
        assert {"started_at", "started_worktree", "started_branch"} <= columns
        # v3 (findings domain) tables exist after the upgrade.
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"findings", "finding_evidence", "finding_links", "finding_events"} <= tables
        conn.close()

    def test_migrate_is_idempotent(self, tmp_path):
        db_path = self._make_v1_db(tmp_path)
        todo_db.migrate_db(db_path)
        assert todo_db.migrate_db(db_path) == []

    def test_migrate_command_registered(self):
        assert "migrate" in todo_db._HANDLERS


class TestCreateFromPayload:
    PAYLOAD = {
        "id": "payload-item",
        "title": "Created from a JSON payload",
        "worktree": "spike",
        "priority": "high",
        "description": "Structured creation without flag soup.",
        "work": [
            {"id": "w1", "summary": "implement the thing"},
            {"id": "w2", "summary": "verify the thing", "needs": ["w1"]},
        ],
        "scope": {"only_modify": ["src/*"], "do_not_modify": ["docs/*"]},
        "verifications": [{"description": "unit gate", "command": "true"}],
        "preserves": ["existing behavior stays"],
        "anti_patterns": [{"dont": "widen scope", "why": "risk", "instead": "defer it"}],
        "prior_art": [{"path": "src/x.py", "concept": "pattern", "decision": "reuse"}],
    }

    def test_create_from_payload_roundtrip(self, conn):
        todo_db.create_from_payload(conn, "tester", self.PAYLOAD)
        item = todo_db.get_item(conn, "payload-item")
        assert item["priority"] == "high"
        assert [u["wid"] for u in item["work"]] == ["w1", "w2"]
        assert item["work"][1]["needs"] == ["w1"]
        assert {(s["kind"], s["path_glob"]) for s in item["scope"]} == {
            ("only_modify", "src/*"),
            ("do_not_modify", "docs/*"),
        }
        assert item["verifications"][0]["command"] == "true"
        assert item["anti_patterns"][0]["instead"] == "defer it"
        assert item["prior_art"][0]["decision"] == "reuse"

    def test_create_from_payload_missing_required_field(self, conn):
        payload = dict(self.PAYLOAD)
        del payload["title"]
        with pytest.raises(todo_db.TodoError, match="title"):
            todo_db.create_from_payload(conn, "tester", payload)

    def test_cli_create_from_stdin(self, tmp_path, monkeypatch, capsys):
        db = str(tmp_path / "cli.sqlite")
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(self.PAYLOAD)))
        assert todo_db.main(["--db", db, "--actor", "t", "create", "--from", "-"]) == 0
        assert "payload-item" in capsys.readouterr().out


class TestActorChain:
    """The actor identity must be resolvable from any agent harness."""

    def test_todo_actor_wins_over_harness_vars(self, monkeypatch):
        monkeypatch.setenv("TODO_ACTOR", "neutral-actor")
        monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session")
        assert todo_db.default_actor() == "neutral-actor"

    def test_non_claude_harness_session_var_is_recognized(self, monkeypatch):
        for var in todo_db.ACTOR_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("CODEX_SESSION_ID", "codex-session")
        assert todo_db.default_actor() == "codex-session"

    def test_fallback_is_user_at_host(self, monkeypatch):
        for var in todo_db.ACTOR_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        assert "@" in todo_db.default_actor()


class TestLintConfigGating:
    """Project-convention lint rules must be per-database configuration."""

    def _mk_pinned(self, conn):
        todo_db.create_item(
            conn,
            "tester",
            item_id="pinned-item",
            title="Item citing point-in-time evidence",
            worktree="spike",
            priority="medium",
            description="Behavior verified on develop @ fc31f3604 with a PASS run.",
            work=[{"id": "w1", "summary": "first unit"}],
        )

    def test_convention_rules_default_on(self, conn):
        self._mk_pinned(conn)
        findings = todo_db.lint_item(conn, "pinned-item")
        assert any("w0" in f for f in findings)
        assert any("scope rules" in f for f in findings)

    def test_rules_can_be_disabled_per_db(self, conn):
        self._mk_pinned(conn)
        todo_db.set_config(conn, "tester", "lint.require_w0_revalidation", "off")
        todo_db.set_config(conn, "tester", "lint.require_scope_rules", "off")
        findings = todo_db.lint_item(conn, "pinned-item")
        assert not any("w0" in f for f in findings)
        assert not any("scope rules" in f for f in findings)

    def test_unknown_config_key_rejected(self, conn):
        with pytest.raises(todo_db.TodoError, match="unknown config key"):
            todo_db.set_config(conn, "tester", "lint.no_such_rule", "off")

    def test_schema_version_not_settable_via_config(self, conn):
        with pytest.raises(todo_db.TodoError, match="unknown config key"):
            todo_db.set_config(conn, "tester", "schema_version", "99")

    def test_invalid_value_rejected(self, conn):
        with pytest.raises(todo_db.TodoError, match="on.*off|off.*on"):
            todo_db.set_config(conn, "tester", "lint.require_w0_revalidation", "maybe")

    def test_config_command_registered(self):
        assert "config" in todo_db._HANDLERS


class TestLintUnrunnableCommands:
    """A rung command that cannot execute exits non-zero on every tree, so it
    vacuously satisfies "must fail on the unfixed tree" — lint must report it."""

    def _mk_with_command(self, conn, item_id, command):
        todo_db.create_item(
            conn,
            "tester",
            item_id=item_id,
            title="Item with a verification rung",
            worktree="spike",
            priority="medium",
            description="A description longer than ten characters.",
            work=[{"id": "w1", "summary": "one unit of work"}],
            verifications=[{"description": "rung", "command": command, "expected": "whatever"}],
        )

    def test_placeholder_command_is_reported_with_its_text(self, conn):
        self._mk_with_command(conn, "ph-item", "<record the four run ids on this item>")
        findings = todo_db.lint_item(conn, "ph-item")
        assert any("cannot execute" in f and "record the four run ids" in f for f in findings)

    def test_shell_parse_failure_is_reported(self, conn):
        self._mk_with_command(conn, "parse-item", "echo 'unterminated")
        findings = todo_db.lint_item(conn, "parse-item")
        assert any("cannot execute" in f and "shell parse" in f for f in findings)

    def test_runnable_command_is_not_flagged(self, conn):
        self._mk_with_command(conn, "ok-item", "uv run -- python -m pytest tests -q")
        assert not any("cannot execute" in f for f in todo_db.lint_item(conn, "ok-item"))

    def test_piped_command_is_not_flagged(self, conn):
        self._mk_with_command(conn, "piped-item", "_project/scripts/todo lint some-item | grep -qi 'pattern'")
        assert not any("cannot execute" in f for f in todo_db.lint_item(conn, "piped-item"))

    def test_multiline_negated_command_is_not_flagged(self, conn):
        self._mk_with_command(conn, "ml-item", "set -e\nmake regen\n! grep -q 'stale' out.log")
        assert not any("cannot execute" in f for f in todo_db.lint_item(conn, "ml-item"))

    def test_rung_without_command_is_not_flagged_as_unrunnable(self, conn):
        self._mk_with_command(conn, "nocmd-item", "uv run -- true")
        todo_db.create_item(
            conn,
            "tester",
            item_id="desc-only-item",
            title="Item whose rung is description-only",
            worktree="spike",
            priority="medium",
            description="A description longer than ten characters.",
            work=[{"id": "w1", "summary": "one unit of work"}],
            verifications=[{"description": "manual acceptance only"}],
        )
        assert not any("cannot execute" in f for f in todo_db.lint_item(conn, "desc-only-item"))


class TestLintUnresolvableScopeAndLadderPaths:
    """Scope globs and rung file arguments must resolve against the working
    tree — with planned-new-file literals staying legal on open items."""

    def _mk_scoped(self, conn, item_id, scope=None, verifications=None):
        todo_db.create_item(
            conn,
            "tester",
            item_id=item_id,
            title="Item exercising scope/path resolution",
            worktree="spike",
            priority="medium",
            description="A description longer than ten characters.",
            work=[{"id": "w1", "summary": "one unit of work"}],
            scope=scope or [],
            verifications=verifications or [],
        )

    def test_resolvable_glob_is_clean(self, conn):
        self._mk_scoped(
            conn,
            "ok-scope",
            scope=[("only_modify", "tests/unit/scripts/test_todo_db_v2.py"), ("only_modify", "_project/scripts/**")],
        )
        assert not any("matches nothing" in f or "does not exist" in f for f in todo_db.lint_item(conn, "ok-scope"))

    def test_open_item_wildcard_glob_matching_nothing_is_legal(self, conn):
        # A prospective allowlist for planned outputs: check-scope fnmatches
        # it against future changed files, so emptiness today is normal.
        self._mk_scoped(conn, "prospective-glob", scope=[("only_modify", "_project/decisions/planned-out-*.md")])
        findings = todo_db.lint_item(conn, "prospective-glob")
        assert not any("planned-out" in f for f in findings)

    def test_settled_item_unresolvable_paths_are_flagged(self):
        item = {
            "state": "done",
            "scope": [
                {"kind": "only_modify", "path_glob": "tests/no-such-dir/**"},
                {"kind": "only_modify", "path_glob": "tests/unit/scripts/test_never_materialized.py"},
            ],
            "verifications": [
                {"seq": 1, "command": "uv run -- python -m pytest tests/unit/scripts/test_never_materialized.py -q"}
            ],
        }
        scope_findings = todo_db._unresolvable_scope_findings(item)
        assert any("resolves to nothing" in f and "tests/no-such-dir/**" in f for f in scope_findings)
        assert any("test_never_materialized" in f for f in scope_findings)
        command_findings = todo_db._unresolvable_command_path_findings(item)
        assert any("resolves to nothing" in f and "test_never_materialized" in f for f in command_findings)

    def test_absolute_paths_are_skipped_even_when_settled(self):
        item = {
            "state": "done",
            "scope": [{"kind": "do_not_modify", "path_glob": "/Users/someone/.claude/projects/**"}],
            "verifications": [],
        }
        assert todo_db._unresolvable_scope_findings(item) == []

    def test_planned_new_file_literal_stays_legal_on_open_item(self, conn):
        self._mk_scoped(conn, "planned-file", scope=[("only_modify", "tests/unit/scripts/test_zq_upcoming_widget.py")])
        findings = todo_db.lint_item(conn, "planned-file")
        assert not any("test_zq_upcoming_widget" in f for f in findings)

    def test_near_miss_literal_is_flagged_on_open_item(self, conn):
        self._mk_scoped(conn, "typo-file", scope=[("only_modify", "tests/unit/scripts/test_todo_db_v3.py")])
        findings = todo_db.lint_item(conn, "typo-file")
        assert any("suspiciously close" in f and "test_todo_db_v3.py" in f for f in findings)

    def test_command_path_argument_is_resolved(self, conn):
        self._mk_scoped(
            conn,
            "bad-cmd-path",
            verifications=[
                {
                    "description": "rung",
                    "command": "uv run -- python -m pytest tests/unit/scripts/test_todo_db_v9000.py -q",
                    "expected": "whatever",
                }
            ],
        )
        findings = todo_db.lint_item(conn, "bad-cmd-path")
        assert any("suspiciously close" in f and "test_todo_db_v9000.py" in f for f in findings)

    def test_command_path_with_pytest_node_id_resolves_file_part(self, conn):
        self._mk_scoped(
            conn,
            "node-id-cmd",
            verifications=[
                {
                    "description": "rung",
                    "command": "uv run -- python -m pytest tests/unit/scripts/test_todo_db_v2.py::TestLintUnresolvableScopeAndLadderPaths -q",
                    "expected": "whatever",
                }
            ],
        )
        findings = todo_db.lint_item(conn, "node-id-cmd")
        assert not any("test_todo_db_v2" in f for f in findings)


class TestLintFalsifiabilityAndScopeCompleteness:
    """A ladder must contain at least one rung that FAILS on the unfixed tree
    (declared in its expected text), and only_modify must not orphan a source
    file's existing test file."""

    def _mk_item(self, conn, item_id, verifications=None, scope=None, category=None):
        # Claim-level checks are per-database opt-in (the shared DB turns them
        # on); enable them here so the tests exercise the checks.
        todo_db.set_config(conn, "tester", "lint.require_falsifiable_rung", "on")
        todo_db.set_config(conn, "tester", "lint.require_scope_test_files", "on")
        todo_db.create_item(
            conn,
            "tester",
            item_id=item_id,
            title="Item exercising claim-level lint",
            worktree="spike",
            priority="medium",
            description="A description longer than ten characters.",
            category=category,
            work=[{"id": "w1", "summary": "one unit of work"}],
            scope=scope or [],
            verifications=verifications or [],
        )

    def test_falsifiability_flags_pass_only_ladder(self, conn):
        self._mk_item(
            conn,
            "pass-only",
            verifications=[
                {"description": "suite green", "command": "uv run -- pytest tests -q", "expected": "all pass"}
            ],
        )
        assert any("falsifiability" in f for f in todo_db.lint_item(conn, "pass-only"))

    def test_falsifiability_accepts_a_gating_rung(self, conn):
        self._mk_item(
            conn,
            "gated",
            verifications=[
                {
                    "description": "defect gate",
                    "command": "uv run -- python -c 'raise SystemExit(1)'",
                    "expected": "exits 1 on an unfixed tree, 0 once fixed",
                },
                {"description": "suite green", "command": "uv run -- pytest tests -q", "expected": "all pass"},
            ],
        )
        assert not any("falsifiability" in f for f in todo_db.lint_item(conn, "gated"))

    def test_falsifiability_broken_rung_does_not_vacuously_satisfy(self, conn):
        # The only rung declaring unfixed-tree failure cannot execute; it exits
        # non-zero on EVERY tree, so it must not count as the gating rung.
        self._mk_item(
            conn,
            "broken-gate",
            verifications=[
                {
                    "description": "defect gate",
                    "command": "<run the real check here>",
                    "expected": "exits 1 on an unfixed tree",
                }
            ],
        )
        findings = todo_db.lint_item(conn, "broken-gate")
        assert any("falsifiability" in f for f in findings)
        assert any("cannot execute" in f for f in findings)

    def test_falsifiability_exempts_flake_tripwires(self, conn):
        self._mk_item(
            conn,
            "flake-watch",
            category="flake",
            verifications=[
                {"description": "still green", "command": "uv run -- pytest tests -q", "expected": "passes"}
            ],
        )
        assert not any("falsifiability" in f for f in todo_db.lint_item(conn, "flake-watch"))

    def test_scope_completeness_flags_omitted_existing_test_file(self, conn):
        self._mk_item(
            conn,
            "orphan-scope",
            scope=[("only_modify", "benchbox/core/results/anonymization.py")],
        )
        findings = todo_db.lint_item(conn, "orphan-scope")
        assert any("scope completeness" in f and "tests/unit/core/results/test_anonymization.py" in f for f in findings)

    def test_scope_completeness_satisfied_by_covering_glob(self, conn):
        self._mk_item(
            conn,
            "covered-scope",
            scope=[
                ("only_modify", "_project/scripts/todo_db.py"),
                ("only_modify", "tests/unit/scripts/test_todo_db.py"),
                ("only_modify", "tests/unit/scripts/test_todo_db_*.py"),
            ],
        )
        assert not any("scope completeness" in f for f in todo_db.lint_item(conn, "covered-scope"))

    def test_scope_completeness_ignores_sources_without_existing_tests(self, conn):
        self._mk_item(
            conn,
            "no-test-yet",
            scope=[("only_modify", "benchbox/core/results/no_such_module.py")],
        )
        assert not any("scope completeness" in f for f in todo_db.lint_item(conn, "no-test-yet"))


class TestInstructiveGateErrors:
    """Every gate refusal must name its recovery command — the error messages
    are the harness-portable instruction layer."""

    def _mk_flow(self, conn):
        todo_db.create_item(
            conn,
            "tester",
            item_id="gate-item",
            title="Gate error message item",
            worktree="spike",
            priority="medium",
            description="A description longer than ten characters.",
            work=[
                {"id": "w1", "summary": "first unit"},
                {"id": "w2", "summary": "second unit", "needs": ["w1"]},
            ],
        )

    def _err(self, fn, *args, **kwargs) -> str:
        with pytest.raises(todo_db.TodoError) as excinfo:
            fn(*args, **kwargs)
        return str(excinfo.value)

    def test_missing_evidence_names_flag(self, conn):
        self._mk_flow(conn)
        assert "--evidence" in self._err(todo_db.done_unit, conn, "t", "gate-item", "w1", " ")

    def test_unfinished_needs_names_done_command(self, conn):
        self._mk_flow(conn)
        message = self._err(todo_db.done_unit, conn, "t", "gate-item", "w2", "evidence")
        assert "todo done" in message

    def test_complete_with_undone_units_names_done_command(self, conn):
        self._mk_flow(conn)
        todo_db.claim_item(conn, "t", "gate-item")
        assert "todo done" in self._err(todo_db.complete_item, conn, "t", "gate-item", None)

    def test_complete_with_open_deferral_names_both_commands(self, conn):
        self._mk_flow(conn)
        todo_db.claim_item(conn, "t", "gate-item")
        todo_db.done_unit(conn, "t", "gate-item", "w1", "ok")
        todo_db.done_unit(conn, "t", "gate-item", "w2", "ok")
        todo_db.defer_work(conn, "t", "gate-item", "later", "reason")
        message = self._err(todo_db.complete_item, conn, "t", "gate-item", None)
        assert "todo promote" in message and "todo dismiss" in message

    def test_drop_with_open_deferral_names_both_commands(self, conn):
        self._mk_flow(conn)
        todo_db.defer_work(conn, "t", "gate-item", "later", "reason")
        message = self._err(todo_db.drop_item, conn, "t", "gate-item", "not needed")
        assert "todo promote" in message and "todo dismiss" in message

    def test_blocked_complete_names_unblock(self, conn):
        self._mk_flow(conn)
        todo_db.claim_item(conn, "t", "gate-item")
        todo_db.done_unit(conn, "t", "gate-item", "w1", "ok")
        todo_db.done_unit(conn, "t", "gate-item", "w2", "ok")
        todo_db.block_item(conn, "t", "gate-item", "waiting")
        assert "todo unblock" in self._err(todo_db.complete_item, conn, "t", "gate-item", None)

    def test_live_claim_conflict_names_sweep_and_ready(self, conn):
        self._mk_flow(conn)
        todo_db.claim_item(conn, "alice", "gate-item")
        message = self._err(todo_db.claim_item, conn, "bob", "gate-item")
        assert "todo sweep-stale" in message and "todo ready" in message

    def test_unmet_dependency_names_ready(self, conn):
        self._mk_flow(conn)
        todo_db.create_item(
            conn,
            "tester",
            item_id="downstream-item",
            title="Depends on the gate item",
            worktree="spike",
            priority="medium",
            description="A description longer than ten characters.",
            deps=["gate-item"],
        )
        assert "todo ready" in self._err(todo_db.claim_item, conn, "t", "downstream-item")

    def test_complete_from_planning_names_claim(self, conn):
        self._mk_flow(conn)
        assert "todo claim" in self._err(todo_db.complete_item, conn, "t", "gate-item", None)
