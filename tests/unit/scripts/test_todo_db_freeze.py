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
import math
import sqlite3
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


class TestFreezeTtlIsBounded:
    """A TTL that timedelta cannot represent used to wedge the tracker through
    the documented `--ttl` flag: every mutating command, `--status`, `--release`
    and even `--release --force` raised OverflowError, leaving raw SQL as the
    only recovery. The lease exists precisely so that cannot happen.
    """

    @pytest.mark.parametrize("bad", ["inf", "-inf", "nan"])
    def test_non_finite_ttl_is_refused(self, conn, bad):
        with pytest.raises(todo_db.TodoError):
            todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=float(bad))
        assert todo_db.get_freeze(conn) is None

    def test_ttl_beyond_the_ceiling_is_refused(self, conn):
        with pytest.raises(todo_db.TodoError):
            todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=todo_db.MAX_FREEZE_TTL_HOURS + 1)
        assert todo_db.get_freeze(conn) is None

    def test_ttl_at_the_ceiling_is_allowed(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=todo_db.MAX_FREEZE_TTL_HOURS)
        assert todo_db.get_freeze(conn)["ttl_hours"] == todo_db.MAX_FREEZE_TTL_HOURS

    @pytest.mark.parametrize("stored", ["inf", "nan", "1e308", "not-a-number", "-5"])
    def test_a_tampered_ttl_row_never_raises(self, conn, stored):
        """Recovery path for a database wedged before the validation landed."""
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (todo_db.FREEZE_TTL_KEY, stored),
        )
        live = todo_db.get_freeze(conn)  # must not raise
        assert live is not None
        assert math.isfinite(live["ttl_hours"])
        assert 0 < live["ttl_hours"] <= todo_db.MAX_FREEZE_TTL_HOURS

    def test_a_wedged_database_can_still_be_released(self, tmp_path):
        db = tmp_path / "todo.sqlite"
        connection = todo_db.connect(db)
        todo_db.set_freeze(connection, "alice", "cutover", ttl_hours=1)
        connection.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (todo_db.FREEZE_TTL_KEY, "inf"),
        )
        connection.commit()
        connection.close()
        assert _run(db, "freeze", "--release", "--force", actor="bob") == 0


