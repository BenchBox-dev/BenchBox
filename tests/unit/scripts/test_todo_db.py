"""Tests for the local-SQLite TODO tracker spike (_project/scripts/todo_db.py)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


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


@pytest.fixture()
def conn(tmp_path):
    connection = todo_db.connect(tmp_path / "todo.sqlite")
    yield connection
    connection.close()


def _mk(conn, item_id="sample-item", **overrides):
    kwargs = {
        "item_id": item_id,
        "title": "A sample tracked item",
        "worktree": "spike",
        "priority": "medium",
        "description": "A description longer than ten characters.",
    }
    kwargs.update(overrides)
    todo_db.create_item(conn, "tester", **kwargs)
    return item_id


class TestSchemaAndCreate:
    def test_connect_initializes_schema_version(self, conn):
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        assert int(row["value"]) == todo_db.SCHEMA_VERSION

    def test_create_and_get_roundtrip(self, conn):
        _mk(
            conn,
            work=[
                {"id": "w1", "summary": "first unit", "needs": []},
                {"id": "w2", "summary": "second unit", "needs": ["w1"]},
            ],
            scope=[("only_modify", "benchbox/core/*")],
            verifications=[{"description": "fast tests", "command": "true"}],
            preserves=["CLI --help output unchanged"],
        )
        item = todo_db.get_item(conn, "sample-item")
        assert item["state"] == "planning"
        assert [u["wid"] for u in item["work"]] == ["w1", "w2"]
        assert item["work"][1]["needs"] == ["w1"]
        assert item["scope"] == [{"kind": "only_modify", "path_glob": "benchbox/core/*"}]
        assert item["preserves"] == ["CLI --help output unchanged"]

    def test_invalid_priority_rejected(self, conn):
        with pytest.raises(todo_db.TodoError, match="invalid priority"):
            _mk(conn, priority="urgent")

    def test_invalid_slug_rejected(self, conn):
        with pytest.raises(todo_db.TodoError, match="slug"):
            _mk(conn, item_id="Bad_Slug")

    def test_junk_work_unit_id_rejected(self, conn):
        # Guards the CHECK-constraint fix: 'w1abc' must not be accepted.
        with pytest.raises(todo_db.TodoError, match="invalid work-unit id"):
            _mk(conn, work=[{"id": "w1abc", "summary": "junk id unit"}])

    def test_duplicate_id_rejected(self, conn):
        _mk(conn)
        with pytest.raises(todo_db.TodoError, match="cannot create"):
            _mk(conn)


class TestClaimAndLease:
    def test_claim_moves_planning_to_active(self, conn):
        _mk(conn)
        order = todo_db.claim_item(conn, "alice", "sample-item")
        assert order["state"] == "active"
        assert order["claimed_by"] == "alice"

    def test_second_actor_cannot_claim_live_lease(self, conn):
        _mk(conn)
        todo_db.claim_item(conn, "alice", "sample-item")
        with pytest.raises(todo_db.TodoError, match="claimed by 'alice'"):
            todo_db.claim_item(conn, "bob", "sample-item")

    def test_expired_lease_is_claimable(self, conn):
        _mk(conn)
        todo_db.claim_item(conn, "alice", "sample-item")
        conn.execute("UPDATE items SET claimed_at = '2020-01-01T00:00:00Z' WHERE id='sample-item'")
        conn.commit()
        order = todo_db.claim_item(conn, "bob", "sample-item")
        assert order["claimed_by"] == "bob"

    def test_claim_blocked_by_unmet_dependency(self, conn):
        _mk(conn, item_id="upstream-item")
        _mk(conn, item_id="downstream-item", deps=["upstream-item"])
        with pytest.raises(todo_db.TodoError, match="unmet dependencies"):
            todo_db.claim_item(conn, "alice", "downstream-item")

    def test_sweep_stale_releases_expired_claims(self, conn):
        _mk(conn)
        todo_db.claim_item(conn, "alice", "sample-item")
        conn.execute("UPDATE items SET claimed_at = '2020-01-01T00:00:00Z' WHERE id='sample-item'")
        conn.commit()
        assert todo_db.sweep_stale(conn, "sweeper") == ["sample-item"]
        item = todo_db.get_item(conn, "sample-item")
        assert item["claimed_by"] is None


class TestWorkUnits:
    def test_done_requires_evidence(self, conn):
        _mk(conn, work=[{"id": "w1", "summary": "first unit"}])
        with pytest.raises(todo_db.TodoError, match="evidence"):
            todo_db.done_unit(conn, "tester", "sample-item", "w1", "  ")

    def test_done_respects_needs_order(self, conn):
        _mk(
            conn,
            work=[
                {"id": "w1", "summary": "first unit"},
                {"id": "w2", "summary": "second unit", "needs": ["w1"]},
            ],
        )
        todo_db.claim_item(conn, "tester", "sample-item")
        with pytest.raises(todo_db.TodoError, match="needs unfinished"):
            todo_db.done_unit(conn, "tester", "sample-item", "w2", "ran tests")
        todo_db.done_unit(conn, "tester", "sample-item", "w1", "ran tests")
        todo_db.done_unit(conn, "tester", "sample-item", "w2", "ran tests")

    def test_work_cycle_rejected(self, conn):
        with pytest.raises(todo_db.TodoError, match="cycle"):
            _mk(
                conn,
                work=[
                    {"id": "w1", "summary": "first unit", "needs": ["w2"]},
                    {"id": "w2", "summary": "second unit", "needs": ["w1"]},
                ],
            )

    def test_ready_units_split(self, conn):
        _mk(
            conn,
            work=[
                {"id": "w1", "summary": "first unit"},
                {"id": "w2", "summary": "second unit", "needs": ["w1"]},
            ],
        )
        ready, blocked = todo_db.ready_units(conn, "sample-item")
        assert [u["wid"] for u in ready] == ["w1"]
        assert [u["wid"] for u in blocked] == ["w2"]


class TestDeferralGate:
    def test_complete_refuses_open_deferral(self, conn):
        _mk(conn, work=[{"id": "w1", "summary": "first unit"}])
        todo_db.claim_item(conn, "tester", "sample-item")
        todo_db.done_unit(conn, "tester", "sample-item", "w1", "ran tests")
        todo_db.defer_work(conn, "tester", "sample-item", "follow-up work", "out of scope")
        with pytest.raises(todo_db.TodoError, match="unresolved deferrals"):
            todo_db.complete_item(conn, "tester", "sample-item", 123)

    def test_promote_then_complete(self, conn):
        _mk(conn, work=[{"id": "w1", "summary": "first unit"}])
        todo_db.claim_item(conn, "tester", "sample-item")
        todo_db.done_unit(conn, "tester", "sample-item", "w1", "ran tests")
        deferral_id = todo_db.defer_work(conn, "tester", "sample-item", "follow-up work", "out of scope")
        todo_db.promote_deferral(conn, "tester", deferral_id, new_item_id="follow-up-item")
        todo_db.complete_item(conn, "tester", "sample-item", 123)
        parent = todo_db.get_item(conn, "sample-item")
        child = todo_db.get_item(conn, "follow-up-item")
        assert parent["state"] == "done"
        assert parent["completed_pr"] == 123
        assert child["state"] == "planning"
        assert "deferral" in child["description"]

    def test_dismiss_then_complete(self, conn):
        _mk(conn)
        todo_db.claim_item(conn, "tester", "sample-item")
        deferral_id = todo_db.defer_work(conn, "tester", "sample-item", "follow-up work", "out of scope")
        todo_db.dismiss_deferral(conn, "tester", deferral_id, "obsoleted by redesign")
        todo_db.complete_item(conn, "tester", "sample-item", None)
        assert todo_db.get_item(conn, "sample-item")["state"] == "done"

    def test_drop_refuses_open_deferral(self, conn):
        _mk(conn)
        todo_db.defer_work(conn, "tester", "sample-item", "follow-up work", "out of scope")
        with pytest.raises(todo_db.TodoError, match="unresolved deferral"):
            todo_db.drop_item(conn, "tester", "sample-item", "no longer needed")


class TestLifecycle:
    def test_complete_refuses_undone_units(self, conn):
        _mk(conn, work=[{"id": "w1", "summary": "first unit"}])
        todo_db.claim_item(conn, "tester", "sample-item")
        with pytest.raises(todo_db.TodoError, match="not done"):
            todo_db.complete_item(conn, "tester", "sample-item", None)

    def test_complete_from_planning_is_illegal(self, conn):
        _mk(conn)
        with pytest.raises(todo_db.TodoError, match="illegal transition"):
            todo_db.complete_item(conn, "tester", "sample-item", None)

    def test_blocked_item_cannot_complete(self, conn):
        _mk(conn)
        todo_db.claim_item(conn, "tester", "sample-item")
        todo_db.block_item(conn, "tester", "sample-item", "waiting on upstream")
        with pytest.raises(todo_db.TodoError, match="while blocked"):
            todo_db.complete_item(conn, "tester", "sample-item", None)

    def test_item_dep_cycle_rejected(self, conn):
        _mk(conn, item_id="first-item")
        _mk(conn, item_id="second-item", deps=["first-item"])
        with pytest.raises(todo_db.TodoError, match="cycle"):
            with conn:
                todo_db.add_item_dep(conn, "first-item", "second-item")

    def test_dangling_dep_rejected(self, conn):
        _mk(conn)
        with pytest.raises(todo_db.TodoError, match="missing item"):
            with conn:
                todo_db.add_item_dep(conn, "sample-item", "no-such-item")

    def test_ready_excludes_unmet_then_includes(self, conn):
        _mk(conn, item_id="upstream-item", work=[{"id": "w1", "summary": "first unit"}])
        _mk(conn, item_id="downstream-item", deps=["upstream-item"])
        ready_ids = [i["id"] for i in todo_db.ready_items(conn, "tester")]
        assert "downstream-item" not in ready_ids
        todo_db.claim_item(conn, "tester", "upstream-item")
        todo_db.done_unit(conn, "tester", "upstream-item", "w1", "ran tests")
        todo_db.complete_item(conn, "tester", "upstream-item", None)
        ready_ids = [i["id"] for i in todo_db.ready_items(conn, "tester")]
        assert "downstream-item" in ready_ids

    def test_events_recorded(self, conn):
        _mk(conn)
        todo_db.claim_item(conn, "tester", "sample-item")
        actions = [row["action"] for row in conn.execute("SELECT action FROM events")]
        assert actions == ["create", "claim"]


class TestScopeAndLint:
    def test_scope_matches_absolute_cross_repository_globs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rules = [{"kind": "only_modify", "path_glob": f"{tmp_path}/**"}]
        assert todo_db.check_paths(["src/todo_db/cli.py"], rules) == []

    def test_check_paths_only_modify(self):
        rules = [{"kind": "only_modify", "path_glob": "benchbox/core/*"}]
        violations = todo_db.check_paths(["benchbox/core/foo.py", "docs/guide.md"], rules)
        assert violations == ["docs/guide.md: outside only_modify allowlist"]

    def test_check_paths_do_not_modify(self):
        rules = [{"kind": "do_not_modify", "path_glob": "benchbox/core/equivalence/*"}]
        violations = todo_db.check_paths(["benchbox/core/equivalence/rules.py"], rules)
        assert violations == ["benchbox/core/equivalence/rules.py: matches do_not_modify"]

    def test_lint_flags_missing_verification_and_scope(self, conn):
        _mk(conn, work=[{"id": "w1", "summary": "first unit"}])
        findings = todo_db.lint_item(conn, "sample-item")
        assert any("verification" in f for f in findings)
        assert any("scope rules" in f for f in findings)

    def test_lint_flags_unpinned_evidence(self, conn):
        _mk(
            conn,
            description="Behavior verified on develop @ fc31f3604 with a PASS run.",
            work=[{"id": "w1", "summary": "first unit"}],
        )
        findings = todo_db.lint_item(conn, "sample-item")
        assert any("w0 re-validation" in f for f in findings)

    def test_lint_clean_item(self, conn):
        _mk(
            conn,
            description="Behavior verified on develop @ fc31f3604 with a PASS run.",
            work=[
                {"id": "w0", "summary": "re-validate evidence at HEAD"},
                {"id": "w1", "summary": "first unit"},
            ],
            scope=[("only_modify", "benchbox/core/*")],
            verifications=[{"description": "fast tests", "command": "true"}],
        )
        assert todo_db.lint_item(conn, "sample-item") == []


class TestVerifyRun:
    def test_verify_run_pass_and_fail(self, conn):
        _mk(
            conn,
            verifications=[
                {"description": "always passes", "command": "true"},
                {"description": "always fails", "command": "false"},
            ],
        )
        todo_db.claim_item(conn, "tester", "sample-item")
        result, _ = todo_db.run_verification(conn, "tester", "sample-item", 1)
        assert result == "pass"
        result, _ = todo_db.run_verification(conn, "tester", "sample-item", 2)
        assert result == "fail"
        rows = conn.execute(
            "SELECT seq, last_result FROM verifications WHERE item_id='sample-item' ORDER BY seq"
        ).fetchall()
        assert [(r["seq"], r["last_result"]) for r in rows] == [(1, "pass"), (2, "fail")]

    def test_verify_rung_lock_contention_is_indeterminate(self, conn, tmp_path, monkeypatch):
        """A lock timeout records an environmental non-verdict, not a failure."""
        fcntl = pytest.importorskip("fcntl")
        _mk(conn, verifications=[{"description": "blocked", "command": "true"}])
        todo_db.claim_item(conn, "tester", "sample-item")
        assert todo_db.run_verification(conn, "tester", "sample-item", 1)[0] == "pass"
        before = conn.execute(
            "SELECT last_run, last_result FROM verifications WHERE item_id='sample-item' AND seq=1"
        ).fetchone()
        lock_dir = tmp_path / "lock"
        lock_dir.mkdir()
        lock_path = lock_dir / "test.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setenv("BENCHBOX_TEST_LOCK_DIR", str(lock_dir))
        monkeypatch.setenv("BENCHBOX_VERIFY_LOCK_TIMEOUT", "0")
        monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
        try:
            result, output = todo_db.run_verification(conn, "tester", "sample-item", 1)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

        assert result == "indeterminate"
        assert "verification command was not run" in output
        row = conn.execute(
            "SELECT last_run, last_result FROM verifications WHERE item_id='sample-item' AND seq=1"
        ).fetchone()
        assert (row["last_run"], row["last_result"]) == (before["last_run"], before["last_result"])
        event = conn.execute("SELECT detail FROM events WHERE action='verify' ORDER BY seq DESC LIMIT 1").fetchone()
        assert '"result": "indeterminate"' in event["detail"]

    def test_verify_run_ignores_stale_lock_diagnostic(self, conn, tmp_path, monkeypatch):
        """A dead owner's leftover diagnostic file does not block acquisition."""
        _mk(conn, verifications=[{"description": "passes", "command": "true"}])
        todo_db.claim_item(conn, "tester", "sample-item")
        lock_dir = tmp_path / "lock"
        lock_dir.mkdir()
        (lock_dir / "test.lock").write_text("pid:999999 started:never\n", encoding="utf-8")
        monkeypatch.setenv("BENCHBOX_TEST_LOCK_DIR", str(lock_dir))

        result, _ = todo_db.run_verification(conn, "tester", "sample-item", 1)

        assert result == "pass"

    def test_verify_expected_is_human_acceptance_text(self, conn):
        """`expected` documents a rung; it must never be graded.

        Deliberate: 95% of the corpus's `expected` strings are prose like
        "All tests pass" that would never match command output literally, so
        evaluating them would fail almost every verification in the tracker.
        Rungs assert via their command's exit status instead -- lint_item
        flags the ones that cannot (see TestUnsatisfiableVerificationLint).
        """
        _mk(
            conn,
            verifications=[
                {"description": "passes", "command": "true", "expected": "human-readable criterion"},
                {"description": "fails", "command": "false", "expected": "human-readable criterion"},
            ],
        )
        todo_db.claim_item(conn, "tester", "sample-item")
        assert todo_db.run_verification(conn, "tester", "sample-item", 1)[0] == "pass"
        assert todo_db.run_verification(conn, "tester", "sample-item", 2)[0] == "fail"

    def test_verify_expected_is_rendered_in_work_order_and_listing(self, conn, capsys):
        _mk(
            conn,
            verifications=[{"description": "passes", "command": "true", "expected": "human-readable criterion"}],
        )

        todo_db._print_work_order(todo_db.work_order(conn, "sample-item"))
        assert "expected: human-readable criterion" in capsys.readouterr().out

        todo_db._cmd_verify(conn, "tester", SimpleNamespace(id="sample-item", run=None))
        assert "expected: human-readable criterion" in capsys.readouterr().out


