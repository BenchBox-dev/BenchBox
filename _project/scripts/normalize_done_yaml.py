#!/usr/bin/env python3
"""Normalize archived DONE YAML files to current TODO schema-compatible format.

This script is intentionally conservative: it fills required fields, coerces common
legacy structures, and preserves existing semantic content wherever possible.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml

VALID_STATUS = {"Not Started", "Identified", "In Progress", "Blocked", "Under Review", "Completed"}
VALID_PRIORITY = {"Critical", "High", "Medium-High", "Medium", "Low"}

STATUS_MAP = {
    "planning": "Completed",
    "planned": "Completed",
    "complete": "Completed",
    "completed": "Completed",
    "done": "Completed",
    "in_progress": "In Progress",
    "in progress": "In Progress",
    "not started": "Not Started",
    "identified": "Identified",
    "blocked": "Blocked",
    "under review": "Under Review",
}

PRIORITY_MAP = {
    "critical": "Critical",
    "p0": "Critical",
    "high": "High",
    "p1": "High",
    "medium-high": "Medium-High",
    "medium high": "Medium-High",
    "medium": "Medium",
    "p2": "Medium",
    "low": "Low",
    "p3": "Low",
}

SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")


def sanitize_slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "item"


def to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = to_text(item)
            if text:
                out.append(f"- {text}")
        return "\n".join(out)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"].strip()
        if isinstance(value.get("content"), str):
            return value["content"].strip()
        if isinstance(value.get("summary"), str):
            return value["summary"].strip()
        if isinstance(value.get("metric"), str):
            return value["metric"].strip()
        if isinstance(value.get("question"), str):
            answer = to_text(value.get("answer") or value.get("notes"))
            if answer:
                return f"{value['question'].strip()} - {answer}"
            return value["question"].strip()
        if isinstance(value.get("name"), str):
            nested = to_text(value.get("items") or value.get("content") or value.get("text") or value.get("summary"))
            return f"{value['name'].strip()}: {nested}" if nested else value["name"].strip()
        # fallback stable-ish stringification
        parts = []
        for k, v in value.items():
            t = to_text(v)
            if t:
                parts.append(f"{k}: {t}")
        return "; ".join(parts)
    return str(value)


def normalize_sections(data: dict[str, Any]) -> bool:
    if "sections" not in data:
        return False
    sections = data.get("sections")
    if isinstance(sections, dict):
        changed = False
        fixed: dict[str, str] = {}
        for k, v in sections.items():
            text = to_text(v)
            if text != v:
                changed = True
            fixed[str(k)] = text
        if changed:
            data["sections"] = fixed
        return changed
    if isinstance(sections, list):
        fixed: dict[str, str] = {}
        for idx, entry in enumerate(sections, 1):
            if isinstance(entry, dict):
                name = str(entry.get("name") or f"Section {idx}")
                body = to_text(entry.get("content") or entry.get("text") or entry.get("summary") or entry.get("items") or entry)
            else:
                name = f"Section {idx}"
                body = to_text(entry)
            fixed[name] = body
        data["sections"] = fixed
        return True
    data["sections"] = {"Implementation Notes": to_text(sections)}
    return True


def normalize_list_of_strings(data: dict[str, Any], key: str) -> bool:
    if key not in data:
        return False
    values = data.get(key)
    if not isinstance(values, list):
        data[key] = [to_text(values)] if to_text(values) else []
        return True
    out: list[str] = []
    changed = False
    for entry in values:
        text = to_text(entry)
        if not isinstance(entry, str):
            changed = True
        if text:
            out.append(text)
    if out != values:
        changed = True
    if changed:
        data[key] = out
    return changed


def normalize_commits(data: dict[str, Any]) -> bool:
    if "commits" not in data:
        return False
    commits = data.get("commits")
    if not isinstance(commits, list):
        data.pop("commits", None)
        return True

    out: list[str] = []
    changed = False
    for entry in commits:
        sha = None
        if isinstance(entry, str):
            m = SHA_RE.search(entry.lower())
            if m:
                sha = m.group(0)
            else:
                changed = True
        elif isinstance(entry, dict):
            raw = entry.get("hash") or entry.get("sha") or entry.get("commit")
            if isinstance(raw, str):
                m = SHA_RE.search(raw.lower())
                if m:
                    sha = m.group(0)
            changed = True
        else:
            changed = True
        if sha and sha not in out:
            out.append(sha)

    if not out:
        data.pop("commits", None)
        return True
    if out != commits:
        data["commits"] = out
        return True
    return changed


def normalize_files_affected(data: dict[str, Any]) -> bool:
    if "files_affected" not in data:
        return False
    fa = data["files_affected"]
    if isinstance(fa, dict):
        changed = False
        out: dict[str, list[str]] = {}
        for bucket in ("modified", "added", "removed"):
            vals = fa.get(bucket, [])
            if not isinstance(vals, list):
                vals = [vals]
                changed = True
            new_vals = [to_text(v) for v in vals if to_text(v)]
            if vals != new_vals:
                changed = True
            out[bucket] = new_vals
        if changed:
            data["files_affected"] = out
        return changed

    out = {"modified": [], "added": [], "removed": []}
    changed = True
    if isinstance(fa, list):
        for entry in fa:
            if isinstance(entry, str):
                out["modified"].append(entry)
            elif isinstance(entry, dict):
                change_type = str(entry.get("change_type") or entry.get("type") or "modified").lower()
                if "add" in change_type:
                    bucket = "added"
                elif "remov" in change_type or "delete" in change_type:
                    bucket = "removed"
                else:
                    bucket = "modified"
                paths = entry.get("paths")
                if isinstance(paths, list):
                    out[bucket].extend([to_text(p) for p in paths if to_text(p)])
                elif entry.get("path"):
                    ptxt = to_text(entry.get("path"))
                    if ptxt:
                        out[bucket].append(ptxt)
                else:
                    txt = to_text(entry)
                    if txt:
                        out[bucket].append(txt)
            else:
                txt = to_text(entry)
                if txt:
                    out["modified"].append(txt)
    else:
        txt = to_text(fa)
        if txt:
            out["modified"].append(txt)

    data["files_affected"] = out
    return changed


def normalize_required_fields(data: dict[str, Any], path: Path) -> bool:
    changed = False

    # worktree
    if not data.get("worktree"):
        rel = path.relative_to(path.parents[2])  # DONE/...
        worktree = rel.parts[0] if len(rel.parts) > 0 else path.parent.name
        data["worktree"] = sanitize_slug(worktree)
        changed = True

    # priority
    priority = data.get("priority")
    if not isinstance(priority, str):
        data["priority"] = "Medium"
        changed = True
    else:
        mapped = PRIORITY_MAP.get(priority.strip().lower())
        if mapped:
            if mapped != priority:
                data["priority"] = mapped
                changed = True
        elif priority not in VALID_PRIORITY:
            data["priority"] = "Medium"
            changed = True

    # status
    status = data.get("status")
    if not isinstance(status, str):
        data["status"] = "Completed"
        changed = True
    else:
        mapped = STATUS_MAP.get(status.strip().lower())
        if mapped:
            if mapped != status:
                data["status"] = mapped
                changed = True
        elif status not in VALID_STATUS:
            data["status"] = "Completed"
            changed = True

    # description
    desc = data.get("description")
    if not isinstance(desc, str) or len(desc.strip()) < 10:
        fallback = ""
        sections = data.get("sections")
        if isinstance(sections, dict) and sections:
            first_key = next(iter(sections.keys()))
            fallback = to_text(sections[first_key])
        if not fallback:
            fallback = f"Archived DONE item for: {data.get('title', path.stem)}"
        if len(fallback.strip()) < 10:
            fallback = f"Archived DONE item for: {data.get('title', path.stem)}"
        data["description"] = fallback
        changed = True

    return changed


def assign_unique_done_id(data: dict[str, Any], path: Path, used_ids: set[str], todo_ids: set[str]) -> bool:
    changed = False
    existing = data.get("id")
    if isinstance(existing, str) and existing.strip():
        base = sanitize_slug(existing)
    else:
        base = sanitize_slug(path.stem)
        changed = True

    if base in used_ids or base in todo_ids:
        worktree = sanitize_slug(str(data.get("worktree") or path.parent.name))
        base = sanitize_slug(f"{worktree}-{path.stem}")

    candidate = base
    i = 2
    while candidate in used_ids or candidate in todo_ids:
        candidate = f"{base}-{i}"
        i += 1

    if data.get("id") != candidate:
        data["id"] = candidate
        changed = True

    used_ids.add(candidate)
    return changed


def collect_todo_ids(todo_dir: Path) -> set[str]:
    out: set[str] = set()
    for p in todo_dir.rglob("*.yaml"):
        if "_indexes" in p.parts:
            continue
        try:
            data = yaml.safe_load(p.read_text())
        except Exception:
            continue
        if isinstance(data, dict):
            raw = data.get("id", p.stem)
            out.add(sanitize_slug(str(raw)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize DONE YAML files to current schema-compatible format")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    done_dir = root / "DONE"
    todo_dir = root / "TODO"

    todo_ids = collect_todo_ids(todo_dir)
    used_done_ids: set[str] = set()

    changed_files = 0
    scanned = 0
    parse_failures: list[str] = []

    files = sorted([p for p in done_dir.rglob("*.yaml") if "_indexes" not in p.parts])
    for path in files:
        scanned += 1
        try:
            data = yaml.safe_load(path.read_text())
        except Exception as e:
            parse_failures.append(f"{path}: {e}")
            continue
        if not isinstance(data, dict):
            parse_failures.append(f"{path}: root is not mapping")
            continue

        changed = False
        changed |= normalize_sections(data)
        changed |= normalize_list_of_strings(data, "success_metrics")
        changed |= normalize_list_of_strings(data, "open_questions")
        changed |= normalize_commits(data)
        changed |= normalize_files_affected(data)
        changed |= normalize_required_fields(data, path)
        changed |= assign_unique_done_id(data, path, used_done_ids, todo_ids)

        if changed:
            changed_files += 1
            if args.apply:
                path.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120))

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"normalize_done_yaml.py ({mode})")
    print(f"  Scanned files:  {scanned}")
    print(f"  Changed files:  {changed_files}")
    print(f"  Parse failures: {len(parse_failures)}")
    for line in parse_failures[:20]:
        print(f"    - {line}")

    return 0 if not parse_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
