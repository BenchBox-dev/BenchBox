#!/usr/bin/env python3
"""Fail closed when the TODO schema, migrations, wrapper, or rollout record drift.

This guard is intentionally stdlib-only so the always-required ``ci-paths`` job
can run it before dependency installation. It parses declarations instead of
importing the tracker, avoiding any backend initialization or credential use.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


class SchemaMigrationError(ValueError):
    """The checked schema-migration contract is incomplete or inconsistent."""


def _integer_assignment(module: ast.Module, name: str, source: Path) -> int:
    for node in module.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, int):
                    return value.value
                raise SchemaMigrationError(f"{source}: {name} must be an integer literal")
    raise SchemaMigrationError(f"{source}: missing {name} assignment")


def _migration_revisions(module: ast.Module, source: Path) -> list[int]:
    for node in module.body:
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == "MIGRATIONS" for target in targets):
            continue
        if not isinstance(value, ast.Dict):
            raise SchemaMigrationError(f"{source}: MIGRATIONS must be a dict literal")
        revisions: list[int] = []
        for key, statements in zip(value.keys, value.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, int):
                raise SchemaMigrationError(f"{source}: every MIGRATIONS key must be an integer literal")
            if isinstance(statements, (ast.List, ast.Tuple)) and not statements.elts:
                raise SchemaMigrationError(f"{source}: migration {key.value} has no statements")
            revisions.append(key.value)
        return revisions
    raise SchemaMigrationError(f"{source}: missing MIGRATIONS assignment")


def validate_contract(*, tracker: Path, wrapper: Path, inventory: Path) -> None:
    module = ast.parse(tracker.read_text(encoding="utf-8"), filename=str(tracker))
    schema_version = _integer_assignment(module, "SCHEMA_VERSION", tracker)
    revisions = _migration_revisions(module, tracker)
    expected_revisions = list(range(2, schema_version + 1))
    if revisions != expected_revisions:
        raise SchemaMigrationError(
            f"{tracker}: migration revisions {revisions!r} must be ordered and contiguous {expected_revisions!r}"
        )

    wrapper_text = wrapper.read_text(encoding="utf-8")
    wrapper_match = re.search(r"(?m)^TODO_SCHEMA_VERSION=([0-9]+)$", wrapper_text)
    if wrapper_match is None:
        raise SchemaMigrationError(f"{wrapper}: missing literal TODO_SCHEMA_VERSION declaration")
    wrapper_version = int(wrapper_match.group(1))
    if wrapper_version != schema_version:
        raise SchemaMigrationError(
            f"{wrapper}: TODO_SCHEMA_VERSION={wrapper_version} does not match CLI schema {schema_version}"
        )

    try:
        inventory_text = inventory.read_text(encoding="utf-8")
        record = json.loads(inventory_text)
    except (json.JSONDecodeError, OSError) as exc:
        raise SchemaMigrationError(f"{inventory}: cannot read migration inventory: {exc}") from exc
    if re.search(r"(?i)(?:libsql://|TODO_DB_AUTH_TOKEN|(?:auth[_-]?)?token\s*[:=])", inventory_text):
        raise SchemaMigrationError(f"{inventory}: migration inventory must not contain backend URLs or tokens")
    if record.get("schema_version") != schema_version:
        raise SchemaMigrationError(
            f"{inventory}: schema_version={record.get('schema_version')!r} does not match CLI schema {schema_version}"
        )
    entries = record.get("migrations")
    if not isinstance(entries, list):
        raise SchemaMigrationError(f"{inventory}: migrations must be a list")
    inventory_revisions = [entry.get("revision") for entry in entries if isinstance(entry, dict)]
    if len(inventory_revisions) != len(entries) or inventory_revisions != revisions:
        raise SchemaMigrationError(
            f"{inventory}: revisions {inventory_revisions!r} do not match runtime migrations {revisions!r}"
        )
    for entry in entries:
        revision = entry["revision"]
        for field in ("summary", "deployment_order"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise SchemaMigrationError(f"{inventory}: revision {revision} needs non-empty {field}")
    current = entries[-1]
    evidence = current.get("deployment_evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise SchemaMigrationError(
            f"{inventory}: current revision {schema_version} needs sanitized deployment_evidence"
        )
    evidence_path = Path(evidence)
    if evidence_path.is_absolute() or ".." in evidence_path.parts:
        raise SchemaMigrationError(f"{inventory}: deployment_evidence must be a repository-relative path")
    repo_root = tracker.resolve().parents[2]
    if not (repo_root / evidence_path).is_file():
        raise SchemaMigrationError(f"{inventory}: deployment_evidence path does not exist")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    validate_contract(
        tracker=root / "_project/scripts/todo_db.py",
        wrapper=root / "_project/scripts/todo",
        inventory=root / "_project/todo-schema-migrations.json",
    )
    print("TODO schema migration contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