class TestExport:
    def test_export_deterministic(self, conn, tmp_path):
        _mk(conn, work=[{"id": "w1", "summary": "first unit"}])
        _mk(conn, item_id="second-item")
        first_dir, second_dir = tmp_path / "a", tmp_path / "b"
        todo_db.write_export(conn, first_dir)
        todo_db.write_export(conn, second_dir)
        assert (first_dir / "items.jsonl").read_text() == (second_dir / "items.jsonl").read_text()
        assert "second-item" in (first_dir / "index.md").read_text()


class TestHostedRow:
    """_HostedRow is the libsql/Turso stand-in for sqlite3.Row (see its
    docstring in todo_db.py). libsql's cursor.description has been observed
    to report a keyword column name ("instead", via INSTEAD OF triggers)
    back in uppercase, while local sqlite3 preserves the lowercase SELECT
    casing. sqlite3.Row is case-insensitive on name access, so _HostedRow
    must be too, or hosted-only KeyErrors sneak past local-only test runs."""

    def test_case_insensitive_access_and_dict_roundtrip(self):
        r = todo_db._HostedRow(["dont", "why", "INSTEAD"], ("a", "b", "c"))
        assert r["instead"] == "c"
        assert r["INSTEAD"] == "c"
        assert dict(r) == {"dont": "a", "why": "b", "instead": "c"}
        assert r[2] == "c"
        assert list(r.keys()) == ["dont", "why", "instead"]

    def test_missing_column_raises_index_error(self):
        r = todo_db._HostedRow(["dont", "why", "instead"], ("a", "b", "c"))
        with pytest.raises(IndexError, match="no such column: nope"):
            r["nope"]