class TestTornFreezeFailsClosed:
    """A half-written freeze must read as still-frozen. Returning "expired" let
    every other actor write straight through it -- a safety gate whose degraded
    state is "unlocked".
    """

    def _tear(self, conn, value=None):
        if value is None:
            conn.execute("DELETE FROM meta WHERE key = ?", (todo_db.FREEZE_AT_KEY,))
        else:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (todo_db.FREEZE_AT_KEY, value),
            )

    def test_missing_stamp_reads_as_live(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        self._tear(conn)
        live = todo_db.get_freeze(conn)
        assert live is not None
        assert live["holder"] == "alice"

    def test_malformed_stamp_reads_as_live(self, conn):
        todo_db.set_freeze(conn, "alice", "cutover", ttl_hours=1)
        self._tear(conn, "not-a-timestamp")
        assert todo_db.get_freeze(conn) is not None

    @pytest.mark.parametrize("stamp", [None, "not-a-timestamp"])
    def test_torn_freeze_refuses_a_foreign_write_cleanly(self, tmp_path, stamp):
        db = tmp_path / "todo.sqlite"
        connection = todo_db.connect(db)
        _mk(connection, "existing-item")
        todo_db.set_freeze(connection, "alice", "cutover", ttl_hours=1)
        self._tear(connection, stamp)
        connection.commit()
        connection.close()
        # exit 2, not an uncaught ValueError escaping main()
        assert _run(db, "claim", "existing-item", actor="bob") == 2

    @pytest.mark.parametrize("stamp", [None, "not-a-timestamp"])
    def test_torn_freeze_is_still_liftable(self, tmp_path, stamp):
        db = tmp_path / "todo.sqlite"
        connection = todo_db.connect(db)
        todo_db.set_freeze(connection, "alice", "cutover", ttl_hours=1)
        self._tear(connection, stamp)
        connection.commit()
        connection.close()
        assert _run(db, "freeze", "--release", "--force", actor="bob") == 0


class TestMigrateIsGatedByTheFreeze:
    """`migrate` runs before connect_backend() -- which refuses an outdated
    schema -- so the normal gate is unreachable on exactly the databases that
    have migrations pending. Without its own check, a schema change lands
    mid-cutover through a live freeze.
    """

    def _v3_db(self, tmp_path, holder):
        db = tmp_path / "todo.sqlite"
        raw = sqlite3.connect(db)
        raw.row_factory = sqlite3.Row
        raw.executescript(todo_db._CORE_SCHEMA_SQL)
        # Climb to v3 only; v4 is what the CLI under test should (or should not)
        # apply. _CORE_SCHEMA_SQL already carries the v2 columns.
        for statement in todo_db.MIGRATIONS[3]:
            raw.execute(statement)
        raw.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '3')")
        for key, value in (
            (todo_db.FREEZE_HOLDER_KEY, holder),
            (todo_db.FREEZE_AT_KEY, todo_db.utc_now()),
            (todo_db.FREEZE_REASON_KEY, "cutover"),
            (todo_db.FREEZE_TTL_KEY, "2.0"),
        ):
            raw.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        raw.commit()
        raw.close()
        return db

    def _version(self, db):
        raw = sqlite3.connect(db)
        raw.row_factory = sqlite3.Row
        try:
            return todo_db._schema_version(raw)
        finally:
            raw.close()

    def test_foreign_actor_cannot_migrate_through_a_freeze(self, tmp_path):
        db = self._v3_db(tmp_path, holder="alice")
        assert self._version(db) == 3
        assert _run(db, "migrate", actor="bob") == 2
        assert self._version(db) == 3, "schema changed under a live freeze"

    def test_the_holder_may_still_migrate(self, tmp_path):
        """The holder runs the cutover, so it must keep its own write access."""
        db = self._v3_db(tmp_path, holder="alice")
        assert _run(db, "migrate", actor="alice") == 0
        assert self._version(db) == todo_db.SCHEMA_VERSION

    def test_migrate_is_unaffected_with_no_freeze(self, tmp_path):
        db = self._v3_db(tmp_path, holder="alice")
        raw = sqlite3.connect(db)
        raw.execute("DELETE FROM meta WHERE key LIKE 'maintenance.%'")
        raw.commit()
        raw.close()
        assert _run(db, "migrate", actor="bob") == 0
        assert self._version(db) == todo_db.SCHEMA_VERSION


class TestFreezeCoversBulkWritePaths:
    """The two paths that stage through a temp local database before copying to
    the primary. Both are gated at the command level in main(), before dispatch,
    so neither can reach `bulk_transfer` under a foreign freeze -- but that was
    reasoned rather than executed until these tests existed.
    """

    @pytest.fixture()
    def frozen_db(self, tmp_path):
        db = tmp_path / "todo.sqlite"
        connection = todo_db.connect(db)
        todo_db.set_freeze(connection, "alice", "cutover", ttl_hours=1)
        connection.commit()
        connection.close()
        return db

    def test_import_yaml_replace_is_refused(self, frozen_db, capsys):
        # Assert on the REASON, not the exit code. `--replace` exits 2 on a local
        # backend regardless, so an exit-code-only assertion passes even with the
        # gate deleted -- verified by mutation, which is how this test was fixed.
        assert _run(frozen_db, "import-yaml", "--replace", actor="bob") == 2
        assert "frozen for maintenance" in capsys.readouterr().err

    def test_import_yaml_dry_run_is_a_read(self, frozen_db, capsys):
        # --dry-run writes nothing, so a freeze must not block it.
        _run(frozen_db, "import-yaml", "--dry-run", actor="bob")
        assert "frozen for maintenance" not in capsys.readouterr().err

    def test_finding_import_bulk_is_refused(self, frozen_db, tmp_path, capsys):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        assert (
            _run(
                frozen_db,
                "finding",
                "import",
                "--corpus",
                str(corpus),
                "--bulk",
                "--confirm-target",
                "benchbox-todo",
                actor="bob",
            )
            == 2
        )
        assert "frozen for maintenance" in capsys.readouterr().err

    def test_the_refusal_is_the_freeze_not_an_incidental_error(self, tmp_path, capsys):
        """Control: with no freeze the same command fails for a DIFFERENT reason."""
        db = tmp_path / "todo.sqlite"
        todo_db.connect(db).close()
        _run(db, "import-yaml", "--replace", actor="bob")
        assert "frozen for maintenance" not in capsys.readouterr().err


