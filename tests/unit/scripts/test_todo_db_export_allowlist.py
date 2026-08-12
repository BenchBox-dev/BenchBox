"""Pinning tests for the repo-committed export boundary (findings-domain
phase 2).

The committed snapshot under ``_project/todo-db-export/`` must never carry a
findings-domain table -- review prose is deliberately not version-controlled
(see ``_project/specs/findings-domain.md``, "Export boundary"). These tests
pin that boundary structurally: the exporter reads only an explicit allowlist,
any ``finding%`` table fails closed by construction, and the ``events``
provenance table round-trips through the committed snapshot.

Marked ``medium`` (not ``fast``): this file is out of the fast-lane cap's
scope and materialises a scratch database, so it must not consume fast-lane
budget.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
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


class TestExportAllowlistShape:
    def test_allowlist_excludes_findings_tables(self):
        # The whole point of the boundary: no findings-domain table may ever be
        # named in the committed-export allowlist.
        leaks = [t for t in todo_db.EXPORT_TABLE_ALLOWLIST if t.startswith("finding")]
        assert leaks == [], f"findings tables must never be allowlisted for the committed export: {leaks}"

    def test_allowlist_is_subset_of_backup_scope(self):
        # The committed snapshot can only contain tables that are also part of
        # the full backup/restore scope; it is a subset, never a superset.
        extra = todo_db.EXPORT_TABLE_ALLOWLIST - set(todo_db.TRANSFER_TABLES)
        assert extra == set(), f"allowlist tables missing from TRANSFER_TABLES: {sorted(extra)}"

    def test_exporter_coverage_equals_allowlist(self):
        # The exporter's actual coverage (item-nested tables + events) must
        # equal the allowlist exactly -- this is what write_export asserts at
        # runtime; pin it here so drift is caught in unit tests too.
        covered = todo_db._ITEM_NESTED_EXPORT_TABLES | {"events"}
        assert covered == todo_db.EXPORT_TABLE_ALLOWLIST


class TestExportFailsClosed:
    def test_unlisted_finding_table_never_reaches_the_snapshot(self, conn, tmp_path):
        # The real findings-domain tables (v3 schema) carrying prose in every
        # prose-heavy column must not leak into any committed export file.
        # Because the exporter reads only allowlisted tables, this data is never
        # read -> never written. Exercises all four tables so the guarantee is
        # not tied to one name the exporter's SELECTs happen not to reference.
        _mk(conn, item_id="real-item")
        sentinel = "LEAK-SENTINEL-finding-prose-do-not-commit"
        fid = "2026-01-01-000000-leak-class"
        conn.execute(
            "INSERT INTO findings (id, date, finding_kind, review_context, title,"
            " finding_text, why_matters, next_steps, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fid,
                "2026-01-01",
                "framework-gap",
                f"{sentinel}-review-context",
                f"{sentinel}-title",
                f"{sentinel}-finding",
                f"{sentinel}-why",
                f"{sentinel}-next",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO finding_evidence (finding_id, path, note) VALUES (?, ?, ?)",
            (fid, "some/path.py", f"{sentinel}-evidence"),
        )
        conn.execute(
            "INSERT INTO finding_links (finding_id, kind, note) VALUES (?, 'informs', ?)",
            (fid, f"{sentinel}-link"),
        )
        conn.execute(
            "INSERT INTO finding_events (at, actor, finding_id, action, detail) VALUES (?, ?, ?, ?, ?)",
            ("2026-01-01T00:00:00Z", "tester", fid, "sync", f"{sentinel}-event"),
        )
        conn.commit()

        out_dir = tmp_path / "export"
        todo_db.write_export(conn, out_dir)

        finding_tables = ("findings", "finding_evidence", "finding_links", "finding_events")
        for produced in sorted(out_dir.iterdir()):
            text = produced.read_text(encoding="utf-8")
            assert sentinel not in text, f"findings data leaked into committed export file {produced.name}"
            for table in finding_tables:
                assert table not in text, f"findings table name {table!r} leaked into {produced.name}"

    def test_write_export_raises_if_coverage_drifts(self, conn, tmp_path, monkeypatch):
        # If the allowlist and the exporter's coverage disagree, write_export
        # must fail loudly rather than silently drop or leak a table.
        monkeypatch.setattr(
            todo_db,
            "EXPORT_TABLE_ALLOWLIST",
            todo_db.EXPORT_TABLE_ALLOWLIST | {"some_new_table"},
        )
        with pytest.raises(RuntimeError, match="drifted from EXPORT_TABLE_ALLOWLIST"):
            todo_db.write_export(conn, tmp_path / "export")


class TestEventsRoundTrip:
    def test_events_are_exported_deterministically(self, conn, tmp_path):
        _mk(conn, item_id="first-item")
        _mk(conn, item_id="second-item")

        first_dir, second_dir = tmp_path / "a", tmp_path / "b"
        todo_db.write_export(conn, first_dir)
        todo_db.write_export(conn, second_dir)

        events_a = (first_dir / "events.jsonl").read_text(encoding="utf-8")
        events_b = (second_dir / "events.jsonl").read_text(encoding="utf-8")
        assert events_a == events_b, "events export must be deterministic"

        lines = [line for line in events_a.splitlines() if line]
        assert lines, "events.jsonl must not be empty when the tracker has recorded events"
        rows = [json.loads(line) for line in lines]

        # Ordered by the monotonic seq PK.
        seqs = [row["seq"] for row in rows]
        assert seqs == sorted(seqs)

        # Round-trip: every event row in the DB appears in the export.
        db_count = conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"]
        assert len(rows) == db_count
        assert {"action", "actor", "at", "item_id", "seq"} <= set(rows[0].keys())
        assert any(row["action"] == "create" for row in rows)


class TestMigrationSnapshotScope:
    """The snapshot is a BACKUP artifact, scoped separately from the export."""

    def test_snapshot_scope_is_backup_scope_plus_meta_plus_findings(self):
        # Scoped to the backup/restore set, NOT to the committed-export
        # allowlist. The two overlap, but deriving the snapshot from the
        # allowlist would mean narrowing what may be committed silently narrows
        # what a migration carries.
        expected = frozenset(todo_db.TRANSFER_TABLES) | {"meta"} | todo_db.RESTORE_LEGACY_OPTIONAL_TABLES
        assert expected == todo_db.SNAPSHOT_TABLES

    def test_snapshot_satisfies_the_importer_contract_in_both_directions(self):
        # restore-legacy requires its 12 tables and REJECTS anything outside
        # required|optional, so the snapshot must be a superset of one and a
        # subset of the other. build_snapshot enforces this at runtime; pin it
        # here so a divergence is named by a unit test rather than a cutover.
        assert todo_db.RESTORE_LEGACY_REQUIRED_TABLES <= todo_db.SNAPSHOT_TABLES
        rejected = (
            todo_db.SNAPSHOT_TABLES - todo_db.RESTORE_LEGACY_REQUIRED_TABLES - todo_db.RESTORE_LEGACY_OPTIONAL_TABLES
        )
        assert rejected == set(), f"importer would reject: {sorted(rejected)}"

    def test_snapshot_includes_findings_tables(self):
        # Deliberately inverted from the original assertion. Findings were
        # excluded while restore-legacy discarded unknown tables -- shipping
        # prose that would be thrown away only risked leaking it. That importer
        # now loads findings, so excluding them here would make the migration
        # silently lossy instead. Safe because write_snapshot refuses any
        # destination inside a Git work tree.
        expected = {"findings", "finding_evidence", "finding_links", "finding_events", "finding_sections"}
        assert expected <= todo_db.SNAPSHOT_TABLES


class TestMigrationSnapshotShape:
    def test_snapshot_covers_every_required_table(self, conn):
        _mk(conn, item_id="snapshot-item")
        snapshot = todo_db.build_snapshot(conn)
        missing = sorted(todo_db.RESTORE_LEGACY_REQUIRED_TABLES - snapshot.keys())
        assert missing == [], f"restore-legacy would reject this snapshot: missing {missing}"

    def test_items_are_normalized_not_nested(self, conn):
        # The committed export nests child rows inside each item; restore_legacy
        # strips exactly those keys and looks for sibling tables instead. A
        # snapshot carrying nested items is structurally invalid input.
        _mk(conn, item_id="snapshot-item")
        snapshot = todo_db.build_snapshot(conn)
        nested = {"work", "deps", "scope", "verifications", "preserves", "anti_patterns", "prior_art", "deferrals"}
        leaked = sorted({key for item in snapshot["items"] for key in nested & set(item)})
        assert leaked == [], f"items must be raw rows, not the export's nested shape: {leaked}"

    def test_child_rows_travel_in_their_own_tables(self, conn):
        _mk(conn, item_id="snapshot-item", scope=[("only_modify", "src/**")])
        snapshot = todo_db.build_snapshot(conn)
        assert snapshot["scope_rules"], "scope rules must survive as their own table"
        assert all(row["item_id"] == "snapshot-item" for row in snapshot["scope_rules"])

    def test_snapshot_is_deterministic(self, conn):
        _mk(conn, item_id="b-item")
        _mk(conn, item_id="a-item")
        assert todo_db.build_snapshot(conn) == todo_db.build_snapshot(conn)


class TestMigrationSnapshotStaysOutOfGit:
    """A snapshot carries every deferral and event body; it must not reach Git."""

    def test_refuses_a_destination_inside_a_work_tree(self, conn, tmp_path):
        work_tree = tmp_path / "checkout"
        (work_tree / ".git").mkdir(parents=True)
        with pytest.raises(SystemExit, match="refusing to write a tracker snapshot"):
            todo_db.write_snapshot(conn, work_tree / "snapshot.json")
        assert not (work_tree / "snapshot.json").exists()

    def test_refuses_a_nested_destination_inside_a_work_tree(self, conn, tmp_path):
        work_tree = tmp_path / "checkout"
        (work_tree / ".git").mkdir(parents=True)
        nested = work_tree / "_project" / "scripts"
        nested.mkdir(parents=True)
        with pytest.raises(SystemExit, match="refusing to write a tracker snapshot"):
            todo_db.write_snapshot(conn, nested / "snapshot.json")

    def test_refuses_inside_a_linked_worktree_where_dot_git_is_a_file(self, conn, tmp_path):
        # Linked worktrees carry a `.git` FILE, not a directory,
        # and are separate roots from the main clone -- a main-root check lets
        # them through, which is exactly where agents do their work.
        work_tree = tmp_path / "pool-01"
        work_tree.mkdir()
        (work_tree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/pool-01\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="refusing to write a tracker snapshot"):
            todo_db.write_snapshot(conn, work_tree / "snapshot.json")

    def test_writes_outside_any_work_tree(self, conn, tmp_path):
        _mk(conn, item_id="snapshot-item")
        target = tmp_path / "backups" / "snapshot.json"
        written = todo_db.write_snapshot(conn, target)
        assert written.exists()
        payload = json.loads(written.read_text(encoding="utf-8"))
        assert payload.keys() >= todo_db.RESTORE_LEGACY_REQUIRED_TABLES


class TestSnapshotCarriesFindingsButExportDoesNot:
    """Two boundaries that must not drift into each other.

    The committed export is findings-free on purpose: review prose is not
    version-controlled. A migration snapshot is the opposite — it must carry
    findings or the migration silently drops them — and that is safe only
    because write_snapshot refuses any destination inside a Git work tree.
    """

    def test_committed_export_allowlist_stays_findings_free(self):
        leaks = sorted(t for t in todo_db.EXPORT_TABLE_ALLOWLIST if t.startswith("finding"))
        assert leaks == [], f"findings must never reach the committed export: {leaks}"

    def test_a_finding_reaches_the_snapshot_but_not_the_committed_export(self, conn, tmp_path):
        _mk(conn, item_id="real-item")
        sentinel = "SNAPSHOT-ONLY-finding-prose"
        fid = "2026-01-01-000000-snapshot-class"
        conn.execute(
            "INSERT INTO findings (id, date, finding_kind, review_context, title,"
            " finding_text, why_matters, next_steps, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fid,
                "2026-01-01",
                "framework-gap",
                "ctx",
                f"{sentinel}-title",
                f"{sentinel}-finding",
                "why",
                "next",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()

        snapshot = todo_db.build_snapshot(conn)
        assert [row["id"] for row in snapshot["findings"]] == [fid]
        assert sentinel in json.dumps(snapshot)

        out_dir = tmp_path / "export"
        todo_db.write_export(conn, out_dir)
        for produced in sorted(out_dir.iterdir()):
            assert sentinel not in produced.read_text(encoding="utf-8"), (
                f"findings prose leaked into the committed export file {produced.name}"
            )

    def test_build_snapshot_refuses_a_scope_the_importer_would_reject(self, conn, monkeypatch):
        # Fail closed: a table the importer neither requires nor accepts must
        # stop the snapshot being built, not be discovered during a cutover.
        monkeypatch.setattr(todo_db, "SNAPSHOT_TABLES", todo_db.SNAPSHOT_TABLES | {"some_future_table"})
        with pytest.raises(RuntimeError, match="importer would reject"):
            todo_db.build_snapshot(conn)