class TestPrintWorkOrderHostedRegression:
    """Regression coverage for the `todo claim` crash on the hosted backend:
    get_item() builds anti_patterns entries via dict(row); on hosted, an
    unfixed _HostedRow yielded the key "INSTEAD" (uppercase) instead of
    "instead", and _print_work_order's `anti['instead']` lookup raised
    KeyError. The state transition itself succeeded — only the banner print
    crashed — so this must exercise the print path directly, not just the
    lifecycle functions (which are backend-agnostic and were never broken)."""

    def test_anti_pattern_from_hosted_row_does_not_raise(self, capsys):
        hosted_row = todo_db._HostedRow(
            ["dont", "why", "INSTEAD"],
            ("skip the fast tests", "flakiness hides real regressions", "run make test-fast locally first"),
        )
        order = {
            "id": "sample-item",
            "priority": "medium",
            "title": "A sample tracked item",
            "state": "active",
            "worktree": "spike",
            "claimed_by": "tester",
            "blocked_reason": None,
            "scope": [],
            "preserves": [],
            "anti_patterns": [dict(hosted_row)],
            "verifications": [],
            "deferrals": [],
        }
        todo_db._print_work_order(order)  # must not raise KeyError
        out = capsys.readouterr().out
        assert "instead: run make test-fast locally first" in out


