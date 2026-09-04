#!/usr/bin/env python3
"""Render the version-controlled items-domain views from a ``todo-db`` envelope.

The floor ``todo-db export`` command (0.6.0+) emits a single lossless JSON
envelope via ``--output FILE``: project identity, metadata, migrations, every
table, and the audit trail. The weekly export workflow still needs the three
committed files that used to be produced by the retired
``_project/scripts/todo`` shim -- ``items.jsonl``, ``events.jsonl`` and
``index.md`` -- so this script consumes that envelope and writes them.

Only the items domain is rendered. ``_item_rows`` joins ``items`` with
``work_units``, ``work_needs``, ``item_deps``, ``scope_rules``,
``verifications``, ``preserves``, ``anti_patterns``, ``prior_art`` and
``deferrals`` (all under ``tables``), plus the top-level ``events`` list. It
never reads any ``findings*`` table. This is deliberate: the findings domain
carries review prose that is not version-controlled and travels only via the
workflow's 90-day CI artifact channel (see
``_project/specs/findings-domain.md``). ``claim_token`` is stripped from every
item -- claim generation tokens coordinate private mutations and belong only in
the lossless recovery artifact.

The lossless envelope itself is copied verbatim to ``--lossless-out`` (a CI
staging directory), never under ``--out``, so the workflow's ``git add`` can
never stage it.

Output is byte-identical to the retired shim's adapter path, so the committed
``_project/todo-db-export/`` diff stays stable across the switch. stdlib only.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any


def _item_rows(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    tables = envelope.get("tables") or {}
    items = [dict(row) for row in tables.get("items") or []]
    units = tables.get("work_units") or []
    needs = tables.get("work_needs") or []
    deps = tables.get("item_deps") or []
    scope = tables.get("scope_rules") or []
    verifications = tables.get("verifications") or []
    preserves = tables.get("preserves") or []
    anti_patterns = tables.get("anti_patterns") or []
    prior_art = tables.get("prior_art") or []
    deferrals = tables.get("deferrals") or []
    for item in items:
        # Claim generation tokens coordinate private mutations and must remain
        # only in the separate lossless recovery artifact, never public views.
        item.pop("claim_token", None)
        item_id = item["id"]
        item["work"] = []
        for unit in units:
            if unit["item_id"] != item_id:
                continue
            child = dict(unit)
            child["needs"] = sorted(
                edge["needs_wid"] for edge in needs if edge["item_id"] == item_id and edge["wid"] == unit["wid"]
            )
            item["work"].append(child)
        item["work"].sort(key=lambda row: row["wid"])
        item["deps"] = sorted(edge["needs_item"] for edge in deps if edge["item_id"] == item_id)
        item["scope"] = sorted(
            (
                {key: value for key, value in dict(row).items() if key != "item_id"}
                for row in scope
                if row["item_id"] == item_id
            ),
            key=lambda row: (row["kind"], row["path_glob"]),
        )
        item["verifications"] = sorted(
            (dict(row) for row in verifications if row["item_id"] == item_id), key=lambda row: row["seq"]
        )
        item["preserves"] = sorted(row["behavior"] for row in preserves if row["item_id"] == item_id)
        item["anti_patterns"] = sorted(
            (
                {key: value for key, value in dict(row).items() if key != "item_id"}
                for row in anti_patterns
                if row["item_id"] == item_id
            ),
            key=lambda row: row["dont"],
        )
        item["prior_art"] = sorted(
            (
                {key: value for key, value in dict(row).items() if key != "item_id"}
                for row in prior_art
                if row["item_id"] == item_id
            ),
            key=lambda row: (row["path"], row["concept"]),
        )
        item["deferrals"] = sorted(
            (dict(row) for row in deferrals if row["from_item"] == item_id), key=lambda row: row["id"]
        )
    return sorted(items, key=lambda row: row["id"])


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def _write_legacy_export(
    output_dir: Path, envelope: dict[str, Any], lossless_content: bytes, lossless_dir: Path | None = None
) -> tuple[Path, Path, Path, Path]:
    """Write the committed items-domain views, plus the lossless envelope.

    ``output_dir`` receives ONLY the items-domain views -- ``items.jsonl``,
    ``events.jsonl``, ``index.md`` -- because it is the version-controlled export
    snapshot. The lossless ``todo-db.json`` (every table, including the findings
    domain whose review prose is deliberately not version-controlled) goes to
    ``lossless_dir``, which defaults to a sibling *outside* ``output_dir`` so the
    workflow's `git add` can never stage it. It remains the complete recovery
    artifact the restore round-trip replays.

    ``events.jsonl`` is derived from THIS envelope, not left over from a separate
    main-path export: both committed views therefore come from one read snapshot,
    so an item can never be missing the event that created it.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    lossless_dir = lossless_dir if lossless_dir is not None else output_dir.parent / f"{output_dir.name}-lossless"
    lossless_dir.mkdir(parents=True, exist_ok=True)
    legacy_envelope = output_dir / "todo-db.json"
    if legacy_envelope.exists() or legacy_envelope.is_symlink():
        if not legacy_envelope.is_file() and not legacy_envelope.is_symlink():
            raise ValueError(f"legacy export path is not a file: {legacy_envelope}")
        legacy_envelope.unlink()
    lossless_path = lossless_dir / "todo-db.json"
    items_path = output_dir / "items.jsonl"
    events_path = output_dir / "events.jsonl"
    index_path = output_dir / "index.md"
    items = _item_rows(envelope)
    _atomic_write_bytes(lossless_path, lossless_content)
    _atomic_write(items_path, "".join(_canonical_json(item) for item in items))
    events = sorted((dict(row) for row in envelope.get("events") or []), key=lambda row: row["seq"])
    _atomic_write(events_path, "".join(_canonical_json(event) for event in events))
    lines = ["# TODO export", "", "| id | state | priority | worktree | title |", "|---|---|---|---|---|"]
    for item in items:
        lines.append(f"| {item['id']} | {item['state']} | {item['priority']} | {item['worktree']} | {item['title']} |")
    _atomic_write(index_path, "\n".join(lines) + "\n")
    return lossless_path, items_path, events_path, index_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the committed items-domain export views from a todo-db lossless envelope.",
    )
    parser.add_argument(
        "--envelope",
        required=True,
        type=Path,
        help="lossless JSON envelope written by `todo-db export --output FILE`",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="version-controlled items-domain view directory (items.jsonl, events.jsonl, index.md)",
    )
    parser.add_argument(
        "--lossless-out",
        required=True,
        type=Path,
        dest="lossless_out",
        help="directory for the lossless todo-db.json copy; never place this under --out",
    )
    args = parser.parse_args(argv)

    lossless_content = args.envelope.read_bytes()
    envelope = json.loads(lossless_content)
    lossless, items, events, index = _write_legacy_export(
        args.out, envelope, lossless_content, lossless_dir=args.lossless_out
    )
    print(f"wrote {items}, {events} and {index} (lossless envelope: {lossless})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
