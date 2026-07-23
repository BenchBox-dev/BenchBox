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