class TestAntiPatternParse:
    def test_full_form(self):
        dont, why, instead = todo_db._parse_anti_pattern(
            "DO NOT add a new base class - because the hierarchy is deep - extend the mixin instead"
        )
        assert dont == "add a new base class"
        assert why == "the hierarchy is deep"
        assert instead == "extend the mixin instead"

    def test_double_dash_no_instead(self):
        dont, why, instead = todo_db._parse_anti_pattern(
            "DO NOT exclude the 4 queries unconditionally -- reference-seed runs must keep validating them."
        )
        assert dont == "exclude the 4 queries unconditionally"
        assert why == "reference-seed runs must keep validating them."
        assert instead == "(not specified)"


class TestImporter:
    SAMPLE = textwrap.dedent(
        """
        id: sample-import
        title: "Imported sample item"
        worktree: spike
        priority: High
        status: Not Started
        category: "Core Functionality"
        description: |
          Imported from YAML for the spike evaluation.
        work:
          - id: w1
            summary: "First imported unit"
            status: pending
            needs: []
          - id: w2
            summary: "Second imported unit"
            status: pending
            needs: [w1]
        deferred:
          - summary: "Deferred follow-up"
            reason: "Out of scope for the import"
        scope_limit:
          only_modify:
            - benchbox/core/*
        must_preserve:
          - "Existing adapters keep passing"
        verification:
          - description: "Run the fast suite"
            command: "make test-fast"
        metadata:
          created_date: 2026-01-15
        """
    )

    def _import(self, conn, tmp_path, content, filename="sample-import.yaml"):
        tree = tmp_path / "TODO" / "spike" / "planning"
        tree.mkdir(parents=True)
        (tree / filename).write_text(content, encoding="utf-8")
        return todo_db.import_yaml_tree(conn, "importer", tmp_path / "TODO")

    def test_import_full_item(self, conn, tmp_path):
        report = self._import(conn, tmp_path, self.SAMPLE)
        assert report["imported"] == ["sample-import"]
        assert report["skipped"] == []
        item = todo_db.get_item(conn, "sample-import")
        assert item["priority"] == "high"
        assert item["state"] == "planning"
        assert item["category"] == "Core Functionality"
        assert item["created_at"] == "2026-01-15T00:00:00Z"
        assert [u["wid"] for u in item["work"]] == ["w1", "w2"]
        assert item["work"][1]["needs"] == ["w1"]
        assert item["scope"] == [{"kind": "only_modify", "path_glob": "benchbox/core/*"}]
        assert len(item["deferrals"]) == 1
        assert item["deferrals"][0]["resolution"] == "open"
        assert item["verifications"][0]["command"] == "make test-fast"

    def test_import_completed_in_open_tree_becomes_done_with_drift_warning(self, conn, tmp_path):
        content = self.SAMPLE.replace("status: Not Started", "status: Completed")
        report = self._import(conn, tmp_path, content)
        assert report["imported"] == ["sample-import"]
        assert any("tree/status drift" in warning for warning in report["warnings"])
        assert todo_db.get_item(conn, "sample-import")["state"] == "done"

    def test_import_blocked_status_maps_to_annotation(self, conn, tmp_path):
        content = self.SAMPLE.replace("status: Not Started", "status: Blocked")
        self._import(conn, tmp_path, content)
        item = todo_db.get_item(conn, "sample-import")
        assert item["state"] == "active"
        assert "Blocked" in item["blocked_reason"]

    def test_import_dangling_dep_warns(self, conn, tmp_path):
        content = self.SAMPLE + "deps:\n  needs: [not-imported-item]\n"
        report = self._import(conn, tmp_path, content)
        assert any("dangling" in warning for warning in report["warnings"])
        assert report["counts"]["deps_dangling"] == 1
        assert todo_db.get_item(conn, "sample-import")["deps"] == []


