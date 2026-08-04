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


def _migration_revisions(module: ast.Module, source: Path) -> tuple[list[int], set[int]]:
    """Returns the declared revisions and which of them carry no statements.

    An empty migration is no longer rejected outright: a FENCE migration (one
    that moves SCHEMA_VERSION purely to lock out stale clones, ADR D2/D9) has no
    DDL by design. It is still rejected unless the inventory declares it as one,
    so the case this guard actually exists for -- a builder that silently returns
    [] -- fails exactly as before.
    """
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
        empty: set[int] = set()
        for key, statements in zip(value.keys, value.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, int):
                raise SchemaMigrationError(f"{source}: every MIGRATIONS key must be an integer literal")
            if isinstance(statements, (ast.List, ast.Tuple)) and not statements.elts:
                empty.add(key.value)
            revisions.append(key.value)
        return revisions, empty
    raise SchemaMigrationError(f"{source}: missing MIGRATIONS assignment")


def _migration_statement_counts(module: ast.Module, source: Path) -> dict[int, int]:
    for node in module.body:
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == "MIGRATION_STATEMENT_COUNTS" for target in targets):
            continue
        if not isinstance(value, ast.Dict):
            raise SchemaMigrationError(f"{source}: MIGRATION_STATEMENT_COUNTS must be a dict literal")
        counts: dict[int, int] = {}
        for key, count in zip(value.keys, value.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, int):
                raise SchemaMigrationError(f"{source}: every migration-count key must be an integer literal")
            # 0 is legal only for a fence migration, cross-checked against the
            # inventory below; a negative or non-integer count is never legal.
            if not isinstance(count, ast.Constant) or not isinstance(count.value, int) or count.value < 0:
                raise SchemaMigrationError(f"{source}: migration {key.value} needs a non-negative statement count")
            counts[key.value] = count.value
        return counts
    raise SchemaMigrationError(f"{source}: missing MIGRATION_STATEMENT_COUNTS assignment")


def _check_fence_declaration(
    entry: dict,
    *,
    revision: int,
    expected_count: int,
    is_empty: bool,
    inventory: Path,
) -> None:
    """A statement-free migration must be an explicit, reasoned fence, and a
    migration declared as a fence must genuinely carry no DDL.

    Both directions are enforced: the first keeps an accidentally-empty migration
    failing closed (the case this guard was written for), the second keeps
    "fence" from becoming a label that ships unreviewed DDL under a claim that
    there is none.
    """
    declared_fence = entry.get("kind") == "fence"
    if is_empty and not declared_fence:
        raise SchemaMigrationError(
            f'{inventory}: revision {revision} has no statements; declare "kind": "fence" '
            f"with a fence_rationale, or give the migration real DDL"
        )
    if not declared_fence:
        return
    if not is_empty:
        raise SchemaMigrationError(
            f'{inventory}: revision {revision} is declared "kind": "fence" but carries '
            f"{expected_count} statement(s); a fence must carry no DDL"
        )
    rationale = entry.get("fence_rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise SchemaMigrationError(f"{inventory}: fence revision {revision} needs a non-empty fence_rationale")


def validate_contract(*, tracker: Path, wrapper: Path, inventory: Path) -> None:
    module = ast.parse(tracker.read_text(encoding="utf-8"), filename=str(tracker))
    schema_version = _integer_assignment(module, "SCHEMA_VERSION", tracker)
    revisions, empty_revisions = _migration_revisions(module, tracker)
    statement_counts = _migration_statement_counts(module, tracker)
    expected_revisions = list(range(2, schema_version + 1))
    if revisions != expected_revisions:
        raise SchemaMigrationError(
            f"{tracker}: migration revisions {revisions!r} must be ordered and contiguous {expected_revisions!r}"
        )
    if list(statement_counts) != revisions:
        raise SchemaMigrationError(
            f"{tracker}: migration statement counts {list(statement_counts)!r} must match revisions {revisions!r}"
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
        expected_count = statement_counts[revision]
        if entry.get("statement_count") != expected_count:
            raise SchemaMigrationError(
                f"{inventory}: revision {revision} statement_count={entry.get('statement_count')!r} "
                f"does not match runtime contract {expected_count}"
            )
        _check_fence_declaration(
            entry,
            revision=revision,
            expected_count=expected_count,
            is_empty=revision in empty_revisions or expected_count == 0,
            inventory=inventory,
        )
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
