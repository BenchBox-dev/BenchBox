"""Backend-agnostic gate-hardening tests for todo_db.py.

Adversarial review of the hosted-backend work surfaced two check-then-act
writers that were weaker than the module's own `_write_txn` discipline:
`promote_deferral` (gate read outside any transaction, unconditional UPDATE)
and `sweep_stale` (unconditional lease release). These tests pin the
hardened behavior against real concurrent SQLite connections.

Marked medium (not fast) deliberately: the fast lane is budget-gated.
"""

from __future__ import annotations

import importlib.util
import sqlite3
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


def _make_parent(conn, item_id="parent-item"):
    todo_db.create_item(
        conn,
        "tester",
        item_id=item_id,
        title="Hardening parent item",
        worktree="spike",
        priority="low",
        description="Parent for deferral-gate hardening tests.",
    )


class TestPromoteAtomicity:
    def test_double_promotion_refused(self, tmp_path):
        db = tmp_path / "t.sqlite"
        conn = todo_db.connect(db)
        _make_parent(conn)
        deferral_id = todo_db.defer_work(conn, "tester", "parent-item", "follow-up", "later")
        todo_db.promote_deferral(conn, "actor-a", deferral_id, new_item_id="child-a")
        with pytest.raises(todo_db.TodoError, match="already|concurrently"):
            todo_db.promote_deferral(conn, "actor-b", deferral_id, new_item_id="child-b")
        # exactly one child exists; provenance points at the winner
        ids = [r["id"] for r in conn.execute("SELECT id FROM items WHERE id LIKE 'child-%'")]
        assert ids == ["child-a"]
        row = conn.execute("SELECT resolution, resolved_item FROM deferrals WHERE id = ?", (deferral_id,)).fetchone()
        assert (row["resolution"], row["resolved_item"]) == ("promoted", "child-a")

    def test_promote_after_dismiss_refused(self, tmp_path):
        conn = todo_db.connect(tmp_path / "t.sqlite")
        _make_parent(conn)
        deferral_id = todo_db.defer_work(conn, "tester", "parent-item", "follow-up", "later")
        todo_db.dismiss_deferral(conn, "actor-a", deferral_id, "not needed")
        with pytest.raises(todo_db.TodoError, match="already"):
            todo_db.promote_deferral(conn, "actor-b", deferral_id, new_item_id="child-x")
        assert conn.execute("SELECT count(*) FROM items WHERE id = 'child-x'").fetchone()[0] == 0

    def test_failed_promotion_leaves_deferral_open(self, tmp_path):
        conn = todo_db.connect(tmp_path / "t.sqlite")
        _make_parent(conn)
        deferral_id = todo_db.defer_work(conn, "tester", "parent-item", "follow-up", "later")
        # promoting onto an existing item id fails; the deferral must stay
        # open and no half-committed state may survive (single transaction)
        with pytest.raises(todo_db.TodoError, match="cannot create"):
            todo_db.promote_deferral(conn, "actor-a", deferral_id, new_item_id="parent-item")
        row = conn.execute("SELECT resolution FROM deferrals WHERE id = ?", (deferral_id,)).fetchone()
        assert row["resolution"] == "open"

    def test_promote_holds_the_write_lock_for_its_whole_span(self, tmp_path, monkeypatch):
        """A concurrent writer must be locked out between the gate read and
        the resolution update — the exact window the pre-hardening code left
        open (gate outside the transaction, unconditional UPDATE)."""
        db = tmp_path / "t.sqlite"
        conn_a = todo_db.connect(db)
        conn_b = todo_db.connect(db)
        conn_b.execute("PRAGMA busy_timeout = 100")
        _make_parent(conn_a)
        deferral_id = todo_db.defer_work(conn_a, "tester", "parent-item", "follow-up", "later")
        original_gate = todo_db._require_deferral
        probe: dict[str, bool] = {}

        def hooked(conn, deferral_id_arg):
            row = original_gate(conn, deferral_id_arg)
            if "fired" not in probe:
                probe["fired"] = True
                # AT THE GATE READ another connection must already be locked
                # out — the pre-hardening code read the gate with no
                # transaction at all, so this write would have succeeded and
                # the unconditional UPDATE would then have overwritten it.
                with pytest.raises(sqlite3.OperationalError):
                    conn_b.execute("UPDATE deferrals SET resolution = 'dismissed' WHERE id = ?", (deferral_id,))
            return row

        monkeypatch.setattr(todo_db, "_require_deferral", hooked)
        todo_db.promote_deferral(conn_a, "actor-a", deferral_id, new_item_id="child-locked")
        assert probe.get("fired"), "the promote event hook never fired"
        row = conn_a.execute("SELECT resolution FROM deferrals WHERE id = ?", (deferral_id,)).fetchone()
        assert row["resolution"] == "promoted"


class TestSweepStalePredicate:
    def test_sweep_releases_only_stale_leases(self, tmp_path):
        conn = todo_db.connect(tmp_path / "t.sqlite")
        _make_parent(conn, item_id="stale-item")
        _make_parent(conn, item_id="fresh-item")
        todo_db.claim_item(conn, "old-actor", "stale-item")
        todo_db.claim_item(conn, "live-actor", "fresh-item")
        with todo_db._write_txn(conn):
            conn.execute(
                "UPDATE items SET claimed_at = '2020-01-01T00:00:00Z' WHERE id = 'stale-item'",
            )
        released = todo_db.sweep_stale(conn, "sweeper")
        assert released == ["stale-item"]
        holder = conn.execute("SELECT claimed_by FROM items WHERE id = 'fresh-item'").fetchone()
        assert holder["claimed_by"] == "live-actor"

    def test_sweep_release_is_conditional_on_the_observed_lease(self, tmp_path, monkeypatch):
        """If the lease changes hands between the sweep's read and its write,
        the release must not fire (conditional UPDATE, like claim_item)."""
        db = tmp_path / "t.sqlite"
        conn = todo_db.connect(db)
        interloper = todo_db.connect(db)
        _make_parent(conn, item_id="contested-item")
        todo_db.claim_item(conn, "old-actor", "contested-item")
        with todo_db._write_txn(conn):
            conn.execute("UPDATE items SET claimed_at = '2020-01-01T00:00:00Z' WHERE id = 'contested-item'")

        original_expired = todo_db._lease_expired
        state: dict[str, bool] = {}

        def hooked(claimed_at, ttl_hours):
            # After the sweep has read the stale lease but before it writes,
            # the lease is renewed by another actor on a second connection.
            # (Runs outside the sweep's txn window in local SQLite only if the
            # sweep is not serialized; with BEGIN IMMEDIATE this write blocks,
            # so emulate the hosted stale-replica read instead: mutate through
            # the SAME connection the sweep holds, simulating that the row it
            # read no longer matches primary state.)
            if "renewed" not in state:
                state["renewed"] = True
                conn.execute(
                    "UPDATE items SET claimed_by = 'new-actor', claimed_at = ? WHERE id = 'contested-item'",
                    (todo_db.utc_now(),),
                )
            return original_expired(claimed_at, ttl_hours)

        monkeypatch.setattr(todo_db, "_lease_expired", hooked)
        released = todo_db.sweep_stale(conn, "sweeper")
        assert released == [], "a renewed lease must not be swept"
        row = conn.execute("SELECT claimed_by FROM items WHERE id = 'contested-item'").fetchone()
        assert row["claimed_by"] == "new-actor"
        interloper.close()