class TestArchiveImport:
    ARCHIVED = textwrap.dedent(
        """
        id: archived-item
        title: "An archived item"
        worktree: spike
        priority: Medium
        status: Completed
        completed_date: "2025-11-29"
        description: |
          Finished work kept for the record.
        deferred:
          - summary: "Buried follow-up from the archive"
            reason: "Was never promoted"
        """
    )

    LEGACY = textwrap.dedent(
        """
        id: legacy-item
        title: "A legacy archive entry"
        worktree: spike
        priority: Medium
        status: Completed
        description: |
          Legacy entry using the deprecated structures.
        tasks:
          phases:
            - name: "Phase 1"
        dependencies:
          blocked_by:
            - "_project/DONE/spike/archived-item.yaml"
        """
    )

    def _import_both(self, conn, tmp_path, open_files=(), done_files=()):
        todo_tree = tmp_path / "TODO" / "spike" / "planning"
        done_tree = tmp_path / "DONE" / "spike"
        todo_tree.mkdir(parents=True)
        done_tree.mkdir(parents=True)
        for name, content in open_files:
            (todo_tree / name).write_text(content, encoding="utf-8")
        for name, content in done_files:
            (done_tree / name).write_text(content, encoding="utf-8")
        return todo_db.import_yaml_tree(conn, "importer", tmp_path / "TODO", done_dir=tmp_path / "DONE")

    def test_archive_item_imported_done_with_open_deferral(self, conn, tmp_path):
        report = self._import_both(conn, tmp_path, done_files=[("archived-item.yaml", self.ARCHIVED)])
        assert report["counts"]["done_items"] == 1
        item = todo_db.get_item(conn, "archived-item")
        assert item["state"] == "done"
        assert item["completed_at"] == "2025-11-29T00:00:00Z"
        assert item["deferrals"][0]["resolution"] == "open"

    def test_legacy_structures_counted_not_fatal(self, conn, tmp_path):
        report = self._import_both(
            conn,
            tmp_path,
            done_files=[("archived-item.yaml", self.ARCHIVED), ("legacy-item.yaml", self.LEGACY)],
        )
        assert report["counts"]["legacy_tasks_structure"] == 1
        assert report["counts"]["legacy_dependencies_field"] == 1
        # blocked_by path resolved to the sibling archive item.
        assert todo_db.get_item(conn, "legacy-item")["deps"] == ["archived-item"]

    def test_open_dep_on_archived_item_resolves_and_is_ready(self, conn, tmp_path):
        open_item = TestImporter.SAMPLE + "deps:\n  needs: [archived-item]\n"
        report = self._import_both(
            conn,
            tmp_path,
            open_files=[("sample-import.yaml", open_item)],
            done_files=[("archived-item.yaml", self.ARCHIVED)],
        )
        assert report["counts"]["deps_resolved"] == 1
        assert todo_db.get_item(conn, "sample-import")["deps"] == ["archived-item"]
        # The archived dep is state=done, so the open item is claimable.
        ready_ids = [i["id"] for i in todo_db.ready_items(conn, "importer")]
        assert "sample-import" in ready_ids

    def test_id_collision_gets_archive_suffix(self, conn, tmp_path):
        clash = self.ARCHIVED.replace("id: archived-item", "id: sample-import")
        report = self._import_both(
            conn,
            tmp_path,
            open_files=[("sample-import.yaml", TestImporter.SAMPLE)],
            done_files=[("sample-import.yaml", clash)],
        )
        assert any("already imported" in warning for warning in report["warnings"])
        assert todo_db.get_item(conn, "sample-import")["state"] == "planning"
        assert todo_db.get_item(conn, "sample-import-archived")["state"] == "done"

    def test_archive_missing_title_description_fallbacks(self, conn, tmp_path):
        minimal = "id: bare-item\nworktree: spike\nstatus: Completed\n"
        report = self._import_both(conn, tmp_path, done_files=[("bare-item.yaml", minimal)])
        assert report["counts"]["done_items"] == 1
        item = todo_db.get_item(conn, "bare-item")
        assert "Archived item" in item["title"]
        assert "no description recorded" in item["description"]