class TestFalsifiabilityGrandfathering:
    """Items authored before the falsifiability rule are reported as NOTES, not
    findings (see `_FALSIFIABILITY_RULE_EPOCH`).

    Ladders are create-time-only, so the only fix is a terminal drop+recreate
    that cascades through dependents. 118 of 138 affected items predate the
    rule; grandfathering keeps them visible without drowning the 20 that do not.
    """

    def _item_with_unfalsifiable_ladder(self, conn, item_id, created_at):
        todo_db.create_item(
            conn,
            "tester",
            item_id=item_id,
            title=f"Item {item_id} title",
            worktree="main",
            priority="medium",
            description="A description longer than ten characters.",
            verifications=[{"seq": 1, "description": "it works", "command": "make check", "expected": "exit 0"}],
        )
        conn.execute("UPDATE items SET created_at = ? WHERE id = ?", (created_at, item_id))
        todo_db.set_config(conn, "tester", "lint.require_falsifiable_rung", "on")
        return item_id

    def _old(self, conn, item_id="legacy-item"):
        return self._item_with_unfalsifiable_ladder(conn, item_id, "2026-01-01T00:00:00Z")

    def _new(self, conn, item_id="recent-item"):
        return self._item_with_unfalsifiable_ladder(conn, item_id, "2026-12-01T00:00:00Z")

    def test_a_pre_rule_item_is_not_a_finding(self, conn):
        item = self._old(conn)
        assert not [f for f in todo_db.lint_item(conn, item) if "falsifiability" in f]

    def test_a_pre_rule_item_is_still_reported_as_a_note(self, conn):
        """Grandfathered must mean visible, not invisible."""
        item = self._old(conn)
        notes = [n for n in todo_db.lint_item_notes(conn, item) if "grandfathered" in n]
        assert len(notes) == 1
        # The note must not collide with the finding's own wording, or a caller
        # grepping for the finding reads a cleared backlog as unfixed.
        assert "no falsifiability" not in notes[0]

    def test_a_post_rule_item_is_still_a_finding(self, conn):
        item = self._new(conn)
        assert [f for f in todo_db.lint_item(conn, item) if "no falsifiability" in f]

    def test_grandfathering_can_be_switched_off_to_audit_the_backlog(self, conn):
        item = self._old(conn)
        todo_db.set_config(conn, "tester", "lint.grandfather_falsifiability", "off")
        assert [f for f in todo_db.lint_item(conn, item) if "no falsifiability" in f]

    def test_a_missing_creation_stamp_buys_no_exemption(self, conn):
        """Otherwise clearing created_at becomes an opt-out."""
        item = self._old(conn, "undated-item")
        conn.execute("UPDATE items SET created_at = '' WHERE id = ?", (item,))
        assert [f for f in todo_db.lint_item(conn, item) if "no falsifiability" in f]

    def test_a_pre_rule_item_with_a_good_ladder_gets_no_note(self, conn):
        """Grandfathering reports only items that would otherwise trip."""
        todo_db.create_item(
            conn,
            "tester",
            item_id="good-legacy-item",
            title="Good legacy item title",
            worktree="main",
            priority="medium",
            description="A description longer than ten characters.",
            verifications=[
                {
                    "seq": 1,
                    "description": "it fails first",
                    "command": "make check",
                    "expected": "exits 1 on an unfixed tree",
                }
            ],
        )
        conn.execute("UPDATE items SET created_at = '2026-01-01T00:00:00Z' WHERE id = 'good-legacy-item'")
        todo_db.set_config(conn, "tester", "lint.require_falsifiable_rung", "on")
        assert not [n for n in todo_db.lint_item_notes(conn, "good-legacy-item") if "grandfathered" in n]
def _downgrade(db_path, version):
    """Rewrite the recorded schema version, simulating a clone that never pulled."""
    raw = sqlite3.connect(db_path)
    raw.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(version),))
    raw.commit()
    raw.close()


