#!/usr/bin/env python3
"""Non-destructive BenchBox YAML shadow-import and semantic comparison.

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
import tempfile
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


class ShadowMigrationError(RuntimeError):
    """Raised when a shadow migration cannot prove a safe comparison."""


def yaml_paths(todo_dir: Path, done_dir: Path | None) -> list[tuple[Path, str]]:
    paths: list[tuple[Path, str]] = []
    for root, source_state in ((todo_dir, "open"), (done_dir, "archived")):
        if root is None:
            continue
        paths.extend((path, source_state) for path in sorted(root.rglob("*.yaml")) if "_indexes" not in path.parts)
    return paths


def validate_target(target: Path, *, benchbox_db: Path, standalone_db: Path) -> None:
    resolved = target.resolve()
    forbidden = {benchbox_db.resolve(), standalone_db.resolve()}
    if resolved in forbidden:
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


def legacy_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    """Read a legacy DB into the same nested item shape as ``export_all``."""

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
    snapshot.update({"items": items, "events": _rows(connection, "events"), "meta": _rows(connection, "meta")})
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
    return (event.get("action"), item_id, detail)


def compare_snapshots(legacy: dict[str, Any], standalone: dict[str, Any]) -> dict[str, Any]:
    legacy_items = {item["id"]: item for item in legacy.get("items", [])}
    standalone_items = {item["id"]: item for item in _standalone_items(standalone)}
    missing = sorted(set(legacy_items) - set(standalone_items))
    unexpected = sorted(set(standalone_items) - set(legacy_items))
    item_diffs = {
        item_id: {"legacy": legacy_items[item_id], "standalone": standalone_items[item_id]}
        for item_id in sorted(set(legacy_items) & set(standalone_items))
        if _json(legacy_items[item_id]) != _json(standalone_items[item_id])
    }
    legacy_events = sorted((_event_signature(event, legacy=True) for event in legacy.get("events", [])), key=_json)
    standalone_events = sorted(
        (_event_signature(event, legacy=False) for event in (standalone.get("events") or [])), key=_json
    )
    event_result = {
        "legacy_count": len(legacy_events),
        "standalone_count": len(standalone_events),
        "legacy_actions": [list(event) for event in legacy_events],
        "standalone_actions": [list(event) for event in standalone_events],
        "equal_provenance": legacy_events == standalone_events,
    }
    table_counts = {
        table: {
            "legacy": len(legacy.get(table, [])) if table != "items" else len(legacy_items),
            "standalone": len((standalone.get("tables") or {}).get(table) or []),
        }
        for table in TABLE_NAMES
    }
    legacy_meta = {row["key"]: row["value"] for row in legacy.get("meta", [])}
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
        and meta_result["equal"]
        and all(counts["legacy"] == counts["standalone"] for counts in table_counts.values())
    )
    return result


def _require_imported_items(snapshot: dict[str, Any], *, source_count: int, importer: str) -> None:
    """Reject a silent all-records import failure before comparison can pass."""
    item_count = len(snapshot.get("items", [])) if importer == "legacy" else len(_standalone_items(snapshot))
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


def run_shadow(
    *,
    repo_root: Path,
    todo_dir: Path,
    done_dir: Path,
    target: Path,
    report_path: Path,
    standalone_project: Path,
    standalone_command: str = "todo-db",
) -> dict[str, Any]:
    sources = yaml_paths(todo_dir, done_dir)
    if not sources:
        raise ShadowMigrationError(
            f"no YAML tracker records found under {todo_dir} or {done_dir}; refusing a false zero-item migration"
        )
    validate_target(
        target,
        benchbox_db=repo_root / ".todo-db" / "todo.sqlite",
        standalone_db=Path("/Users/joe/Developer/todo-db/.todo-db/todo.sqlite"),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.setdefault("TODO_DB_PROJECT_ID", "benchbox")
    environment.setdefault("TODO_DB_REPOSITORY", "https://github.com/joeharris76/BenchBox")
    created_target = False
    export_path: Path | None = None
    legacy_temporary = tempfile.TemporaryDirectory(prefix="benchbox-legacy-shadow-")
    command_reports: list[dict[str, Any]] = []
    try:
        legacy_db = Path(legacy_temporary.name) / "legacy.sqlite"
        command_reports.append(
            _run(
                [
                    "uv",
                    "run",
                    "--project",
                    str(repo_root / "_project" / "scripts"),
                    "--",
                    "python",
                    str(repo_root / "_project" / "scripts" / "todo_db.py"),
                    "--db",
                    str(legacy_db),
                    "init",
                ],
                cwd=repo_root,
                env=environment,
            )
        )
        command_reports.append(
            _run(
                [
                    "uv",
                    "run",
                    "--project",
                    str(repo_root / "_project" / "scripts"),
                    "--",
                    "python",
                    str(repo_root / "_project" / "scripts" / "todo_db.py"),
                    "--db",
                    str(legacy_db),
                    "import-yaml",
                    "--todo-dir",
                    str(todo_dir),
                    "--done-dir",
                    str(done_dir),
                ],
                cwd=repo_root,
                env=environment,
            )
        )
        with sqlite3.connect(legacy_db) as connection:
            legacy = legacy_snapshot(connection)
        _require_imported_items(legacy, source_count=len(sources), importer="legacy")
        created_target = True
        command_reports.append(
            _run(
                [
                    "uv",
                    "run",
                    "--project",
                    str(standalone_project),
                    "--extra",
                    "legacy",
                    standalone_command,
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
        command_reports.append(
            _run(
                [
                    "uv",
                    "run",
                    "--project",
                    str(standalone_project),
                    "--extra",
                    "legacy",
                    standalone_command,
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
        export_path = target.with_suffix(".export.json")
        command_reports.append(
            _run(
                [
                    "uv",
                    "run",
                    "--project",
                    str(standalone_project),
                    "--extra",
                    "legacy",
                    standalone_command,
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
        result = {
            "source": {"todo_dir": str(todo_dir), "done_dir": str(done_dir), "yaml_records": len(sources)},
            "commands": command_reports,
            "comparison": compare_snapshots(legacy, standalone),
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
    finally:
        legacy_temporary.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--todo-dir", type=Path, required=True)
    parser.add_argument("--done-dir", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True, help="new dedicated shadow target; must not exist")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--standalone-project", type=Path, default=Path("/Users/joe/Developer/todo-db"))
    args = parser.parse_args(argv)
    try:
        result = run_shadow(
            repo_root=args.repo_root.resolve(),
            todo_dir=args.todo_dir.resolve(),
            done_dir=args.done_dir.resolve(),
            target=args.db,
            report_path=args.report,
            standalone_project=args.standalone_project.resolve(),
        )
    except (OSError, ShadowMigrationError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_json(result))
    return 0 if result["comparison"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