class TestTerminalDeferralGuard:
    def test_defer_rejected_on_done_item(self, conn):
        todo_db.create_item(
            conn,
            "tester",
            item_id="finished-item",
            title="Already finished item",
            worktree="spike",
            priority="medium",
            description="A description longer than ten characters.",
            state="done",
            completed_at="2026-01-01T00:00:00Z",
        )
        with pytest.raises(todo_db.TodoError, match="terminal items"):
            todo_db.defer_work(conn, "tester", "finished-item", "late follow-up", "found later")

    def test_importer_bypass_allows_terminal(self, conn):
        todo_db.create_item(
            conn,
            "tester",
            item_id="finished-item",
            title="Already finished item",
            worktree="spike",
            priority="medium",
            description="A description longer than ten characters.",
            state="done",
        )
        deferral_id = todo_db.defer_work(
            conn, "importer", "finished-item", "historical deferral", "archive record", allow_terminal=True
        )
        assert deferral_id == 1

    def test_completed_pr_requires_done_state(self, conn):
        with pytest.raises(todo_db.TodoError, match="only valid with state='done'"):
            todo_db.create_item(
                conn,
                "tester",
                item_id="bad-item",
                title="Planning item with completion metadata",
                worktree="spike",
                priority="medium",
                description="A description longer than ten characters.",
                completed_pr=99,
            )


class TestCliSmoke:
    def test_end_to_end_via_main(self, tmp_path, capsys):
        db = str(tmp_path / "cli.sqlite")
        base = ["--db", db, "--actor", "cli-test"]
        assert todo_db.main(base + ["init"]) == 0
        assert (
            todo_db.main(
                base
                + [
                    "create",
                    "cli-item",
                    "--title",
                    "CLI exercised item",
                    "--worktree",
                    "spike",
                    "--priority",
                    "high",
                    "--description",
                    "Created through the CLI surface.",
                    "--work",
                    "w1:do the thing",
                    "--verify",
                    "fast::true",
                    "--only-modify",
                    "benchbox/*",
                ]
            )
            == 0
        )
        assert todo_db.main(base + ["claim", "cli-item"]) == 0
        out = capsys.readouterr().out
        assert "ready units" in out
        assert "only_modify: benchbox/*" in out
        assert todo_db.main(base + ["done", "cli-item", "w1", "--evidence", "ran it"]) == 0
        assert todo_db.main(base + ["defer", "cli-item", "--summary", "later work", "--reason", "out of scope"]) == 0
        # Gate fires through the CLI too.
        assert todo_db.main(base + ["complete", "cli-item"]) == 2
        assert todo_db.main(base + ["dismiss", "1", "--reason", "not needed"]) == 0
        assert todo_db.main(base + ["complete", "cli-item", "--pr", "42"]) == 0
        assert todo_db.main(base + ["stats"]) == 0
        assert '"done": 1' in capsys.readouterr().out


class TestUnsatisfiableVerificationLint:
    """Rungs whose command cannot express their expectation.

    A rung is graded only on exit status, so an expectation naming a string
    that must be ABSENT describes something the exit code cannot encode. Such
    a rung reports fail forever, however correct the implementation is --
    confirmed twice in practice (a `--strict` checker whose correct behaviour
    is a non-zero exit, and an `open http://...` command that always exits 0).
    """

    def _lint(self, conn, command, expected):
        _mk(conn, verifications=[{"description": "d", "command": command, "expected": expected}])
        return [f for f in todo_db.lint_item(conn, "sample-item") if "expects output that must be absent" in f]

    def test_flags_absent_output_expectation_with_a_bare_command(self, conn):
        """The real case: exit status cannot show a string was not printed."""
        findings = self._lint(
            conn,
            "uv run -- python _project/scripts/timing_policy_check.py --strict",
            "reports a tooling/environment error, not 'Fast lane policy violations: 4'",
        )
        assert findings, "expected the unsatisfiable-rung finding"
        assert "self-asserting" in findings[0]

    def test_flags_a_command_that_can_never_fail(self, conn):
        """`open URL` exits 0 regardless of what the page renders."""
        assert self._lint(
            conn,
            "open http://localhost:5173/results/does-not-exist/",
            "Page renders the NotFound component, not 'DOES-NOT-EXIST Results'",
        )

    @pytest.mark.parametrize(
        "command",
        [
            "cmd 2>&1 | grep -q FAST_LANE_ENVIRONMENT_ERROR",
            "! cmd --strict",
            "cmd && test -f out.json",
            "uv run -- python script.py --check",
        ],
    )
    def test_does_not_flag_a_self_asserting_command(self, conn, command):
        """Composing the assertion into the command is the fix, not a finding."""
        assert not self._lint(conn, command, "reports the error, not 'policy violations'")

    def test_does_not_treat_setup_prose_as_an_absent_output_assertion(self, conn):
        """Phrases such as 'instead of failing setup' describe exit status, not output."""
        assert not self._lint(
            conn,
            "uv run -- python scripts/check_setup.py",
            "completes instead of failing setup",
        )

    @pytest.mark.parametrize(
        "command",
        [
            "producer | jq '.forbidden == null'",
            "producer | jq --arg expected null '.forbidden == $expected'",
        ],
    )
    def test_flags_jq_without_exit_status_for_absent_output(self, conn, command):
        """Bare jq reports a result but still exits zero for false/null output."""
        assert self._lint(conn, command, "does not contain 'forbidden'")

    @pytest.mark.parametrize(
        "command",
        [
            "producer | jq -e '.forbidden == null'",
            "producer | jq --exit-status '.forbidden == null'",
        ],
    )
    def test_does_not_flag_jq_with_exit_status_for_absent_output(self, conn, command):
        """jq's exit-status modes make the output assertion gradeable."""
        assert not self._lint(conn, command, "does not contain 'forbidden'")

    @pytest.mark.parametrize(
        "expected",
        ["All tests pass", "Exit code 0", "No errors", "Adapter lifecycle tests pass."],
    )
    def test_does_not_flag_ordinary_prose_expectations(self, conn, expected):
        """Regression guard: the corpus is 95% prose paired with plain commands.

        Calibrated against the live tracker -- this rule flags 8 of 2958
        verifications. A rule that fired on ordinary prose would be noise on
        thousands of items and would be ignored.
        """
        assert not self._lint(conn, "uv run -- python -m pytest -m fast -q", expected)

    def test_does_not_flag_a_rung_with_no_command(self, conn):
        """A command-less rung is already reported by a different finding."""
        assert not self._lint(conn, None, "must not print 'boom'")

    def test_clean_item_still_lints_clean(self, conn):
        """The new rule must not disturb an otherwise healthy item."""
        _mk(
            conn,
            work=[{"id": "w0", "summary": "do it"}],
            scope=[("only_modify", "benchbox/core/*")],
            verifications=[{"description": "fast tests", "command": "true", "expected": "All tests pass"}],
        )
        assert todo_db.lint_item(conn, "sample-item") == []