def _shape(db_path):
    raw = sqlite3.connect(db_path)
    try:
        return sorted(raw.execute("SELECT type, name, sql FROM sqlite_master").fetchall())
    finally:
        raw.close()


class TestSchemaVersionFencesStaleClones:
    """v5 is a write fence, not a shape change (ADR D2/D9).

    The freeze alone is advisory: a clone that never pulled does not know the
    freeze exists and writes straight through it. Moving SCHEMA_VERSION is what
    turns "please don't" into "cannot". The accepted cost is that a stale clone
    loses reads too, because the version check runs before every subcommand.
    """

    @pytest.fixture()
    def stale_db(self, tmp_path):
        db = tmp_path / "todo.sqlite"
        connection = todo_db.connect(db)
        _mk(connection, "existing-item")
        connection.commit()
        connection.close()
        _downgrade(db, todo_db.SCHEMA_VERSION - 1)
        return db

    # These two are RELATIVE to SCHEMA_VERSION, so they survive reverting the bump
    # -- verified by mutation. They do not pin v5; they pin that the fence covers
    # READS as well as writes, which is the design that was chosen over exempting
    # read-only subcommands. Deleting the read case is the regression to catch.
    def test_a_stale_clone_cannot_read(self, stale_db, capsys):
        assert _run(stale_db, "list", actor="bob") == 2
        assert "run `todo migrate`" in capsys.readouterr().err

    def test_a_stale_clone_cannot_write(self, stale_db, capsys):
        assert _run(stale_db, "create", "some-new-item", actor="bob") != 0
        assert "run `todo migrate`" in capsys.readouterr().err

    def test_migrate_lifts_the_fence(self, stale_db, capsys):
        assert _run(stale_db, "migrate", actor="bob") == 0
        capsys.readouterr()
        assert _run(stale_db, "list", actor="bob") == 0

    def test_the_fence_migration_carries_no_ddl(self, tmp_path):
        """v5 must stay empty: a later DDL statement smuggled into the fence
        would make a migrated database diverge from a fresh one."""
        assert todo_db.MIGRATIONS[todo_db.SCHEMA_VERSION] == []
        migrated = tmp_path / "migrated.sqlite"
        todo_db.connect(migrated).close()
        _downgrade(migrated, todo_db.SCHEMA_VERSION - 1)
        assert todo_db.migrate_db(migrated, actor="tester") == [todo_db.SCHEMA_VERSION]
        fresh = tmp_path / "fresh.sqlite"
        todo_db.connect(fresh).close()
        assert _shape(migrated) == _shape(fresh)


class TestTheWedgeIsExplained:
    """A stale clone under a foreign freeze has no working command but `doctor`.

    That wedge is intended -- fencing stale clones out mid-cutover is the point.
    What is NOT acceptable is telling that operator "Reads still work", which the
    refusal did verbatim until the fence landed and made it false.
    """

    @pytest.fixture()
    def frozen_db(self, tmp_path):
        db = tmp_path / "todo.sqlite"
        connection = todo_db.connect(db)
        todo_db.set_freeze(connection, "alice", "cutover", ttl_hours=1)
        connection.commit()
        connection.close()
        return db

    def test_a_wedged_clone_is_not_told_that_reads_work(self, frozen_db, capsys):
        _downgrade(frozen_db, todo_db.SCHEMA_VERSION - 1)
        assert _run(frozen_db, "migrate", actor="bob") == 2
        err = capsys.readouterr().err
        assert "Reads still work" not in err
        assert "reads are fenced too" in err
        assert "`todo doctor` works throughout" in err

    def test_a_current_clone_is_still_told_that_reads_work(self, frozen_db, capsys):
        """Control: the honest message must not be lost for the clone it fits."""
        assert _run(frozen_db, "migrate", actor="bob") == 2
        assert "Reads still work" in capsys.readouterr().err

    def test_doctor_survives_the_wedge(self, frozen_db, capsys):
        """The one command that must keep working, since it is how the operator
        learns why everything else stopped."""
        _downgrade(frozen_db, todo_db.SCHEMA_VERSION - 1)
        _run(frozen_db, "doctor", actor="bob")
        out = capsys.readouterr().out
        assert f"expected v{todo_db.SCHEMA_VERSION}" in out
        assert "run `todo migrate`" in out
