#!/usr/bin/env python3
"""BenchBox compatibility verbs absent from the locked ``todo-db`` release.

The standalone package still owns connection, identity, migration, and audit
verification. This module only reuses BenchBox's existing audited renew/freeze
operations against that package-opened connection during the compatibility
window. Remove it when the released package exposes the same verbs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path = [entry for entry in sys.path if Path(entry or ".").resolve() != SCRIPTS_DIR]
MODULE_ROOT = SCRIPTS_DIR.parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from todo_db.backends import CredentialMode
from todo_db.cli import _config, _discover_repo_config, _resolve_db, _resolve_identity
from todo_db.database import TodoDatabase
from todo_db.errors import TodoDBError, TodoError
from todo_db.tracker import DEFAULT_LEASE_TTL_HOURS, TodoTracker, _lease_expired, utc_now

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(SCRIPTS_DIR))

from _project.scripts import todo_db as legacy  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db")
    parser.add_argument("--replica", type=Path)
    parser.add_argument("--actor")
    parser.add_argument("--project-id")
    parser.add_argument("--repository")
    sub = parser.add_subparsers(dest="command", required=True)

    renew = sub.add_parser("renew")
    renew.add_argument("id")

    freeze = sub.add_parser("freeze")
    group = freeze.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true")
    group.add_argument("--release", action="store_true")
    freeze.add_argument("--reason", default="")
    freeze.add_argument("--ttl", type=float, default=legacy.DEFAULT_FREEZE_TTL_HOURS)
    freeze.add_argument("--force", action="store_true")
    sub.add_parser("freeze-guard")
    sub.add_parser("activity")
    return parser


def _open_database(args: argparse.Namespace, mode: CredentialMode = CredentialMode.READ_WRITE) -> TodoDatabase:
    discovered = _discover_repo_config()
    identity = _resolve_identity(args, discovered)
    args.db = _resolve_db(args.db, discovered)
    return TodoDatabase.open(_config(args, mode, identity))


def _renew(tracker: TodoTracker, item_id: str) -> str:
    with tracker.database.transaction():
        item = tracker._require_item(item_id)
        holder = item["claimed_by"]
        if holder is None:
            raise TodoError(f"{item_id!r} is not claimed; use `todo claim {item_id}` to take it")
        if holder != tracker.actor:
            raise TodoError(
                f"{item_id!r} is claimed by {holder!r}, not {tracker.actor!r}; only the holder can renew it"
            )
        if _lease_expired(item["claimed_at"], DEFAULT_LEASE_TTL_HOURS):
            raise TodoError(
                f"{item_id!r}'s lease expired at {item['claimed_at']} and may already have been swept or reassigned; "
                f"re-acquire it with `todo claim {item_id}`"
            )
        stamp = utc_now()
        tracker.connection.execute(
            "UPDATE items SET claimed_at = ? WHERE id = ? AND claimed_by = ? AND claimed_at IS ?",
            (stamp, item_id, tracker.actor, item["claimed_at"]),
        )
        if tracker.connection.execute("SELECT changes() AS n").fetchone()["n"] != 1:
            raise TodoError(f"{item_id!r}'s lease changed hands concurrently; re-check with `todo show {item_id}`")
        tracker._event("renew", item_id, {"previous_claimed_at": item["claimed_at"]})
    return stamp


def _set_freeze(tracker: TodoTracker, reason: str, ttl_hours: float) -> dict[str, object]:
    ttl = legacy._coerce_freeze_ttl(ttl_hours)
    if ttl is None or ttl <= 0:
        raise TodoError(
            "freeze --ttl must be positive and finite; an unbounded freeze is exactly the stuck lock this avoids"
        )
    if ttl > legacy.MAX_FREEZE_TTL_HOURS:
        raise TodoError(
            f"freeze --ttl must not exceed {legacy.MAX_FREEZE_TTL_HOURS:g}h; use a renewable bounded lease instead"
        )
    with tracker.database.transaction():
        live = legacy.get_freeze(tracker.connection)
        if live and live["holder"] != tracker.actor:
            raise TodoError(f"freeze is already held by {live['holder']} since {live['since']}")
        stamp = utc_now()
        values = {
            legacy.FREEZE_HOLDER_KEY: tracker.actor,
            legacy.FREEZE_AT_KEY: stamp,
            legacy.FREEZE_REASON_KEY: reason,
            legacy.FREEZE_TTL_KEY: str(ttl),
        }
        for key, value in values.items():
            tracker.connection.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        tracker._event("freeze", None, {"reason": reason, "ttl_hours": ttl})
    return {"holder": tracker.actor, "since": stamp, "reason": reason, "ttl_hours": ttl}


def _clear_freeze(tracker: TodoTracker, *, force: bool) -> bool:
    with tracker.database.transaction():
        live = legacy.get_freeze(tracker.connection)
        if live and live["holder"] != tracker.actor and not force:
            raise TodoError(
                f"freeze is held by {live['holder']}, not {tracker.actor}; "
                "wait for its lease to lapse or override with `todo freeze --release --force`"
            )
        had_rows = tracker.connection.execute(
            "SELECT 1 FROM meta WHERE key = ?", (legacy.FREEZE_HOLDER_KEY,)
        ).fetchone()
        for key in (
            legacy.FREEZE_HOLDER_KEY,
            legacy.FREEZE_AT_KEY,
            legacy.FREEZE_REASON_KEY,
            legacy.FREEZE_TTL_KEY,
        ):
            tracker.connection.execute("DELETE FROM meta WHERE key = ?", (key,))
        if had_rows:
            tracker._event("unfreeze", None, {"released_holder": live["holder"] if live else None})
    return had_rows is not None


def _run(args: argparse.Namespace) -> int:
    actor = args.actor or legacy.default_actor()
    mode = CredentialMode.READ_ONLY if args.command in {"freeze-guard", "activity"} else CredentialMode.READ_WRITE
    with _open_database(args, mode) as database:
        tracker = TodoTracker(database, actor=actor)
        if args.command == "activity":
            print(
                legacy.json.dumps(
                    {
                        "events": legacy.write_activity(tracker.connection),
                        "stale": bool(getattr(tracker.connection, "stale", False)),
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "freeze-guard":
            live = legacy.get_freeze(tracker.connection)
            if live and live["holder"] != tracker.actor:
                print(legacy._freeze_refusal_message(live), file=sys.stderr)
                return 2
            return 0
        if args.command == "renew":
            renewed = _renew(tracker, args.id)
            print(f"renewed {args.id}; lease now runs from {renewed}")
            return 0
        if args.status:
            live = legacy.get_freeze(tracker.connection)
            print(legacy.json.dumps(live, indent=2, sort_keys=True) if live else "no live freeze")
            return 0
        if args.release:
            print("freeze lifted" if _clear_freeze(tracker, force=args.force) else "no live freeze to lift")
            return 0
        held = _set_freeze(tracker, args.reason, args.ttl)
        print(
            f"tracker frozen by {held['holder']} at {held['since']} for {held['ttl_hours']}h"
            f"{': ' + held['reason'] if held['reason'] else ''}"
        )
        print("other actors' writes now fail; reads are unaffected. Lift with `todo freeze --release`.")
        return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(_parser().parse_args(argv))
    except (TodoDBError, TodoError, OSError, ValueError, legacy.sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