class TestPromoteCarriesGuardrails:
    """Promoted items must not be born without scope, ladder or work units."""

    def _defer(self, conn):
        _mk(conn)
        return todo_db.defer_work(conn, "tester", "sample-item", summary="found a thing", reason="out of scope here")

    def test_promote_accepts_scope_and_verifications(self, conn):
        deferral_id = self._defer(conn)
        todo_db.promote_deferral(
            conn,
            "tester",
            deferral_id,
            new_item_id="promoted-with-guardrails",
            scope=[("only_modify", "benchbox/utils/*")],
            verifications=[{"description": "fast tests", "command": "true", "expected": "exit 0"}],
            preserves=["nothing else changes"],
        )
        item = todo_db.get_item(conn, "promoted-with-guardrails")
        assert item["scope"] == [{"kind": "only_modify", "path_glob": "benchbox/utils/*"}]
        assert [v["description"] for v in item["verifications"]] == ["fast tests"]
        assert item["preserves"] == ["nothing else changes"]

    def test_promote_without_guardrails_still_works(self, conn):
        """Backwards compatible: the flags are optional."""
        deferral_id = self._defer(conn)
        todo_db.promote_deferral(conn, "tester", deferral_id, new_item_id="promoted-bare")
        item = todo_db.get_item(conn, "promoted-bare")
        assert item["scope"] == []
        assert item["verifications"] == []


