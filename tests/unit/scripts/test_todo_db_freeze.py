"""Tests for the leased maintenance freeze and the write-activity fingerprint.

The freeze exists because `restore-legacy --replace` rebuilds every table from a
snapshot: any write landing between snapshot and restore is destroyed silently,
and the rebuilt audit chain still verifies because it is rehashed from that same
snapshot. A claim check cannot gate this -- claims cover claim/start/done/
complete on existing items, while `create`, `defer`, `promote`, `block` and
config writes take no claim at all.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def _mk(conn, item_id, actor="tester"):
    todo_db.create_item(
        conn,
        actor,
        item_id=item_id,
        title=f"Item {item_id} title",
        worktree="main",
        priority="medium",
        description="A description longer than ten characters.",
    )
    return item_id


def _run(db_path, *argv, actor):
    """Invoke main() the way a session does, so the gate in main() is exercised."""
    return todo_db.main(["--db", str(db_path), "--actor", actor, *argv])


class TestWriteActivityFingerprint:
    def test_absent_before_any_write(self, conn):
        activity = todo_db.write_activity(conn)
        assert activity["count"] == 0
        assert activity["last_seq"] is None

    def test_moves_on_an_unclaimed_create(self, conn):
        before = todo_db.write_activity(conn)
        _mk(conn, "some-item")
        after = todo_db.write_activity(conn)
        assert after["count"] > before["count"]
        assert after["last_seq"] != before["last_seq"]

    def test_stable_across_reads_when_nobody_writes(self, conn):
        _mk(conn, "some-item")
        first = todo_db.write_activity(conn)
        # Reads must not perturb the fingerprint, or the quiescence check that
        # gates the cutover would never converge.
        todo_db.stats(conn)
        conn.execute("SELECT count(*) FROM items").fetchone()
        assert todo_db.write_activity(conn) == first

    def test_exposed_through_stats(self, conn):
        _mk(conn, "some-item")
        computed = todo_db.stats(conn)
        assert computed["events"] == todo_db.write_activity(conn)
        assert computed["events"]["count"] > 0

    def test_stats_keeps_its_existing_keys(self, conn):
        _mk(conn, "some-item")
        computed = todo_db.stats(conn)
        for key in (
            "items_by_state",
            "open_by_priority",
            "open_by_worktree",
            "deferrals_by_resolution",
            "claimed",
            "findings_by_disposition",
        ):
            assert key in computed


class TestFreezeLifecycle:
    def test_no_freeze_by_default(self, conn):
        assert todo_db.get_freeze(conn) is None

    def test_set_then_get(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        live = todo_db.get_freeze(conn)
        assert live["holder"] == "alice"
        assert live["reason"] == "cutover"

    def test_holder_may_re_freeze(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        todo_db.set_freeze(conn, "alice", "cutover round two", ttl_hours=1)
        assert todo_db.get_freeze(conn)["reason"] == "cutover round two"

    def test_second_actor_cannot_steal_a_live_freeze(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        with pytest.raises(todo_db.TodoError, match="already frozen by alice"):
            todo_db.set_freeze(conn, "bob", "my turn", ttl_hours=1)

    def test_release_by_holder(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        assert todo_db.clear_freeze(conn, "alice") is True
        assert todo_db.get_freeze(conn) is None

    def test_release_by_other_actor_refused(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        with pytest.raises(todo_db.TodoError, match="held by alice"):
            todo_db.clear_freeze(conn, "bob")
        assert todo_db.get_freeze(conn) is not None

    def test_release_by_other_actor_with_force(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        assert todo_db.clear_freeze(conn, "bob", force=True) is True
        assert todo_db.get_freeze(conn) is None

    def test_release_with_no_freeze_is_not_an_error(self, conn):
        assert todo_db.clear_freeze(conn, "alice") is False

    def test_freeze_is_audited(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        todo_db.clear_freeze(conn, "alice")
        actions = [r["action"] for r in conn.execute("SELECT action FROM events ORDER BY seq")]
        assert "freeze" in actions
        assert "unfreeze" in actions


class TestFreezeCannotWedgeTheTracker:
    """must-preserve: a maintenance mode cannot become a permanently stuck lock
    if the holder dies."""

    def _backdate(self, conn, hours):
        stale = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (todo_db.FREEZE_AT_KEY, stale),
        )

    def test_expired_freeze_reads_as_absent(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        self._backdate(conn, hours=3)
        assert todo_db.get_freeze(conn) is None

    def test_expired_freeze_lets_another_actor_take_over(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        self._backdate(conn, hours=3)
        todo_db.set_freeze(conn, "bob", "alice never came back", ttl_hours=1)
        assert todo_db.get_freeze(conn)["holder"] == "bob"

    def test_expired_freeze_does_not_block_writes(self, tmp_path):
        db = tmp_path / "todo.sqlite"
        connection = todo_db.connect(db)
        todo_db.set_freeze(connection, "alice", "cutover", ttl_hours=1)
        self._backdate(connection, hours=3)
        connection.commit()
        connection.close()
        assert (
            _run(
                db,
                "create",
                "bob-item",
                "--title",
                "Bob item title",
                "--worktree",
                "main",
                "--priority",
                "medium",
                "--description",
                "A description longer than ten characters.",
                actor="bob",
            )
            == 0
        )

    def test_unbounded_freeze_refused(self, conn):
        with pytest.raises(todo_db.TodoError, match="must be positive"):
            todo_db.set_freeze(conn, "alice", "forever", ttl_hours=0)


class TestFreezeGate:
    @pytest.fixture()
    def frozen_db(self, tmp_path):
        db = tmp_path / "todo.sqlite"
        connection = todo_db.connect(db)
        _mk(connection, "existing-item")
        todo_db.set_freeze(connection, "alice", "cutover", ttl_hours=1)
        connection.commit()
        connection.close()
        return db

    @pytest.mark.parametrize(
        "argv",
        [
            # The unclaimed write paths a claim check is blind to.
            (
                "create",
                "new-item",
                "--title",
                "New item title",
                "--worktree",
                "main",
                "--priority",
                "medium",
                "--description",
                "A description longer than ten characters.",
            ),
            ("config", "lint.require_scope_rules", "off"),
            ("block", "existing-item", "--reason", "blocked during the cutover window"),
            # ...and a claimed one, for completeness.
            ("claim", "existing-item"),
        ],
        ids=["create", "config", "block", "claim"],
    )
    def test_foreign_writes_are_refused(self, frozen_db, argv):
        assert _run(frozen_db, *argv, actor="bob") == 2

    @pytest.mark.parametrize(
        "argv",
        [("list",), ("stats",), ("show", "existing-item"), ("ready",)],
        ids=["list", "stats", "show", "ready"],
    )
    def test_reads_still_work(self, frozen_db, argv):
        assert _run(frozen_db, *argv, actor="bob") == 0

    def test_holder_can_still_write(self, frozen_db):
        assert _run(frozen_db, "claim", "existing-item", actor="alice") == 0

    def test_holder_can_always_lift_its_own_freeze(self, frozen_db):
        assert _run(frozen_db, "freeze", "--release", actor="alice") == 0
        assert _run(frozen_db, "claim", "existing-item", actor="bob") == 0

    def test_status_is_readable_by_anyone(self, frozen_db):
        assert _run(frozen_db, "freeze", "--status", actor="bob") == 0

    def test_foreign_actor_cannot_lift(self, frozen_db):
        assert _run(frozen_db, "freeze", "--release", actor="bob") == 2

    def test_writes_flow_normally_with_no_freeze(self, tmp_path):
        """must-preserve: normal multi-session operation is unaffected when no
        cutover is in progress."""
        db = tmp_path / "todo.sqlite"
        connection = todo_db.connect(db)
        _mk(connection, "existing-item")
        connection.commit()
        connection.close()
        assert _run(db, "claim", "existing-item", actor="bob") == 0
        assert _run(db, "config", "lint.require_scope_rules", "off", actor="carol") == 0

    def test_status_does_not_mutate(self, tmp_path):
        db = tmp_path / "todo.sqlite"
        connection = todo_db.connect(db)
        _mk(connection, "existing-item")
        connection.commit()
        before = todo_db.write_activity(connection)
        connection.close()
        assert _run(db, "freeze", "--status", actor="bob") == 0
        connection = todo_db.connect(db)
        assert todo_db.write_activity(connection) == before
        connection.close()
