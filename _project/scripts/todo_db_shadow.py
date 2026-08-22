#!/usr/bin/env python3
"""Non-destructive BenchBox YAML shadow-import and export-fidelity check.

The command deliberately requires a fresh, explicit target database.  It will
not use either BenchBox's live database or the standalone project's planning
database, and it refuses an empty YAML source so an absent legacy tree cannot
be reported as a successful zero-item migration.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TABLE_NAMES = (
    "items",
    "work_units",
    "work_needs",
    "item_deps",
    "scope_rules",
    "verifications",
    "preserves",
    "anti_patterns",
    "prior_art",
    "deferrals",
)
FINDING_TABLE_NAMES = (
    "findings",
    "finding_evidence",
    "finding_links",
    "finding_events",
    "finding_sections",
)


class ShadowMigrationError(RuntimeError):
    """Raised when a shadow migration cannot prove a safe comparison."""


def yaml_paths(todo_dir: Path, done_dir: Path | None) -> list[tuple[Path, str]]:
    paths: list[tuple[Path, str]] = []
    for root, source_state in ((todo_dir, "open"), (done_dir, "archived")):
        if root is None:
            continue
        paths.extend((path, source_state) for path in sorted(root.rglob("*.yaml")) if "_indexes" not in path.parts)
    return paths


def validate_target(target: Path, *, benchbox_db: Path) -> None:
    resolved = target.resolve()
    if resolved == benchbox_db.resolve():
        raise ShadowMigrationError(f"refusing protected tracker database: {resolved}")
    if target.exists() or target.is_symlink():
        raise ShadowMigrationError(f"shadow target must not already exist: {target}")
    export_path = target.with_suffix(".export.json")
    if export_path.exists() or export_path.is_symlink():
        raise ShadowMigrationError(f"shadow export path must not already exist: {export_path}")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    order_by = {
        "events": "seq",
        "meta": "key",
        "metadata": "key",
        "work_units": "item_id, wid",
        "work_needs": "item_id, wid, needs_wid",
        "item_deps": "item_id, needs_item",
        "scope_rules": "item_id, kind, path_glob",
        "verifications": "item_id, seq",
        "preserves": "item_id, behavior",
        "anti_patterns": "item_id, dont",
        "prior_art": "item_id, path, concept",
        "deferrals": "from_item, id",
    }.get(table, "rowid")
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order_by}")]


def write_hosted_legacy_snapshot(connection: Any, output: Path) -> dict[str, int]:
    """Write one bulk-query-per-table legacy snapshot without exposing credentials."""

    if output.exists() or output.is_symlink():
        raise ShadowMigrationError(f"hosted snapshot target must not already exist: {output}")
    table_names = ("items", *(name for name in TABLE_NAMES if name != "items"), *FINDING_TABLE_NAMES, "events", "meta")
    snapshot = {table: _rows(connection, table) for table in table_names}
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(_json(snapshot) + "\n")
    return {table: len(rows) for table, rows in snapshot.items()}


def capture_hosted_legacy_snapshot(*, repo_root: Path, url: str, output: Path) -> dict[str, int]:
    """Connect to the legacy hosted primary in read-only mode and capture it."""

    from todo_db.backends import connect
    from todo_db.models import CredentialMode, DatabaseConfig

    del repo_root  # Retained for CLI compatibility with the pre-cutover command.
    token = os.environ.get("TODO_DB_RO_AUTH_TOKEN", "")
    if not token:
        raise ShadowMigrationError("hosted snapshot requires TODO_DB_RO_AUTH_TOKEN carrying read-only authority")
    try:
        connection = connect(DatabaseConfig(path=url, credential_mode=CredentialMode.READ_ONLY, auth_token=token))
    except Exception as exc:
        message = str(exc).replace(url, "[REDACTED]")
        if token:
            message = message.replace(token, "[REDACTED]")
        raise ShadowMigrationError(f"hosted snapshot connection failed: {message}") from exc
    try:
        return write_hosted_legacy_snapshot(connection, output)
    except Exception as exc:
        message = str(exc).replace(url, "[REDACTED]")
        if token:
            message = message.replace(token, "[REDACTED]")
        raise ShadowMigrationError(f"hosted snapshot failed: {message}") from exc
    finally:
        connection.close()


def database_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    """Read the package database into the same nested item shape as its export."""

    connection.row_factory = sqlite3.Row
    items = []
    for row in connection.execute("SELECT id FROM items ORDER BY id"):
        item = dict(connection.execute("SELECT * FROM items WHERE id = ?", (row["id"],)).fetchone())
        item_id = item["id"]
        item["work"] = []
        for unit in connection.execute("SELECT * FROM work_units WHERE item_id = ? ORDER BY wid", (item_id,)):
            child = dict(unit)
            child["needs"] = [
                edge["needs_wid"]
                for edge in connection.execute(
                    "SELECT needs_wid FROM work_needs WHERE item_id = ? AND wid = ? ORDER BY needs_wid",
                    (item_id, unit["wid"]),
                )
            ]
            item["work"].append(child)
        item["deps"] = [
            row["needs_item"]
            for row in connection.execute(
                "SELECT needs_item FROM item_deps WHERE item_id = ? ORDER BY needs_item", (item_id,)
            )
        ]
        for name, query, params in (
            ("scope", "SELECT kind, path_glob FROM scope_rules WHERE item_id = ? ORDER BY kind, path_glob", (item_id,)),
            ("verifications", "SELECT * FROM verifications WHERE item_id = ? ORDER BY seq", (item_id,)),
            (
                "anti_patterns",
                "SELECT dont, why, instead FROM anti_patterns WHERE item_id = ? ORDER BY dont",
                (item_id,),
            ),
            (
                "prior_art",
                "SELECT path, concept, decision FROM prior_art WHERE item_id = ? ORDER BY path, concept",
                (item_id,),
            ),
            ("deferrals", "SELECT * FROM deferrals WHERE from_item = ? ORDER BY id", (item_id,)),
        ):
            values = [dict(child) for child in connection.execute(query, params)]
            item[name] = values
            if name == "scope":
                item[name] = values
        item["preserves"] = [
            row["behavior"]
            for row in connection.execute(
                "SELECT behavior FROM preserves WHERE item_id = ? ORDER BY behavior", (item_id,)
            )
        ]
        items.append(item)
    snapshot = {table: _rows(connection, table) for table in TABLE_NAMES if table != "items"}
    snapshot.update({"items": items, "events": _rows(connection, "events"), "meta": _rows(connection, "metadata")})
    return snapshot


def _standalone_items(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(envelope, dict) or not isinstance(envelope.get("tables"), dict):
        raise ShadowMigrationError("standalone export envelope must contain an object-valued items table collection")
    tables = envelope["tables"]
    if not isinstance(tables.get("items"), list):
        raise ShadowMigrationError("standalone export envelope must contain an items table")
    items = [dict(row) for row in tables.get("items") or []]
    for item in items:
        item_id = item["id"]
        item["work"] = []
        for unit in tables.get("work_units") or []:
            if unit["item_id"] != item_id:
                continue
            child = dict(unit)
            child["needs"] = sorted(
                edge["needs_wid"]
                for edge in tables.get("work_needs") or []
                if edge["item_id"] == item_id and edge["wid"] == unit["wid"]
            )
            item["work"].append(child)
        item["deps"] = sorted(
            edge["needs_item"] for edge in tables.get("item_deps") or [] if edge["item_id"] == item_id
        )
        item["scope"] = sorted(
            (
                {key: value for key, value in dict(row).items() if key != "item_id"}
                for row in tables.get("scope_rules") or []
                if row["item_id"] == item_id
            ),
            key=lambda row: (row["kind"], row["path_glob"]),
        )
        item["verifications"] = sorted(
            (dict(row) for row in tables.get("verifications") or [] if row["item_id"] == item_id),
            key=lambda row: row["seq"],
        )
        item["preserves"] = sorted(
            row["behavior"] for row in tables.get("preserves") or [] if row["item_id"] == item_id
        )
        item["anti_patterns"] = sorted(
            (
                {key: value for key, value in dict(row).items() if key != "item_id"}
                for row in tables.get("anti_patterns") or []
                if row["item_id"] == item_id
            ),
            key=lambda row: row["dont"],
        )
        item["prior_art"] = sorted(
            (
                {key: value for key, value in dict(row).items() if key != "item_id"}
                for row in tables.get("prior_art") or []
                if row["item_id"] == item_id
            ),
            key=lambda row: (row["path"], row["concept"]),
        )
        item["deferrals"] = sorted(
            (dict(row) for row in tables.get("deferrals") or [] if row["from_item"] == item_id),
            key=lambda row: row["id"],
        )
    return sorted(items, key=lambda row: row["id"])


def _event_signature(event: dict[str, Any], *, legacy: bool) -> tuple[Any, ...]:
    detail = event.get("detail")
    if isinstance(detail, str):
        detail = json.loads(detail)
    detail = dict(detail or {})
    item_id = event.get("item_id")
    if not legacy:
        item_id = detail.pop("item_id", None)
    if event.get("action") == "defer":
        detail.pop("deferral_id", None)
    return (event.get("action"), item_id, detail)


def _timestamp_in_window(value: Any, import_window: tuple[datetime, datetime] | None) -> bool:
    if not isinstance(value, str) or import_window is None:
        return False
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if timestamp.tzinfo is None:
        return False
    return import_window[0] <= timestamp <= import_window[1]


def _semantic_item(
    item: dict[str, Any], *, peer: dict[str, Any], import_window: tuple[datetime, datetime] | None
) -> dict[str, Any]:
    """Remove only database-generated identities while retaining durable source values."""

    normalized = dict(item)
    if _timestamp_in_window(normalized.get("created_at"), import_window) and _timestamp_in_window(
        peer.get("created_at"), import_window
    ):
        normalized.pop("created_at", None)
    normalized["deferrals"] = [
        {key: value for key, value in deferral.items() if key not in {"id", "created_at"}}
        for deferral in normalized.get("deferrals", [])
    ]
    return normalized


def compare_snapshots(
    legacy: dict[str, Any],
    standalone: dict[str, Any],
    *,
    import_window: tuple[datetime, datetime] | None = None,
    source_is_package: bool = False,
) -> dict[str, Any]:
    legacy_items = {item["id"]: item for item in legacy.get("items", [])}
    standalone_items = {item["id"]: item for item in _standalone_items(standalone)}
    missing = sorted(set(legacy_items) - set(standalone_items))
    unexpected = sorted(set(standalone_items) - set(legacy_items))
    item_diffs = {
        item_id: {"legacy": legacy_items[item_id], "standalone": standalone_items[item_id]}
        for item_id in sorted(set(legacy_items) & set(standalone_items))
        if _json(_semantic_item(legacy_items[item_id], peer=standalone_items[item_id], import_window=import_window))
        != _json(_semantic_item(standalone_items[item_id], peer=legacy_items[item_id], import_window=import_window))
    }
    legacy_events = sorted(
        (_event_signature(event, legacy=not source_is_package) for event in legacy.get("events", [])), key=_json
    )
    all_standalone_events = sorted(
        (_event_signature(event, legacy=False) for event in (standalone.get("events") or [])), key=_json
    )
    if source_is_package:
        standalone_events = all_standalone_events
        dependency_events: list[tuple[Any, ...]] = []
        expected_dependency_events: list[tuple[Any, ...]] = []
    else:
        standalone_events = [event for event in all_standalone_events if event[0] != "dependency"]
        dependency_events = [event for event in all_standalone_events if event[0] == "dependency"]
        expected_dependency_events = sorted(
            [
                ("dependency", row["item_id"], {"needs_item": row["needs_item"]})
                for row in (standalone.get("tables") or {}).get("item_deps") or []
            ],
            key=_json,
        )
    supplemental_actions = {
        "dependency": len(dependency_events),
    }
    event_result = {
        "legacy_count": len(legacy_events),
        "standalone_count": len(all_standalone_events),
        "legacy_actions": [list(event) for event in legacy_events],
        "standalone_actions": [list(event) for event in all_standalone_events],
        "standalone_supplemental_actions": supplemental_actions,
        "supplemental_provenance_equal": dependency_events == expected_dependency_events,
        "equal_provenance": legacy_events == standalone_events,
    }
    table_counts = {
        table: {
            "legacy": len(legacy.get(table, [])) if table != "items" else len(legacy_items),
            "standalone": len((standalone.get("tables") or {}).get(table) or []),
        }
        for table in TABLE_NAMES
    }
    legacy_meta = {row["key"]: row["value"] for row in legacy.get("meta", []) if row["key"] != "schema_version"}
    standalone_meta = standalone.get("metadata") or {}
    meta_result = {"legacy": legacy_meta, "standalone": standalone_meta, "equal": legacy_meta == standalone_meta}
    result = {
        "format_version": 1,
        "items": {
            "legacy_count": len(legacy_items),
            "standalone_count": len(standalone_items),
            "missing": missing,
            "unexpected": unexpected,
            "field_diffs": item_diffs,
        },
        "table_counts": table_counts,
        "events": event_result,
        "meta": meta_result,
    }
    result["passed"] = (
        not missing
        and not unexpected
        and not item_diffs
        and event_result["equal_provenance"]
        and event_result["supplemental_provenance_equal"]
        and meta_result["equal"]
        and all(counts["legacy"] == counts["standalone"] for counts in table_counts.values())
    )
    return result


def _require_imported_items(snapshot: dict[str, Any], *, source_count: int, importer: str) -> None:
    """Reject a silent all-records import failure before comparison can pass."""
    item_count = (
        len(snapshot.get("items", [])) if importer in {"legacy", "database"} else len(_standalone_items(snapshot))
    )
    if source_count and item_count == 0:
        raise ShadowMigrationError(
            f"{importer} import produced zero items for {source_count} YAML records; "
            "refusing a false zero-item migration"
        )


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    secrets = (env.get("TODO_DB_AUTH_TOKEN", ""), env.get("TODO_DB_RO_AUTH_TOKEN", ""))
    stdout = result.stdout
    stderr = result.stderr
    for secret in secrets:
        if secret:
            stdout = stdout.replace(secret, "[REDACTED]")
            stderr = stderr.replace(secret, "[REDACTED]")
    if result.returncode:
        raise ShadowMigrationError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout={stdout[-2000:]}\nstderr={stderr[-2000:]}"
        )
    return {"stdout": stdout, "stderr": stderr, "returncode": result.returncode}


def _canonical_todo_command(repo_root: Path) -> list[str]:
    """Return the only supported canonical CLI route for this repository.

    The package is resolved by BenchBox's isolated ``uv`` project and its lock
    state.  There is deliberately no PATH fallback, sibling checkout, or
    developer-machine path: an absent or incompatible package must fail closed.
    """

    scripts_project = repo_root / "_project" / "scripts"
    if not (scripts_project / "pyproject.toml").is_file():
        raise ShadowMigrationError(f"BenchBox scripts project is missing: {scripts_project}")
    if not (scripts_project / "uv.lock").is_file():
        raise ShadowMigrationError(f"BenchBox scripts lockfile is missing: {scripts_project / 'uv.lock'}")
    return ["uv", "run", "--project", str(scripts_project), "--locked", "--", "todo-db"]


def run_shadow(
    *,
    repo_root: Path,
    todo_dir: Path,
    done_dir: Path,
    target: Path,
    report_path: Path,
) -> dict[str, Any]:
    sources = yaml_paths(todo_dir, done_dir)
    if not sources:
        raise ShadowMigrationError(
            f"no YAML tracker records found under {todo_dir} or {done_dir}; refusing a false zero-item migration"
        )
    validate_target(
        target,
        benchbox_db=repo_root / ".todo-db" / "todo.sqlite",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["TODO_DB_PROJECT_ID"] = "benchbox"
    environment["TODO_DB_REPOSITORY"] = "https://github.com/joeharris76/BenchBox"
    created_target = False
    export_path: Path | None = None
    command_reports: list[dict[str, Any]] = []
    import_started_at = datetime.now(timezone.utc)
    try:
        canonical_command = _canonical_todo_command(repo_root)
        command_reports.append(
            _run(
                [
                    *canonical_command,
                    "--db",
                    str(target),
                    "init",
                    "--project-id",
                    "benchbox",
                    "--repository",
                    "https://github.com/joeharris76/BenchBox",
                ],
                cwd=repo_root,
                env=environment,
            )
        )
        created_target = True
        command_reports.append(
            _run(
                [
                    *canonical_command,
                    "--db",
                    str(target),
                    "import-yaml",
                    "--todo-dir",
                    str(todo_dir),
                    "--done-dir",
                    str(done_dir),
                    "--project-id",
                    "benchbox",
                    "--repository",
                    "https://github.com/joeharris76/BenchBox",
                ],
                cwd=repo_root,
                env=environment,
            )
        )
        with sqlite3.connect(target) as connection:
            raw_database = database_snapshot(connection)
        _require_imported_items(raw_database, source_count=len(sources), importer="database")
        export_path = target.with_suffix(".export.json")
        command_reports.append(
            _run(
                [
                    *canonical_command,
                    "--db",
                    str(target),
                    "export",
                    "--output",
                    str(export_path),
                    "--project-id",
                    "benchbox",
                    "--repository",
                    "https://github.com/joeharris76/BenchBox",
                ],
                cwd=repo_root,
                env=environment,
            )
        )
        standalone = json.loads(export_path.read_text(encoding="utf-8"))
        _require_imported_items(standalone, source_count=len(sources), importer="standalone")
        import_finished_at = datetime.now(timezone.utc)
        result = {
            "source": {"todo_dir": str(todo_dir), "done_dir": str(done_dir), "yaml_records": len(sources)},
            "commands": command_reports,
            "comparison": compare_snapshots(
                raw_database,
                standalone,
                import_window=(import_started_at, import_finished_at),
                source_is_package=True,
            ),
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_json(result) + "\n", encoding="utf-8")
        return result
    except Exception:
        if created_target and target.is_file():
            target.unlink()
        if export_path is not None and export_path.is_file():
            export_path.unlink()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--todo-dir", type=Path)
    parser.add_argument("--done-dir", type=Path)
    parser.add_argument("--db", type=Path, help="new dedicated shadow target; must not exist")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--hosted-url", help="legacy hosted source URL; never written to output")
    parser.add_argument("--hosted-snapshot-output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.hosted_snapshot_output:
            if not args.hosted_url:
                raise ShadowMigrationError("--hosted-snapshot-output requires --hosted-url")
            counts = capture_hosted_legacy_snapshot(
                repo_root=args.repo_root.resolve(),
                url=args.hosted_url,
                output=args.hosted_snapshot_output,
            )
            print(_json({"snapshot": str(args.hosted_snapshot_output), "counts": counts}))
            return 0
        if not all((args.todo_dir, args.done_dir, args.db, args.report)):
            raise ShadowMigrationError("shadow mode requires --todo-dir, --done-dir, --db, and --report")
        result = run_shadow(
            repo_root=args.repo_root.resolve(),
            todo_dir=args.todo_dir.resolve(),
            done_dir=args.done_dir.resolve(),
            target=args.db,
            report_path=args.report,
        )
    except (OSError, ShadowMigrationError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_json(result))
    return 0 if result["comparison"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