class TestCheckScopeReportsWhatItActuallyChecked:
    """`check-scope` must not claim a pass it never performed.

    An item with no scope rules has nothing to violate, so `check_paths()`
    returned clean and the command printed "scope OK" over a diff it had never
    looked at. Every item promoted before the guardrail flags existed has
    empty scope, so this was the common case, not an edge case.
    """

    def _run(self, conn, monkeypatch, item_id, files, strict=False):
        monkeypatch.setattr(todo_db, "changed_files", lambda base: files)
        return todo_db._cmd_check_scope(conn, "tester", SimpleNamespace(id=item_id, base=None, strict=strict))

    def test_no_rules_reports_unchecked_not_ok(self, conn, monkeypatch, capsys):
        """The headline: no rules must never render as OK."""
        _mk(conn)
        rc = self._run(conn, monkeypatch, "sample-item", ["benchbox/anything.py", "docs/x.md"])
        out = capsys.readouterr().out
        assert "SCOPE_UNCHECKED" in out
        assert "scope OK" not in out
        assert "2 changed file(s) were not checked" in out
        assert rc == 0  # default stays non-blocking for existing callers

    def test_no_rules_under_strict_exits_non_zero(self, conn, monkeypatch, capsys):
        """Opt-in gate for callers that want an unchecked item to fail."""
        _mk(conn)
        assert self._run(conn, monkeypatch, "sample-item", ["benchbox/x.py"], strict=True) == 1
        assert "SCOPE_UNCHECKED" in capsys.readouterr().out

    def test_strict_is_optional_for_programmatic_callers(self, conn, monkeypatch, capsys):
        """A namespace without --strict must not raise (getattr, not attribute)."""
        _mk(conn)
        monkeypatch.setattr(todo_db, "changed_files", lambda base: ["a.py"])
        assert todo_db._cmd_check_scope(conn, "tester", SimpleNamespace(id="sample-item", base=None)) == 0

    def test_scoped_item_compliant_still_reports_ok(self, conn, monkeypatch, capsys):
        """Must-preserve: an item WITH rules keeps its pass behaviour."""
        _mk(conn, scope=[("only_modify", "benchbox/core/*")])
        rc = self._run(conn, monkeypatch, "sample-item", ["benchbox/core/thing.py"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "scope OK (1 changed file(s))" in out
        assert "SCOPE_UNCHECKED" not in out

    def test_scoped_item_violation_still_fails(self, conn, monkeypatch, capsys):
        """Must-preserve: violations keep exit 1 and their message."""
        _mk(conn, scope=[("only_modify", "benchbox/core/*")])
        rc = self._run(conn, monkeypatch, "sample-item", ["benchbox/cli/other.py"])
        out = capsys.readouterr().out
        assert rc == 1
        assert "benchbox/cli/other.py" in out
        assert "SCOPE_UNCHECKED" not in out

    def test_scoped_item_violation_under_strict_is_unchanged(self, conn, monkeypatch):
        """--strict only affects the no-rules case."""
        _mk(conn, scope=[("only_modify", "benchbox/core/*")])
        assert self._run(conn, monkeypatch, "sample-item", ["benchbox/cli/x.py"], strict=True) == 1


class TestConfigDiscovery:
    """Credential-free `.todo-db/config.json` URL discovery (selected hosted)."""

    _CONFIG_URL = "libsql://benchbox-todo-from-config.turso.io"

    def _clear_backend_env(self, monkeypatch):
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        monkeypatch.delenv("TODO_DB_URL", raising=False)
        monkeypatch.delenv("TODO_DB_AUTH_TOKEN", raising=False)

    def _write_config(self, root: Path, payload: dict | str) -> Path:
        cfg_dir = root / ".todo-db"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        path = cfg_dir / "config.json"
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_config_url_selects_hosted_not_implicit_local(self, monkeypatch, tmp_path):
        self._clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
        self._write_config(tmp_path, {"url": self._CONFIG_URL})

        backend, implicit_default_local, auto_provisioned, provision_failure = todo_db._resolve_backend(None)

        assert backend == self._CONFIG_URL
        assert implicit_default_local is False
        assert auto_provisioned is False
        assert provision_failure is None

    def test_config_url_outranks_auto_provision(self, monkeypatch, tmp_path):
        self._clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
        self._write_config(tmp_path, {"url": self._CONFIG_URL})

        def boom(*_args, **_kwargs):
            raise AssertionError("auto-provisioning must not run when config.json supplies a URL")

        monkeypatch.setattr(todo_db, "_try_turso_auto_provision", boom)

        backend, implicit, auto, provision_failure = todo_db._resolve_backend(None)
        assert backend == self._CONFIG_URL
        assert implicit is False
        assert auto is False
        assert provision_failure is None

    def test_env_url_outranks_config(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        monkeypatch.setenv("TODO_DB_URL", "libsql://from-env.turso.io")
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
        self._write_config(tmp_path, {"url": self._CONFIG_URL})

        backend, implicit, auto, provision_failure = todo_db._resolve_backend(None)
        assert backend == "libsql://from-env.turso.io"
        assert implicit is False
        assert auto is False
        assert provision_failure is None

    def test_env_path_outranks_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TODO_DB_PATH", str(tmp_path / "pin.sqlite"))
        monkeypatch.delenv("TODO_DB_URL", raising=False)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
        self._write_config(tmp_path, {"url": self._CONFIG_URL})

        backend, implicit, auto, provision_failure = todo_db._resolve_backend(None)
        assert backend == Path(tmp_path / "pin.sqlite")
        assert implicit is False
        assert auto is False
        assert provision_failure is None

    def test_missing_config_falls_through_to_local(self, monkeypatch, tmp_path):
        self._clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
        monkeypatch.setattr(todo_db, "_try_turso_auto_provision", lambda: (None, None))

        backend, implicit, auto, provision_failure = todo_db._resolve_backend(None)
        assert backend == tmp_path / ".todo-db" / "todo.sqlite"
        assert implicit is True
        assert auto is False
        assert provision_failure is None

    def test_config_with_token_key_is_rejected(self, monkeypatch, tmp_path):
        self._clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
        self._write_config(tmp_path, {"url": self._CONFIG_URL, "auth_token": "sekrit"})

        with pytest.raises(todo_db.TodoError, match="must not contain credentials"):
            todo_db._resolve_backend(None)

    def test_config_http_url_is_rejected(self, monkeypatch, tmp_path):
        self._clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
        self._write_config(tmp_path, {"url": "http://insecure.example/db"})

        with pytest.raises(todo_db.TodoError, match="plaintext http"):
            todo_db._resolve_backend(None)

    def test_report_backend_never_echoes_config_url(self, monkeypatch, tmp_path, capsys):
        self._clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
        self._write_config(tmp_path, {"url": self._CONFIG_URL})

        backend, implicit, auto, provision_failure = todo_db._resolve_backend(None)
        todo_db._report_backend(
            backend,
            implicit_default_local=implicit,
            auto_provisioned=auto,
            provision_failure=provision_failure,
        )
        err = capsys.readouterr().err
        assert "todo backend: hosted" in err
        assert self._CONFIG_URL not in err
        assert "LOCAL FALLBACK" not in err

    def test_mutating_via_config_is_not_implicit_local_refusal(self, monkeypatch, tmp_path, capsys):
        """Config-selected hosted must reach connect/auth, not the local write fence."""
        self._clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
        self._write_config(tmp_path, {"url": self._CONFIG_URL})

        rc = todo_db.main(["claim", "missing-item"])
        err = capsys.readouterr().err
        assert rc == 2
        assert "refusing to write through the implicit local fallback" not in err
        # Missing token is the expected hard-error path for a selected hosted backend.
        assert "TODO_DB_AUTH_TOKEN" in err
        assert self._CONFIG_URL not in err
